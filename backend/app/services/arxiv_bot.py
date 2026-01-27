import asyncio
import os
import arxiv
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from sqlmodel import Session, select

from app.models import Paper, PaperCreate, AppSettings
from app.database import get_sync_session
from app.services.pdf_renderer import generate_thumbnail


def _get_analysis_client():
    """
    Get the appropriate analysis client based on configuration.
    Prefers Dify if DIFY_API_KEY is set, otherwise falls back to LLMBrain.
    """
    if os.getenv("DIFY_API_KEY"):
        from app.services.dify_client import get_dify_client
        return get_dify_client(), "dify"
    else:
        from app.services.llm_brain import get_llm_brain
        return get_llm_brain(), "deepseek"

class ArxivBot:
    """Bot for fetching and processing arXiv papers."""

    def __init__(self):
        self.client = arxiv.Client(
            page_size=50,
            delay_seconds=3,
            num_retries=3
        )

    def build_query(self, session: Session) -> str:
        """Builds a targeted arXiv query using AppSettings or defaults."""
        settings = session.get(AppSettings, 1)
        
        # Defaults
        default_categories = ['cs.CV', 'cs.LG', 'cs.CL']
        default_focus = (
            '((ti:transformer OR abs:transformer OR ti:diffusion OR abs:diffusion OR ti:DiT OR abs:DiT) AND '
            '(ti:"kv cache" OR abs:"kv cache" OR ti:compression OR abs:compression OR ti:pruning OR abs:pruning OR '
            'ti:quantization OR abs:quantization OR ti:sparse OR abs:sparse OR ti:"token merging" OR abs:"token merging" OR '
            'ti:distillation OR abs:distillation OR ti:efficiency OR abs:efficiency))'
        )
        categories = default_categories
        focus_query = default_focus

        if settings:
            if settings.arxiv_categories:
                categories = settings.arxiv_categories
            
            # Use focus_keywords if available, otherwise fallback to research_focus string or default
            if settings.focus_keywords and (not settings.research_focus or ";" in settings.research_focus):
                # Construct OR logic for keywords: (all:k1) OR (all:"k 2")
                keywords_parts = []
                for k in settings.focus_keywords:
                    # Wrap in quotes if it contains spaces and isn't already quoted
                    if " " in k and not (k.startswith('"') and k.endswith('"')):
                        term = f'"{k}"'
                    else:
                        term = k
                    keywords_parts.append(f'(all:{term})')
                
                if keywords_parts:
                    focus_query = f"({' OR '.join(keywords_parts)})"
            
            elif settings.research_focus and settings.research_focus.strip():
                # Fallback to the raw string if keywords list is empty but string exists (backward compatibility)
                focus_query = f"({settings.research_focus})"
        
        # 1. Categories
        cat_query = "(" + " OR ".join([f"cat:{c}" for c in categories]) + ")"

        # 2. Combine
        final_query = f"{cat_query} AND {focus_query}"
        
        return final_query

    def fetch_recent_papers(
        self,
        session: Session,
        max_results: int = 50,
        hours_back: int = 168,  # 7 days to catch weekly arXiv updates
    ) -> List[PaperCreate]:
        """Fetch recent targeted papers from arXiv."""
        query = self.build_query(session)
        print(f"Executing Arxiv Query: {query}")

        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )

        # Use UTC aware time for comparison
        cutoff_date = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        papers = []

        for result in self.client.results(search):
            # Arxiv dates are timezone aware (UTC)
            if result.published < cutoff_date:
                # Since results are sorted descending, we can stop early
                break

            paper = PaperCreate(
                arxiv_id=result.entry_id.split("/")[-1],
                title=result.title.replace("\n", " ").strip(),
                authors=", ".join([author.name for author in result.authors]),
                abstract=result.summary.replace("\n", " ").strip(),
                categories=", ".join(result.categories),
                # Convert to naive UTC for DB storage
                published=result.published.astimezone(timezone.utc).replace(tzinfo=None),
                updated=result.updated.astimezone(timezone.utc).replace(tzinfo=None),
                pdf_url=result.pdf_url,
            )
            papers.append(paper)

        return papers

    def save_paper(self, session: Session, paper_data: PaperCreate) -> Optional[Paper]:
        """Save a paper to database if not exists."""
        existing = session.exec(
            select(Paper).where(Paper.arxiv_id == paper_data.arxiv_id)
        ).first()

        if existing:
            return None

        paper = Paper(**paper_data.model_dump())
        session.add(paper)
        session.commit()
        session.refresh(paper)
        return paper

    async def process_paper(self, session: Session, paper: Paper) -> bool:
        """Process a paper with LLM analysis and thumbnail generation."""
        if paper.is_processed:
            return False

        try:
            paper.processing_status = "processing"
            session.add(paper)
            session.commit()
            session.refresh(paper)

            # Get the appropriate analysis client
            client, client_type = _get_analysis_client()
            settings = session.get(AppSettings, 1)
            system_prompt_override = settings.system_prompt if settings else None

            # Execute analysis based on client type
            loop = asyncio.get_running_loop()

            if client_type == "dify":
                # Use Dify client with PDF upload (async)
                result = await client.analyze_paper(
                    pdf_url=paper.pdf_url,
                    title=paper.title,
                    user_id=f"batch-paper-{paper.id}",
                )
                if result:
                    analysis = client.to_llm_analysis(result)
                else:
                    analysis = None
            else:
                # Use legacy DeepSeek client (sync, run in executor)
                analysis = await loop.run_in_executor(
                    None,
                    client.analyze_paper,
                    paper.title,
                    paper.abstract,
                    system_prompt_override,
                )

            thumbnail_url = await generate_thumbnail(paper.arxiv_id, paper.pdf_url)

            # Update thumbnail regardless of relevance (visuals are good)
            if thumbnail_url:
                paper.thumbnail_url = thumbnail_url

            if analysis:
                paper.summary_zh = analysis.summary_zh
                paper.relevance_score = analysis.relevance_score
                paper.relevance_reason = analysis.relevance_reason
                paper.heuristic_idea = analysis.heuristic_idea
                paper.is_processed = True
                paper.processed_at = datetime.utcnow()

                if analysis.relevance_score >= 9:
                    paper.processing_status = "processed"
                elif analysis.relevance_score >= 5:
                    paper.processing_status = "processed"
                else:
                    paper.processing_status = "skipped"

                session.add(paper)
                session.commit()
                return True
            paper.processing_status = "failed"
            session.add(paper)
            session.commit()
            session.refresh(paper)

        except Exception as e:
            print(f"Error processing paper {paper.arxiv_id}: {e}")
            paper.processing_status = "failed"
            session.add(paper)
            session.commit()

        return False


