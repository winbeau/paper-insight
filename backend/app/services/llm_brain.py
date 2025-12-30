import os
import json
from typing import Optional
from openai import OpenAI
from dotenv import load_dotenv

from app.models import LLMAnalysis

load_dotenv()

SYSTEM_PROMPT = """你是一名资深研究员，专注于 **Autoregressive Diffusion Transformers (DiT)** 的推理加速，特别是 **KV Cache 的压缩**（Quantization, Pruning, Token Merging）。

你的任务是阅读给定的论文摘要（及标题），并按以下要求进行深入分析。

请严格按照以下JSON格式返回分析结果：
{
    "summary_zh": "用中文一句话概括核心贡献。",
    "relevance_score": 0-10的相关性评分（10=必须阅读，0=完全无关）。评分需严格，评估该论文对你的研究（DiT推理加速/KV Cache压缩）有多大参考价值。",
    "relevance_reason": "详细说明评分理由。如果涉及LLM的KV Cache或ViT剪枝，请说明其方法是否具备迁移潜力。",
    "heuristic_idea": "发散思维：即使这篇论文讲的是其他领域（如LLM或ViT），请通过逻辑推演，告诉我它的方法如何迁移到 DiT 上？例如：如果它利用了 Attention Map 的稀疏性，那么在 Diffusion 的生成过程中，这种稀疏性是否随时间步（Timestep）变化？我们能否利用这一点？"
}

评分参考：
- 9-10: 直接针对 DiT 的推理加速或 KV Cache 优化。
- 7-8: 高度相关的技术，如 LLM 的先进 KV Cache 压缩算法、ViT 的动态剪枝，且迁移路径清晰。
- 5-6: 中等相关，如通用的 Transformer 优化、量化方法，可能需要较大改动才能迁移。
- 3-4: 仅在思路上有参考价值，技术细节差异大。
- 0-2: 与目标领域无关。

注意：必须返回有效的JSON格式，不要包含任何额外文本。"""


class LLMBrain:
    """DeepSeek LLM client for paper analysis."""

    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY environment variable is not set")

        self.client = OpenAI(
            api_key=api_key,
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        )
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    def analyze_paper(self, title: str, abstract: str) -> Optional[LLMAnalysis]:
        """Analyze a paper and return structured analysis."""
        user_prompt = f"""请分析以下论文：

标题: {title}

摘要: {abstract}

请按照系统提示中的JSON格式返回分析结果。"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=1500,
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            if not content:
                return None

            data = json.loads(content)
            return LLMAnalysis(
                summary_zh=data.get("summary_zh", ""),
                relevance_score=float(data.get("relevance_score", 0)),
                relevance_reason=data.get("relevance_reason", ""),
                heuristic_idea=data.get("heuristic_idea", ""),
            )

        except json.JSONDecodeError as e:
            print(f"JSON parsing error: {e}")
            return None
        except Exception as e:
            print(f"LLM analysis error: {e}")
            return None


# Singleton instance
_llm_brain: Optional[LLMBrain] = None


def get_llm_brain() -> LLMBrain:
    """Get or create LLMBrain singleton."""
    global _llm_brain
    if _llm_brain is None:
        _llm_brain = LLMBrain()
    return _llm_brain
