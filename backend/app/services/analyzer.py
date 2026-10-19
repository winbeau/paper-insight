"""Paper analysis pipeline (replaces the Dify workflow).

    download ─▶ parse (MinerU cloud | local) ─▶ vision (VLM over figures) ─▶ analyze (reasoning LLM) ─▶ finalize

`run_pipeline` is a pure async generator of PipelineEvents (no DB writes);
`process_paper` wraps it with the paper's DB state: atomic claim, save on success,
'failed' on error or cancellation. The SSE endpoint and the scheduler both use it.
"""

import asyncio
import contextlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, TypeVar

from sqlalchemy import text

from app.config import parsed_dir_for
from app.database import engine, get_sync_session
from app.logging_config import get_logger
from app.models import AppSettings, LLMAnalysis, Paper
from app.prompts import build_analysis_messages
from app.schemas import AppSettingsRead, ModelRef, Provider, get_provider, load_settings
from app.services.errors import PipelineError
from app.services.llm_client import stream_chat
from app.services.parsers import ParseRequest, parse_document, validate_parser_config
from app.services.parsers.base import ProgressFn, load_cached
from app.services.pdf_renderer import ensure_pdf, generate_thumbnail
from app.services.vision import build_visual_evidence, select_figures

logger = get_logger("services.analyzer")

T = TypeVar("T")

STEPS: List[Dict[str, str]] = [
    {"key": "download", "label": "下载PDF"},
    {"key": "parse", "label": "解析PDF"},
    {"key": "vision", "label": "图像识别"},
    {"key": "analyze", "label": "推理分析"},
    {"key": "finalize", "label": "整合输出"},
]

ENGINE_LABELS = {"mineru_cloud": "MinerU 云端", "mineru_local": "MinerU 本地"}


# --- Result model (same fields the Dify workflow returned) --------------------------


@dataclass
class ConceptBridging:
    source_concept: str = ""      # 目标论文中的关键技术概念
    target_concept: str = ""      # 用户 Idea 中的对应概念
    mechanism_transfer: str = ""  # 迁移机制说明


@dataclass
class AnalysisResult:
    paper_essence: str = ""
    concept_bridging: ConceptBridging = field(default_factory=ConceptBridging)
    visual_verification: str = ""
    relevance_score: float = 0
    relevance_reason: str = ""
    heuristic_suggestion: str = ""
    thought_process: Optional[str] = None

    def to_event_payload(self) -> Dict[str, Any]:
        return {
            "paper_essence": self.paper_essence,
            "concept_bridging": {
                "source_concept": self.concept_bridging.source_concept,
                "target_concept": self.concept_bridging.target_concept,
                "mechanism_transfer": self.concept_bridging.mechanism_transfer,
            },
            "visual_verification": self.visual_verification,
            "relevance_score": self.relevance_score,
            "relevance_reason": self.relevance_reason,
            "heuristic_suggestion": self.heuristic_suggestion,
            "thought_process": self.thought_process,
        }


@dataclass
class PipelineEvent:
    # step_started | step_progress | step_finished | step_skipped | thinking | answer | result
    type: str
    step: Optional[str] = None
    message: str = ""
    text: str = ""
    result: Optional[AnalysisResult] = None
    thumbnail_url: Optional[str] = None


@dataclass
class PaperSnapshot:
    id: int
    arxiv_id: str
    title: str
    abstract: str
    pdf_url: str
    thumbnail_url: Optional[str]


# --- Output parsing (ported from the Dify client) -----------------------------------

_RESULT_FIELDS = (
    "paper_essence", "concept_bridging", "visual_verification",
    "relevance_score", "relevance_reason", "heuristic_suggestion",
)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(_as_text(v) for v in value if _as_text(v))
    if isinstance(value, dict):
        return "\n".join(f"{k}: {_as_text(v)}" for k, v in value.items())
    return str(value)


def _as_score(value: Any) -> float:
    if isinstance(value, (int, float)):
        score = float(value)
    else:
        match = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
        score = float(match.group()) if match else 0.0
    return max(0.0, min(10.0, score))


