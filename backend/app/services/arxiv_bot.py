import asyncio
import re

import arxiv
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from sqlalchemy import or_
from sqlmodel import Session, select

from app.logging_config import get_logger
from app.models import AppSettings, Paper, PaperCreate, ResearchDirection
from app.database import get_sync_session

logger = get_logger("services.arxiv_bot")


DEFAULT_CATEGORIES = ["cs.CV", "cs.LG", "cs.CL"]
DEFAULT_FOCUS = (
    '((ti:transformer OR abs:transformer OR ti:diffusion OR abs:diffusion OR ti:DiT OR abs:DiT) AND '
    '(ti:"kv cache" OR abs:"kv cache" OR ti:compression OR abs:compression OR ti:pruning OR abs:pruning OR '
    'ti:quantization OR abs:quantization OR ti:sparse OR abs:sparse OR ti:"token merging" OR abs:"token merging" OR '
    'ti:distillation OR abs:distillation OR ti:efficiency OR abs:efficiency))'
)


def compose_query(categories: List[str], research_focus: str, focus_keywords: List[str]) -> str:
    """The arXiv search query the daily fetch uses: (categories) AND (focus).

    A ';'-separated focus is treated as a keyword list (OR of all:keyword); anything else
    is used as a raw arXiv query. Shared with the research-direction agent so the query it
    tests is exactly the one that will run.
    """
    categories = categories or DEFAULT_CATEGORIES
    focus_query = DEFAULT_FOCUS
    if focus_keywords and (not research_focus or ";" in research_focus):
        parts = []
        for keyword in focus_keywords:
            term = f'"{keyword}"' if " " in keyword and not (keyword.startswith('"') and keyword.endswith('"')) else keyword
            parts.append(f"(all:{term})")
        if parts:
            focus_query = f"({' OR '.join(parts)})"
    elif research_focus and research_focus.strip():
        focus_query = f"({research_focus.strip()})"
    cat_query = "(" + " OR ".join(f"cat:{c}" for c in categories) + ")"
    return f"{cat_query} AND {focus_query}"


class ArxivBot:
    """Bot for fetching and processing arXiv papers."""

    def __init__(self):
        self.client = arxiv.Client(
            page_size=50,
            delay_seconds=3,
            num_retries=3
        )

    def fetch_recent_papers(
        self,
        query: str,
        max_results: int = 50,
        hours_back: int = 168,
    ) -> List[PaperCreate]:
        """Fetch recent papers matching an arXiv query (see compose_query)."""
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

    def save_paper(self, session: Session, paper_data: PaperCreate, direction_id: int) -> Optional[Paper]:
        """Save a paper into a direction unless that direction already has it."""
        base_id = re.sub(r"v\d+$", "", paper_data.arxiv_id)  # any version counts as the same paper
        existing = session.exec(
            select(Paper).where(
                Paper.direction_id == direction_id,
                Paper.arxiv_id.startswith(base_id),
            )
        ).first()

        if existing:
            return None

        paper = Paper(**paper_data.model_dump(), direction_id=direction_id)
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


def query_for_direction(direction: ResearchDirection) -> str:
    return compose_query(
        direction.arxiv_categories or [],
        direction.research_focus or "",
        direction.focus_keywords or [],
    )


def list_directions() -> List[ResearchDirection]:
    with get_sync_session() as session:
        return list(session.exec(
            select(ResearchDirection).order_by(ResearchDirection.position, ResearchDirection.id)
        ).all())


async def fetch_and_save(
    direction_id: Optional[int] = None, max_results: int = 50, hours_back: int = 168
) -> tuple[int, int]:
    """Fetch recent papers for one direction (or all) and store new ones.

    Directions are fetched one after another under a lock (arXiv asks for slow,
    sequential clients). Returns (fetched, saved) summed over the directions.
    """
    directions = [d for d in list_directions() if direction_id is None or d.id == direction_id]
    if not directions:
        raise ValueError("research direction not found")
    fetched_total = saved_total = 0
    async with _fetch_lock:
        bot = get_arxiv_bot()
        loop = asyncio.get_running_loop()
        for direction in directions:
            papers = await loop.run_in_executor(
                None, bot.fetch_recent_papers, query_for_direction(direction), max_results, hours_back
            )
            with get_sync_session() as session:
                saved = sum(1 for data in papers if bot.save_paper(session, data, direction.id))
            logger.info("Direction %s (%s): fetched %d papers, %d new", direction.id, direction.name, len(papers), saved)
            fetched_total += len(papers)
            saved_total += saved
        _record_fetch_time()
    return fetched_total, saved_total


def pending_paper_ids(direction_id: Optional[int] = None) -> List[int]:
    with get_sync_session() as session:
        query = select(Paper.id).where(
            Paper.is_processed == False,
            or_(
                Paper.processing_status == "pending",
                Paper.processing_status == "failed",
            ),
        )
        if direction_id is not None:
            query = query.where(Paper.direction_id == direction_id)
        return list(session.exec(query.order_by(Paper.id)).all())


def prefetch_parses(paper_ids: List[int]) -> int:
    """Queue MinerU parsing for these papers right away (see services.parse_queue)."""
    from app.schemas import load_settings
    from app.services.errors import PipelineError
    from app.services.parse_queue import ParseTarget, get_parse_queue
    from app.services.parsers import validate_parser_config

    with get_sync_session() as session:
        settings = load_settings(session.get(AppSettings, 1))
        papers = [session.get(Paper, pid) for pid in paper_ids]
        targets = [
            ParseTarget(arxiv_id=p.arxiv_id, title=p.title, pdf_url=p.pdf_url)
            for p in papers
            if p is not None and not p.is_processed
        ]
    try:
        validate_parser_config(settings.pipeline.parser)
    except PipelineError as e:
        logger.info("Parse prefetch skipped: %s", e.message)
        return 0
    return get_parse_queue().prefetch(targets, settings.pipeline.parser)


async def run_daily_fetch_async():
    """Fetch recent papers from arXiv, then analyze everything pending."""
    from app.services.analyzer import analyze_paper, current_generation, reasoning_configured

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
    prefetch_parses(paper_ids)
    generation = current_generation()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def run(paper_id: int) -> bool:
        async with semaphore:
            if current_generation() != generation:
                return False  # "stop all" was pressed: don't start more papers
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
