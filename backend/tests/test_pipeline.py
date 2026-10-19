import asyncio
import contextlib
import json
from datetime import datetime

import pytest

import app.services.analyzer as analyzer
from app.database import get_sync_session
from app.models import AppSettings, Paper
from app.services.errors import PipelineError
from app.services.parsers.base import Figure, ParsedDocument

RESULT = {
    "paper_essence": "核心创新",
    "concept_bridging": {"source_concept": "a", "target_concept": "b", "mechanism_transfer": "c"},
    "visual_verification": "Figure 1 支持",
    "relevance_score": 7,
    "relevance_reason": "相关",
    "heuristic_suggestion": "1. 试试",
}


def add_paper() -> int:
    with get_sync_session() as session:
        paper = Paper(
            arxiv_id="2401.00001v1", title="Test Paper", authors="A", abstract="Abstract.",
            categories="cs.CV", published=datetime(2024, 1, 1), updated=datetime(2024, 1, 1),
            pdf_url="https://arxiv.org/pdf/2401.00001v1",
        )
        session.add(paper)
        session.add(AppSettings(
            id=1,
            research_idea="我的研究",
            providers=[{"id": "p", "name": "P", "base_url": "https://llm.test/v1", "api_key": "k"}],
            pipeline={
                "parser": {"engine": "mineru_cloud", "cloud": {"token": "t"}},
                "vision": {"provider_id": "p", "model": "vl"},
                "reasoning": {"provider_id": "p", "model": "r1"},
            },
        ))
        session.commit()
        return paper.id


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    calls = {"vision": 0, "messages": None, "gate": None}
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"%PDF-")
    image = tmp_path / "images" / "f.jpg"
    image.parent.mkdir()
    image.write_bytes(b"x" * 10000)

    async def fake_ensure_pdf(arxiv_id, url):
        return pdf

    async def fake_parse(config, request, progress):
        await progress("MinerU 云端解析中 1/2 页")
        return ParsedDocument(
            root=tmp_path, markdown="# Paper\n\nBody", engine="mineru_cloud",
            figures=[Figure(n=1, kind="image", path="images/f.jpg", caption="Figure 1: Speed")],
        )

    async def fake_evidence(doc, figures, provider, config, title, progress, abstract=""):
        calls["vision"] += 1
        await progress("已识别 1/1 张图表")
        return "[Figure 1] Figure 1: Speed — 2x 加速"

    async def fake_stream(provider, model, messages, **kwargs):
        calls["messages"] = messages
        if calls["gate"] is not None:
            await calls["gate"].wait()
        yield "thinking", "想一想"
        yield "answer", json.dumps(RESULT, ensure_ascii=False)

    async def fake_thumbnail(arxiv_id, pdf_path):
        return "/static/thumbnails/2401.00001v1.jpg"

    import app.services.parse_queue as parse_queue

    monkeypatch.setattr(analyzer, "ensure_pdf", fake_ensure_pdf)
    monkeypatch.setattr(parse_queue, "ensure_pdf", fake_ensure_pdf)
    monkeypatch.setattr(parse_queue, "parse_document", fake_parse)
    monkeypatch.setattr(parse_queue, "_queue", None)
    monkeypatch.setattr(analyzer, "build_visual_evidence", fake_evidence)
    monkeypatch.setattr(analyzer, "stream_chat", fake_stream)
    monkeypatch.setattr(analyzer, "generate_thumbnail", fake_thumbnail)
    return calls


async def collect(paper_id):
    events = []
    async with contextlib.aclosing(analyzer.process_paper(paper_id)) as stream:
        async for event in stream:
            events.append(event)
    return events


async def test_full_pipeline_event_sequence_and_persistence(fakes):
    paper_id = add_paper()
    events = await collect(paper_id)

    steps = [(e.type, e.step) for e in events if e.type.startswith("step_") and e.type != "step_progress"]
    assert steps == [
        ("step_started", "download"), ("step_finished", "download"),
        ("step_started", "parse"), ("step_finished", "parse"),
        ("step_started", "vision"), ("step_finished", "vision"),
        ("step_started", "analyze"), ("step_finished", "analyze"),
        ("step_started", "finalize"), ("step_finished", "finalize"),
    ]
    assert [e.text for e in events if e.type == "thinking"] == ["想一想"]
    assert events[-1].type == "result" and events[-1].result.relevance_score == 7

    user_prompt = fakes["messages"][1]["content"]
    assert "我的研究" in user_prompt and "[Figure 1]" in user_prompt and "# Paper" in user_prompt

    with get_sync_session() as session:
        paper = session.get(Paper, paper_id)
        assert paper.is_processed and paper.processing_status == "processed"
        assert paper.concept_bridging == "源概念: a\n目标概念: b\n迁移机制: c"
        assert paper.thumbnail_url == "/static/thumbnails/2401.00001v1.jpg"
        assert paper.processing_error is None


async def test_vision_disabled_is_skipped(fakes):
    paper_id = add_paper()
    with get_sync_session() as session:
        settings = session.get(AppSettings, 1)
        settings.pipeline = {**settings.pipeline, "vision": {"enabled": False}}
        session.add(settings)
        session.commit()
    events = await collect(paper_id)
    assert ("step_skipped", "vision") in [(e.type, e.step) for e in events]
    assert fakes["vision"] == 0


async def test_missing_reasoning_model_fails_with_config_error(fakes):
    paper_id = add_paper()
    with get_sync_session() as session:
        settings = session.get(AppSettings, 1)
        settings.pipeline = {**settings.pipeline, "reasoning": {}}
        session.add(settings)
        session.commit()
    with pytest.raises(PipelineError) as info:
        await collect(paper_id)
    assert info.value.code == "config_error"
    with get_sync_session() as session:
        paper = session.get(Paper, paper_id)
        assert paper.processing_status == "failed" and paper.processing_error.startswith("config_error")


