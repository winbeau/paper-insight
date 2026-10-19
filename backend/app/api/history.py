"""History management: list, delete and clear paper entries; cache cleanup."""

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.dependencies import get_session
from app.models import Paper, ResearchDirection
from app.services.history import delete_papers, prune_orphan_files, storage_usage

router = APIRouter(prefix="/history")

Status = Literal["processed", "skipped", "failed", "pending", "processing"]


def _filtered(query, direction_id: Optional[int], status: Optional[str], q: str):
    if direction_id is not None:
        query = query.where(Paper.direction_id == direction_id)
    if status:
        query = query.where(Paper.processing_status == status)
    q = q.strip()
    if q:
        like = f"%{q}%"
        query = query.where(or_(Paper.title.ilike(like), Paper.arxiv_id.ilike(like)))
    return query


@router.get("")
def list_history(
    session: Session = Depends(get_session),
    direction_id: Optional[int] = Query(None),
    status: Optional[Status] = Query(None),
    q: str = Query(""),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """All paper entries (incl. low-relevance ones hidden from the feed), newest first."""
    total = session.exec(_filtered(select(func.count()).select_from(Paper), direction_id, status, q)).one()
    papers = session.exec(
        _filtered(select(Paper), direction_id, status, q)
        .order_by(Paper.created_at.desc(), Paper.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    names = {d.id: d.name for d in session.exec(select(ResearchDirection)).all()}
    return {
        "total": total,
        "items": [
            {
                "id": p.id,
                "arxiv_id": p.arxiv_id,
                "title": p.title,
                "direction_id": p.direction_id,
                "direction_name": names.get(p.direction_id, ""),
                "processing_status": p.processing_status,
                "relevance_score": p.relevance_score,
                "created_at": p.created_at,
                "published": p.published,
            }
            for p in papers
        ],
        "storage": storage_usage(),
    }


class DeleteRequest(BaseModel):
    paper_ids: List[int]
    delete_files: bool = True


class ClearRequest(BaseModel):
    """Delete every entry matching the filter (all entries when empty)."""
    direction_id: Optional[int] = None
    status: Optional[Status] = None
    q: str = ""
    delete_files: bool = True


@router.post("/delete")
def delete_entries(body: DeleteRequest):
    return delete_papers(body.paper_ids, body.delete_files)


@router.post("/clear")
def clear_entries(body: ClearRequest, session: Session = Depends(get_session)):
    ids = session.exec(_filtered(select(Paper.id), body.direction_id, body.status, body.q)).all()
    return delete_papers(ids, body.delete_files)


@router.post("/prune")
def prune_cache():
    """Remove cached files of papers that are no longer in any direction."""
    return {**prune_orphan_files(), "storage": storage_usage()}
