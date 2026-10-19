"""Parsed-document model, MinerU output normalization and the on-disk parse cache.

Both MinerU engines (cloud v4 and local 4.x api-server) return an archive with a
markdown file, an `images/` folder and (usually) a content-list JSON. Layout and file
names differ between versions, so everything goes through `normalize_output_dir`, which
copies the result into the paper's cache dir in one canonical shape:

    parsed/<id>/markdown.md
    parsed/<id>/images/...
    parsed/<id>/figures.json     [Figure, ...]
    parsed/<id>/meta.json        {"engine": ..., "created_at": ...}
"""

import io
import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol

from app.logging_config import get_logger
from app.services.errors import PipelineError

logger = get_logger("services.parsers")

ProgressFn = Callable[[str], Awaitable[None]]

_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)[^)]*\)")
_PAGE_IN_NAME_RE = re.compile(r"page_(\d+)_")  # MinerU 4 asset names: images/page_{page_idx}_{type}_{n}.jpg
_CAPTION_RE = re.compile(r"^\s*(?:\*\*)?(fig(?:ure)?\.?|table|tab\.|图|表)\s*\d+", re.IGNORECASE)


@dataclass
class Figure:
    n: int                      # 1-based order in the document (used to cite in the evidence)
    kind: str                   # "image" | "table"
    path: str                   # relative to the parsed dir, e.g. "images/abc.jpg"
    caption: str = ""
    context: str = ""           # nearby body text (pseudo-caption when caption is empty)
    page: Optional[int] = None  # 1-based


@dataclass
class ParsedDocument:
    root: Path
    markdown: str
    figures: List[Figure] = field(default_factory=list)
    engine: str = ""
    from_cache: bool = False

    def figure_path(self, figure: Figure) -> Path:
        return self.root / figure.path


@dataclass
class ParseRequest:
    arxiv_id: str
    title: str
    pdf_url: str
    pdf_path: Path
    out_dir: Path


class PdfParser(Protocol):
    engine: str

    async def parse(self, request: ParseRequest, progress: ProgressFn) -> ParsedDocument: ...


def parse_error(message: str) -> PipelineError:
    return PipelineError("parse_error", message)


# --- Cache -------------------------------------------------------------------------


def load_cached(out_dir: Path) -> Optional[ParsedDocument]:
    meta_path = out_dir / "meta.json"
    md_path = out_dir / "markdown.md"
    if not (meta_path.exists() and md_path.exists()):
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        figures_raw = json.loads((out_dir / "figures.json").read_text(encoding="utf-8"))
        figures = [Figure(**f) for f in figures_raw]
    except (OSError, ValueError, TypeError) as e:
        logger.warning("Ignoring corrupt parse cache %s: %s", out_dir, e)
        return None
    return ParsedDocument(
        root=out_dir,
        markdown=md_path.read_text(encoding="utf-8"),
        figures=figures,
        engine=meta.get("engine", ""),
        from_cache=True,
    )


def clear_cache(out_dir: Path) -> None:
    shutil.rmtree(out_dir, ignore_errors=True)


# --- Archive handling --------------------------------------------------------------


