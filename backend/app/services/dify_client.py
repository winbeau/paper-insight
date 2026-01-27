"""
Dify Workflow API Client with PDF Upload and Streaming Support.

This module handles:
1. Download PDF from arXiv
2. Upload PDF to Dify
3. Send chat-messages with file reference for paper analysis
"""

import os
import json
import httpx
import tempfile
from typing import Optional, AsyncGenerator, Dict, Any
from dataclasses import dataclass
from dotenv import load_dotenv
from pathlib import Path

from app.models import LLMAnalysis

load_dotenv()


# Default idea template for paper analysis
DEFAULT_IDEA_INPUT = """研究主题：基于 Head-level 稀疏索引的视频 DiT 自适应注意力推理加速方案

技术背景与动机：
在自回归视频生成模型（如 Self-Forcing DiT）中，观测到 Self-attention 存在显著的 head-level 差异性：不同 Head 对视频连贯性的建模窗口长度不一。传统的全张量计算在处理这种非均匀滑窗时会产生大量补齐（Padding）开销，导致显存冗余及 Ragged Tensor（参差不齐张量）处理难题。

核心方法论：
1. 块矩阵平展化存储：将 Q, K, V 向量按 [1, D] 分块，作为最小存储模块
2. 前缀和哈希索引：建立动态偏移量索引，实现对非均匀序列的快速定位
3. 高精细度 Attention Kernel 重构：利用索引动态切片提取对应 Head 的 Ragged Tensor

预期科学贡献：
- 显存优化：通过消除 Ragged Tensor 的空位填充，显著降低长视频生成时的 KV Cache 压力
- 频域关联：支持根据 FFT 分析得出的"6 帧周期特性"，为不同 Head 动态分配最佳滑窗长度
"""

DEFAULT_QUERY = """请对上传的 PDF 论文进行深入分析，结合我提供的研究 Idea，输出结构化的论文洞察报告。
重点关注：
1. 该论文的核心贡献与我的研究方向的契合度
2. 技术方法的可迁移性（特别是 LLM KV Cache → DiT 的映射）
3. 可以借鉴的具体实验方案或算法设计"""


@dataclass
class DifyStreamEvent:
    """Represents a single event from Dify's streaming response."""
    event: str
    data: Dict[str, Any]
    thought: Optional[str] = None
    answer: Optional[str] = None
    outputs: Optional[Dict[str, Any]] = None


@dataclass
class TechnicalMapping:
    """Technical mapping analysis from Dify workflow."""
    token_vs_patch: str = ""
    temporal_logic: str = ""
    frequency_domain: str = ""


@dataclass
class DifyAnalysisResult:
    """Complete analysis result from Dify workflow."""
    summary_zh: str
    relevance_score: float
    relevance_reason: str
    technical_mapping: TechnicalMapping
    heuristic_idea: str
    thought_process: Optional[str] = None


class DifyClientError(Exception):
    """Base exception for Dify client errors."""
    pass


class DifyEntityTooLargeError(DifyClientError):
    """Raised when request payload exceeds Dify's limit (413)."""
    pass


class DifyTimeoutError(DifyClientError):
    """Raised when request times out."""
    pass


class DifyRateLimitError(DifyClientError):
    """Raised when rate limit is exceeded (429)."""
    pass


