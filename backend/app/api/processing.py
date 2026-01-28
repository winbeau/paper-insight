"""Paper processing and streaming endpoints."""

import asyncio
import contextlib
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select
from sqlalchemy import or_

from app.logging_config import get_logger
from app.models import Paper, AppSettings
from app.dependencies import get_session
from app.database import get_sync_session
from app.services.arxiv_bot import get_arxiv_bot, run_daily_fetch
from app.services.dify_client import (
    get_dify_client,
    DifyClientError,
    DifyEntityTooLargeError,
    DifyTimeoutError,
    DifyRateLimitError,
)
from app.services.pdf_renderer import generate_thumbnail

logger = get_logger("api.processing")

router = APIRouter()


@router.get("/fetch/stream")
async def fetch_papers_stream(session: Session = Depends(get_session)):
    """Fetch papers from arXiv with streaming progress updates."""

    async def generate_events():
        try:
            yield f"event: started\ndata: {json.dumps({'status': 'started'})}\n\n"
            yield f"event: fetching\ndata: {json.dumps({'status': 'fetching', 'message': '正在从 arXiv 获取论文...'})}\n\n"

            bot = get_arxiv_bot()

            loop = asyncio.get_running_loop()
            papers = await loop.run_in_executor(None, bot.fetch_recent_papers, session, 50, 168)

            yield f"event: fetched\ndata: {json.dumps({'status': 'fetched', 'message': f'获取到 {len(papers)} 篇论文', 'count': len(papers)})}\n\n"
            yield f"event: saving\ndata: {json.dumps({'status': 'saving', 'message': '正在保存到数据库...'})}\n\n"

            saved_count = 0
            for paper_data in papers:
                paper = bot.save_paper(session, paper_data)
                if paper:
                    saved_count += 1

            yield f"event: done\ndata: {json.dumps({'status': 'done', 'fetched': len(papers), 'saved': saved_count, 'message': f'保存了 {saved_count} 篇新论文'})}\n\n"

        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/process/batch")
def process_papers_batch(
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """Trigger batch processing of all pending/failed papers."""
    pending_count = len(session.exec(
        select(Paper).where(
            Paper.is_processed == False,
            or_(
                Paper.processing_status == "pending",
                Paper.processing_status == "failed",
            ),
        )
    ).all())

    if pending_count == 0:
        return {"message": "No papers to process", "count": 0}

    background_tasks.add_task(run_daily_fetch)
    return {"message": f"Batch processing started for {pending_count} papers", "count": pending_count}


@router.get("/process/batch/stream")
async def process_papers_batch_stream(session: Session = Depends(get_session)):
    """Process all pending/failed papers with streaming progress updates."""

    # Reset stuck "processing" papers
    stuck_papers = session.exec(
        select(Paper).where(
            Paper.processing_status == "processing",
            Paper.is_processed == False,
        )
    ).all()
    if stuck_papers:
        for paper in stuck_papers:
            paper.processing_status = "failed"
            session.add(paper)
        session.commit()

    papers_to_process = session.exec(
        select(Paper).where(
            Paper.is_processed == False,
            or_(
                Paper.processing_status == "pending",
                Paper.processing_status == "failed",
            ),
        )
    ).all()

    paper_ids = [p.id for p in papers_to_process]
    total_count = len(paper_ids)

    async def generate_events():
        if total_count == 0:
            yield f"event: done\ndata: {json.dumps({'status': 'no_papers', 'message': 'No papers to process'})}\n\n"
            return

        yield f"event: started\ndata: {json.dumps({'total': total_count})}\n\n"

        bot = get_arxiv_bot()
        MAX_CONCURRENT = 3
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)

        processed_count = 0
        failed_count = 0

        event_queue: asyncio.Queue = asyncio.Queue()

        async def process_paper_with_events(paper_id: int):
            nonlocal processed_count, failed_count
            async with semaphore:
                task_session = get_sync_session()
                try:
                    paper = task_session.get(Paper, paper_id)
                    if not paper:
                        return None

                    await event_queue.put(
                        f"event: paper_processing\ndata: {json.dumps({'paper_id': paper_id, 'title': paper.title})}\n\n"
                    )

                    success = await bot.process_paper(task_session, paper)

                    if success:
                        processed_count += 1
                        await event_queue.put(
                            f"event: paper_completed\ndata: {json.dumps({'paper_id': paper_id, 'title': paper.title, 'processed': processed_count, 'total': total_count})}\n\n"
                        )
                    else:
                        failed_count += 1
                        await event_queue.put(
                            f"event: paper_failed\ndata: {json.dumps({'paper_id': paper_id, 'title': paper.title, 'failed': failed_count, 'total': total_count})}\n\n"
                        )
                    return True
                except Exception as e:
                    failed_count += 1
                    await event_queue.put(
                        f"event: paper_failed\ndata: {json.dumps({'paper_id': paper_id, 'error': str(e), 'failed': failed_count, 'total': total_count})}\n\n"
                    )
                    return False
                finally:
                    task_session.close()

        tasks = [asyncio.create_task(process_paper_with_events(pid)) for pid in paper_ids]

        all_done = False
        while not all_done or not event_queue.empty():
            all_done = all(t.done() for t in tasks)

            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                yield event
            except asyncio.TimeoutError:
                continue

        yield f"event: done\ndata: {json.dumps({'status': 'completed', 'processed': processed_count, 'failed': failed_count, 'total': total_count})}\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{paper_id}/process")
