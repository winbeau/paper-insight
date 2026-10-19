"""Paper history: deleting entries and the cached files they leave behind.

PDFs, MinerU output (incl. cached figure evidence) and thumbnails are keyed by arXiv ID
and shared by every direction that contains the paper, so they are only removed once no
paper row references that arXiv ID any more.
"""

import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from sqlmodel import select

from app.config import PARSED_DIR, PDF_CACHE_DIR, THUMBNAILS_DIR, parsed_dir_for, pdf_path_for, safe_id, thumbnail_path_for, thumbnail_url_for
from app.database import get_sync_session
from app.logging_config import get_logger
from app.models import Paper

logger = get_logger("services.history")


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return 0


def remove_paper_files(arxiv_id: str, thumbnail_url: Optional[str] = None) -> int:
    """Delete one paper's cached files. Returns the bytes freed."""
    freed = 0
    thumbnail = thumbnail_path_for(thumbnail_url or thumbnail_url_for(arxiv_id))
    for path in (pdf_path_for(arxiv_id), thumbnail):
        if path is not None and path.is_file():
            try:
                freed += path.stat().st_size
                path.unlink()
            except OSError as e:
                logger.warning("Failed to delete %s: %s", path, e)
    parsed = parsed_dir_for(arxiv_id)
    if parsed.is_dir():
        freed += _size(parsed)
        shutil.rmtree(parsed, ignore_errors=True)
    return freed


def delete_papers(paper_ids: Iterable[int], delete_files: bool = True) -> Dict[str, int]:
    """Delete paper entries. Papers with a running analysis are skipped."""
    from app.services.analyzer import active_paper_ids

    ids = list(dict.fromkeys(paper_ids))
    active = set(active_paper_ids())
    with get_sync_session() as session:
        papers = session.exec(select(Paper).where(Paper.id.in_(ids))).all() if ids else []
        removable = [p for p in papers if p.id not in active]
        files = {(p.arxiv_id, p.thumbnail_url) for p in removable}
        for paper in removable:
            session.delete(paper)
        session.commit()

        freed = 0
        if delete_files:
            for arxiv_id, thumbnail_url in files:
                still_used = session.exec(select(Paper.id).where(Paper.arxiv_id == arxiv_id)).first()
                if still_used is None:
                    freed += remove_paper_files(arxiv_id, thumbnail_url)

    if removable:
        logger.info("Deleted %d papers (%d skipped while running, %d bytes freed)",
                    len(removable), len(papers) - len(removable), freed)
    return {
        "deleted": len(removable),
        "skipped_active": len(papers) - len(removable),
        "freed_bytes": freed,
    }


def storage_usage() -> Dict[str, int]:
    pdfs = _size(PDF_CACHE_DIR)
    parsed = _size(PARSED_DIR)
    thumbnails = _size(THUMBNAILS_DIR)
    return {"pdfs": pdfs, "parsed": parsed, "thumbnails": thumbnails, "total": pdfs + parsed + thumbnails}


def prune_orphan_files() -> Dict[str, int]:
    """Delete cached files whose arXiv paper is no longer in any direction."""
    with get_sync_session() as session:
        in_use = {safe_id(a) for a in session.exec(select(Paper.arxiv_id)).all()}

    freed = removed = 0
    candidates: List[Path] = []
    if PDF_CACHE_DIR.is_dir():
        candidates += [p for p in PDF_CACHE_DIR.iterdir() if p.suffix in (".pdf", ".part") and p.stem not in in_use]
    if THUMBNAILS_DIR.is_dir():
        candidates += [p for p in THUMBNAILS_DIR.iterdir() if p.is_file() and p.stem not in in_use]
    if PARSED_DIR.is_dir():
        candidates += [p for p in PARSED_DIR.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name not in in_use]
    for path in candidates:
        freed += _size(path)
        removed += 1
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    if removed:
        logger.info("Pruned %d orphan cache entries (%d bytes)", removed, freed)
    return {"removed": removed, "freed_bytes": freed}
