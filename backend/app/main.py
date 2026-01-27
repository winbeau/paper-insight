from contextlib import asynccontextmanager
from typing import List, Optional
import re
import json
from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pathlib import Path
from sqlmodel import Session, select
from sqlalchemy import or_
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import create_db_and_tables, ensure_appsettings_schema, ensure_paper_schema, get_session, get_sync_session
from app.models import Paper, PaperRead, AppSettings
from app.services.arxiv_bot import get_arxiv_bot, run_daily_fetch
from app.services.dify_client import (
    get_dify_client,
    DifyClientError,
    DifyEntityTooLargeError,
    DifyTimeoutError,
    DifyRateLimitError,
)
from app.services.pdf_renderer import generate_thumbnail
from app.constants import ARXIV_OPTIONS

# Global scheduler instance
scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    ensure_appsettings_schema()
    ensure_paper_schema()

    # Start APScheduler for daily paper fetching
    # Schedule at 06:00 UTC daily
    scheduler.add_job(
        run_daily_fetch,
        CronTrigger(hour=6, minute=0),
        id="daily_paper_fetch",
        name="Daily Paper Fetch",
        replace_existing=True,
    )
    scheduler.start()
    print("[Scheduler] Started - Daily paper fetch scheduled at 06:00 UTC")

    yield

    # Shutdown scheduler gracefully
    scheduler.shutdown(wait=False)
    print("[Scheduler] Shutdown complete")


app = FastAPI(
    title="Paper Insight API",
    description="API for fetching and summarizing arXiv papers focused on Autoregressive DiT and KV Cache Compression",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
static_path = Path(__file__).parent / "static"
static_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_path), name="static")


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/constants")
def get_constants():
    """Get application constants."""
    return {"arxiv_options": ARXIV_OPTIONS}


@app.get("/settings", response_model=AppSettings)
def get_settings(session: Session = Depends(get_session)):
    """Get application settings."""
    settings = session.get(AppSettings, 1)
    if not settings:
        settings = AppSettings(id=1)
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings


@app.put("/settings", response_model=AppSettings)
def update_settings(new_settings: AppSettings, session: Session = Depends(get_session)):
    """Update application settings."""
    settings = session.get(AppSettings, 1)
    if not settings:
        settings = AppSettings(id=1)
        session.add(settings)
    
    settings.research_focus = new_settings.research_focus
    settings.system_prompt = new_settings.system_prompt
    settings.arxiv_categories = new_settings.arxiv_categories
    
    # Parse focus keywords
    if new_settings.research_focus:
        raw_focus = new_settings.research_focus.strip()
        if ";" in raw_focus:
            keywords = [
                k.strip() for k in re.split(r"[;]+", raw_focus)
                if k.strip()
            ]
        else:
            parts = re.split(r"\bOR\b|\bAND\b", raw_focus, flags=re.IGNORECASE)
            keywords = []
            for part in parts:
                cleaned = part.strip()
                if not cleaned:
                    continue
                cleaned = re.sub(r"^[()]+|[()]+$", "", cleaned).strip()
                cleaned = re.sub(r"^(?:all|abs|ti):", "", cleaned, flags=re.IGNORECASE).strip()
                cleaned = cleaned.strip('"').strip()
                if cleaned:
                    keywords.append(cleaned)

            seen = set()
            deduped = []
            for keyword in keywords:
                if keyword not in seen:
                    deduped.append(keyword)
                    seen.add(keyword)
            keywords = deduped

        settings.focus_keywords = keywords
    else:
        settings.focus_keywords = []
    
    session.add(settings)
    session.commit()
    session.refresh(settings)
    return settings


@app.get("/papers", response_model=List[PaperRead])
def get_papers(
    session: Session = Depends(get_session),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    min_score: Optional[float] = Query(None, ge=0, le=10),
    processed_only: bool = Query(False),
):
    """Get papers with optional filtering."""
    query = select(Paper).where(
        or_(Paper.processing_status.is_(None), Paper.processing_status != "skipped")
    )

    if processed_only:
        query = query.where(Paper.is_processed == True)

    if min_score is not None:
        query = query.where(Paper.relevance_score >= min_score)

    query = query.order_by(
        Paper.is_processed.desc(),
        Paper.relevance_score.desc().nulls_last(),
        Paper.published.desc()
    ).offset(skip).limit(limit)
    papers = session.exec(query).all()
    return papers


@app.get("/papers/pending")
def get_pending_paper_ids(session: Session = Depends(get_session)):
    """Get IDs of all pending/failed papers that need processing.

    Also resets any stuck 'processing' papers to 'pending' so they can be retried.
    This handles cases where the frontend was refreshed during processing.
    """
    # First, reset any stuck "processing" papers (no active stream after page refresh)
    stuck_papers = session.exec(
        select(Paper).where(
            Paper.processing_status == "processing",
            Paper.is_processed == False,
        )
    ).all()

    if stuck_papers:
        for paper in stuck_papers:
            paper.processing_status = "pending"
            session.add(paper)
        session.commit()

    # Then get all papers that need processing
    papers = session.exec(
        select(Paper.id).where(
            Paper.is_processed == False,
            or_(
                Paper.processing_status == "pending",
                Paper.processing_status == "failed",
            ),
        )
    ).all()
    return {"paper_ids": papers}


