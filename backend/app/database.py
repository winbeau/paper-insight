import os
from typing import Generator
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import inspect, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/paper_insight"
)

engine = create_engine(DATABASE_URL, echo=False)


def create_db_and_tables():
    """Create all database tables."""
    SQLModel.metadata.create_all(engine)


def ensure_appsettings_schema():
    """Ensure AppSettings has expected columns for legacy databases."""
    inspector = inspect(engine)
    if "appsettings" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("appsettings")}
    added = set()
    ddl_statements = []

    if "research_focus" not in columns:
        ddl_statements.append("ALTER TABLE appsettings ADD COLUMN research_focus TEXT")
        added.add("research_focus")
    if "focus_keywords" not in columns:
        ddl_statements.append("ALTER TABLE appsettings ADD COLUMN focus_keywords JSON")
        added.add("focus_keywords")
    if "system_prompt" not in columns:
        ddl_statements.append("ALTER TABLE appsettings ADD COLUMN system_prompt TEXT")
        added.add("system_prompt")
    if "arxiv_categories" not in columns:
        ddl_statements.append("ALTER TABLE appsettings ADD COLUMN arxiv_categories JSON")
        added.add("arxiv_categories")

    if not ddl_statements and not columns:
        return

    final_columns = columns | added
    with engine.begin() as conn:
        for stmt in ddl_statements:
            conn.execute(text(stmt))

        if "research_focus" in final_columns:
            conn.execute(
                text("UPDATE appsettings SET research_focus = '' WHERE research_focus IS NULL")
            )
        if "system_prompt" in final_columns:
            conn.execute(
                text("UPDATE appsettings SET system_prompt = '' WHERE system_prompt IS NULL")
            )
        if "focus_keywords" in final_columns:
            conn.execute(
                text("UPDATE appsettings SET focus_keywords = '[]' WHERE focus_keywords IS NULL")
            )
        if "arxiv_categories" in final_columns:
            conn.execute(
                text(
                    "UPDATE appsettings SET arxiv_categories = "
                    "'[\"cs.CV\",\"cs.LG\"]' WHERE arxiv_categories IS NULL"
                )
            )


def ensure_paper_schema():
    """Ensure Paper has expected columns for legacy databases."""
    inspector = inspect(engine)
    table_name = None
    if "paper" in inspector.get_table_names():
        table_name = "paper"
    elif "papers" in inspector.get_table_names():
        table_name = "papers"

    if not table_name:
        return

    columns = {col["name"] for col in inspector.get_columns(table_name)}
    added = set()
    ddl_statements = []

    if "processing_status" not in columns:
        ddl_statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN processing_status TEXT"
        )
        added.add("processing_status")

    # New LLM output format fields
    if "paper_essence" not in columns:
        ddl_statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN paper_essence TEXT"
        )
        added.add("paper_essence")

    if "concept_bridging" not in columns:
        ddl_statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN concept_bridging TEXT"
        )
        added.add("concept_bridging")

    if "visual_verification" not in columns:
        ddl_statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN visual_verification TEXT"
        )
        added.add("visual_verification")

    if "heuristic_suggestion" not in columns:
        ddl_statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN heuristic_suggestion TEXT"
        )
        added.add("heuristic_suggestion")

    final_columns = columns | added
    with engine.begin() as conn:
        for stmt in ddl_statements:
            conn.execute(text(stmt))

        if "processing_status" in final_columns:
            conn.execute(
                text(
                    f"UPDATE {table_name} "
                    "SET processing_status = CASE "
                    "WHEN is_processed THEN 'processed' ELSE 'pending' END "
                    "WHERE processing_status IS NULL"
                )
            )
            conn.execute(
                text(
                    f"UPDATE {table_name} "
                    "SET processing_status = 'skipped' "
                    "WHERE is_processed = TRUE "
                    "AND relevance_score IS NOT NULL "
                    "AND relevance_score < 5 "
                    "AND processing_status = 'processed'"
                )
            )


def get_session() -> Generator[Session, None, None]:
    """Dependency for getting database session."""
    with Session(engine) as session:
        yield session


def get_sync_session() -> Session:
    """Get a synchronous session for non-FastAPI contexts."""
    return Session(engine)
