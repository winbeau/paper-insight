import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

import app.services.research_agent as agent
from app.schemas import Provider
from app.services.arxiv_probe import ProbePaper, ProbeResult, parse_feed
from app.services.errors import PipelineError

PROVIDER = Provider(id="ds", name="DeepSeek", base_url="https://api.deepseek.com", api_key="k")
NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)


def atom(entries, total):
    items = "".join(
        f"<entry><id>http://arxiv.org/abs/{i}</id><title>{t}</title><summary>s</summary>"
        f"<published>{d.isoformat().replace('+00:00', 'Z')}</published></entry>"
        for i, (t, d) in enumerate(entries)
    )
    return (
        '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">'
        f"<opensearch:totalResults>{total}</opensearch:totalResults>{items}</feed>"
    )


def test_parse_feed_counts_weekly_and_total():
    xml = atom([("A", NOW - timedelta(days=1)), ("B", NOW - timedelta(days=6)), ("C", NOW - timedelta(days=9))], 321)
    result = parse_feed("q", xml, now=NOW)
    assert (result.total, result.weekly, result.weekly_capped) == (321, 2, False)
    assert [p.title for p in result.papers] == ["A", "B", "C"]


def test_parse_feed_reports_query_syntax_errors():
    xml = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors#bad</id>'
           "<title>Error</title><summary>malformed query</summary></entry></feed>")
    with pytest.raises(PipelineError) as info:
        parse_feed("q", xml)
    assert info.value.code == "config_error"


def probe_result(query, weekly, n_samples=12, capped=False):
    papers = [ProbePaper(title=f"Paper {i}", abstract="abs", published=NOW) for i in range(n_samples)]
    return ProbeResult(query=query, total=weekly * 30, weekly=weekly, weekly_capped=capped, papers=papers)


@pytest.fixture
def scripted(monkeypatch):
    state = {"replies": [], "requests": [], "probes": []}

    async def fake_stream_chat(provider, model, messages, **kwargs):
        state["requests"].append(copy.deepcopy(messages))
        assert kwargs.get("purpose") == "research_agent"
        yield "thinking", "思考…"
        yield "answer", json.dumps(state["replies"].pop(0), ensure_ascii=False)

    async def fake_probe(query):
        state["probes"].append(query)
        return state["probe_results"].pop(0)

    monkeypatch.setattr(agent, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(agent, "probe_query", fake_probe)
    return state


async def run(description="我在做视频扩散模型推理加速，关注 DiT 的 KV cache 压缩"):
    return [event async for event in agent.run_research_agent(description, PROVIDER, "deepseek-flash")]


async def test_agent_refines_until_acceptable_and_keeps_conversation_append_only(scripted):
    draft = {
        "arxiv_categories": ["cs.CV", "cs.LG", "not.a.cat"],
        "research_focus": 'cat:cs.CV AND abs:diffusion',
        "research_idea": "**研究主题**：…",
        "analysis_prompt": "你是视频生成加速专家……",
    }
    scripted["replies"] = [
        draft,
        {"relevant": [1, 2, 3], "assessment": "太宽泛", "done": False,
         "research_focus": '(abs:"diffusion transformer" OR abs:DiT) AND abs:"kv cache"'},
        {"relevant": list(range(1, 11)), "assessment": "很好", "done": True,
         "research_focus": '(abs:"diffusion transformer" OR abs:DiT) AND abs:"kv cache"'},
    ]
    scripted["probe_results"] = [probe_result("q1", 50, capped=True), probe_result("q2", 18)]
    events = await run()

    types = [e.type for e in events]
    assert types.count("round") == 2 and types[-1] == "result" and "thinking" in types
    draft_event = next(e for e in events if e.type == "draft")
    assert draft_event.data["arxiv_categories"] == ["cs.CV", "cs.LG"]   # invalid code dropped
    assert draft_event.data["research_focus"] == "abs:diffusion"         # cat: stripped
    assert scripted["probes"][0] == "(cat:cs.CV OR cat:cs.LG) AND (abs:diffusion)"

    rounds = [e.data for e in events if e.type == "round"]
    assert rounds[0]["acceptable"] is False and rounds[1]["acceptable"] is True
    assert rounds[1]["precision"] == pytest.approx(10 / 12)
    result = events[-1].data
    assert result["best_round"] == 2
    assert result["fields"]["research_focus"] == '(abs:"diffusion transformer" OR abs:DiT) AND abs:"kv cache"'
    assert result["fields"]["system_prompt"].startswith("你是视频生成加速专家")

    # Every request extends the previous one (cache-friendly), system prompt first and unchanged
    requests = scripted["requests"]
    for previous, current in zip(requests, requests[1:]):
        assert current[:len(previous)] == previous
    assert requests[0][0]["content"] == agent.SYSTEM_PROMPT


async def test_agent_tests_at_least_two_queries_and_stops_on_repeat(scripted):
    query = 'abs:"kv cache" AND abs:diffusion'
    scripted["replies"] = [
        {"arxiv_categories": ["cs.CV"], "research_focus": query, "research_idea": "x", "analysis_prompt": "y"},
        {"relevant": list(range(1, 12)), "done": True, "research_focus": query + ' OR abs:"video DiT"'},
        {"relevant": list(range(1, 9)), "done": True, "research_focus": query + ' OR abs:"video DiT"'},
    ]
    scripted["probe_results"] = [probe_result("q1", 20), probe_result("q2", 35)]
    events = await run()
    rounds = [e.data for e in events if e.type == "round"]
    assert len(rounds) == 2  # round 1 already acceptable, but a second candidate is tested
    assert events[-1].data["best_round"] == 1  # higher precision wins


async def test_agent_rejects_too_short_description(scripted):
    with pytest.raises(PipelineError):
        await run("加速")


async def test_probe_retries_transient_failures(monkeypatch):
    import httpx

    import app.services.arxiv_probe as probe

    calls = {"n": 0}

    async def flaky_get(query):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.RemoteProtocolError("peer closed connection")
        return httpx.Response(200, text=atom([("A", datetime.now(timezone.utc))], 1))

    monkeypatch.setattr(probe, "_get", flaky_get)
    monkeypatch.setattr(probe, "REQUEST_SPACING", 0)
    result = await probe.probe_query("q")
    assert calls["n"] == 3 and result.total == 1


async def test_agent_keeps_best_tested_query_when_arxiv_fails_later(scripted, monkeypatch):
    scripted["replies"] = [
        {"arxiv_categories": ["cs.CV"], "research_focus": "abs:a", "research_idea": "x", "analysis_prompt": "y"},
        {"relevant": [1, 2, 3, 4, 5, 6, 7, 8, 9], "done": False, "research_focus": "abs:b"},
    ]
    scripted["probe_results"] = [probe_result("q1", 20)]

    async def failing_probe(query):
        if scripted["probe_results"]:
            return scripted["probe_results"].pop(0)
        raise PipelineError("download_error", "无法访问 arXiv")

    monkeypatch.setattr(agent, "probe_query", failing_probe)
    events = await run()
    assert events[-1].type == "result" and events[-1].data["fields"]["research_focus"] == "abs:a"