class DifyClient:
    """Dify Chatflow API client with PDF upload and streaming support."""

    def __init__(self):
        self.api_key = os.getenv("DIFY_API_KEY")
        if not self.api_key:
            raise ValueError("DIFY_API_KEY environment variable is not set")

        self.base_url = os.getenv("DIFY_API_BASE", "http://82.157.209.193:8080/v1")
        self.chat_endpoint = f"{self.base_url}/chat-messages"
        self.upload_endpoint = f"{self.base_url}/files/upload"
        self.timeout = httpx.Timeout(300.0, connect=30.0)  # 5 min for R1 reasoning

    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authorization headers."""
        return {
            "Authorization": f"Bearer {self.api_key}",
        }

    async def download_pdf(self, pdf_url: str) -> bytes:
        """Download PDF from arXiv or other URL."""
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(pdf_url)
            if response.status_code != 200:
                raise DifyClientError(f"Failed to download PDF: {response.status_code}")
            return response.content

    async def upload_file(
        self,
        file_content: bytes,
        filename: str,
        user_id: str,
        mime_type: str = "application/pdf",
    ) -> str:
        """
        Upload a file to Dify and return the file ID.

        Returns:
            str: The uploaded file's ID
        """
        headers = self._get_auth_headers()

        # Create multipart form data
        files = {
            "file": (filename, file_content, mime_type),
        }
        data = {
            "user": user_id,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.upload_endpoint,
                headers=headers,
                files=files,
                data=data,
            )

            if response.status_code == 413:
                raise DifyEntityTooLargeError("PDF file too large for Dify")
            elif response.status_code == 415:
                raise DifyClientError("Unsupported file type")
            elif response.status_code >= 400:
                raise DifyClientError(
                    f"File upload failed: {response.status_code} - {response.text}"
                )

            result = response.json()
            return result["id"]

    def _build_chat_request(
        self,
        query: str,
        idea_input: str,
        file_id: str,
        user_id: str,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build the chat request body with file reference."""
        # Dify workflow expects paper_pdf in inputs referencing the uploaded file
        file_ref = {
            "type": "document",
            "transfer_method": "local_file",
            "upload_file_id": file_id,
        }

        body = {
            "inputs": {
                "idea_input": idea_input,
                "paper_pdf": file_ref,  # Reference file in inputs for workflow
            },
            "query": query,
            "response_mode": "streaming",
            "user": user_id,
            "files": [file_ref],  # Also include in files array
        }

        if conversation_id:
            body["conversation_id"] = conversation_id

        return body

    async def analyze_paper_stream(
        self,
        pdf_url: str,
        title: str,
        user_id: str = "paper-insight-user",
        idea_input: Optional[str] = None,
        query: Optional[str] = None,
    ) -> AsyncGenerator[DifyStreamEvent, None]:
        """
        Analyze a paper using Dify workflow with streaming.

        Args:
            pdf_url: URL to download the PDF from (e.g., arXiv PDF URL)
            title: Paper title (used for filename)
            user_id: User identifier
            idea_input: Research idea context (uses default if None)
            query: Analysis query (uses default if None)

        Yields:
            DifyStreamEvent objects for each SSE event received.
        """
        # Use defaults if not provided
        idea_input = idea_input or DEFAULT_IDEA_INPUT
        query = query or DEFAULT_QUERY

        # Step 1: Download PDF
        try:
            pdf_content = await self.download_pdf(pdf_url)
        except Exception as e:
            raise DifyClientError(f"Failed to download PDF: {e}")

        # Step 2: Upload PDF to Dify
        # Clean filename from title
        safe_title = "".join(c for c in title[:50] if c.isalnum() or c in " -_").strip()
        filename = f"{safe_title}.pdf" if safe_title else "paper.pdf"

        try:
            file_id = await self.upload_file(pdf_content, filename, user_id)
        except Exception as e:
            raise DifyClientError(f"Failed to upload PDF: {e}")

        # Step 3: Send chat request with file reference
        body = self._build_chat_request(query, idea_input, file_id, user_id)
        headers = {
            **self._get_auth_headers(),
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                async with client.stream(
                    "POST",
                    self.chat_endpoint,
                    json=body,
                    headers=headers,
                ) as response:
                    if response.status_code == 413:
                        raise DifyEntityTooLargeError("Request too large")
                    elif response.status_code == 429:
                        raise DifyRateLimitError("Rate limit exceeded")
                    elif response.status_code >= 400:
                        error_text = await response.aread()
                        raise DifyClientError(
                            f"Dify API error {response.status_code}: {error_text.decode()}"
                        )

                    # Parse SSE stream
                    buffer = ""
                    async for chunk in response.aiter_text():
                        buffer += chunk
                        while "\n\n" in buffer:
                            event_str, buffer = buffer.split("\n\n", 1)
                            event = self._parse_sse_event(event_str)
                            if event:
                                yield event

            except httpx.TimeoutException as e:
                raise DifyTimeoutError(f"Request timed out: {e}")
            except httpx.RequestError as e:
                raise DifyClientError(f"Request failed: {e}")

    def _parse_sse_event(self, event_str: str) -> Optional[DifyStreamEvent]:
        """Parse a single SSE event string into DifyStreamEvent."""
        lines = event_str.strip().split("\n")
        event_type = ""
        data_str = ""

        for line in lines:
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_str = line[5:].strip()

        if not data_str:
            return None

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return None

        event = DifyStreamEvent(
            event=event_type or data.get("event", ""),
            data=data,
        )

        # Extract common fields
        if "thought" in data:
            event.thought = data["thought"]
        if "answer" in data:
            event.answer = data["answer"]
        # outputs may be at top level or nested under data.data
        if "outputs" in data:
            event.outputs = data["outputs"]
        elif isinstance(data.get("data"), dict) and "outputs" in data["data"]:
            event.outputs = data["data"]["outputs"]

        return event

    async def analyze_paper(
        self,
        pdf_url: str,
        title: str,
        user_id: str = "paper-insight-user",
        idea_input: Optional[str] = None,
        query: Optional[str] = None,
    ) -> Optional[DifyAnalysisResult]:
        """
        Analyze a paper and return the complete result.

        This method consumes the entire stream and returns the final result.
        """
        thought_parts = []
        answer_parts = []
        final_outputs = None

        try:
            async for event in self.analyze_paper_stream(
                pdf_url, title, user_id, idea_input, query
            ):
                if event.thought:
                    thought_parts.append(event.thought)
                if event.answer:
                    answer_parts.append(event.answer)
                if event.outputs:
                    final_outputs = event.outputs

                if event.event == "workflow_finished" and event.outputs:
                    final_outputs = event.outputs

            # Parse the final outputs
            if final_outputs:
                return self._parse_outputs(final_outputs, "".join(thought_parts))

            # Try to parse from answer if outputs not available
            full_answer = "".join(answer_parts)
            if full_answer:
                return self._parse_answer(full_answer, "".join(thought_parts))

            return None

        except DifyClientError as e:
            print(f"Dify analysis error: {e}")
            return None

    def _parse_outputs(
        self,
        outputs: Dict[str, Any],
        thought_process: str = "",
    ) -> DifyAnalysisResult:
        """Parse Dify workflow outputs into DifyAnalysisResult."""
        # If outputs only contains 'answer' (text with embedded JSON), extract from it
        if "answer" in outputs and "summary_zh" not in outputs:
            answer_text = outputs["answer"]
            # Extract thought from <think> tags
            if "<think>" in answer_text and "</think>" in answer_text:
                think_start = answer_text.find("<think>") + 7
                think_end = answer_text.find("</think>")
                extracted_thought = answer_text[think_start:think_end].strip()
                if not thought_process:
                    thought_process = extracted_thought
                # Get the part after </think>
                answer_text = answer_text[think_end + 8:].strip()

            result = self._parse_answer(answer_text, thought_process)
            if result:
                return result

        technical_mapping = TechnicalMapping()
        if "technical_mapping" in outputs:
            tm = outputs["technical_mapping"]
            if isinstance(tm, dict):
                technical_mapping = TechnicalMapping(
                    token_vs_patch=tm.get("token_vs_patch", ""),
                    temporal_logic=tm.get("temporal_logic", ""),
                    frequency_domain=tm.get("frequency_domain", ""),
                )

        # Handle relevance_score that might be string or number
        score = outputs.get("relevance_score", 0)
        try:
            score = float(score)
        except (ValueError, TypeError):
            score = 0.0

        return DifyAnalysisResult(
            summary_zh=outputs.get("summary_zh", ""),
            relevance_score=score,
            relevance_reason=outputs.get("relevance_reason", ""),
            technical_mapping=technical_mapping,
            heuristic_idea=outputs.get("heuristic_idea", ""),
            thought_process=thought_process if thought_process else None,
        )

    def _parse_answer(
        self,
        answer: str,
        thought_process: str = "",
    ) -> Optional[DifyAnalysisResult]:
        """Parse answer string (JSON) into DifyAnalysisResult."""
        try:
            # Try to extract JSON from the answer
            # Sometimes the answer contains markdown code blocks
            if "```json" in answer:
                start = answer.find("```json") + 7
                end = answer.find("```", start)
                answer = answer[start:end].strip()
            elif "```" in answer:
                start = answer.find("```") + 3
                end = answer.find("```", start)
                answer = answer[start:end].strip()

            data = json.loads(answer)
            return self._parse_outputs(data, thought_process)
        except json.JSONDecodeError:
            # If not JSON, create a minimal result
            return DifyAnalysisResult(
                summary_zh=answer[:200] if answer else "",
                relevance_score=0,
                relevance_reason="无法解析结构化输出",
                technical_mapping=TechnicalMapping(),
                heuristic_idea="",
                thought_process=thought_process if thought_process else None,
            )

    def to_llm_analysis(self, result: DifyAnalysisResult) -> LLMAnalysis:
        """Convert DifyAnalysisResult to legacy LLMAnalysis model."""
        tech_mapping_str = ""
        if result.technical_mapping:
            parts = []
            if result.technical_mapping.token_vs_patch:
                parts.append(f"Token/Patch映射: {result.technical_mapping.token_vs_patch}")
            if result.technical_mapping.temporal_logic:
                parts.append(f"时序逻辑: {result.technical_mapping.temporal_logic}")
            if result.technical_mapping.frequency_domain:
                parts.append(f"频域分析: {result.technical_mapping.frequency_domain}")
            if parts:
                tech_mapping_str = "\n\n【技术映射】\n" + "\n".join(parts)

        heuristic_with_mapping = result.heuristic_idea + tech_mapping_str

        return LLMAnalysis(
            summary_zh=result.summary_zh,
            relevance_score=result.relevance_score,
            relevance_reason=result.relevance_reason,
            heuristic_idea=heuristic_with_mapping,
        )


# Singleton instance
_dify_client: Optional[DifyClient] = None


def get_dify_client() -> DifyClient:
    """Get or create DifyClient singleton."""
    global _dify_client
    if _dify_client is None:
        _dify_client = DifyClient()
    return _dify_client