async def run_daily_fetch_async():
    """Async wrapper for daily fetch logic."""
    print(f"[{datetime.now()}] Starting daily paper fetch...")

    bot = ArxivBot()
    session = get_sync_session()

    # Concurrency limit for paper processing
    MAX_CONCURRENT = 3
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def process_with_semaphore(paper_id: int) -> bool:
        """Process a paper with semaphore-controlled concurrency and its own session."""
        async with semaphore:
            # Create a new session for each concurrent task to avoid session conflicts
            task_session = get_sync_session()
            try:
                paper = task_session.get(Paper, paper_id)
                if not paper:
                    return False
                return await bot.process_paper(task_session, paper)
            finally:
                task_session.close()

    try:
        # Fetch new papers (Sync)
        # Using run_in_executor to avoid blocking the event loop if this takes time
        # We pass the session to fetch_recent_papers
        loop = asyncio.get_running_loop()
        papers = await loop.run_in_executor(None, bot.fetch_recent_papers, session, 50, 168)
        print(f"Fetched {len(papers)} papers from arXiv")

        # Save to database (Sync)
        saved_count = 0
        for paper_data in papers:
            paper = bot.save_paper(session, paper_data)
            if paper:
                saved_count += 1
        print(f"Saved {saved_count} new papers to database")

        # Reset stuck "processing" papers (processing for too long)
        # Since we don't have a "processing_started_at" field, reset all stuck papers
        stuck_papers = session.exec(
            select(Paper).where(
                Paper.processing_status == "processing",
                Paper.is_processed == False,
            )
        ).all()

        reset_count = 0
        for paper in stuck_papers:
            paper.processing_status = "failed"
            session.add(paper)
            reset_count += 1

        if reset_count > 0:
            session.commit()
            print(f"Reset {reset_count} stuck 'processing' papers to 'failed'")

        # Process unprocessed papers (Async with concurrency limit)
        # Include: new papers (pending status) and failed papers (for retry)
        from sqlalchemy import or_
        unprocessed = session.exec(
            select(Paper).where(
                Paper.is_processed == False,
                or_(
                    Paper.processing_status == "pending",
                    Paper.processing_status == "failed",
                ),
            )
        ).all()

        # Extract paper IDs for concurrent processing (avoid passing detached objects)
        paper_ids = [p.id for p in unprocessed]
        print(f"Processing {len(paper_ids)} unprocessed papers (max {MAX_CONCURRENT} concurrent)...")

        # Process papers concurrently with semaphore limit
        # Each task gets its own session to avoid conflicts
        tasks = [process_with_semaphore(pid) for pid in paper_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_count = sum(1 for r in results if r is True)
        error_count = sum(1 for r in results if isinstance(r, Exception))

        if error_count > 0:
            print(f"  {error_count} papers encountered errors during processing")

        print(f"Processed {processed_count} papers with LLM analysis")

    except Exception as e:
        print(f"Error in daily fetch: {e}")
    finally:
        session.close()

    print(f"[{datetime.now()}] Daily fetch completed")

def run_daily_fetch():
    """Entry point that runs the async fetcher in a loop."""
    asyncio.run(run_daily_fetch_async())


# Singleton instance
_arxiv_bot: Optional[ArxivBot] = None


def get_arxiv_bot() -> ArxivBot:
    """Get or create ArxivBot singleton."""
    global _arxiv_bot
    if _arxiv_bot is None:
        _arxiv_bot = ArxivBot()
    return _arxiv_bot