def _extract_json(answer: str) -> Optional[Dict[str, Any]]:
    candidates = []
    for pattern in (r"```json\s*(.*?)```", r"```\s*(.*?)```"):
        match = re.search(pattern, answer, re.DOTALL)
        if match:
            candidates.append(match.group(1))
    candidates.append(answer)
    start, end = answer.find("{"), answer.rfind("}")
    if 0 <= start < end:
        candidates.append(answer[start:end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


def outputs_to_result(outputs: Dict[str, Any], thought_process: str = "") -> AnalysisResult:
    concept_bridging = ConceptBridging()
    cb = outputs.get("concept_bridging")
    if isinstance(cb, dict):
        concept_bridging = ConceptBridging(
            source_concept=_as_text(cb.get("source_concept")),
            target_concept=_as_text(cb.get("target_concept")),
            mechanism_transfer=_as_text(cb.get("mechanism_transfer")),
        )
    elif cb:
        concept_bridging = ConceptBridging(mechanism_transfer=_as_text(cb))

    return AnalysisResult(
        paper_essence=_as_text(outputs.get("paper_essence")),
        concept_bridging=concept_bridging,
        visual_verification=_as_text(outputs.get("visual_verification")),
        relevance_score=_as_score(outputs.get("relevance_score")),
        relevance_reason=_as_text(outputs.get("relevance_reason")),
        heuristic_suggestion=_as_text(outputs.get("heuristic_suggestion")),
        thought_process=thought_process or None,
    )


def parse_analysis(answer: str, thought_process: str = "") -> AnalysisResult:
    """Parse the reasoning model's answer into an AnalysisResult or raise llm_error."""
    text_ = (answer or "").strip()
    # Inline reasoning that slipped through (e.g. only a closing </think> was emitted)
    if "</think>" in text_:
        before, text_ = text_.rsplit("</think>", 1)
        if not thought_process:
            thought_process = before.replace("<think>", "").strip()
    data = _extract_json(text_)
    if not data or not any(key in data for key in _RESULT_FIELDS):
        preview = " ".join(text_.split())[:200] or "（空）"
        raise PipelineError("llm_error", f"模型输出不是有效的分析 JSON：{preview}")
    return outputs_to_result(data, thought_process)


def to_llm_analysis(result: AnalysisResult) -> LLMAnalysis:
    """Flatten for storage: concept_bridging becomes the 3-line string the UI renders."""
    parts = []
    if result.concept_bridging.source_concept:
        parts.append(f"源概念: {result.concept_bridging.source_concept}")
    if result.concept_bridging.target_concept:
        parts.append(f"目标概念: {result.concept_bridging.target_concept}")
    if result.concept_bridging.mechanism_transfer:
        parts.append(f"迁移机制: {result.concept_bridging.mechanism_transfer}")
    return LLMAnalysis(
        paper_essence=result.paper_essence,
        concept_bridging_str="\n".join(parts),
        visual_verification=result.visual_verification,
        relevance_score=result.relevance_score,
        relevance_reason=result.relevance_reason,
        heuristic_suggestion=result.heuristic_suggestion,
    )


# --- Pipeline ------------------------------------------------------------------------


def _require_provider(settings: AppSettingsRead, ref: ModelRef, what: str) -> Provider:
    if not ref.configured:
        raise PipelineError("config_error", f"未配置{what}（设置 → 解析流程）")
    provider = get_provider(settings, ref.provider_id)
    if provider is None:
        raise PipelineError("config_error", f"{what}使用的模型服务不存在，请重新选择")
    if provider.needs_api_key:
        raise PipelineError("config_error", f"请在 设置 → 模型服务 中填写 {provider.name} 的 API Key")
    return provider


async def _with_progress(
    step: str,
    fn: Callable[[ProgressFn], Awaitable[T]],
    holder: List[T],
) -> AsyncIterator[PipelineEvent]:
    """Run `fn(progress)`; relay its progress messages as events; store its result."""
    queue: asyncio.Queue = asyncio.Queue()

    async def progress(message: str) -> None:
        await queue.put(message)

    task = asyncio.create_task(fn(progress))
    try:
        while True:
            getter = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
            if getter in done:
                yield PipelineEvent("step_progress", step, message=getter.result())
            else:
                getter.cancel()
            if task in done:
                while not queue.empty():
                    yield PipelineEvent("step_progress", step, message=queue.get_nowait())
                holder.append(task.result())
                return
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


async def run_pipeline(paper: PaperSnapshot, settings: AppSettingsRead) -> AsyncIterator[PipelineEvent]:
    pipeline = settings.pipeline
    reasoning_provider = _require_provider(settings, pipeline.reasoning, "推理模型")
    if not load_cached(parsed_dir_for(paper.arxiv_id)):
        validate_parser_config(pipeline.parser)

    vision_provider: Optional[Provider] = None
    vision_skip_reason = ""
    if not pipeline.vision.enabled:
        vision_skip_reason = "已关闭图像识别"
    elif not pipeline.vision.configured:
        vision_skip_reason = "未配置视觉模型"
    else:
        vision_provider = get_provider(settings, pipeline.vision.provider_id)
        if vision_provider is None:
            vision_skip_reason = "视觉模型服务不存在"
        elif vision_provider.needs_api_key:
            vision_provider = None
            vision_skip_reason = "视觉模型服务未填写 API Key"

    # 1. Download
    yield PipelineEvent("step_started", "download", message="下载 PDF...")
    pdf_path = await ensure_pdf(paper.arxiv_id, paper.pdf_url)
    yield PipelineEvent(
        "step_finished", "download", message=f"PDF {pdf_path.stat().st_size / 1024 / 1024:.1f} MB"
    )

    # 2. Parse
    engine_label = ENGINE_LABELS.get(pipeline.parser.engine, pipeline.parser.engine)
    yield PipelineEvent("step_started", "parse", message=f"{engine_label} 解析中...")
    request = ParseRequest(
        arxiv_id=paper.arxiv_id,
        title=paper.title,
        pdf_url=paper.pdf_url,
        pdf_path=pdf_path,
        out_dir=parsed_dir_for(paper.arxiv_id),
    )
    parsed_holder: list = []
    async with contextlib.aclosing(_with_progress(
        "parse", lambda progress: parse_document(pipeline.parser, request, progress), parsed_holder
    )) as events:
        async for event in events:
            yield event
    doc = parsed_holder[0]
    yield PipelineEvent(
        "step_finished",
        "parse",
        message=(
            f"{ENGINE_LABELS.get(doc.engine, doc.engine)}{'（缓存）' if doc.from_cache else ''}："
            f"{len(doc.markdown) // 1000}k 字符，{len(doc.figures)} 张图表"
        ),
    )

    # 3. Vision
    visual_evidence = ""
    figures = select_figures(doc, pipeline.vision.max_figures) if vision_provider else []
    if vision_provider is None:
        yield PipelineEvent("step_skipped", "vision", message=vision_skip_reason)
    elif not figures:
        yield PipelineEvent("step_skipped", "vision", message="论文中没有可识别的图表")
    else:
        yield PipelineEvent(
            "step_started", "vision", message=f"{pipeline.vision.model} 识别 {len(figures)} 张图表..."
        )
        evidence_holder: list = []
        async with contextlib.aclosing(_with_progress(
            "vision",
            lambda progress: build_visual_evidence(
                doc, figures, vision_provider, pipeline.vision, paper.title, progress
            ),
            evidence_holder,
        )) as events:
            async for event in events:
                yield event
        visual_evidence = evidence_holder[0]
        count = visual_evidence.count("\n") + 1 if visual_evidence else 0
        yield PipelineEvent("step_finished", "vision", message=f"{count} 条视觉证据")

    # 4. Analyze (streamed)
    reasoning = pipeline.reasoning
    yield PipelineEvent("step_started", "analyze", message=f"{reasoning.model} 推理中...")
    messages = build_analysis_messages(
        system_prompt=settings.system_prompt,
        research_idea=settings.research_idea,
        research_focus=settings.research_focus,
        title=paper.title,
        arxiv_id=paper.arxiv_id,
        abstract=paper.abstract,
        markdown=doc.markdown,
        visual_evidence=visual_evidence,
        max_input_chars=reasoning.max_input_chars,
    )
    thought_parts: List[str] = []
    answer_parts: List[str] = []
    async with contextlib.aclosing(stream_chat(
        reasoning_provider,
        reasoning.model,
        messages,
        temperature=reasoning.temperature,
        max_tokens=reasoning.max_tokens,
        json_mode=reasoning_provider.json_mode,
    )) as chunks:
        async for kind, chunk in chunks:
            if kind == "thinking":
                thought_parts.append(chunk)
                yield PipelineEvent("thinking", "analyze", text=chunk)
            else:
                answer_parts.append(chunk)
                yield PipelineEvent("answer", "analyze", text=chunk)
    yield PipelineEvent("step_finished", "analyze")

    # 5. Finalize
    yield PipelineEvent("step_started", "finalize", message="整合输出...")
    result = parse_analysis("".join(answer_parts), "".join(thought_parts))
    thumbnail_url = paper.thumbnail_url or await generate_thumbnail(paper.arxiv_id, pdf_path)
    yield PipelineEvent("step_finished", "finalize", message=f"相关性 {result.relevance_score:g}/10")
    yield PipelineEvent("result", result=result, thumbnail_url=thumbnail_url)


# --- DB state around a run -------------------------------------------------------------

# Papers with a live run in this process (the app is a single process)
_active: set[int] = set()


def active_paper_ids() -> List[int]:
    return list(_active)



def claim_paper(paper_id: int) -> bool:
    """Atomically move a paper into 'processing'. False if another run already owns it."""
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE paper SET processing_status = 'processing', "
                "processing_started_at = :now, processing_error = NULL "
                "WHERE id = :id AND processing_status != 'processing'"
            ),
            {"id": paper_id, "now": datetime.utcnow()},
        )
        return result.rowcount == 1


