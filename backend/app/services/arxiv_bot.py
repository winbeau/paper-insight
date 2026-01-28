import asyncio
import arxiv
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from sqlmodel import Session, select

from app.logging_config import get_logger
from app.models import Paper, PaperCreate, AppSettings
from app.database import get_sync_session
from app.services.pdf_renderer import generate_thumbnail
from app.services.dify_client import get_dify_client

logger = get_logger("services.arxiv_bot")


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

            if settings.focus_keywords and (not settings.research_focus or ";" in settings.research_focus):
                keywords_parts = []
                for k in settings.focus_keywords:
                    if " " in k and not (k.startswith('"') and k.endswith('"')):
                        term = f'"{k}"'
                    else:
                        term = k
                    keywords_parts.append(f'(all:{term})')

                if keywords_parts:
                    focus_query = f"({' OR '.join(keywords_parts)})"

            elif settings.research_focus and settings.research_focus.strip():
                focus_query = f"({settings.research_focus})"

        cat_query = "(" + " OR ".join([f"cat:{c}" for c in categories]) + ")"
        final_query = f"{cat_query} AND {focus_query}"

        return final_query

    def fetch_recent_papers(
        self,
        session: Session,
        max_results: int = 50,
        hours_back: int = 168,
    ) -> List[PaperCreate]:
        """Fetch recent targeted papers from arXiv."""
        query = self.build_query(session)
        logger.info("Executing arXiv query: %s", query)

        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )

        cutoff_date = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        papers = []

        for result in self.client.results(search):
            if result.published < cutoff_date:
                break

            paper = PaperCreate(
                arxiv_id=result.entry_id.split("/")[-1],
                title=result.title.replace("\n", " ").strip(),
                authors=", ".join([author.name for author in result.authors]),
                abstract=result.summary.replace("\n", " ").strip(),
                categories=", ".join(result.categories),
                published=result.published.astimezone(timezone.utc).replace(tzinfo=None),
                updated=result.updated.astimezone(timezone.utc).replace(tzinfo=None),
                pdf_url=result.pdf_url,
            )
            papers.append(paper)

        return papers

    def fetch_paper_by_id(self, arxiv_id: str) -> Optional[PaperCreate]:
        """Fetch a single paper from arXiv by its ID."""
        clean_id = arxiv_id.split('v')[0] if 'v' in arxiv_id else arxiv_id
        search = arxiv.Search(id_list=[clean_id])

        try:
            results = list(self.client.results(search))
            if not results:
                return None

            result = results[0]
            return PaperCreate(
                arxiv_id=result.entry_id.split("/")[-1],
                title=result.title.replace("\n", " ").strip(),
                authors=", ".join([author.name for author in result.authors]),
                abstract=result.summary.replace("\n", " ").strip(),
                categories=", ".join(result.categories),
                published=result.published.astimezone(timezone.utc).replace(tzinfo=None),
                updated=result.updated.astimezone(timezone.utc).replace(tzinfo=None),
                pdf_url=result.pdf_url,
            )
        except Exception as e:
            logger.error("Failed to fetch paper %s: %s", arxiv_id, e)
            return None

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
        """Process a paper with Dify LLM analysis and thumbnail generation."""
        if paper.is_processed:
            return False

        try:
            paper.processing_status = "processing"
            session.add(paper)
            session.commit()
            session.refresh(paper)

            client = get_dify_client()
            settings = session.get(AppSettings, 1)
            idea_input = settings.research_idea if settings and settings.research_idea else None

            result = await client.analyze_paper(
                pdf_url=paper.pdf_url,
                title=paper.title,
                user_id=f"batch-paper-{paper.id}",
                idea_input=idea_input,
            )

            thumbnail_url = await generate_thumbnail(paper.arxiv_id, paper.pdf_url)

            if thumbnail_url:
                paper.thumbnail_url = thumbnail_url

            if result:
                analysis = client.to_llm_analysis(result)
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
                logger.info("Paper %s processed (score=%.1f)", paper.arxiv_id, analysis.relevance_score)
                return True

            paper.processing_status = "failed"
            session.add(paper)
            session.commit()
            session.refresh(paper)

        except Exception as e:
            logger.error("Failed to process paper %s: %s", paper.arxiv_id, e)
            paper.processing_status = "failed"
            session.add(paper)
            session.commit()

        return False


async def run_daily_fetch_async():
    """Async wrapper for daily fetch logic."""
    logger.info("Starting daily paper fetch")

    bot = ArxivBot()
    session = get_sync_session()

    MAX_CONCURRENT = 3
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def process_with_semaphore(paper_id: int) -> bool:
        async with semaphore:
            task_session = get_sync_session()
            try:
                paper = task_session.get(Paper, paper_id)
                if not paper:
                    return False
                return await bot.process_paper(task_session, paper)
            finally:
                task_session.close()

    try:
        loop = asyncio.get_running_loop()
        papers = await loop.run_in_executor(None, bot.fetch_recent_papers, session, 50, 168)
        logger.info("Fetched %d papers from arXiv", len(papers))

        saved_count = 0
        for paper_data in papers:
            paper = bot.save_paper(session, paper_data)
            if paper:
                saved_count += 1
        logger.info("Saved %d new papers to database", saved_count)

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
            logger.warning("Reset %d stuck 'processing' papers to 'failed'", reset_count)

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

        paper_ids = [p.id for p in unprocessed]
        logger.info("Processing %d unprocessed papers (max %d concurrent)", len(paper_ids), MAX_CONCURRENT)

        tasks = [process_with_semaphore(pid) for pid in paper_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_count = sum(1 for r in results if r is True)
        error_count = sum(1 for r in results if isinstance(r, Exception))

        if error_count > 0:
            logger.warning("%d papers encountered errors during processing", error_count)

        logger.info("Processed %d papers with LLM analysis", processed_count)

    except Exception as e:
        logger.error("Daily fetch failed: %s", e)
    finally:
        session.close()

    logger.info("Daily fetch completed")

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
