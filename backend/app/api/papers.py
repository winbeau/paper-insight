"""Papers CRUD endpoints."""

import re
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlmodel import Session, select
from sqlalchemy import or_

from app.logging_config import get_logger
from app.database import ensure_default_direction
from app.models import Paper, PaperRead, ResearchDirection
from app.dependencies import get_session
from app.services.analyzer import active_paper_ids
from app.services.arxiv_bot import get_arxiv_bot, pending_paper_ids, run_daily_fetch_async
from app.services.history import delete_papers

logger = get_logger("api.papers")

router = APIRouter()


@router.get("", response_model=List[PaperRead])
def get_papers(
    session: Session = Depends(get_session),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    min_score: Optional[float] = Query(None, ge=0, le=10),
    processed_only: bool = Query(False),
    direction_id: Optional[int] = Query(None),
):
    """Get papers with optional filtering."""
    query = select(Paper).where(
        or_(Paper.processing_status.is_(None), Paper.processing_status != "skipped")
    )
    if direction_id is not None:
        query = query.where(Paper.direction_id == direction_id)

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


@router.get("/pending")
def get_pending_paper_ids(
    session: Session = Depends(get_session),
    direction_id: Optional[int] = Query(None),
):
    """Get IDs of all pending/failed papers that need processing.

    Papers left in 'processing' that no run in this process owns are reset to 'pending'
    (papers being analyzed right now — e.g. by the scheduler — are left alone).
    """
    stuck_papers = session.exec(
        select(Paper).where(
            Paper.processing_status == "processing",
            Paper.is_processed == False,
            Paper.id.not_in(active_paper_ids()),
        )
    ).all()

    if stuck_papers:
        for paper in stuck_papers:
            paper.processing_status = "pending"
            session.add(paper)
        session.commit()

    return {"paper_ids": pending_paper_ids(direction_id)}


@router.get("/{paper_id}", response_model=PaperRead)
def get_paper(paper_id: int, session: Session = Depends(get_session)):
    """Get a specific paper by ID."""
    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.delete("/{paper_id}")
def delete_paper(paper_id: int, session: Session = Depends(get_session)):
    """Delete a paper; its cached files go too unless another direction still has it."""
    if not session.get(Paper, paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    result = delete_papers([paper_id])
    if result["skipped_active"]:
        raise HTTPException(status_code=409, detail="Paper is being analyzed")
    return {"message": "Paper deleted successfully", "paper_id": paper_id}


@router.post("/import")
def import_paper_from_arxiv(
    arxiv_url: str = Query(..., description="arXiv URL or ID"),
    direction_id: Optional[int] = Query(None, description="Direction to import into (default: first)"),
    session: Session = Depends(get_session),
):
    """Import a paper from arXiv by URL or ID."""
    # Parse arXiv ID from various URL formats
    arxiv_id = None
    arxiv_id_pattern = r'(\d{4}\.\d{4,5}(?:v\d+)?)'

    if 'arxiv.org' in arxiv_url:
        match = re.search(arxiv_id_pattern, arxiv_url)
        if match:
            arxiv_id = match.group(1)
    else:
        match = re.match(arxiv_id_pattern, arxiv_url.strip())
        if match:
            arxiv_id = match.group(1)

    if not arxiv_id:
        raise HTTPException(
            status_code=400,
            detail="Invalid arXiv URL or ID. Please provide a valid arXiv link or ID"
        )

    if direction_id is None or session.get(ResearchDirection, direction_id) is None:
        direction_id = ensure_default_direction()

    # Check if paper already exists in this direction
    existing = session.exec(
        select(Paper).where(
            Paper.direction_id == direction_id,
            Paper.arxiv_id.startswith(re.sub(r"v\d+$", "", arxiv_id)),
        )
    ).first()

    if existing:
        return {
            "message": "Paper already exists in database",
            "paper_id": existing.id,
            "arxiv_id": existing.arxiv_id,
            "title": existing.title,
            "is_new": False,
        }

    # Fetch paper from arXiv
    bot = get_arxiv_bot()
    paper_data = bot.fetch_paper_by_id(arxiv_id)

    if not paper_data:
        raise HTTPException(
            status_code=404,
            detail=f"Paper not found on arXiv: {arxiv_id}"
        )

    # Save to database
    paper = bot.save_paper(session, paper_data, direction_id)

    if not paper:
        existing = session.exec(
            select(Paper).where(Paper.arxiv_id == paper_data.arxiv_id, Paper.direction_id == direction_id)
        ).first()
        return {
            "message": "Paper already exists in database",
            "paper_id": existing.id if existing else None,
            "arxiv_id": paper_data.arxiv_id,
            "title": paper_data.title,
            "is_new": False,
        }

    return {
        "message": "Paper imported successfully",
        "paper_id": paper.id,
        "arxiv_id": paper.arxiv_id,
        "title": paper.title,
        "is_new": True,
    }


@router.get("/arxiv/{arxiv_id}", response_model=PaperRead)
def get_paper_by_arxiv_id(arxiv_id: str, session: Session = Depends(get_session)):
    """Get a specific paper by arXiv ID."""
    paper = session.exec(select(Paper).where(Paper.arxiv_id == arxiv_id)).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.post("/fetch")
def fetch_papers(background_tasks: BackgroundTasks):
    """Trigger paper fetching (and analysis) in the background."""
    background_tasks.add_task(run_daily_fetch_async)
    return {"message": "Paper fetch started in background"}
