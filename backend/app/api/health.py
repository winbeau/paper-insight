"""Health check endpoints."""

from fastapi import APIRouter

from app.constants import ARXIV_OPTIONS

router = APIRouter()


@router.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@router.get("/constants")
def get_constants():
    """Get application constants."""
    return {"arxiv_options": ARXIV_OPTIONS}
