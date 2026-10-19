"""Parse queue: keeps MinerU busy ahead of the analysis steps.

Parsing (download + MinerU) is the slow, capacity-limited part of the pipeline, while the
vision and reasoning steps go to remote APIs and parallelize well. The queue decouples the
two: when processing starts, every pending paper is queued for parsing at once (prefetch),
MinerU works through them back to back, and each paper's analysis starts the moment its
parse is ready — while MinerU is already busy with the next one.

Jobs are deduplicated per paper and keep running when the analysis that asked for them is
cancelled (the result is cached for the next run). A paper analyzed on its own (not part of
the prefetched batch) jumps ahead of the backlog; prefetched papers keep their order. A failed prefetch is handed to the next analysis of that paper once, so a
batch doesn't parse a broken PDF twice.
"""

import asyncio
import contextlib
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, Optional, Set

from app.config import parsed_dir_for
from app.logging_config import get_logger
from app.schemas import ParserConfig
from app.services.errors import PipelineError
from app.services.parsers import ParseRequest, parse_document
from app.services.parsers.base import ParsedDocument, ProgressFn, load_cached
from app.services.pdf_renderer import ensure_pdf

logger = get_logger("services.parse_queue")

CLOUD_CONCURRENCY = 5         # mineru.net handles batches; this just bounds uploads
FAILED_JOB_TTL = 3600         # seconds a failed prefetch is kept for its analysis


@dataclass
class ParseTarget:
    arxiv_id: str
    title: str
    pdf_url: str


@dataclass
class _Job:
    target: ParseTarget
    config: ParserConfig
    future: asyncio.Future
    listeners: Set[asyncio.Queue] = field(default_factory=set)
    task: Optional[asyncio.Task] = None
    last_message: str = ""
    finished_at: Optional[float] = None

    @property
    def key(self) -> str:
        return self.target.arxiv_id

    @property
    def engine(self) -> str:
        return self.config.engine


def _limit(config: ParserConfig) -> int:
    return config.local.concurrency if config.engine == "mineru_local" else CLOUD_CONCURRENCY


def _retrieve_exception(future: asyncio.Future) -> None:
    # Prefetch results nobody awaited must not log "exception was never retrieved"
    if not future.cancelled():
        future.exception()


