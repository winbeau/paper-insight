"""API routers for PaperInsight (mounted under /api in app.main)."""

from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.settings import router as settings_router
from app.api.papers import router as papers_router
from app.api.processing import router as processing_router
from app.api.stats import router as stats_router
from app.api.providers import router as providers_router
from app.api.mineru import router as mineru_router
from app.api.research import router as research_router
from app.api.history import router as history_router

api_router = APIRouter()

api_router.include_router(health_router, tags=["health"])
api_router.include_router(settings_router, tags=["settings"])
api_router.include_router(papers_router, prefix="/papers", tags=["papers"])
api_router.include_router(processing_router, prefix="/papers", tags=["processing"])
api_router.include_router(stats_router, tags=["stats"])
api_router.include_router(providers_router, tags=["providers"])
api_router.include_router(mineru_router, tags=["mineru"])
api_router.include_router(research_router, tags=["research"])
api_router.include_router(history_router, tags=["history"])
