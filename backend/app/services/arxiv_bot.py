import arxiv
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from sqlmodel import Session, select

from app.models import Paper, PaperCreate
from app.database import get_sync_session
from app.services.llm_brain import get_llm_brain

class ArxivBot:
    """Bot for fetching and processing arXiv papers."""

    def __init__(self):
        self.client = arxiv.Client(
            page_size=50,
            delay_seconds=3,
            num_retries=3
        )

    def build_query(self) -> str:
        """Builds a targeted arXiv query for DiT and KV Cache Compression."""
        # 1. Categories: CV, LG, CL
        categories = ['cs.CV', 'cs.LG', 'cs.CL']
        cat_query = "(" + " OR ".join([f"cat:{c}" for c in categories]) + ")"

        # 2. Keywords
        # Group A: Architecture (Transformer, Diffusion, DiT)
        group_a = '(ti:transformer OR ti:diffusion OR abs:transformer OR abs:diffusion OR abs:dit)'
        
        # Group B: Optimization (KV Cache, Compression, Pruning, Sparse, Quantization, Token)
        group_b = '(abs:"kv cache" OR abs:compression OR abs:pruning OR abs:sparse OR abs:quantization OR abs:token)'

        return f"{cat_query} AND {group_a} AND {group_b}"

    def fetch_recent_papers(
        self,
        max_results: int = 50,
        hours_back: int = 48,
    ) -> List[PaperCreate]:
        """Fetch recent targeted papers from arXiv."""
        query = self.build_query()
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

    def process_paper(self, session: Session, paper: Paper) -> bool:
        """Process a paper with LLM analysis."""
        if paper.is_processed:
            return False

        try:
            llm = get_llm_brain()
            analysis = llm.analyze_paper(paper.title, paper.abstract)

            if analysis:
                if analysis.relevance_score < 4:
                    print(f"Skipping paper {paper.arxiv_id} due to low relevance score: {analysis.relevance_score}")
                    return False

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
        # Fetch new papers using the optimized targeted query
        papers = bot.fetch_recent_papers(max_results=50, hours_back=48)
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