class ParseQueue:
    def __init__(self) -> None:
        self._jobs: Dict[str, _Job] = {}
        self._pending: Deque[str] = deque()
        self._running: Dict[str, int] = {}

    # --- public API ------------------------------------------------------------------

    def prefetch(self, targets: Iterable[ParseTarget], config: ParserConfig) -> int:
        """Queue parses for papers that aren't parsed yet. Returns how many were queued."""
        queued = 0
        for target in targets:
            if target.arxiv_id in self._jobs or load_cached(parsed_dir_for(target.arxiv_id)):
                continue
            self._submit(target, config, priority=False)
            queued += 1
        if queued:
            logger.info("Queued %d papers for parsing (%s)", queued, config.engine)
        return queued

    async def parse(self, target: ParseTarget, config: ParserConfig, progress: ProgressFn) -> ParsedDocument:
        """Parsed document for a paper: from cache, an existing job, or a new priority job."""
        if target.arxiv_id not in self._jobs:
            cached = load_cached(parsed_dir_for(target.arxiv_id))
            if cached is not None:
                return cached

        job = self._submit(target, config, priority=True)
        listener: asyncio.Queue = asyncio.Queue()
        job.listeners.add(listener)
        if job.last_message:
            listener.put_nowait(job.last_message)
        getter: Optional[asyncio.Future] = None
        try:
            # Waiting on the job's future (instead of awaiting it) means cancelling this
            # analysis leaves the shared parse running.
            while not job.future.done():
                getter = asyncio.ensure_future(listener.get())
                done, _ = await asyncio.wait({getter, job.future}, return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    await progress(getter.result())
                    getter = None
            if self._jobs.get(job.key) is job:
                del self._jobs[job.key]  # consumed (relevant for a kept failure)
            if job.future.cancelled():
                raise PipelineError("stopped", "解析已停止")
            return job.future.result()
        finally:
            job.listeners.discard(listener)
            if getter is not None:
                getter.cancel()

    def cancel_all(self) -> int:
        """Drop queued parses and cancel running ones. Returns how many were affected."""
        affected = 0
        self._pending.clear()
        for key, job in list(self._jobs.items()):
            if job.task is not None and not job.task.done():
                job.task.cancel()
                affected += 1
            elif not job.future.done():
                job.future.cancel()
                affected += 1
            self._jobs.pop(key, None)
        return affected

    def stats(self) -> Dict[str, int]:
        return {"parse_queued": len(self._pending), "parse_running": sum(self._running.values())}

    # --- internals -----------------------------------------------------------------------

    def _submit(self, target: ParseTarget, config: ParserConfig, priority: bool) -> _Job:
        self._purge_expired()
        job = self._jobs.get(target.arxiv_id)
        if job is not None:
            return job  # already queued/running: keep its place in the batch order

        future = asyncio.get_running_loop().create_future()
        future.add_done_callback(_retrieve_exception)
        job = _Job(target=target, config=config, future=future)
        self._jobs[job.key] = job
        if priority:
            self._pending.appendleft(job.key)
        else:
            self._pending.append(job.key)
        self._dispatch()
        if job.key in self._pending:
            self._announce_positions()
        return job

    def _purge_expired(self) -> None:
        now = time.monotonic()
        for key, job in list(self._jobs.items()):
            if job.finished_at is not None and now - job.finished_at > FAILED_JOB_TTL:
                del self._jobs[key]

    def _dispatch(self) -> None:
        started = False
        for key in list(self._pending):
            job = self._jobs.get(key)
            if job is None:
                self._pending.remove(key)
                continue
            if self._running.get(job.engine, 0) >= _limit(job.config):
                continue
            self._pending.remove(key)
            self._running[job.engine] = self._running.get(job.engine, 0) + 1
            job.task = asyncio.create_task(self._run(job), name=f"parse-{key}")
            started = True
        if started:
            self._announce_positions()

    def _announce_positions(self) -> None:
        ahead_by_engine: Dict[str, int] = dict(self._running)
        for key in self._pending:
            job = self._jobs.get(key)
            if job is None:
                continue
            ahead = ahead_by_engine.get(job.engine, 0)
            ahead_by_engine[job.engine] = ahead + 1
            if job.listeners:
                self._broadcast(job, f"排队等待解析（前面还有 {ahead} 篇）")

    @staticmethod
    def _broadcast(job: _Job, message: str) -> None:
        job.last_message = message
        for listener in list(job.listeners):
            listener.put_nowait(message)

    async def _run(self, job: _Job) -> None:
        async def progress(message: str) -> None:
            self._broadcast(job, message)

        try:
            pdf_path = await ensure_pdf(job.target.arxiv_id, job.target.pdf_url)
            request = ParseRequest(
                arxiv_id=job.target.arxiv_id,
                title=job.target.title,
                pdf_url=job.target.pdf_url,
                pdf_path=pdf_path,
                out_dir=parsed_dir_for(job.target.arxiv_id),
            )
            job.future.set_result(await parse_document(job.config, request, progress))
        except asyncio.CancelledError:
            if not job.future.done():
                job.future.cancel()
            raise
        except Exception as e:
            if not job.future.done():
                job.future.set_exception(e)
            logger.warning("Parse of %s failed: %s", job.key, e)
        finally:
            if not job.future.done():  # e.g. GeneratorExit when the loop shuts down
                job.future.cancel()
            self._running[job.engine] = max(0, self._running.get(job.engine, 0) - 1)
            if job.future.cancelled() or job.future.exception() is None:
                if self._jobs.get(job.key) is job:
                    del self._jobs[job.key]  # success is in the disk cache
            else:
                job.finished_at = time.monotonic()  # keep the failure for its analysis
            with contextlib.suppress(RuntimeError):
                self._dispatch()


_queue: Optional[ParseQueue] = None


def get_parse_queue() -> ParseQueue:
    global _queue
    if _queue is None:
        _queue = ParseQueue()
    return _queue
