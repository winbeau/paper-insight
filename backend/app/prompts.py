"""Prompts for the analysis pipeline.

The analysis prompt reconstructs what the former Dify workflow did: the persona and
scoring rubric come from the pre-Dify prompt (git show ada8fdb^:backend/app/services/llm_brain.py),
generalized from the hard-coded DiT topic to "relative to the user's research idea";
the output fields are the ones the Dify workflow returned. A direction's `system_prompt`
replaces the persona/rubric part; the output spec is fixed.

Prompt-cache layout — DeepSeek (and other providers) cache identical prompt *prefixes*,
so every request is ordered by how much of it repeats, in tokens, and the repeated parts
are byte-identical (no timestamps, ids or per-request wording in them):

  analysis   [system: static role + output spec]
             [user: paper text | visual evidence | direction's rubric | research idea]
             -> the paper (~10-30k tokens) is shared when the same paper is analyzed again:
                in another direction, on a retry, or after the idea/rubric was edited;
                the system prompt is shared by every analysis
  vision     [system: static instructions] [user: paper context | figure info | image]
             -> shared by all figures of a paper; the first figure warms the cache
  research   one append-only conversation; each round extends the previous request
"""

import re

ANALYSIS_PERSONA = """你是一名资深 AI 研究员，擅长**跨领域技术迁移**：能从其他方向（如 LLM、ViT、系统与算法优化）的论文中，提炼出可以迁移到用户研究方向上的机制与灵感。

评分标准（相对于用户的研究 Idea）：
- 9-10：直接解决用户研究的核心问题，或方法几乎无需改动即可应用；
- 7-8：相邻领域的高质量工作，迁移路径清晰；
- 5-6：有一定参考价值（通用技术，部分思路可借鉴）；
- 0-4：与用户研究方向基本无关。"""

ANALYSIS_OUTPUT_SPEC = """你会依次收到：
1. 一篇论文的全文（由 MinerU 解析为 Markdown，可能经过截断）；
2. 视觉证据（Visual Evidence）：视觉模型对论文图表的逐条描述，按论文自身的编号标注（如 [Figure 3]、[Table 2]）；
3. 本研究方向的「分析视角与评分标准」——评分时以它为准；
4. 用户的研究 Idea（研究主题、技术背景与动机、核心方法论、预期贡献）。

请完成分析，并**只输出一个 JSON 对象**（不要输出其他文字，不要使用 Markdown 代码块），字段如下：
{
  "paper_essence": "中文一句话概括论文的核心创新，直击机制（例如：'提出基于注意力头重要性的动态 KV Cache 剪枝，在 4× 压缩下保持 99% 精度'）",
  "concept_bridging": {
    "source_concept": "论文中的关键技术概念",
    "target_concept": "用户研究 Idea 中与之对应的概念",
    "mechanism_transfer": "迁移机制：该方法如何映射/改造后用于用户的研究，以及需要注意的差异"
  },
  "visual_verification": "基于视觉证据做事实核查：引用具体编号（如 Figure 3、Table 2）说明哪些图表支持论文的核心主张、哪些主张缺乏图表证据；若没有视觉证据，说明仅基于正文判断",
  "relevance_score": 0 到 10 的数字,
  "relevance_reason": "评分理由：与用户研究 Idea 的契合点或差距",
  "heuristic_suggestion": "可执行的研究建议：给出编号的具体实验方案（方法设计 / 实验设置 / 评测指标），可引用视觉证据作为依据"
}

要求：全部使用中文；不要编造论文正文或视觉证据中不存在的数据；relevance_score 必须是数字。"""


ANALYSIS_SYSTEM_PROMPT = f"""你是一名资深 AI 研究员，负责评估一篇论文对用户研究的价值，并给出可迁移的洞察。

{ANALYSIS_OUTPUT_SPEC}"""


def analysis_system_prompt() -> str:
    """Identical for every analysis request (the start of the cached prefix)."""
    return ANALYSIS_SYSTEM_PROMPT


def analysis_persona(custom: str = "") -> str:
    """The direction's perspective and 0-10 rubric (custom or default)."""
    return (custom or "").strip() or ANALYSIS_PERSONA

NO_IDEA_PLACEHOLDER = "（用户尚未填写研究 Idea。请基于论文本身的学术价值与可迁移性做通用评估。）"

# Static: every instruction lives here so the per-figure messages carry only data
VISION_SYSTEM_PROMPT = """你是论文图表分析助手，负责为后续的论文分析提供准确、可引用的视觉证据。

每次你会收到：论文标题与摘要（背景），一张图表的编号、图注与附近正文，以及这张图表的图片。

请用中文描述这张图表：
1. 它展示了什么（实验设置、对比对象、坐标轴或列含义）；
2. 关键的定量结果：具体数值、相对提升、趋势与拐点；
3. 它支持论文的哪个结论，或与哪个结论不一致。

要求：不超过 150 字；只依据图片与给出的文字，不要编造图中没有的信息；看不清的数值写"不可辨认"。"""

VISION_PAPER_CONTEXT = """论文：{title}
摘要：{abstract}"""

VISION_FIGURE_PROMPT = """图表编号：{label}（{kind_zh}，第 {page} 页）
图注：{caption}
附近正文：{context}"""

_IMAGE_LINK_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_REFERENCES_RE = re.compile(r"^#{1,6}\s*(references|bibliography|参考文献)\s*$", re.IGNORECASE | re.MULTILINE)


def clean_markdown(markdown: str, max_chars: int) -> str:
    """Strip image links and the reference list, then fit into `max_chars` (head + tail)."""
    text = _IMAGE_LINK_RE.sub("", markdown)
    match = _REFERENCES_RE.search(text)
    if match and match.start() > len(text) * 0.4:
        # Drop the bibliography but keep appendices that follow it
        after = text[match.end():]
        next_heading = re.search(r"^#{1,6}\s+\S", after, re.MULTILINE)
        text = text[:match.start()] + (after[next_heading.start():] if next_heading else "")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= max_chars:
        return text
    marker = "\n\n[……中间部分因长度限制已省略……]\n\n"
    head = int(max_chars * 0.75)
    tail = max_chars - head - len(marker)
    return text[:head] + marker + text[-tail:]


def build_analysis_messages(
    *,
    system_prompt: str,
    research_idea: str,
    research_focus: str,
    title: str,
    arxiv_id: str,
    abstract: str,
    markdown: str,
    visual_evidence: str,
    max_input_chars: int,
) -> list[dict]:
    idea = research_idea.strip()
    if not idea:
        idea = NO_IDEA_PLACEHOLDER
        if research_focus.strip():
            idea += f"\n用户的检索关注点：{research_focus.strip()}"

    body = clean_markdown(markdown, max_input_chars)
    evidence = visual_evidence.strip() or "（无：未启用视觉模型，或论文中没有可识别的图表）"
    # Paper first: it is the large, repeated part (see the cache layout above)
    user = (
        f"## 论文\n标题：{title}\narXiv：{arxiv_id}\n\n"
        f"### 摘要\n{abstract}\n\n"
        f"### 正文（MinerU 解析）\n{body}\n\n"
        f"## 视觉证据（Visual Evidence）\n{evidence}\n\n"
        f"## 分析视角与评分标准\n{analysis_persona(system_prompt)}\n\n"
        f"## 我的研究 Idea\n{idea}\n\n"
        "请按要求只输出 JSON。"
    )
    return [
        {"role": "system", "content": analysis_system_prompt()},
        {"role": "user", "content": user},
    ]
