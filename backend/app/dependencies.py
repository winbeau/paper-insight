"""FastAPI dependency injection providers."""

from typing import Generator
from sqlmodel import Session
from app.database import engine


def get_session() -> Generator[Session, None, None]:
    """Dependency for getting database session."""
    with Session(engine) as session:
        yield session
