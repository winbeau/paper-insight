"""PDF download cache + first-page thumbnails."""

import asyncio
from pathlib import Path
from typing import Optional

import fitz  # pymupdf
import httpx

from app.config import THUMBNAILS_DIR, pdf_path_for, thumbnail_url_for, thumbnail_path_for
from app.logging_config import get_logger
from app.services.errors import PipelineError
from app.services.network import USER_AGENT

logger = get_logger("services.pdf_renderer")

MAX_PDF_BYTES = 200 * 1024 * 1024

# One download per paper at a time (the parse queue may prefetch while an analysis starts)
_download_locks: dict[str, asyncio.Lock] = {}


async def ensure_pdf(arxiv_id: str, pdf_url: str) -> Path:
    """Return the cached PDF for a paper, downloading it on first use."""
    path = pdf_path_for(arxiv_id)
    if path.exists() and path.stat().st_size > 0:
        return path
    lock = _download_locks.setdefault(arxiv_id, asyncio.Lock())
    async with lock:
        if path.exists() and path.stat().st_size > 0:
            return path
        return await _download_pdf(path, pdf_url)


async def _download_pdf(path: Path, pdf_url: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".part")
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(120.0, connect=20.0),
            headers={"User-Agent": USER_AGENT},
        ) as client:
            async with client.stream("GET", pdf_url) as response:
                if response.status_code != 200:
                    raise PipelineError(
                        "download_error", f"下载 PDF 失败: HTTP {response.status_code} ({pdf_url})"
                    )
                size = 0
                with open(tmp_path, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_PDF_BYTES:
                            raise PipelineError("entity_too_large", "PDF 超过 200MB")
                        f.write(chunk)
        with open(tmp_path, "rb") as f:
            if f.read(5) != b"%PDF-":
                raise PipelineError("download_error", f"下载内容不是 PDF ({pdf_url})")
        tmp_path.replace(path)
        return path
    except PipelineError:
        tmp_path.unlink(missing_ok=True)
        raise
    except httpx.TimeoutException as e:
        tmp_path.unlink(missing_ok=True)
        raise PipelineError("timeout", f"下载 PDF 超时: {e}")
    except httpx.HTTPError as e:
        tmp_path.unlink(missing_ok=True)
        raise PipelineError("download_error", f"下载 PDF 失败: {e}")


async def generate_thumbnail(arxiv_id: str, pdf_path: Path) -> Optional[str]:
    """Render the first page of a cached PDF to a JPG.

    Returns the thumbnail URL ("/static/thumbnails/<id>.jpg"), or None on failure.
    """
    url = thumbnail_url_for(arxiv_id)
    file_path = thumbnail_path_for(url)
    if file_path is None:
        return None
    if file_path.exists():
        return url
    try:
        THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
        pdf_data = await asyncio.to_thread(pdf_path.read_bytes)
        success = await asyncio.to_thread(_render_thumbnail, pdf_data, file_path)
        return url if success else None
    except Exception as e:
        logger.error("Error generating thumbnail for %s: %s", arxiv_id, e)
        return None


def _render_thumbnail(pdf_data: bytes, file_path: Path) -> bool:
    """Render the first page of a PDF to a thumbnail on disk."""
    doc = None
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        if len(doc) < 1:
            return False
        page = doc[0]
        # Matrix(1.5, 1.5) increases resolution for better quality
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        pix.save(str(file_path))
        return True
    except Exception as e:
        logger.error("Error rendering thumbnail: %s", e)
        return False
    finally:
        if doc is not None:
            doc.close()
