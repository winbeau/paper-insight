from datetime import datetime
from typing import Any, Dict, List, Optional
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

    # AI-generated analysis fields (new format based on LLM prompt)
    paper_essence: Optional[str] = Field(default=None, sa_column=Column(Text))  # 核心创新点
    concept_bridging: Optional[str] = Field(default=None, sa_column=Column(Text))  # JSON string
    visual_verification: Optional[str] = Field(default=None, sa_column=Column(Text))  # 视觉验证
    relevance_score: Optional[float] = Field(default=None, ge=0, le=10)
    relevance_reason: Optional[str] = Field(default=None, sa_column=Column(Text))
    heuristic_suggestion: Optional[str] = Field(default=None, sa_column=Column(Text))  # 核心建议

    # Metadata
    is_processed: bool = Field(default=False)
    processing_status: str = Field(default="pending", index=True)
    processing_started_at: Optional[datetime] = None
    processing_error: Optional[str] = Field(default=None, sa_column=Column(Text))
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
    paper_essence: Optional[str] = None
    concept_bridging: Optional[str] = None
    visual_verification: Optional[str] = None
    relevance_score: Optional[float] = None
    relevance_reason: Optional[str] = None
    heuristic_suggestion: Optional[str] = None
    is_processed: bool
    processing_status: str
    processing_error: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime]


class LLMAnalysis(BaseModel):
    """Schema for LLM analysis response."""
    paper_essence: str = ""
    concept_bridging_str: str = ""  # Formatted string from concept_bridging object
    visual_verification: str = ""
    relevance_score: float = 0
    relevance_reason: str = ""
    heuristic_suggestion: str = ""


class AppSettings(SQLModel, table=True):
    """Application settings stored in DB (single row, id=1).

    Read/write through app.schemas (AppSettingsRead / AppSettingsUpdate): table models
    skip validation, so JSON columns may be NULL on legacy rows.
    """
    id: int = Field(default=1, primary_key=True)
    research_focus: str = Field(default="", sa_column=Column(Text, default=""))  # arXiv search query
    research_idea: str = Field(default="", sa_column=Column(Text, default=""))   # research context for analysis
    focus_keywords: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    system_prompt: str = Field(default="", sa_column=Column(Text, default=""))   # analysis prompt override
    arxiv_categories: List[str] = Field(
        default_factory=lambda: ["cs.CV", "cs.LG"], sa_column=Column(JSON)
    )
    providers: List[Dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))  # schemas.Provider
    pipeline: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))         # schemas.PipelineConfig
    proxy_url: str = Field(default="", sa_column=Column(Text, default=""))
    last_fetch_at: Optional[datetime] = None
