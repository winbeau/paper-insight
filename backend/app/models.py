from datetime import datetime
from typing import Optional, List
from sqlmodel import SQLModel, Field, Column, Text
from sqlalchemy import JSON
from pydantic import BaseModel


class Paper(SQLModel, table=True):
    """Paper model for storing arXiv papers with AI analysis."""
    id: Optional[int] = Field(default=None, primary_key=True)
    arxiv_id: str = Field(unique=True, index=True)
    title: str
    authors: str
    abstract: str = Field(sa_column=Column(Text))
    categories: str
    published: datetime
    updated: datetime
    pdf_url: str
    thumbnail_url: Optional[str] = None

    # AI-generated analysis fields
    summary_zh: Optional[str] = Field(default=None, sa_column=Column(Text))
    relevance_score: Optional[float] = Field(default=None, ge=0, le=10)
    relevance_reason: Optional[str] = Field(default=None, sa_column=Column(Text))
    heuristic_idea: Optional[str] = Field(default=None, sa_column=Column(Text))

    # Metadata
    is_processed: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: Optional[datetime] = None


class PaperCreate(SQLModel):
    """Schema for creating a new paper."""
    arxiv_id: str
    title: str
    authors: str
    abstract: str
    categories: str
    published: datetime
    updated: datetime
    pdf_url: str


class PaperRead(SQLModel):
    """Schema for reading paper data."""
    id: int
    arxiv_id: str
    title: str
    authors: str
    abstract: str
    categories: str
    published: datetime
    updated: datetime
    pdf_url: str
    thumbnail_url: Optional[str] = None
    summary_zh: Optional[str]
    relevance_score: Optional[float]
    relevance_reason: Optional[str]
    heuristic_idea: Optional[str]
    is_processed: bool
    created_at: datetime
    processed_at: Optional[datetime]


class LLMAnalysis(BaseModel):
    """Schema for LLM analysis response."""
    summary_zh: str
    relevance_score: float
    relevance_reason: str
    heuristic_idea: str


class AppSettings(SQLModel, table=True):
    """Application settings stored in DB."""
    id: int = Field(default=1, primary_key=True)
    research_focus: str = Field(sa_column=Column(Text, default=""))
    focus_keywords: List[str] = Field(default=[], sa_column=Column(JSON))
    system_prompt: str = Field(sa_column=Column(Text, default=""))
    arxiv_categories: List[str] = Field(sa_column=Column(JSON, default=["cs.CV", "cs.LG"]))