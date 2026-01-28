import os
import sqlite3
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

DATABASE_URL = os.getenv("DATABASE_URL", "")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https://.*\.github\.io$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


def get_sqlite_path() -> str:
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="DATABASE_URL is not set")

    if DATABASE_URL.startswith("sqlite:///"):
        path = DATABASE_URL[len("sqlite:///") :]
    elif DATABASE_URL.startswith("sqlite://"):
        path = DATABASE_URL[len("sqlite://") :]
    else:
        path = DATABASE_URL

    if not path:
        raise HTTPException(status_code=500, detail="DATABASE_URL has no path")

    return os.path.abspath(path)


def fetch_papers(limit: int, offset: int) -> List[Dict[str, Any]]:
    db_path = get_sqlite_path()

    table_candidates = ["paper", "papers"]
    last_error: Optional[Exception] = None

    for table in table_candidates:
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    f"SELECT * FROM {table} "
                    "ORDER BY published IS NULL, published DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
                rows = cur.fetchall()
                return [dict(row) for row in rows]
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                last_error = exc
                continue
            last_error = exc
            break
        except Exception as exc:
            last_error = exc
            break

    detail = str(last_error) if last_error else "paper table not found"
    raise HTTPException(status_code=500, detail=f"Database error: {detail}")


@app.get("/papers")
def papers(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> List[Dict[str, Any]]:
    return fetch_papers(limit, offset)


@app.get("/stats")
def stats() -> Dict[str, Any]:
    db_path = get_sqlite_path()
    table_candidates = ["paper", "papers"]
    last_error: Optional[Exception] = None

    for table in table_candidates:
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    f"SELECT COUNT(*) AS total_papers, "
                    f"MAX(published) AS last_update FROM {table}"
                )
                row = cur.fetchone()
                if row is None:
                    return {"total_papers": 0, "last_update": None}
                return {
                    "total_papers": row["total_papers"],
                    "last_update": row["last_update"],
                }
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                last_error = exc
                continue
            last_error = exc
            break
        except Exception as exc:
            last_error = exc
            break

    if last_error:
        raise HTTPException(status_code=500, detail=f"Database error: {last_error}")
    return {"total_papers": 0, "last_update": None}


@app.get("/settings")
def settings() -> Dict[str, Any]:
    return {"theme": "light", "language": "en"}
