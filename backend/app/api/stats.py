"""Statistics endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select
from sqlalchemy import func, or_

from app.models import Paper, ResearchDirection
from app.dependencies import get_session

router = APIRouter()


@router.get("/stats")
def get_stats(session: Session = Depends(get_session), direction_id: Optional[int] = Query(None)):
    """Get statistics about papers (optionally for one direction)."""
    query = select(Paper).where(
        or_(Paper.processing_status.is_(None), Paper.processing_status != "skipped")
    )
    if direction_id is not None:
        query = query.where(Paper.direction_id == direction_id)
    total = session.exec(query).all()
    processed = [p for p in total if p.is_processed]
    high_relevance = [p for p in processed if p.relevance_score and p.relevance_score >= 9]

    return {
        "total_papers": len(total),
        "processed_papers": len(processed),
        "high_relevance_papers": len(high_relevance),
        "pending_processing": len(total) - len(processed),
    }


@router.get("/directions")
def get_directions(session: Session = Depends(get_session)):
    """Research directions with per-direction counts (the home feed's tabs)."""
    directions = session.exec(
        select(ResearchDirection).order_by(ResearchDirection.position, ResearchDirection.id)
    ).all()
    rows = session.exec(
        select(Paper.direction_id, Paper.processing_status, Paper.is_processed, Paper.relevance_score)
    ).all()
    counts = {d.id: {"total": 0, "pending": 0, "processing": 0, "high": 0} for d in directions}
    for direction_id, status, is_processed, score in rows:
        c = counts.get(direction_id)
        if c is None or status == "skipped":
            continue
        c["total"] += 1
        if status == "processing":
            c["processing"] += 1
        elif not is_processed:
            c["pending"] += 1
        if score is not None and score >= 9:
            c["high"] += 1
    return [
        {"id": d.id, "name": d.name, "focus_keywords": d.focus_keywords or [], **counts[d.id]}
        for d in directions
    ]
