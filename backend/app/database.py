import os

from sqlalchemy import event, inspect, text
from sqlmodel import SQLModel, create_engine, Session

from app.config import DB_PATH

DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    # The scheduler thread, threadpool endpoints and streaming tasks all share the engine
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def create_db_and_tables():
    """Create all database tables."""
    SQLModel.metadata.create_all(engine)
    # The DB holds API keys: keep it private to the user
    for suffix in ("", "-wal", "-shm"):
        path = f"{DB_PATH}{suffix}"
        if os.path.exists(path):
            os.chmod(path, 0o600)


def _add_missing_columns(table: str, wanted: dict[str, str]) -> set[str]:
    """ALTER TABLE ADD COLUMN for every missing column. Returns the names added."""
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns(table)}
    added = {name for name in wanted if name not in columns}
    if added:
        with engine.begin() as conn:
            for name in added:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {wanted[name]}"))
    return added


def ensure_appsettings_schema():
    """Ensure AppSettings has expected columns for legacy databases."""
    if "appsettings" not in inspect(engine).get_table_names():
        return

    _add_missing_columns(
        "appsettings",
        {
            "research_focus": "TEXT",
            "research_idea": "TEXT",
            "focus_keywords": "JSON",
            "system_prompt": "TEXT",
            "arxiv_categories": "JSON",
            "providers": "JSON",
            "pipeline": "JSON",
            "proxy_url": "TEXT",
            "last_fetch_at": "DATETIME",
        },
    )

    # Backfill NULLs (cheap no-ops once filled)
    with engine.begin() as conn:
        for column, value in (
            ("research_focus", "''"),
            ("research_idea", "''"),
            ("system_prompt", "''"),
            ("proxy_url", "''"),
            ("focus_keywords", "'[]'"),
            ("providers", "'[]'"),
            ("pipeline", "'{}'"),
            ("arxiv_categories", "'[\"cs.CV\",\"cs.LG\"]'"),
        ):
            conn.execute(
                text(f"UPDATE appsettings SET {column} = {value} WHERE {column} IS NULL")
            )


def ensure_paper_schema():
    """Ensure Paper has expected columns for legacy databases."""
    table_names = inspect(engine).get_table_names()
    table_name = next((t for t in ("paper", "papers") if t in table_names), None)
    if not table_name:
        return

    added = _add_missing_columns(
        table_name,
        {
            "processing_status": "TEXT",
            "paper_essence": "TEXT",
            "concept_bridging": "TEXT",
            "visual_verification": "TEXT",
            "heuristic_suggestion": "TEXT",
            "processing_started_at": "DATETIME",
            "processing_error": "TEXT",
        },
    )

    if "processing_status" in added:
        with engine.begin() as conn:
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


def reset_interrupted_processing() -> int:
    """Mark papers left in 'processing' by a previous run (crash/quit) as failed."""
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE paper SET processing_status = 'failed', "
                "processing_error = 'interrupted' "
                "WHERE processing_status = 'processing' AND is_processed = FALSE"
            )
        )
        return result.rowcount or 0


def get_sync_session() -> Session:
    """Get a synchronous session for non-FastAPI contexts."""
    return Session(engine)