async def test_concurrent_run_is_rejected_as_busy(fakes):
    paper_id = add_paper()
    fakes["gate"] = asyncio.Event()
    first = asyncio.create_task(collect(paper_id))
    await asyncio.sleep(0.05)
    with pytest.raises(PipelineError) as info:
        await collect(paper_id)
    assert info.value.code == "busy"
    fakes["gate"].set()
    await first
    with get_sync_session() as session:
        assert session.get(Paper, paper_id).processing_status == "processed"


async def test_cancellation_marks_paper_failed(fakes):
    paper_id = add_paper()
    fakes["gate"] = asyncio.Event()  # never set: the run blocks in the analyze step
    task = asyncio.create_task(collect(paper_id))
    await asyncio.sleep(0.05)
    assert paper_id in analyzer.active_paper_ids()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    with get_sync_session() as session:
        paper = session.get(Paper, paper_id)
        assert paper.processing_status == "failed" and paper.processing_error.startswith("interrupted")
    assert paper_id not in analyzer.active_paper_ids()


def test_sse_stream_contract(client, fakes):
    paper_id = add_paper()
    with client.stream("GET", f"/api/papers/{paper_id}/process/stream") as response:
        body = "".join(response.iter_text())
    events = []
    for block in body.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if line.startswith(("event:", "data:")))
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    names = [name for name, _ in events]
    assert names[0] == "started" and [s["key"] for s in events[0][1]["steps"]][0] == "download"
    assert names[-2:] == ["result", "done"]
    progress = [d for n, d in events if n == "progress"]
    assert {"status": "step_started", "step": "parse", "message": "MinerU 云端"} in progress
    assert any(d["status"] == "step_progress" and d["step"] == "vision" for d in progress)


async def test_missing_api_key_is_config_error(fakes):
    paper_id = add_paper()
    with get_sync_session() as session:
        settings = session.get(AppSettings, 1)
        settings.providers = [{"id": "p", "name": "P", "base_url": "https://llm.test/v1", "api_key": ""}]
        session.add(settings)
        session.commit()
    with pytest.raises(PipelineError) as info:
        await collect(paper_id)
    assert info.value.code == "config_error" and "API Key" in info.value.message



async def test_stop_all_returns_paper_to_pending(fakes, monkeypatch):
    import app.services.mineru_runtime as runtime_module

    class FakeRuntime:
        async def stop_server(self):
            pass

    monkeypatch.setattr(runtime_module, "get_mineru_runtime", lambda: FakeRuntime())
    paper_id = add_paper()
    fakes["gate"] = asyncio.Event()  # the run blocks in the analyze step
    task = asyncio.create_task(collect(paper_id))
    await asyncio.sleep(0.05)
    assert paper_id in analyzer.active_paper_ids()

    result = await analyzer.stop_all()
    assert result["stopped"] == 1
    with pytest.raises(PipelineError) as info:
        await task
    assert info.value.code == "stopped"
    with get_sync_session() as session:
        paper = session.get(Paper, paper_id)
        assert paper.processing_status == "pending" and paper.processing_error is None
    assert paper_id not in analyzer.active_paper_ids()


async def test_parsing_overlaps_analysis_across_papers(fakes, monkeypatch, tmp_path):
    """MinerU (serial) parses the next paper while the previous one is being analyzed."""
    import time

    import app.services.parse_queue as parse_queue
    from app.services.arxiv_bot import prefetch_parses

    monkeypatch.setattr(parse_queue, "CLOUD_CONCURRENCY", 1)  # serial, like local MinerU
    timeline = []

    async def slow_parse(config, request, progress):
        start = time.monotonic()
        await asyncio.sleep(0.2)
        timeline.append(("parse", request.arxiv_id, start, time.monotonic()))
        return ParsedDocument(root=tmp_path, markdown="# Paper", engine="mineru_cloud")

    async def slow_llm(provider, model, messages, **kwargs):
        arxiv_id = next(line.split("：")[1] for line in messages[1]["content"].splitlines() if line.startswith("arXiv："))
        start = time.monotonic()
        await asyncio.sleep(0.15)
        timeline.append(("llm", arxiv_id, start, time.monotonic()))
        yield "answer", json.dumps(RESULT, ensure_ascii=False)

    monkeypatch.setattr(parse_queue, "parse_document", slow_parse)
    monkeypatch.setattr(analyzer, "stream_chat", slow_llm)

    first = add_paper()
    ids = [first]
    with get_sync_session() as session:
        for n in (2, 3):
            paper = Paper(
                arxiv_id=f"2401.0000{n}v1", title=f"P{n}", authors="A", abstract="x", categories="cs.CV",
                published=datetime(2024, 1, 1), updated=datetime(2024, 1, 1), pdf_url=f"https://x/{n}",
            )
            session.add(paper)
            session.commit()
            ids.append(paper.id)

    started = time.monotonic()
    assert prefetch_parses(ids) == 3
    await asyncio.gather(*(collect(pid) for pid in ids))
    elapsed = time.monotonic() - started

    spans = {(kind, arxiv_id): (s, e) for kind, arxiv_id, s, e in timeline}
    p2_start, p2_end = spans[("parse", "2401.00002v1")]
    a1_start, a1_end = spans[("llm", "2401.00001v1")]
    assert p2_start < a1_end and a1_start < p2_end, "paper 2 parse should overlap paper 1 analysis"
    # serial parse (3 × 0.2s) + the last analysis (0.15s) instead of 3 × (0.2 + 0.15)
    assert elapsed < 0.9
