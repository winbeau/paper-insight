"""PaperInsight FastAPI application entry point."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import APP_VERSION, FRONTEND_DIST, THUMBNAILS_DIR, ensure_dirs
from app.logging_config import setup_logging, get_logger
from app.middleware import LocalOnlyMiddleware, RequestLoggingMiddleware
from app.database import (
    create_db_and_tables,
    ensure_appsettings_schema,
    ensure_default_direction,
    ensure_paper_schema,
    get_sync_session,
    reset_interrupted_processing,
)
from app.models import AppSettings
from app.services.arxiv_bot import run_daily_fetch_async
from app.services.mineru_runtime import get_mineru_runtime
from app.services.network import apply_proxy
from app.api import api_router

# Initialize logging before anything else
setup_logging()
logger = get_logger("main")

FETCH_CATCH_UP_AFTER = timedelta(hours=24)


def _startup_state() -> tuple[str, datetime | None]:
    with get_sync_session() as session:
        settings = session.get(AppSettings, 1)
        if not settings:
            return "", None
        return settings.proxy_url or "", settings.last_fetch_at


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    create_db_and_tables()
    ensure_appsettings_schema()
    ensure_paper_schema()
    ensure_default_direction()
    interrupted = reset_interrupted_processing()
    if interrupted:
        logger.warning("Marked %d interrupted papers as failed", interrupted)

    proxy_url, last_fetch_at = _startup_state()
    apply_proxy(proxy_url)
    get_mineru_runtime().kill_stale_server()

    # Runs on the server's event loop, so pipeline semaphores are shared with requests
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_daily_fetch_async,
        CronTrigger(hour=6, minute=0),
        id="daily_paper_fetch",
        name="Daily Paper Fetch",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=3600,
    )
    # A laptop is often asleep/closed at 06:00: catch up shortly after launch
    if last_fetch_at is None or datetime.utcnow() - last_fetch_at > FETCH_CATCH_UP_AFTER:
        scheduler.add_job(
            run_daily_fetch_async,
            DateTrigger(run_date=datetime.now() + timedelta(seconds=20)),
            id="catch_up_fetch",
            name="Catch-up Paper Fetch",
        )
        logger.info("Last fetch %s — scheduling catch-up fetch", last_fetch_at or "never")
    scheduler.start()
    logger.info("Scheduler started — daily paper fetch at 06:00 (local time)")

    yield

    scheduler.shutdown(wait=False)
    # Quick, lock-free stop: quitting must not wait for MinerU (see MineruRuntime.kill_now)
    await asyncio.to_thread(get_mineru_runtime().kill_now)
    logger.info("Shutdown complete")


app = FastAPI(
    title="PaperInsight",
    description="Local API for fetching and analyzing arXiv papers",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(LocalOnlyMiddleware)

app.include_router(api_router, prefix="/api")

# Thumbnails live in the user's data dir (not the read-only app bundle)
app.mount(
    "/api/static/thumbnails",
    StaticFiles(directory=THUMBNAILS_DIR, check_dir=False),
    name="thumbnails",
)

# Built Vue app (bundled into the .app; in dev the Vite server is used instead)
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
else:
    logger.info("Frontend build not found at %s (dev mode: use the Vite server)", FRONTEND_DIST)
