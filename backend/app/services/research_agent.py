"""Research-direction agent: turns a plain-language description into the four settings of
the Research tab (arXiv categories, arXiv query, research idea, analysis prompt).

The arXiv query is not trusted on the model's word: every candidate is run against the
live arXiv API (services.arxiv_probe) and the model judges the sample papers it returns.
Rounds continue until the query finds a sensible weekly volume of relevant papers; the
best *tested* query wins.

The whole run is one append-only conversation, so each round's request extends the
previous one and reuses its cached prefix (see app.prompts).
"""

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from app.constants import ARXIV_CATEGORY_CODES, ARXIV_OPTIONS
from app.logging_config import get_logger
from app.prompts import ANALYSIS_PERSONA
from app.schemas import Provider
from app.services.arxiv_bot import compose_query
from app.services.arxiv_probe import FETCH_SIZE, ProbeResult, probe_query
from app.services.errors import PipelineError
from app.services.llm_client import stream_chat

logger = get_logger("services.research_agent")

MIN_ROUNDS = 2            # always test at least two candidate queries
MAX_ROUNDS = 4
SAMPLE_SIZE = 12          # papers shown to the model per round
WEEKLY_RANGE = (5, 40)    # papers/week the daily fetch should bring in
MIN_PRECISION = 0.7

_CATEGORY_LINES = "\n".join(f"- {o['code']}: {o['name']} — {o['desc']}" for o in ARXIV_OPTIONS)

# Static (cache-stable) instructions; everything run-specific rides the conversation tail
SYSTEM_PROMPT = f"""你是 PaperInsight 的「研究方向配置助手」。PaperInsight 每天从 arXiv 抓取新论文，并用大模型结合用户的研究方向评估每篇论文。
你的任务：根据用户用大白话写的研究描述，生成「研究方向」页的 4 项设置，并通过多轮 arXiv 实测把检索式调到最好。

## 4 项设置
1. arxiv_categories：从下表选 1–4 个最相关的分类（只能使用表中的代码）：
{_CATEGORY_LINES}

2. research_focus：arXiv API 检索式。程序会把它组合成 `(cat:A OR cat:B) AND (research_focus)`，每周抓取最新的 {FETCH_SIZE} 篇。
   语法：ti:（标题）、abs:（摘要）、all:（全部字段）；AND / OR / ANDNOT；短语用英文双引号（如 abs:"kv cache"）；用括号分组。
   写法建议：用英文术语；核心概念之间用 AND 收窄，同义词/缩写之间用 OR 扩展（如 (abs:"diffusion transformer" OR abs:DiT)）；
   避免过于宽泛的单个常见词（如 all:model），也避免把太多概念 AND 在一起导致几乎没有结果。不要在检索式里写 cat:。

3. research_idea：Markdown，严格包含四部分，基于用户描述扩写成具体、专业的表述，不要编造实验数据：
   **研究主题**：……
   **技术背景与动机**：……
   **核心方法论**：……
   **预期科学贡献**：……

4. analysis_prompt：分析每篇论文时使用的角色设定与 0–10 评分标准，针对用户方向定制（不要写输出格式，程序会自动追加）。参考格式：
{ANALYSIS_PERSONA}

## 质量标准（检索式）
- 近 7 天新论文数量在 {WEEKLY_RANGE[0]}–{WEEKLY_RANGE[1]} 篇之间（太少会漏掉论文，太多会被截断且噪声大）；
- 样本论文中与用户研究相关的比例 ≥ {int(MIN_PRECISION * 100)}%。

## 流程与输出（只输出一个 JSON 对象，不要输出其他文字或代码块）
- 第一次回复：{{"arxiv_categories": [...], "research_focus": "...", "research_idea": "...", "analysis_prompt": "..."}}
- 之后每轮你会收到上一个检索式的 arXiv 实测结果（命中总数、近 7 天数量、带编号的样本论文）。请逐篇判断样本是否与用户研究相关，回复：
  {{"relevant": [相关样本的编号], "assessment": "一句话评价（数量、相关率、主要噪声来源或遗漏）", "done": true 或 false, "research_focus": "改进后的检索式", "arxiv_categories": [...]}}
  如果当前检索式已经达标，done 设为 true，但仍可给出一个可能更好的候选检索式（程序会实测后择优）；数量过多或相关率低时收窄，数量过少时用同义词扩展或放宽 AND 条件。"""


