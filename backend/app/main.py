"""PaperInsight FastAPI application entry point."""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import create_db_and_tables, ensure_appsettings_schema, ensure_paper_schema
from app.services.arxiv_bot import run_daily_fetch
from app.api import api_router

scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    ensure_appsettings_schema()
    ensure_paper_schema()

    scheduler.add_job(
        run_daily_fetch,
        CronTrigger(hour=6, minute=0),
        id="daily_paper_fetch",
        name="Daily Paper Fetch",
        replace_existing=True,
    )
    scheduler.start()
    print("[Scheduler] Started - Daily paper fetch scheduled at 06:00 UTC")

    yield

    scheduler.shutdown(wait=False)
    print("[Scheduler] Shutdown complete")


app = FastAPI(
    title="Paper Insight API",
    description="API for fetching and summarizing arXiv papers",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
static_path = Path(__file__).parent / "static"
static_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_path), name="static")

# Include all API routers
app.include_router(api_router)