@app.get("/papers/{paper_id}", response_model=PaperRead)
def get_paper(paper_id: int, session: Session = Depends(get_session)):
    """Get a specific paper by ID."""
    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@app.delete("/papers/{paper_id}")
def delete_paper(paper_id: int, session: Session = Depends(get_session)):
    """Delete a specific paper by ID, including associated thumbnail."""
    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Delete thumbnail file if exists
    if paper.thumbnail_url:
        # thumbnail_url format: /static/thumbnails/{arxiv_id}.jpg
        thumbnail_path = Path(__file__).parent / paper.thumbnail_url.lstrip("/")
        if thumbnail_path.exists():
            try:
                thumbnail_path.unlink()
            except Exception as e:
                print(f"Warning: Failed to delete thumbnail {thumbnail_path}: {e}")

    # Delete paper from database
    session.delete(paper)
    session.commit()
    return {"message": "Paper deleted successfully", "paper_id": paper_id}


@app.get("/papers/arxiv/{arxiv_id}", response_model=PaperRead)
def get_paper_by_arxiv_id(arxiv_id: str, session: Session = Depends(get_session)):
    """Get a specific paper by arXiv ID."""
    paper = session.exec(select(Paper).where(Paper.arxiv_id == arxiv_id)).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@app.post("/papers/fetch")
