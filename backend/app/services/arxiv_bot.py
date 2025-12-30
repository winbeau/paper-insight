import arxiv
from datetime import datetime, timedelta
from typing import List, Optional
from sqlmodel import Session, select

from app.models import Paper, PaperCreate
from app.database import get_sync_session
from app.services.llm_brain import get_llm_brain

# Research-focused search queries
SEARCH_QUERIES = [
    "Diffusion Transformer DiT",
    "autoregressive image generation",
    "KV cache compression LLM",
    "attention cache optimization",
    "transformer inference efficiency",
    "visual autoregressive model",
]


class ArxivBot:
    """Bot for fetching and processing arXiv papers."""

    def __init__(self):
        self.client = arxiv.Client()

    def fetch_papers(
        self,
        query: str,
        max_results: int = 20,
        days_back: int = 7,
    ) -> List[PaperCreate]:
        """Fetch recent papers from arXiv based on query."""
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )

        cutoff_date = datetime.now() - timedelta(days=days_back)
        papers = []

        for result in self.client.results(search):
            # Filter by date
            if result.published.replace(tzinfo=None) < cutoff_date:
                continue

            paper = PaperCreate(
                arxiv_id=result.entry_id.split("/")[-1],
                title=result.title.replace("\n", " ").strip(),
                authors=", ".join([author.name for author in result.authors]),
                abstract=result.summary.replace("\n", " ").strip(),
                categories=", ".join(result.categories),
                published=result.published.replace(tzinfo=None),
                updated=result.updated.replace(tzinfo=None),
                pdf_url=result.pdf_url,
            )
            papers.append(paper)

        return papers

    def fetch_all_topics(
        self,
        max_results_per_query: int = 15,
        days_back: int = 7,
    ) -> List[PaperCreate]:
        """Fetch papers for all research topics."""
        all_papers = []
        seen_ids = set()

        for query in SEARCH_QUERIES:
            papers = self.fetch_papers(
                query=query,
                max_results=max_results_per_query,
                days_back=days_back,
            )
            for paper in papers:
                if paper.arxiv_id not in seen_ids:
                    seen_ids.add(paper.arxiv_id)
                    all_papers.append(paper)

        return all_papers

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

    def process_paper(self, session: Session, paper: Paper) -> bool:
        """Process a paper with LLM analysis."""
        if paper.is_processed:
            return False

        try:
            llm = get_llm_brain()
            analysis = llm.analyze_paper(paper.title, paper.abstract)

            if analysis:
                paper.summary_zh = analysis.summary_zh
                paper.relevance_score = analysis.relevance_score
                paper.relevance_reason = analysis.relevance_reason
                paper.heuristic_idea = analysis.heuristic_idea
                paper.is_processed = True
                paper.processed_at = datetime.utcnow()

                session.add(paper)
                session.commit()
                return True

        except Exception as e:
            print(f"Error processing paper {paper.arxiv_id}: {e}")

        return False


def run_daily_fetch():
    """Run daily paper fetch and processing job."""
    print(f"[{datetime.now()}] Starting daily paper fetch...")

    bot = ArxivBot()
    session = get_sync_session()

    try:
        # Fetch new papers
        papers = bot.fetch_all_topics(max_results_per_query=15, days_back=3)
        print(f"Fetched {len(papers)} papers from arXiv")

        # Save to database
        saved_count = 0
        for paper_data in papers:
            paper = bot.save_paper(session, paper_data)
            if paper:
                saved_count += 1
        print(f"Saved {saved_count} new papers to database")

        # Process unprocessed papers
        unprocessed = session.exec(
            select(Paper).where(Paper.is_processed == False)
        ).all()
        print(f"Processing {len(unprocessed)} unprocessed papers...")

        processed_count = 0
        for paper in unprocessed:
            if bot.process_paper(session, paper):
                processed_count += 1
                print(f"  Processed: {paper.title[:50]}...")

        print(f"Processed {processed_count} papers with LLM analysis")

    except Exception as e:
        print(f"Error in daily fetch: {e}")
    finally:
        session.close()

    print(f"[{datetime.now()}] Daily fetch completed")


# Singleton instance
_arxiv_bot: Optional[ArxivBot] = None


def get_arxiv_bot() -> ArxivBot:
    """Get or create ArxivBot singleton."""
    global _arxiv_bot
    if _arxiv_bot is None:
        _arxiv_bot = ArxivBot()
    return _arxiv_bot
