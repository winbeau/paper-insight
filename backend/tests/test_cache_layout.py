"""Prompt-cache friendliness: stable prefixes, warm-up ordering and usage accounting."""

import asyncio
import json

import httpx
import respx

import app.services.vision as vision
from app.prompts import ANALYSIS_OUTPUT_SPEC, build_analysis_messages
from app.schemas import Provider, VisionConfig
from app.services.llm_client import clear_client_cache, stream_chat
from app.services.parsers.base import Figure, ParsedDocument
from app.services.usage import summary, usage_from_payload, usage_scope

BASE = "https://llm.test/v1"
PROVIDER = Provider(id="p", name="P", base_url=BASE, api_key="sk-test-123456789")


def test_usage_from_deepseek_and_openai_payloads():
    ds = usage_from_payload({"prompt_tokens": 1000, "prompt_cache_hit_tokens": 800,
                             "prompt_cache_miss_tokens": 200, "completion_tokens": 50})
    assert (ds.cache_hit_tokens, ds.cache_miss_tokens, ds.hit_rate) == (800, 200, 0.8)
    oa = usage_from_payload({"prompt_tokens": 1000, "prompt_tokens_details": {"cached_tokens": 512},
                             "completion_tokens": 10})
    assert (oa.cache_hit_tokens, oa.cache_miss_tokens) == (512, 488)
    unknown = usage_from_payload({"prompt_tokens": 1000, "completion_tokens": 10})
    assert unknown.hit_rate is None  # no cache info: excluded, not counted as 0%


def test_analysis_system_prompt_is_identical_for_every_direction():
    common = dict(research_focus="", title="A", arxiv_id="1", abstract="x", markdown="# A",
                  visual_evidence="", max_input_chars=10000)
    a = build_analysis_messages(system_prompt="", research_idea="idea A", **common)
    b = build_analysis_messages(system_prompt="你是机器人专家。评分标准：……", research_idea="idea B", **common)
    assert a[0] == b[0] and a[0]["content"].endswith(ANALYSIS_OUTPUT_SPEC)
    assert "你是机器人专家" in b[1]["content"] and "跨领域技术迁移" in a[1]["content"]


def test_same_paper_shares_its_text_across_directions():
    paper = dict(research_focus="", title="T", arxiv_id="2401.1", abstract="abs",
                 markdown="# Paper\n" + "body " * 2000, visual_evidence="[Figure 1] x", max_input_chars=50000)
    a = build_analysis_messages(system_prompt="", research_idea="视频加速", **paper)[1]["content"]
    b = build_analysis_messages(system_prompt="机器人评分标准", research_idea="机器人抓取", **paper)[1]["content"]
    shared = a.split("## 分析视角与评分标准")[0]
    assert b.startswith(shared) and "body body" in shared and "[Figure 1]" in shared
    assert len(shared) > 0.9 * len(a)  # nearly the whole request is a cacheable prefix


async def test_vision_warms_cache_with_first_figure_then_parallel(monkeypatch, tmp_path):
    calls = []
    first_done = asyncio.Event()

    async def fake_chat_text(provider, model, messages, **kwargs):
        content = messages[1]["content"]
        calls.append({"context": content[0]["text"], "figure": content[1]["text"],
                      "first_done": first_done.is_set(), "purpose": kwargs.get("purpose")})
        await asyncio.sleep(0.01)
        first_done.set()
        return "描述"

    monkeypatch.setattr(vision, "chat_text", fake_chat_text)
    (tmp_path / "images").mkdir()
    figures = []
    for n in range(1, 4):
        (tmp_path / "images" / f"f{n}.png").write_bytes(b"\x89PNG" + b"0" * 6000)
        figures.append(Figure(n=n, kind="image", path=f"images/f{n}.png", caption=f"Figure {n}: x"))
    doc = ParsedDocument(root=tmp_path, markdown="", figures=figures)
    monkeypatch.setattr(vision, "_image_data_uri", lambda path: ("data:image/png;base64,AAAA", 10))

    async def noop(_):
        pass

    evidence = await vision.build_visual_evidence(
        doc, figures, PROVIDER, VisionConfig(model="vl"), "Title", noop, abstract="Abstract text"
    )
    assert evidence.count("[Figure") == 3
    assert len({c["context"] for c in calls}) == 1  # identical paper context → shared prefix
    assert calls[0]["first_done"] is False and all(c["first_done"] for c in calls[1:])
    assert all(c["purpose"] == "vision" for c in calls)


@respx.mock
async def test_stream_records_usage_from_final_chunk():
    clear_client_cache()
    chunks = [
        {"choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 2000, "prompt_cache_hit_tokens": 1536,
                                  "prompt_cache_miss_tokens": 464, "completion_tokens": 5}},
    ]
    body = "".join(
        f"data: {json.dumps({'id': 'c', 'object': 'chat.completion.chunk', 'created': 0, 'model': 'm', **c})}\n\n"
        for c in chunks
    ) + "data: [DONE]\n\n"
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)
    )
    with usage_scope() as scope:
        out = [x async for x in stream_chat(PROVIDER, "m", [], purpose="analysis")]
    assert out == [("answer", "ok")]
    assert json.loads(route.calls[0].request.content)["stream_options"] == {"include_usage": True}
    assert (scope.cache_hit_tokens, scope.cache_miss_tokens) == (1536, 464)
    assert summary()["by_purpose"]["analysis"]["cache_hit_tokens"] >= 1536