def mark_failed(paper_id: int, code: str, message: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE paper SET processing_status = 'failed', processing_error = :error "
                "WHERE id = :id AND processing_status = 'processing'"
            ),
            {"id": paper_id, "error": f"{code}: {message}"[:2000]},
        )


def save_result(paper_id: int, result: AnalysisResult, thumbnail_url: Optional[str]) -> None:
    analysis = to_llm_analysis(result)
    with get_sync_session() as session:
        paper = session.get(Paper, paper_id)
        if paper is None:
            return
        if thumbnail_url:
            paper.thumbnail_url = thumbnail_url
        paper.paper_essence = analysis.paper_essence
        paper.concept_bridging = analysis.concept_bridging_str
        paper.visual_verification = analysis.visual_verification
        paper.relevance_score = analysis.relevance_score
        paper.relevance_reason = analysis.relevance_reason
        paper.heuristic_suggestion = analysis.heuristic_suggestion
        paper.is_processed = True
        paper.processed_at = datetime.utcnow()
        paper.processing_error = None
        paper.processing_status = "processed" if analysis.relevance_score >= 5 else "skipped"
        session.add(paper)
        session.commit()


def _load(paper_id: int) -> tuple[PaperSnapshot, AppSettingsRead]:
    with get_sync_session() as session:
        paper = session.get(Paper, paper_id)
        if paper is None:
            raise PipelineError("unknown", "论文不存在")
        snapshot = PaperSnapshot(
            id=paper.id,
            arxiv_id=paper.arxiv_id,
            title=paper.title,
            abstract=paper.abstract,
            pdf_url=paper.pdf_url,
            thumbnail_url=paper.thumbnail_url,
        )
        return snapshot, load_settings(session.get(AppSettings, 1))