async def process_paper(paper_id: int, session: Session = Depends(get_session)):
    """Process a specific paper with LLM analysis."""
    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    if paper.is_processed:
        return {"message": "Paper already processed", "paper_id": paper_id}

    bot = get_arxiv_bot()
    success = await bot.process_paper(session, paper)

    if success:
        return {"message": "Paper processed successfully", "paper_id": paper_id}
    else:
        raise HTTPException(status_code=500, detail="Failed to process paper")


@router.get("/{paper_id}/process/stream")
async def process_paper_stream(paper_id: int, session: Session = Depends(get_session)):
    """Process a paper with streaming response for real-time updates."""
    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    async def generate_events():
        """Generate SSE events for paper analysis."""
        try:
            paper.processing_status = "processing"
            session.add(paper)
            session.commit()
            logger.info("Paper %s processing started: %s", paper_id, paper.title)

            settings = session.get(AppSettings, 1)
            idea_input = settings.research_idea if settings and settings.research_idea else None

            yield f"event: progress\ndata: {json.dumps({'status': 'started', 'message': '开始下载PDF...'})}\n\n"

            dify_client = get_dify_client()
            thought_parts = []
            answer_parts = []
            final_outputs = None

            def _preview(text: str, limit: int = 160) -> str:
                clean = " ".join(text.split())
                return clean if len(clean) <= limit else f"{clean[:limit]}..."

            event_queue: asyncio.Queue = asyncio.Queue()

            async def consume_dify_events():
                try:
                    async for event in dify_client.analyze_paper_stream(
                        pdf_url=paper.pdf_url,
                        title=paper.title,
                        user_id=f"paper-{paper_id}",
                        idea_input=idea_input,
                    ):
                        await event_queue.put(("event", event))
                except Exception as e:
                    await event_queue.put(("error", e))
                finally:
                    await event_queue.put(("done", None))

            consumer_task = asyncio.create_task(consume_dify_events())
            keepalive_interval = 15.0

            try:
                while True:
                    try:
                        kind, payload = await asyncio.wait_for(
                            event_queue.get(),
                            timeout=keepalive_interval,
                        )
                    except asyncio.TimeoutError:
                        yield f"event: ping\ndata: {json.dumps({'ts': datetime.utcnow().isoformat()})}\n\n"
                        continue

                    if kind == "event":
                        event = payload

                        if event.thought:
                            thought_parts.append(event.thought)
                            logger.info(
                                "Paper %s thought chunk (%d chars): %s",
                                paper_id,
                                len(event.thought),
                                _preview(event.thought),
                            )
                            yield f"event: thinking\ndata: {json.dumps({'thought': event.thought})}\n\n"

                        if event.answer:
                            answer_parts.append(event.answer)
                            logger.info(
                                "Paper %s answer chunk (%d chars): %s",
                                paper_id,
                                len(event.answer),
                                _preview(event.answer),
                            )
                            yield f"event: answer\ndata: {json.dumps({'answer': event.answer})}\n\n"

                        if event.event == "workflow_started":
                            logger.info("Paper %s workflow started", paper_id)
                            yield f"event: progress\ndata: {json.dumps({'status': 'workflow_started', 'message': 'Dify工作流已启动'})}\n\n"
                        elif event.event == "node_started":
                            node_title = event.data.get("data", {}).get("title", "")
                            if node_title:
                                logger.info("Paper %s node started: %s", paper_id, node_title)
                                yield f"event: progress\ndata: {json.dumps({'status': 'node_started', 'message': f'执行节点: {node_title}'})}\n\n"
                        elif event.event == "node_finished":
                            node_title = event.data.get("data", {}).get("title", "")
                            if node_title:
                                logger.info("Paper %s node finished: %s", paper_id, node_title)
                                yield f"event: progress\ndata: {json.dumps({'status': 'node_finished', 'message': f'完成节点: {node_title}'})}\n\n"
                        elif event.event == "workflow_finished":
                            logger.info("Paper %s workflow finished", paper_id)
                            if event.outputs:
                                final_outputs = event.outputs
                            elif not final_outputs:
                                data = event.data
                                if isinstance(data.get("data"), dict) and "outputs" in data["data"]:
                                    final_outputs = data["data"]["outputs"]
                                elif isinstance(data.get("outputs"), dict):
                                    final_outputs = data["outputs"]
                                elif isinstance(data.get("data"), dict):
                                    nested = data["data"]
                                    if "outputs" in nested:
                                        final_outputs = nested["outputs"]
                        elif event.event == "message_end":
                            if event.outputs and not final_outputs:
                                final_outputs = event.outputs
                        elif event.event == "error":
                            error_msg = event.data.get("message", "") or event.data.get("error", "Unknown Dify error")
                            raise DifyClientError(f"Dify error: {error_msg}")

                    elif kind == "error":
                        raise payload

                    elif kind == "done":
                        break
            finally:
                if not consumer_task.done():
                    consumer_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await consumer_task

            if final_outputs:
                result = dify_client._parse_outputs(final_outputs, "".join(thought_parts))
            elif answer_parts:
                result = dify_client._parse_answer("".join(answer_parts), "".join(thought_parts))
            else:
                raise DifyClientError("No output received from Dify workflow")

            analysis = dify_client.to_llm_analysis(result)

            if not paper.thumbnail_url:
                thumbnail_url = await generate_thumbnail(paper.arxiv_id, paper.pdf_url)
                if thumbnail_url:
                    paper.thumbnail_url = thumbnail_url

            paper.paper_essence = analysis.paper_essence
            paper.concept_bridging = analysis.concept_bridging_str
            paper.visual_verification = analysis.visual_verification
            paper.relevance_score = analysis.relevance_score
            paper.relevance_reason = analysis.relevance_reason
            paper.heuristic_suggestion = analysis.heuristic_suggestion
            paper.is_processed = True
            paper.processed_at = datetime.utcnow()

            if analysis.relevance_score >= 5:
                paper.processing_status = "processed"
            else:
                paper.processing_status = "skipped"

            session.add(paper)
            session.commit()

            result_data = {
                "paper_essence": result.paper_essence,
                "concept_bridging": {
                    "source_concept": result.concept_bridging.source_concept,
                    "target_concept": result.concept_bridging.target_concept,
                    "mechanism_transfer": result.concept_bridging.mechanism_transfer,
                },
                "visual_verification": result.visual_verification,
                "relevance_score": result.relevance_score,
                "relevance_reason": result.relevance_reason,
                "heuristic_suggestion": result.heuristic_suggestion,
                "thought_process": result.thought_process,
            }
            yield f"event: result\ndata: {json.dumps(result_data, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: {json.dumps({'status': 'completed'})}\n\n"
            logger.info("Paper %s processing completed", paper_id)

        except DifyEntityTooLargeError as e:
            paper.processing_status = "failed"
            session.add(paper)
            session.commit()
            logger.error("Paper %s failed (entity too large): %s", paper_id, e)
            yield f"event: error\ndata: {json.dumps({'error': 'entity_too_large', 'message': str(e)})}\n\n"

        except DifyTimeoutError as e:
            paper.processing_status = "failed"
            session.add(paper)
            session.commit()
            logger.error("Paper %s failed (timeout): %s", paper_id, e)
            yield f"event: error\ndata: {json.dumps({'error': 'timeout', 'message': str(e)})}\n\n"

        except DifyRateLimitError as e:
            paper.processing_status = "failed"
            session.add(paper)
            session.commit()
            logger.error("Paper %s failed (rate limit): %s", paper_id, e)
            yield f"event: error\ndata: {json.dumps({'error': 'rate_limit', 'message': str(e)})}\n\n"

        except DifyClientError as e:
            paper.processing_status = "failed"
            session.add(paper)
            session.commit()
            logger.error("Paper %s failed (dify error): %s", paper_id, e)
            yield f"event: error\ndata: {json.dumps({'error': 'dify_error', 'message': str(e)})}\n\n"

        except Exception as e:
            paper.processing_status = "failed"
            session.add(paper)
            session.commit()
            logger.exception("Paper %s failed (unknown error)", paper_id)
            yield f"event: error\ndata: {json.dumps({'error': 'unknown', 'message': str(e)})}\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
