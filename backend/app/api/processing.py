"""Paper fetching / analysis streaming endpoints (SSE)."""

import asyncio
import contextlib
import json
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.database import get_sync_session
from app.logging_config import get_logger
from app.models import Paper
from app.services.analyzer import STEPS, process_paper
from app.services.arxiv_bot import fetch_and_save
from app.services.errors import PipelineError

logger = get_logger("api.processing")

router = APIRouter()

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
KEEPALIVE_INTERVAL = 15.0


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/fetch/stream")
async def fetch_papers_stream():
    """Fetch papers from arXiv with streaming progress updates."""

    async def generate_events():
        try:
            yield sse("started", {"status": "started"})
            yield sse("fetching", {"status": "fetching", "message": "正在从 arXiv 获取论文..."})
            fetched, saved = await fetch_and_save()
            yield sse("fetched", {"status": "fetched", "message": f"获取到 {fetched} 篇论文", "count": fetched})
            yield sse("done", {
                "status": "done",
                "fetched": fetched,
                "saved": saved,
                "message": f"保存了 {saved} 篇新论文",
            })
        except Exception as e:
            logger.error("Fetch failed: %s", e)
            yield sse("error", {"error": str(e)})

    return StreamingResponse(generate_events(), media_type="text/event-stream", headers=SSE_HEADERS)


class _ChunkLogger:
    """Log streamed thinking/answer text at most every 2s or 300 chars."""

    def __init__(self, paper_id: int, label: str):
        self.paper_id = paper_id
        self.label = label
        self.total = 0
        self.last_count = 0
        self.last_time = 0.0

    def add(self, chunk: str) -> None:
        self.total += len(chunk)
        now = time.monotonic()
        if now - self.last_time >= 2.0 or self.total - self.last_count >= 300:
            preview = " ".join(chunk.split())[:160]
            logger.info("Paper %s %s stream (%d chars total): %s", self.paper_id, self.label, self.total, preview)
            self.last_time = now
            self.last_count = self.total


@router.get("/{paper_id}/process/stream")
async def process_paper_stream(paper_id: int):
    """Run the analysis pipeline for a paper, streaming progress as SSE.

    Events: started {steps}, progress {status, step, message}, thinking {thought},
    answer {answer}, result {...}, error {error, message}, done {status}, ping {ts}.
    """
    with get_sync_session() as session:
        paper = session.get(Paper, paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")
        title = paper.title

    async def generate_events():
        # Padding comment: makes WebKit hand the first chunk to fetch() immediately
        yield ": " + " " * 2048 + "\n\n"
        yield sse("started", {"steps": STEPS})
        logger.info("Paper %s processing started: %s", paper_id, title)

        queue: asyncio.Queue = asyncio.Queue()
        thoughts = _ChunkLogger(paper_id, "thought")
        answers = _ChunkLogger(paper_id, "answer")

        async def consume():
            try:
                async with contextlib.aclosing(process_paper(paper_id)) as events:
                    async for event in events:
                        await queue.put(("event", event))
            except Exception as e:
                await queue.put(("error", e))
            finally:
                await queue.put(("done", None))

        consumer_task = asyncio.create_task(consume())
        failed = False
        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL)
                except asyncio.TimeoutError:
                    yield sse("ping", {"ts": datetime.utcnow().isoformat()})
                    continue

                if kind == "event":
                    event = payload
                    if event.type == "thinking":
                        thoughts.add(event.text)
                        yield sse("thinking", {"thought": event.text})
                    elif event.type == "answer":
                        answers.add(event.text)
                        yield sse("answer", {"answer": event.text})
                    elif event.type == "result":
                        yield sse("result", event.result.to_event_payload())
                    else:
                        if event.type != "step_progress":
                            logger.info("Paper %s %s %s %s", paper_id, event.type, event.step, event.message)
                        yield sse("progress", {
                            "status": event.type,
                            "step": event.step,
                            "message": event.message,
                        })
                elif kind == "error":
                    failed = True
                    error = payload
                    if isinstance(error, PipelineError):
                        code, message = error.code, error.message
                    else:
                        logger.exception("Paper %s failed (unexpected)", paper_id, exc_info=error)
                        code, message = "unknown", str(error)
                    if code != "busy":
                        logger.error("Paper %s failed (%s): %s", paper_id, code, message)
                    yield sse("error", {"error": code, "message": message})
                elif kind == "done":
                    break

            if not failed:
                logger.info(
                    "Paper %s processing completed (thought=%d chars, answer=%d chars)",
                    paper_id, thoughts.total, answers.total,
                )
                yield sse("done", {"status": "completed"})
        finally:
            # Client gone (or finished): stop the pipeline; process_paper marks it failed
            if not consumer_task.done():
                consumer_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await consumer_task

    return StreamingResponse(generate_events(), media_type="text/event-stream", headers=SSE_HEADERS)
