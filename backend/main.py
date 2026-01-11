import os
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
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


def fetch_papers(limit: int, offset: int) -> List[Dict[str, Any]]:
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="DATABASE_URL is not set")

    table_candidates = ["paper", "papers"]
    last_error: Optional[Exception] = None

    for table in table_candidates:
        try:
            with psycopg2.connect(DATABASE_URL) as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        f"SELECT * FROM {table} ORDER BY published DESC NULLS LAST LIMIT %s OFFSET %s",
                        (limit, offset),
                    )
                    rows = cur.fetchall()
                    return [dict(row) for row in rows]
        except psycopg2.errors.UndefinedTable as exc:
            last_error = exc
            continue
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
