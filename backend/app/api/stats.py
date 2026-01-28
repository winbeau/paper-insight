"""Statistics endpoints."""

from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from sqlalchemy import or_

from app.models import Paper
from app.dependencies import get_session

router = APIRouter()


@router.get("/stats")
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
