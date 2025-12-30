from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

from app.database import create_db_and_tables, get_session
from app.models import Paper, PaperRead
from app.services.arxiv_bot import get_arxiv_bot, run_daily_fetch


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


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


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/papers", response_model=List[PaperRead])
def get_papers(
    session: Session = Depends(get_session),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    min_score: Optional[float] = Query(None, ge=0, le=10),
    processed_only: bool = Query(False),
):
    """Get papers with optional filtering."""
    query = select(Paper)

    if processed_only:
        query = query.where(Paper.is_processed == True)

    if min_score is not None:
        query = query.where(Paper.relevance_score >= min_score)

    query = query.order_by(Paper.published.desc()).offset(skip).limit(limit)
    papers = session.exec(query).all()
    return papers


@app.get("/papers/{paper_id}", response_model=PaperRead)
def get_paper(paper_id: int, session: Session = Depends(get_session)):
    """Get a specific paper by ID."""
    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


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


@app.post("/papers/{paper_id}/process")
def process_paper(paper_id: int, session: Session = Depends(get_session)):
    """Process a specific paper with LLM analysis."""
    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    if paper.is_processed:
        return {"message": "Paper already processed", "paper_id": paper_id}

    bot = get_arxiv_bot()
    success = bot.process_paper(session, paper)

    if success:
        return {"message": "Paper processed successfully", "paper_id": paper_id}
    else:
        raise HTTPException(status_code=500, detail="Failed to process paper")


@app.get("/stats")
def get_stats(session: Session = Depends(get_session)):
    """Get statistics about papers."""
    total = session.exec(select(Paper)).all()
    processed = [p for p in total if p.is_processed]
    high_relevance = [p for p in processed if p.relevance_score and p.relevance_score >= 7]

    return {
        "total_papers": len(total),
        "processed_papers": len(processed),
        "high_relevance_papers": len(high_relevance),
        "pending_processing": len(total) - len(processed),
    }