def safe_extract_zip(data: bytes, dest: Path) -> None:
    """Extract a zip, refusing entries that would escape `dest` (zip slip)."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise parse_error(f"MinerU 返回的结果不是有效的 zip: {e}")
    dest_resolved = dest.resolve()
    with archive:
        for member in archive.infolist():
            target = (dest / member.filename).resolve()
            if target != dest_resolved and dest_resolved not in target.parents:
                raise parse_error(f"MinerU 结果包含非法路径: {member.filename}")
        archive.extractall(dest)


def _find_markdown(root: Path) -> Optional[Path]:
    candidates = [p for p in root.rglob("*.md") if p.is_file()]
    if not candidates:
        return None
    preferred = [p for p in candidates if p.name in ("full.md", "markdown.md")]
    return max(preferred or candidates, key=lambda p: p.stat().st_size)


def _find_content_list(root: Path) -> Optional[Path]:
    candidates = [
        p for p in root.rglob("*.json")
        if "content_list" in p.name and "v2" not in p.name
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)


def _join_caption(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(v).strip() for v in value if str(v).strip())
    return str(value or "").strip()


def figures_from_content_list(items: List[Dict[str, Any]]) -> List[Figure]:
    figures: List[Figure] = []
    last_text = ""
    for item in items:
        kind = item.get("type")
        if kind == "text":
            text = str(item.get("text") or "").strip()
            if text:
                last_text = text
            continue
        if kind not in ("image", "table", "chart") or not item.get("img_path"):
            continue
        caption = _join_caption(
            item.get("image_caption") or item.get("table_caption") or item.get("chart_caption")
            or item.get("caption")
        )
        footnote = _join_caption(item.get("image_footnote") or item.get("table_footnote"))
        page = item.get("page_idx")
        figures.append(
            Figure(
                n=len(figures) + 1,
                kind="table" if kind == "table" else "image",
                path=str(item["img_path"]),
                caption=caption + (f" ({footnote})" if footnote else ""),
                context=last_text[:400],
                page=page + 1 if isinstance(page, int) else None,
            )
        )
    return figures


def _is_prose(line: str) -> bool:
    """Body text worth using as figure context (not math delimiters, HTML or image links)."""
    text = line.strip()
    return (
        len(text) >= 30
        and not text.startswith(("$$", "<", "|", "!["))
        and not _MD_IMAGE_RE.search(text)
    )


def figures_from_markdown(markdown: str) -> List[Figure]:
    """Images in markdown order (MinerU 4 has no content list); caption = following caption line."""
    figures: List[Figure] = []
    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        for match in _MD_IMAGE_RE.finditer(line):
            path = match.group(1)
            if path.startswith(("http://", "https://", "data:")):
                continue
            caption = ""
            for nxt in lines[i + 1:i + 4]:
                if nxt.strip():
                    if _CAPTION_RE.match(nxt):
                        caption = nxt.strip()
                    break
            context = next(
                (prev.strip()[:400] for prev in reversed(lines[max(0, i - 12):i]) if _is_prose(prev)), ""
            )
            if not caption:
                # Sub-figure labels like "(a) Single-stage v.s. Two-stage" follow the image
                context = next((nxt.strip()[:400] for nxt in lines[i + 1:i + 3] if nxt.strip()), context)
            kind = "table" if caption.lower().startswith(("table", "tab.", "表")) else "image"
            page_match = _PAGE_IN_NAME_RE.search(path)
            figures.append(Figure(
                n=len(figures) + 1, kind=kind, path=path, caption=caption, context=context,
                page=int(page_match.group(1)) + 1 if page_match else None,
            ))
    return figures


def normalize_output_dir(raw_dir: Path, out_dir: Path, engine: str) -> ParsedDocument:
    """Copy a raw MinerU result tree into the canonical cache layout."""
    md_path = _find_markdown(raw_dir)
    if md_path is None:
        raise parse_error("MinerU 结果中没有 Markdown 文件")
    md_root = md_path.parent
    markdown = md_path.read_text(encoding="utf-8", errors="replace")
    if not markdown.strip():
        raise parse_error("MinerU 解析结果为空")

    figures: List[Figure] = []
    content_list_path = _find_content_list(raw_dir)
    if content_list_path is not None:
        try:
            items = json.loads(content_list_path.read_text(encoding="utf-8"))
            if isinstance(items, list):
                figures = figures_from_content_list(items)
            md_root = content_list_path.parent if figures else md_root
        except ValueError as e:
            logger.warning("Unreadable content list %s: %s", content_list_path, e)
    if not figures:
        figures = figures_from_markdown(markdown)

    # Rebuild out_dir atomically-ish: write to a sibling temp dir, then swap
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=out_dir.parent))
    try:
        (staging / "images").mkdir()
        kept: List[Figure] = []
        for figure in figures:
            src = (md_root / figure.path)
            if not src.is_file():
                src = next(iter(raw_dir.rglob(Path(figure.path).name)), src)
            if not src.is_file():
                continue
            dest_rel = f"images/{src.name}"
            shutil.copy2(src, staging / dest_rel)
            figure.path = dest_rel
            kept.append(figure)
        for i, figure in enumerate(kept, start=1):
            figure.n = i

        (staging / "markdown.md").write_text(markdown, encoding="utf-8")
        (staging / "figures.json").write_text(
            json.dumps([asdict(f) for f in kept], ensure_ascii=False, indent=1), encoding="utf-8"
        )
        if content_list_path is not None:
            shutil.copy2(content_list_path, staging / "content_list.json")
        (staging / "meta.json").write_text(
            json.dumps({"engine": engine, "created_at": datetime.utcnow().isoformat()}),
            encoding="utf-8",
        )
        clear_cache(out_dir)
        staging.replace(out_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return ParsedDocument(root=out_dir, markdown=markdown, figures=kept, engine=engine)


def normalize_zip(data: bytes, out_dir: Path, engine: str) -> ParsedDocument:
    with tempfile.TemporaryDirectory(prefix="mineru-") as tmp:
        raw_dir = Path(tmp)
        safe_extract_zip(data, raw_dir)
        return normalize_output_dir(raw_dir, out_dir, engine)
