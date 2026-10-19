import asyncio
import contextlib

import pytest

import app.services.parse_queue as parse_queue
from app.schemas import ParserConfig
from app.services.errors import PipelineError
from app.services.parse_queue import ParseQueue, ParseTarget
from app.services.parsers.base import ParsedDocument

LOCAL = ParserConfig.model_validate({"engine": "mineru_local"})  # concurrency 1


def target(n: int) -> ParseTarget:
    return ParseTarget(arxiv_id=f"2401.0000{n}", title=f"P{n}", pdf_url=f"https://x/{n}.pdf")


@pytest.fixture
def fake_mineru(monkeypatch, tmp_path):
    state = {"order": [], "running": 0, "max_running": 0, "gates": {}, "fail": set()}

    async def fake_ensure_pdf(arxiv_id, url):
        return tmp_path / f"{arxiv_id}.pdf"

    async def fake_parse(config, request, progress):
        state["order"].append(request.arxiv_id)
        state["running"] += 1
        state["max_running"] = max(state["max_running"], state["running"])
        try:
            await progress(f"parsing {request.arxiv_id}")
            gate = state["gates"].get(request.arxiv_id)
            if gate is not None:
                await gate.wait()
            else:
                await asyncio.sleep(0.01)
            if request.arxiv_id in state["fail"]:
                raise PipelineError("parse_error", "broken pdf")
            return ParsedDocument(root=tmp_path, markdown=f"# {request.arxiv_id}", engine=config.engine)
        finally:
            state["running"] -= 1

    monkeypatch.setattr(parse_queue, "ensure_pdf", fake_ensure_pdf)
    monkeypatch.setattr(parse_queue, "parse_document", fake_parse)
    return state


async def noop(_message):
    pass


async def test_prefetch_runs_serially_in_order_and_parse_joins_existing_job(fake_mineru):
    queue = ParseQueue()
    assert queue.prefetch([target(1), target(2), target(3)], LOCAL) == 3
    docs = await asyncio.gather(*(queue.parse(target(n), LOCAL, noop) for n in (1, 2, 3)))
    assert [d.markdown for d in docs] == ["# 2401.00001", "# 2401.00002", "# 2401.00003"]
    assert fake_mineru["order"] == ["2401.00001", "2401.00002", "2401.00003"]  # each parsed once
    assert fake_mineru["max_running"] == 1


async def test_single_paper_jumps_the_backlog_and_reports_position(fake_mineru):
    queue = ParseQueue()
    fake_mineru["gates"]["2401.00001"] = gate = asyncio.Event()
    queue.prefetch([target(1), target(2), target(3)], LOCAL)
    messages = []

    async def progress(message):
        messages.append(message)

    # A paper outside the prefetched batch goes next; batch papers keep their order
    queued = asyncio.create_task(queue.parse(target(3), LOCAL, progress))
    single = asyncio.create_task(queue.parse(target(4), LOCAL, noop))
    await asyncio.sleep(0.02)
    assert "排队等待解析（前面还有 3 篇）" in messages  # #1 running, #4 and #2 ahead
    gate.set()
    await asyncio.gather(queued, single)
    assert fake_mineru["order"] == ["2401.00001", "2401.00004", "2401.00002", "2401.00003"]


async def test_cancelled_analysis_leaves_shared_parse_running(fake_mineru):
    queue = ParseQueue()
    fake_mineru["gates"]["2401.00001"] = gate = asyncio.Event()
    waiter = asyncio.create_task(queue.parse(target(1), LOCAL, noop))
    await asyncio.sleep(0.02)
    waiter.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await waiter
    gate.set()
    doc = await queue.parse(target(1), LOCAL, noop)  # joins the still-running job
    assert doc.markdown == "# 2401.00001"
    assert fake_mineru["order"] == ["2401.00001"]


async def test_failed_prefetch_is_reported_once_then_retried(fake_mineru):
    queue = ParseQueue()
    fake_mineru["fail"].add("2401.00001")
    queue.prefetch([target(1)], LOCAL)
    await asyncio.sleep(0.05)
    with pytest.raises(PipelineError):
        await queue.parse(target(1), LOCAL, noop)  # the prefetch's failure, no new parse
    assert fake_mineru["order"] == ["2401.00001"]
    with pytest.raises(PipelineError):
        await queue.parse(target(1), LOCAL, noop)  # an explicit retry parses again
    assert fake_mineru["order"] == ["2401.00001", "2401.00001"]


async def test_cancel_all_stops_running_and_queued(fake_mineru):
    queue = ParseQueue()
    fake_mineru["gates"]["2401.00001"] = asyncio.Event()
    queue.prefetch([target(1), target(2)], LOCAL)
    waiter = asyncio.create_task(queue.parse(target(1), LOCAL, noop))
    await asyncio.sleep(0.02)
    assert queue.cancel_all() == 2
    with pytest.raises(PipelineError) as info:
        await waiter
    assert info.value.code == "stopped"
    assert queue.stats() == {"parse_queued": 0, "parse_running": 0}
    assert fake_mineru["order"] == ["2401.00001"]


async def test_local_concurrency_setting_allows_parallel_parses(fake_mineru):
    queue = ParseQueue()
    config = ParserConfig.model_validate({"engine": "mineru_local", "local": {"concurrency": 2}})
    for n in (1, 2, 3):
        fake_mineru["gates"][f"2401.0000{n}"] = asyncio.Event()
    queue.prefetch([target(1), target(2), target(3)], config)
    await asyncio.sleep(0.02)
    assert fake_mineru["running"] == 2
    for gate in fake_mineru["gates"].values():
        gate.set()
    await asyncio.sleep(0.05)
    assert fake_mineru["max_running"] == 2 and len(fake_mineru["order"]) == 3
