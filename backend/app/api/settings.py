"""Settings endpoints."""

import re
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete
from sqlmodel import Session, select

from app.dependencies import get_session
from app.models import AppSettings, Paper, ResearchDirection
from app.schemas import (
    AppSettingsRead,
    AppSettingsUpdate,
    Direction,
    load_settings,
    masked,
    unmask_pipeline,
    unmask_providers,
)
from app.services.llm_client import clear_client_cache
from app.services.network import apply_proxy

router = APIRouter()


def get_or_create_settings_row(session: Session) -> AppSettings:
    settings = session.get(AppSettings, 1)
    if not settings:
        settings = AppSettings(id=1)
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings


def derive_focus_keywords(research_focus: str) -> List[str]:
    """Extract display keywords from the arXiv query (or a ';'-separated list)."""
    raw_focus = (research_focus or "").strip()
    if not raw_focus:
        return []
    if ";" in raw_focus:
        return [k.strip() for k in re.split(r"[;]+", raw_focus) if k.strip()]

    # Excluded terms (ANDNOT x / ANDNOT (...)) are not focus keywords
    raw_focus = re.sub(r"\bANDNOT\s*\([^()]*\)", " ", raw_focus, flags=re.IGNORECASE)
    raw_focus = re.sub(r"\bANDNOT\s+\S+", " ", raw_focus, flags=re.IGNORECASE)
    keywords = []
    for part in re.split(r"\bOR\b|\bAND\b", raw_focus, flags=re.IGNORECASE):
        cleaned = part.strip()
        if not cleaned:
            continue
        cleaned = re.sub(r"^[()]+|[()]+$", "", cleaned).strip()
        cleaned = re.sub(r"^(?:all|abs|ti):", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = cleaned.strip('"').strip()
        if cleaned:
            keywords.append(cleaned)
    return list(dict.fromkeys(keywords))


def list_directions(session: Session) -> List[Direction]:
    rows = session.exec(
        select(ResearchDirection).order_by(ResearchDirection.position, ResearchDirection.id)
    ).all()
    return [Direction.from_row(row) for row in rows]


def sync_directions(session: Session, incoming: List[Direction]) -> None:
    """Create/update/reorder directions; delete the ones left out (with their papers)."""
    if not incoming:
        raise HTTPException(status_code=400, detail="At least one research direction is required")
    existing = {row.id: row for row in session.exec(select(ResearchDirection)).all()}
    kept = set()
    for position, direction in enumerate(incoming):
        row = existing.get(direction.id) if direction.id is not None else None
        if row is None:
            row = ResearchDirection()
        row.name = direction.name.strip() or f"研究方向 {position + 1}"
        row.position = position
        row.arxiv_categories = direction.arxiv_categories
        row.research_focus = direction.research_focus
        row.focus_keywords = derive_focus_keywords(direction.research_focus)
        row.research_idea = direction.research_idea
        row.system_prompt = direction.system_prompt
        session.add(row)
        session.flush()
        kept.add(row.id)
    for direction_id, row in existing.items():
        if direction_id not in kept:
            session.exec(delete(Paper).where(Paper.direction_id == direction_id))
            session.delete(row)


def read_settings(session: Session, row: AppSettings) -> AppSettingsRead:
    settings = load_settings(row)
    settings.directions = list_directions(session)
    return masked(settings)


@router.get("/settings", response_model=AppSettingsRead)
def get_settings(session: Session = Depends(get_session)):
    """Get application settings (secrets masked)."""
    return read_settings(session, get_or_create_settings_row(session))


@router.put("/settings", response_model=AppSettingsRead)
def update_settings(update: AppSettingsUpdate, session: Session = Depends(get_session)):
    """Merge the given fields into the stored settings. Masked secrets mean 'unchanged'."""
    row = get_or_create_settings_row(session)
    current = load_settings(row)

    if update.research_focus is not None:
        row.research_focus = update.research_focus
        row.focus_keywords = derive_focus_keywords(update.research_focus)
    if update.research_idea is not None:
        row.research_idea = update.research_idea
    if update.system_prompt is not None:
        row.system_prompt = update.system_prompt
    if update.arxiv_categories is not None:
        row.arxiv_categories = update.arxiv_categories
    if update.providers is not None:
        providers = unmask_providers(update.providers, current.providers)
        row.providers = [p.model_dump() for p in providers]
    if update.pipeline is not None:
        row.pipeline = unmask_pipeline(update.pipeline, current.pipeline).model_dump()
    if update.proxy_url is not None:
        row.proxy_url = update.proxy_url.strip()
        apply_proxy(row.proxy_url)
    if update.directions is not None:
        sync_directions(session, update.directions)

    session.add(row)
    session.commit()
    session.refresh(row)
    clear_client_cache()
    return read_settings(session, row)
