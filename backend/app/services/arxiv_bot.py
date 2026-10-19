import asyncio
import arxiv
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from sqlalchemy import or_
from sqlmodel import Session, select

from app.logging_config import get_logger
from app.models import Paper, PaperCreate, AppSettings
from app.database import get_sync_session

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


MAX_CONCURRENT = 3
_fetch_lock = asyncio.Lock()


def _record_fetch_time() -> None:
    with get_sync_session() as session:
        settings = session.get(AppSettings, 1) or AppSettings(id=1)
        settings.last_fetch_at = datetime.utcnow()
        session.add(settings)
        session.commit()


async def fetch_and_save(max_results: int = 50, hours_back: int = 168) -> tuple[int, int]:
    """Fetch recent papers from arXiv and store new ones. Returns (fetched, saved)."""
    async with _fetch_lock:
        bot = get_arxiv_bot()
        with get_sync_session() as session:
            loop = asyncio.get_running_loop()
            papers = await loop.run_in_executor(
                None, bot.fetch_recent_papers, session, max_results, hours_back
            )
            saved = sum(1 for paper_data in papers if bot.save_paper(session, paper_data))
        _record_fetch_time()
        logger.info("Fetched %d papers from arXiv, %d new", len(papers), saved)
        return len(papers), saved


def pending_paper_ids() -> List[int]:
    with get_sync_session() as session:
        return list(session.exec(
            select(Paper.id).where(
                Paper.is_processed == False,
                or_(
                    Paper.processing_status == "pending",
                    Paper.processing_status == "failed",
                ),
            )
        ).all())


async def run_daily_fetch_async():
    """Fetch recent papers from arXiv, then analyze everything pending."""
    from app.services.analyzer import analyze_paper, reasoning_configured

    logger.info("Starting daily paper fetch")
    try:
        await fetch_and_save()
    except Exception as e:
        logger.error("Daily fetch failed: %s", e)
        return

    if not reasoning_configured():
        logger.info("No reasoning model configured — skipping analysis")
        return

    paper_ids = pending_paper_ids()
    logger.info("Analyzing %d papers (max %d concurrent)", len(paper_ids), MAX_CONCURRENT)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def run(paper_id: int) -> bool:
        async with semaphore:
            return await analyze_paper(paper_id)

    results = await asyncio.gather(*(run(pid) for pid in paper_ids))
    logger.info("Daily fetch completed: %d/%d papers analyzed", sum(results), len(paper_ids))


# Singleton instance
_arxiv_bot: Optional[ArxivBot] = None


def get_arxiv_bot() -> ArxivBot:
    """Get or create ArxivBot singleton."""
    global _arxiv_bot
    if _arxiv_bot is None:
        _arxiv_bot = ArxivBot()
    return _arxiv_bot
