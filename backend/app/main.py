from contextlib import asynccontextmanager
from typing import List, Optional
import re
from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from sqlmodel import Session, select
from sqlalchemy import or_

from app.database import create_db_and_tables, ensure_appsettings_schema, ensure_paper_schema, get_session
from app.models import Paper, PaperRead, AppSettings
from app.services.arxiv_bot import get_arxiv_bot, run_daily_fetch
from app.constants import ARXIV_OPTIONS


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    ensure_appsettings_schema()
    ensure_paper_schema()
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