@dataclass
class AgentFields:
    arxiv_categories: List[str]
    research_focus: str
    research_idea: str
    system_prompt: str


@dataclass
class RoundReport:
    round: int
    query: str
    research_focus: str
    arxiv_categories: List[str]
    total: int
    weekly: int
    weekly_capped: bool
    precision: Optional[float]
    acceptable: bool
    assessment: str = ""
    samples: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def score(self) -> float:
        precision = self.precision or 0.0
        low, high = WEEKLY_RANGE
        if self.weekly < low:
            volume_penalty = (low - self.weekly) / low
        elif self.weekly > high or self.weekly_capped:
            volume_penalty = min(1.0, (self.weekly - high) / high) if not self.weekly_capped else 1.0
        else:
            volume_penalty = 0.0
        return precision - 0.5 * volume_penalty


@dataclass
class AgentEvent:
    type: str          # status | thinking | draft | round | result
    data: Dict[str, Any]


def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text)
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            # strict=False: models often put raw newlines inside long Markdown strings
            data = json.loads(candidate.strip(), strict=False)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    raise PipelineError("llm_error", f"模型没有返回有效的 JSON：{' '.join(text.split())[:160]}")


def _clean_categories(value: Any, fallback: List[str]) -> List[str]:
    if not isinstance(value, list):
        return fallback
    codes = [c.strip() for c in value if isinstance(c, str) and c.strip() in ARXIV_CATEGORY_CODES]
    return list(dict.fromkeys(codes))[:4] or fallback


def _clean_focus(value: Any) -> str:
    focus = " ".join(str(value or "").split())
    focus = re.sub(r"\bcat:[\w.\-]+\s*(AND|OR)?\s*", "", focus).strip()  # categories are separate
    if focus.count("(") != focus.count(")"):
        raise PipelineError("llm_error", f"检索式括号不匹配：{focus}")
    return focus


def _format_probe(round_no: int, probe: ProbeResult) -> str:
    weekly = f"≥{probe.weekly}" if probe.weekly_capped else str(probe.weekly)
    lines = [
        f"第 {round_no} 轮实测结果",
        f"检索式：{probe.query}",
        f"命中总数：{probe.total}；近 7 天新论文：{weekly} 篇",
        "样本论文（最新在前）：",
    ]
    for i, paper in enumerate(probe.papers[:SAMPLE_SIZE], start=1):
        lines.append(f"[{i}] {paper.title} — {paper.abstract[:260]}")
    if not probe.papers:
        lines.append("（没有结果）")
    return "\n".join(lines)


async def _ask(
    provider: Provider, model: str, messages: List[Dict[str, Any]]
) -> AsyncIterator[AgentEvent]:
    """One model turn: stream its reasoning, append the reply to the conversation and
    finish with a "reply" event carrying the parsed JSON."""
    answer: List[str] = []
    async for kind, chunk in stream_chat(
        provider, model, messages, temperature=0.3, max_tokens=8192,
        json_mode=provider.json_mode, purpose="research_agent",
    ):
        if kind == "thinking":
            yield AgentEvent("thinking", {"thought": chunk})
        else:
            answer.append(chunk)
    reply = "".join(answer)
    messages.append({"role": "assistant", "content": reply})  # append-only: keeps the cache prefix
    try:
        data = _extract_json(reply)
    except PipelineError:
        # One repair turn, appended like any other (the prefix stays cached)
        messages.append({"role": "user", "content": "上一条回复不是合法的 JSON。请只输出一个合法的 JSON 对象（字符串内的换行写成 \\n）。"})
        answer = []
        async for kind, chunk in stream_chat(
            provider, model, messages, temperature=0.1, max_tokens=8192,
            json_mode=provider.json_mode, purpose="research_agent",
        ):
            if kind == "thinking":
                yield AgentEvent("thinking", {"thought": chunk})
            else:
                answer.append(chunk)
        reply = "".join(answer)
        messages.append({"role": "assistant", "content": reply})
        data = _extract_json(reply)
    yield AgentEvent("reply", data)


