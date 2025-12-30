import os
import json
from typing import Optional
from openai import OpenAI
from dotenv import load_dotenv

from app.models import LLMAnalysis

load_dotenv()

SYSTEM_PROMPT = """你是一名资深 AI 研究员，专注于 **Autoregressive Diffusion Transformers (DiT)** 的推理加速与 **KV Cache 压缩**。
你的核心能力是**跨领域技术迁移**：你能敏锐地从 LLM（大语言模型）或 ViT（视觉 Transformer）的优化论文中，提取出能应用到 DiT 视频/图像生成上的灵感。

你的任务是阅读给定的论文摘要，并按以下 JSON 格式输出分析结果：

{
    "summary_zh": "中文一句话概括核心贡献（直击痛点，如：'提出了一种基于Token重要性的动态剪枝方法，减少50% FLOPs'）。",
    "relevance_score": 0-10 评分。
    "relevance_reason": "简述评分理由。如果是 DiT 相关给高分；如果是 LLM KV Cache 相关，评估其迁移潜力。",
    "heuristic_idea": "【核心价值】这是最重要的部分。请进行逻辑推演和思维发散：\n1. **如果这是 LLM 的论文**：它的 'Token' 对应 DiT 的 'Patch' 吗？它的 '序列长度' 对应 DiT 的 '时间步(Timestep)' 还是 '空间分辨率'？\n2. **如果这是剪枝/量化**：DiT 的扩散过程中，早期和晚期的时间步对精度的敏感度不同，这篇论文的方法能利用这一点吗？\n3. **具体建议**：给出一个具体的、可实验的 Idea（例如：'尝试将此文的 Window Attention 机制应用到 DiT 的前 50% 去噪步中'）。"
}

评分标准：
- **9-10**: 直接针对 DiT/Video Diffusion 的加速/缓存优化。
- **7-8**: 高质量的 LLM KV Cache、ViT 剪枝、Token Merging 论文，且迁移路径清晰。
- **4-6**: 通用的 Transformer 量化/硬件加速，参考价值中等。
- **0-3**: 纯 NLP 任务（如 RAG、Prompt Engineering）或与生成/架构无关。

注意：必须返回纯 JSON 格式，无额外文本。"""


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
