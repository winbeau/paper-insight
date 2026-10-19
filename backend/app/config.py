"""Runtime paths for PaperInsight.

Everything the app writes lives outside the source tree / app bundle:

    ~/Library/Application Support/PaperInsight/   (DATA_DIR)
        paper_insight.db
        thumbnails/            first-page JPGs, served at /api/static/thumbnails
        pdfs/<id>.pdf          downloaded PDFs (cache)
        parsed/<id>/           MinerU output (markdown, content list, images)
        mineru/                managed local MinerU runtime (venv, models, config)
    ~/Library/Logs/PaperInsight/                  (LOG_DIR)

Set PAPER_INSIGHT_DATA_DIR / PAPER_INSIGHT_LOG_DIR to override (dev, tests).
"""

import os
import sys
from pathlib import Path

APP_NAME = "PaperInsight"
APP_VERSION = "0.3.0"

IS_FROZEN = getattr(sys, "frozen", False)


def _default_data_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / APP_NAME


def _default_log_dir() -> Path:
    return Path.home() / "Library" / "Logs" / APP_NAME


DATA_DIR = Path(os.getenv("PAPER_INSIGHT_DATA_DIR") or _default_data_dir()).expanduser()
LOG_DIR = Path(
    os.getenv("PAPER_INSIGHT_LOG_DIR")
    or (DATA_DIR / "logs" if os.getenv("PAPER_INSIGHT_DATA_DIR") else _default_log_dir())
).expanduser()

DB_PATH = DATA_DIR / "paper_insight.db"
THUMBNAILS_DIR = DATA_DIR / "thumbnails"
PDF_CACHE_DIR = DATA_DIR / "pdfs"
PARSED_DIR = DATA_DIR / "parsed"
# Override to share one local MinerU install between dev data dirs
MINERU_DIR = Path(os.getenv("PAPER_INSIGHT_MINERU_DIR") or DATA_DIR / "mineru").expanduser()

# URL prefix under which DATA_DIR files are served (see main.py)
STATIC_URL_PREFIX = "/static"


def _resource_root() -> Path:
    """Root for bundled read-only resources (PyInstaller sets sys._MEIPASS)."""
    if IS_FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent.parent  # repo root


FRONTEND_DIST = (
    _resource_root() / "frontend_dist"
    if IS_FROZEN
    else _resource_root() / "frontend" / "dist"
)


def bundled_bin_dir() -> Path | None:
    """Directory with helper binaries shipped inside the .app (e.g. uv)."""
    if not IS_FROZEN:
        return None
    # onedir .app: Contents/MacOS/<exe>, resources in Contents/Resources (or Frameworks)
    candidates = [
        Path(sys.executable).parent.parent / "Resources" / "bin",
        _resource_root() / "bin",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def ensure_dirs() -> None:
    """Create the writable directories. Called at startup, never at import."""
    for path in (DATA_DIR, LOG_DIR, THUMBNAILS_DIR, PDF_CACHE_DIR, PARSED_DIR, MINERU_DIR):
        path.mkdir(parents=True, exist_ok=True)


def safe_id(arxiv_id: str) -> str:
    """Filesystem-safe form of an arXiv ID (old-style IDs contain '/')."""
    return (
        arxiv_id.replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace(" ", "_")
    )


def pdf_path_for(arxiv_id: str) -> Path:
    return PDF_CACHE_DIR / f"{safe_id(arxiv_id)}.pdf"


def parsed_dir_for(arxiv_id: str) -> Path:
    return PARSED_DIR / safe_id(arxiv_id)


def thumbnail_url_for(arxiv_id: str) -> str:
    return f"{STATIC_URL_PREFIX}/thumbnails/{safe_id(arxiv_id)}.jpg"


def thumbnail_path_for(url: str) -> Path | None:
    """Map a stored thumbnail URL ('/static/thumbnails/x.jpg') to its file in DATA_DIR."""
    if not url:
        return None
    rel = url.split("?", 1)[0]
    if rel.startswith(STATIC_URL_PREFIX + "/"):
        rel = rel[len(STATIC_URL_PREFIX) + 1:]
    path = (DATA_DIR / rel).resolve()
    # Never resolve outside DATA_DIR
    if DATA_DIR.resolve() not in path.parents:
        return None
    return path