async def run_research_agent(
    description: str, provider: Provider, model: str
) -> AsyncIterator[AgentEvent]:
    description = description.strip()
    if len(description) < 10:
        raise PipelineError("config_error", "请多写几句你的研究内容（至少 10 个字）")

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"我的研究（大白话描述）：\n{description}"},
    ]

    yield AgentEvent("status", {"message": "正在理解你的研究并生成初稿…"})
    draft: Dict[str, Any] = {}
    async for event in _ask(provider, model, messages):
        if event.type == "reply":
            draft = event.data
        else:
            yield event
    fields = AgentFields(
        arxiv_categories=_clean_categories(draft.get("arxiv_categories"), ["cs.LG"]),
        research_focus=_clean_focus(draft.get("research_focus")),
        research_idea=str(draft.get("research_idea") or "").strip(),
        system_prompt=str(draft.get("analysis_prompt") or "").strip(),
    )
    if not fields.research_focus:
        raise PipelineError("llm_error", "模型没有给出检索式")
    yield AgentEvent("draft", asdict(fields))

    reports: List[RoundReport] = []
    candidate_focus, candidate_categories = fields.research_focus, fields.arxiv_categories
    tested: set = set()
    for round_no in range(1, MAX_ROUNDS + 1):
        query = compose_query(candidate_categories, candidate_focus, [])
        if query in tested:
            break  # the model proposed a query we already tested
        tested.add(query)

        yield AgentEvent("status", {"message": f"第 {round_no} 轮：在 arXiv 上测试检索式…"})
        try:
            probe = await probe_query(query)
        except PipelineError as e:
            if not reports:
                raise
            # Keep what was already verified rather than losing the whole run
            yield AgentEvent("status", {"message": f"{e.message}；使用已实测的最佳检索式"})
            break
        samples = probe.papers[:SAMPLE_SIZE]

        yield AgentEvent("status", {"message": f"第 {round_no} 轮：评估样本论文的相关性…"})
        messages.append({"role": "user", "content": _format_probe(round_no, probe)})
        verdict: Dict[str, Any] = {}
        async for event in _ask(provider, model, messages):
            if event.type == "reply":
                verdict = event.data
            else:
                yield event

        relevant = {int(i) for i in verdict.get("relevant") or [] if str(i).isdigit()}
        precision = (len([i for i in range(1, len(samples) + 1) if i in relevant]) / len(samples)) if samples else None
        low, high = WEEKLY_RANGE
        acceptable = (
            precision is not None and precision >= MIN_PRECISION
            and low <= probe.weekly <= high and not probe.weekly_capped
        )
        report = RoundReport(
            round=round_no,
            query=query,
            research_focus=candidate_focus,
            arxiv_categories=candidate_categories,
            total=probe.total,
            weekly=probe.weekly,
            weekly_capped=probe.weekly_capped,
            precision=precision,
            acceptable=acceptable,
            assessment=str(verdict.get("assessment") or ""),
            samples=[{"title": p.title, "relevant": i in relevant} for i, p in enumerate(samples, start=1)],
        )
        reports.append(report)
        yield AgentEvent("round", {**asdict(report), "score": round(report.score, 3)})
        logger.info(
            "Research agent round %d: weekly=%s precision=%s acceptable=%s query=%s",
            round_no, probe.weekly, precision, acceptable, query,
        )

        if round_no >= MIN_ROUNDS and acceptable and verdict.get("done"):
            break
        try:
            candidate_focus = _clean_focus(verdict.get("research_focus")) or candidate_focus
        except PipelineError:
            pass  # keep the last valid query
        candidate_categories = _clean_categories(verdict.get("arxiv_categories"), candidate_categories)

    best = max(reports, key=lambda r: r.score)
    fields.research_focus = best.research_focus
    fields.arxiv_categories = best.arxiv_categories
    yield AgentEvent("result", {
        "fields": asdict(fields),
        "best_round": best.round,
        "acceptable": best.acceptable,
        "rounds": [
            {k: v for k, v in asdict(r).items() if k != "samples"} | {"score": round(r.score, 3)}
            for r in reports
        ],
    })