def reasoning_configured() -> bool:
    with get_sync_session() as session:
        settings = load_settings(session.get(AppSettings, 1))
    ref = settings.pipeline.reasoning
    provider = get_provider(settings, ref.provider_id)
    return ref.configured and provider is not None and not provider.needs_api_key


async def process_paper(paper_id: int) -> AsyncIterator[PipelineEvent]:
    """Run the pipeline for one paper and persist the outcome.

    Raises PipelineError("busy") if the paper is already being processed. If the consumer
    stops early (client disconnect → cancellation), the paper is marked failed.
    """
    snapshot, settings = _load(paper_id)
    if paper_id in _active or not claim_paper(paper_id):
        raise PipelineError("busy", "该论文正在分析中")

    _active.add(paper_id)
    failure = ("interrupted", "分析被中断")
    succeeded = False
    try:
        async with contextlib.aclosing(run_pipeline(snapshot, settings)) as events:
            async for event in events:
                if event.type == "result" and event.result is not None:
                    save_result(paper_id, event.result, event.thumbnail_url)
                    succeeded = True
                yield event
    except PipelineError as e:
        failure = (e.code, e.message)
        raise
    except Exception as e:
        failure = ("unknown", str(e))
        raise
    finally:
        _active.discard(paper_id)
        if not succeeded:
            mark_failed(paper_id, *failure)
            logger.warning("Paper %s failed: %s: %s", paper_id, *failure)


async def analyze_paper(paper_id: int) -> bool:
    """Non-streaming run for the scheduler. Returns True on success."""
    try:
        async with contextlib.aclosing(process_paper(paper_id)) as events:
            async for _ in events:
                pass
        return True
    except PipelineError as e:
        if e.code != "busy":
            logger.error("Paper %s analysis failed (%s): %s", paper_id, e.code, e.message)
        return False
    except Exception:
        logger.exception("Paper %s analysis crashed", paper_id)
        return False
