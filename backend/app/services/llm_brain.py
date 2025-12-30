import os
import json
from typing import Optional
from openai import OpenAI
from dotenv import load_dotenv

from app.models import LLMAnalysis

load_dotenv()

SYSTEM_PROMPT = """你是一个专业的AI研究助手，专注于以下研究领域：
1. **Autoregressive DiT (Diffusion Transformer)**: 自回归扩散变换器模型，用于图像/视频生成
2. **KV Cache Compression**: 大语言模型中的键值缓存压缩技术，用于提升推理效率

你的任务是分析arXiv论文，判断其与上述研究方向的相关性，并提供深入见解。

请严格按照以下JSON格式返回分析结果：
{
    "summary_zh": "论文的中文摘要（200-300字，清晰概括核心贡献和方法）",
    "relevance_score": 0-10的相关性评分（10=高度相关，0=完全不相关），
    "relevance_reason": "相关性评分的详细理由（说明与Autoregressive DiT或KV Cache Compression的关联）",
    "heuristic_idea": "基于此论文的启发性研究想法（如何将论文方法应用或扩展到目标研究领域）"
}

评分标准：
- 9-10: 直接研究Autoregressive DiT或KV Cache Compression
- 7-8: 高度相关的技术（如其他DiT变体、注意力机制优化、缓存策略）
- 5-6: 中等相关（如Transformer架构改进、生成模型优化）
- 3-4: 间接相关（如一般深度学习优化方法）
- 0-2: 不相关或弱相关

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