def fetch_papers(
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """Trigger paper fetching in the background."""
    background_tasks.add_task(run_daily_fetch)
    return {"message": "Paper fetch started in background"}


@app.get("/papers/fetch/stream")
async def fetch_papers_stream(session: Session = Depends(get_session)):
    """
    Fetch papers from arXiv with streaming progress updates.
    Only fetches and saves papers - does NOT process them.
    Use /papers/pending to get IDs for processing via individual streams.

    Returns Server-Sent Events (SSE) with the following event types:
    - started: Fetch started
    - fetching: Fetching from arXiv
    - saving: Saving papers to database
    - done: Fetch completed with count of new papers
    """
    import asyncio

    async def generate_events():
        try:
            yield f"event: started\ndata: {json.dumps({'status': 'started'})}\n\n"
            yield f"event: fetching\ndata: {json.dumps({'status': 'fetching', 'message': '正在从 arXiv 获取论文...'})}\n\n"

            bot = get_arxiv_bot()

            # Fetch papers from arXiv (sync operation, run in executor)
            loop = asyncio.get_running_loop()
            papers = await loop.run_in_executor(None, bot.fetch_recent_papers, session, 50, 168)

            yield f"event: fetched\ndata: {json.dumps({'status': 'fetched', 'message': f'获取到 {len(papers)} 篇论文', 'count': len(papers)})}\n\n"
            yield f"event: saving\ndata: {json.dumps({'status': 'saving', 'message': '正在保存到数据库...'})}\n\n"

            # Save papers to database
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


@app.post("/papers/process/batch")
def process_papers_batch(
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """Trigger batch processing of all pending/failed papers."""
    from sqlalchemy import or_

    # Count papers to process
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


@app.get("/papers/process/batch/stream")
async def process_papers_batch_stream(session: Session = Depends(get_session)):
    """
    Process all pending/failed papers with streaming progress updates.

    Returns Server-Sent Events (SSE) with the following event types:
    - started: Batch processing started with total count
    - paper_processing: A paper started processing
    - paper_completed: A paper finished processing successfully
    - paper_failed: A paper failed to process
    - done: All papers processed
    """
    import asyncio
    from sqlalchemy import or_

    # Reset stuck "processing" papers so they can be retried in this batch
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

    # Get papers to process
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

        # Event queue for real-time streaming
        event_queue: asyncio.Queue = asyncio.Queue()

        async def process_paper_with_events(paper_id: int):
            nonlocal processed_count, failed_count
            async with semaphore:
                task_session = get_sync_session()
                try:
                    paper = task_session.get(Paper, paper_id)
                    if not paper:
                        return None

                    # Emit paper_processing event when starting
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

        # Start all tasks
        tasks = [asyncio.create_task(process_paper_with_events(pid)) for pid in paper_ids]

        # Yield events as they come in while tasks are running
        all_done = False
        while not all_done or not event_queue.empty():
            # Check if all tasks are done
            all_done = all(t.done() for t in tasks)

            # Yield queued events with timeout
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


@app.post("/papers/{paper_id}/process")
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


@app.get("/papers/{paper_id}/process/stream")
async def process_paper_stream(paper_id: int, session: Session = Depends(get_session)):
    """
    Process a paper with streaming response for real-time updates.

    Returns Server-Sent Events (SSE) with the following event types:
    - thinking: R1 reasoning process (thought field)
    - answer: Partial answer content
    - progress: Processing progress updates
    - result: Final structured analysis result
    - error: Error information
    - done: Stream completion signal
    """
    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    async def generate_events():
        """Generate SSE events for paper analysis."""
        try:
            # Update paper status
            paper.processing_status = "processing"
            session.add(paper)
            session.commit()

            # Send initial progress event
            yield f"event: progress\ndata: {json.dumps({'status': 'started', 'message': '开始下载PDF...'})}\n\n"

            dify_client = get_dify_client()
            thought_parts = []
            answer_parts = []
            final_outputs = None

            async for event in dify_client.analyze_paper_stream(
                pdf_url=paper.pdf_url,
                title=paper.title,
                user_id=f"paper-{paper_id}",
            ):
                # Handle thought (R1 thinking process)
                if event.thought:
                    thought_parts.append(event.thought)
                    yield f"event: thinking\ndata: {json.dumps({'thought': event.thought})}\n\n"

                # Handle answer chunks
                if event.answer:
                    answer_parts.append(event.answer)
                    yield f"event: answer\ndata: {json.dumps({'answer': event.answer})}\n\n"

                # Handle workflow events
                if event.event == "workflow_started":
                    yield f"event: progress\ndata: {json.dumps({'status': 'workflow_started', 'message': 'Dify工作流已启动'})}\n\n"
                elif event.event == "node_started":
                    node_title = event.data.get("data", {}).get("title", "")
                    if node_title:
                        yield f"event: progress\ndata: {json.dumps({'status': 'node_started', 'message': f'执行节点: {node_title}'})}\n\n"
                elif event.event == "node_finished":
                    node_title = event.data.get("data", {}).get("title", "")
                    if node_title:
                        yield f"event: progress\ndata: {json.dumps({'status': 'node_finished', 'message': f'完成节点: {node_title}'})}\n\n"
                elif event.event == "workflow_finished":
                    if event.outputs:
                        final_outputs = event.outputs

            # Process final result
            if final_outputs:
                result = dify_client._parse_outputs(final_outputs, "".join(thought_parts))
            elif answer_parts:
                result = dify_client._parse_answer("".join(answer_parts), "".join(thought_parts))
            else:
                raise DifyClientError("No output received from Dify workflow")

            # Convert to LLMAnalysis for database storage
            analysis = dify_client.to_llm_analysis(result)

            # Generate thumbnail if not already present
            if not paper.thumbnail_url:
                thumbnail_url = await generate_thumbnail(paper.arxiv_id, paper.pdf_url)
                if thumbnail_url:
                    paper.thumbnail_url = thumbnail_url

            # Update paper with results
            from datetime import datetime
            paper.summary_zh = analysis.summary_zh
            paper.relevance_score = analysis.relevance_score
            paper.relevance_reason = analysis.relevance_reason
            paper.heuristic_idea = analysis.heuristic_idea
            paper.is_processed = True
            paper.processed_at = datetime.utcnow()

            if analysis.relevance_score >= 5:
                paper.processing_status = "processed"
            else:
                paper.processing_status = "skipped"

            session.add(paper)
            session.commit()

            # Send final result
            result_data = {
                "summary_zh": result.summary_zh,
                "relevance_score": result.relevance_score,
                "relevance_reason": result.relevance_reason,
                "technical_mapping": {
                    "token_vs_patch": result.technical_mapping.token_vs_patch,
                    "temporal_logic": result.technical_mapping.temporal_logic,
                    "frequency_domain": result.technical_mapping.frequency_domain,
                },
                "heuristic_idea": result.heuristic_idea,
                "thought_process": result.thought_process,
            }
            yield f"event: result\ndata: {json.dumps(result_data, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: {json.dumps({'status': 'completed'})}\n\n"

        except DifyEntityTooLargeError as e:
            paper.processing_status = "failed"
            session.add(paper)
            session.commit()
            yield f"event: error\ndata: {json.dumps({'error': 'entity_too_large', 'message': str(e)})}\n\n"

        except DifyTimeoutError as e:
            paper.processing_status = "failed"
            session.add(paper)
            session.commit()
            yield f"event: error\ndata: {json.dumps({'error': 'timeout', 'message': str(e)})}\n\n"

        except DifyRateLimitError as e:
            paper.processing_status = "failed"
            session.add(paper)
            session.commit()
            yield f"event: error\ndata: {json.dumps({'error': 'rate_limit', 'message': str(e)})}\n\n"

        except DifyClientError as e:
            paper.processing_status = "failed"
            session.add(paper)
            session.commit()
            yield f"event: error\ndata: {json.dumps({'error': 'dify_error', 'message': str(e)})}\n\n"

        except Exception as e:
            paper.processing_status = "failed"
            session.add(paper)
            session.commit()
            yield f"event: error\ndata: {json.dumps({'error': 'unknown', 'message': str(e)})}\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@app.get("/stats")
def get_stats(session: Session = Depends(get_session)):
    """Get statistics about papers."""
    total = session.exec(
        select(Paper).where(
            or_(Paper.processing_status.is_(None), Paper.processing_status != "skipped")
        )
    ).all()
    processed = [p for p in total if p.is_processed]
    high_relevance = [p for p in processed if p.relevance_score and p.relevance_score >= 9]

    return {
        "total_papers": len(total),
        "processed_papers": len(processed),
        "high_relevance_papers": len(high_relevance),
        "pending_processing": len(total) - len(processed),
    }
