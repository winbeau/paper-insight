"""Settings endpoints."""

import re
from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.models import AppSettings
from app.dependencies import get_session

router = APIRouter()


@router.get("/settings", response_model=AppSettings)
def get_settings(session: Session = Depends(get_session)):
    """Get application settings."""
    settings = session.get(AppSettings, 1)
    if not settings:
        settings = AppSettings(id=1)
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings


@router.put("/settings", response_model=AppSettings)
def update_settings(new_settings: AppSettings, session: Session = Depends(get_session)):
    """Update application settings."""
    settings = session.get(AppSettings, 1)
    if not settings:
        settings = AppSettings(id=1)
        session.add(settings)

    settings.research_focus = new_settings.research_focus
    settings.research_idea = new_settings.research_idea
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
