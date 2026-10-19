"""Vision step: describe the paper's figures/tables with a vision LLM.

Produces the numbered "Visual Evidence" list the analysis prompt cites by figure number,
mirroring what the Dify workflow's IMAGE-LLM node fed into the reasoning model.
"""

import asyncio
import base64
import re
from pathlib import Path
from typing import List, Optional, Tuple

import fitz  # pymupdf

from app.logging_config import get_logger
from app.prompts import VISION_FIGURE_PROMPT, VISION_SYSTEM_PROMPT
from app.schemas import Provider, VisionConfig
from app.services.errors import PipelineError
from app.services.llm_client import chat_text
from app.services.parsers import Figure, ParsedDocument
from app.services.parsers.base import ProgressFn

logger = get_logger("services.vision")

MIN_IMAGE_BYTES = 4 * 1024           # skip icons, logos, tiny formula crops
MAX_IMAGE_BYTES = 3 * 1024 * 1024    # downscale anything bigger before sending
MAX_TOTAL_BYTES = 16 * 1024 * 1024   # cap across all figures of a paper
MAX_SIDE = 2048

_CAPTION_NUMBER_RE = re.compile(r"^\W*(fig(?:ure)?\.?|table|tab\.?|图|表)\s*(\d+)", re.IGNORECASE)


def figure_label(figure: Figure) -> str:
    """'Figure 3' / 'Table 2' from the caption (the paper's own numbering), else 'Image n'."""
    match = _CAPTION_NUMBER_RE.match(figure.caption or "")
    if match:
        word = match.group(1).lower()
        kind = "Table" if word.startswith(("tab", "表")) else "Figure"
        return f"{kind} {match.group(2)}"
    return f"Image {figure.n}"


def select_figures(doc: ParsedDocument, max_figures: int) -> List[Figure]:
    """Pick the most informative figures: captioned first, then uncaptioned, in page order."""
    usable = []
    for figure in doc.figures:
        path = doc.figure_path(figure)
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size >= MIN_IMAGE_BYTES:
            usable.append(figure)
    captioned = [f for f in usable if f.caption]
    uncaptioned = [f for f in usable if not f.caption and f.context]
    chosen = (captioned + uncaptioned)[:max_figures]
    return sorted(chosen, key=lambda f: f.n)


def _image_data_uri(path: Path) -> Tuple[str, int]:
    data = path.read_bytes()
    suffix = path.suffix.lower()
    mime = {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(suffix, "image/jpeg")
    if len(data) > MAX_IMAGE_BYTES or suffix not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        pix = fitz.Pixmap(str(path))
        if pix.colorspace and pix.colorspace.n not in (1, 3):
            pix = fitz.Pixmap(fitz.csRGB, pix)
        if pix.alpha:
            pix = fitz.Pixmap(pix, 0)
        while max(pix.width, pix.height) > MAX_SIDE:
            pix.shrink(1)
        data = pix.tobytes("jpeg", jpg_quality=85)
        mime = "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}", len(data)


async def _describe(
    provider: Provider, config: VisionConfig, title: str, figure: Figure, data_uri: str
) -> str:
    kind_zh = "表格" if figure.kind == "table" else "图"
    prompt = VISION_FIGURE_PROMPT.format(
        title=title,
        label=figure_label(figure),
        kind=figure.kind,
        kind_zh=kind_zh,
        page=figure.page or "?",
        caption=figure.caption or "（无图注）",
        context=(figure.context or "（无）")[:400],
    )
    return await chat_text(
        provider,
        config.model,
        [
            {"role": "system", "content": VISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            },
        ],
        temperature=0.2,
        max_tokens=config.max_tokens,
    )


def _short(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "…"


async def build_visual_evidence(
    doc: ParsedDocument,
    figures: List[Figure],
    provider: Provider,
    config: VisionConfig,
    title: str,
    progress: ProgressFn,
) -> str:
    """Describe the selected figures (bounded concurrency) and format the evidence list."""
    payloads: List[Tuple[Figure, str]] = []
    total = 0
    for figure in figures:
        try:
            uri, size = await asyncio.to_thread(_image_data_uri, doc.figure_path(figure))
        except Exception as e:
            logger.warning("Skipping unreadable figure %s: %s", figure.path, e)
            continue
        if total + size > MAX_TOTAL_BYTES:
            break
        total += size
        payloads.append((figure, uri))
    if not payloads:
        return ""

    semaphore = asyncio.Semaphore(config.concurrency)
    done_count = 0

    async def run(figure: Figure, uri: str) -> Optional[str]:
        nonlocal done_count
        async with semaphore:
            try:
                return await _describe(provider, config, title, figure, uri)
            finally:
                done_count += 1
                await progress(f"已识别 {done_count}/{len(payloads)} 张图表")

    results = await asyncio.gather(*(run(f, u) for f, u in payloads), return_exceptions=True)

    lines = []
    errors: List[BaseException] = []
    for (figure, _), result in zip(payloads, results):
        if isinstance(result, BaseException):
            errors.append(result)
            logger.warning("Vision model failed on Figure %d: %s", figure.n, result)
            continue
        if not result:
            continue
        caption = _short(figure.caption) if figure.caption else "（无图注）"
        lines.append(f"[{figure_label(figure)}] {caption} — {result.strip()}")

    if not lines and errors:
        # Every call failed: surface it (most often a bad key / non-vision model)
        first = errors[0]
        if isinstance(first, PipelineError):
            raise first
        raise PipelineError("llm_error", f"视觉模型调用失败: {first}")
    return "\n".join(lines)
