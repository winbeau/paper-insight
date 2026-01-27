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
# This should be overridden by app settings (research_focus)
DEFAULT_IDEA_INPUT = """请在应用设置中配置你的研究方向 (research_focus)，描述你当前的研究主题、技术背景和核心方法论。

配置示例：
- 研究主题：你正在研究什么？
- 技术背景与动机：为什么要做这个研究？有什么痛点？
- 核心方法论：你打算用什么方法解决？
- 预期科学贡献：希望达成什么效果？
"""

# Simple trigger query - let Dify workflow prompt handle the analysis logic
DEFAULT_QUERY = """请分析上传的论文，结合我的研究 Idea 进行跨领域洞察分析。"""


@dataclass
class DifyStreamEvent:
    """Represents a single event from Dify's streaming response."""
    event: str
    data: Dict[str, Any]
    thought: Optional[str] = None
    answer: Optional[str] = None
    outputs: Optional[Dict[str, Any]] = None


@dataclass
class ConceptBridging:
    """Concept bridging analysis from Dify workflow."""
    source_concept: str = ""  # 目标论文中的关键技术概念
    target_concept: str = ""  # 用户 Idea 中的对应概念
    mechanism_transfer: str = ""  # 迁移机制说明


@dataclass
class DifyAnalysisResult:
    """Complete analysis result from Dify workflow."""
    paper_essence: str = ""  # 一句话概括核心创新点
    concept_bridging: ConceptBridging = None  # 概念桥接分析
    visual_verification: str = ""  # 视觉证据验证
    relevance_score: float = 0
    relevance_reason: str = ""
    heuristic_suggestion: str = ""  # 核心建议
    thought_process: Optional[str] = None

    def __post_init__(self):
        if self.concept_bridging is None:
            self.concept_bridging = ConceptBridging()


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
        # outputs may be at top level or nested under data.data or data.outputs
        if "outputs" in data:
            event.outputs = data["outputs"]
        elif isinstance(data.get("data"), dict):
            nested_data = data["data"]
            if "outputs" in nested_data:
                event.outputs = nested_data["outputs"]
            # Also check for outputs inside workflow_run
            elif isinstance(nested_data.get("outputs"), dict):
                event.outputs = nested_data["outputs"]
        # Some Dify versions put it under data.workflow_run.outputs
        if not event.outputs and isinstance(data.get("workflow_run"), dict):
            if "outputs" in data["workflow_run"]:
                event.outputs = data["workflow_run"]["outputs"]

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
        if "answer" in outputs and "relevance_score" not in outputs:
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

        # Parse concept_bridging
        concept_bridging = ConceptBridging()
        if "concept_bridging" in outputs:
            cb = outputs["concept_bridging"]
            if isinstance(cb, dict):
                concept_bridging = ConceptBridging(
                    source_concept=cb.get("source_concept", ""),
                    target_concept=cb.get("target_concept", ""),
                    mechanism_transfer=cb.get("mechanism_transfer", ""),
                )

        # Handle relevance_score that might be string or number
        score = outputs.get("relevance_score", 0)
        try:
            score = float(score)
        except (ValueError, TypeError):
            score = 0.0

        return DifyAnalysisResult(
            paper_essence=outputs.get("paper_essence", ""),
            concept_bridging=concept_bridging,
            visual_verification=outputs.get("visual_verification", ""),
            relevance_score=score,
            relevance_reason=outputs.get("relevance_reason", ""),
            heuristic_suggestion=outputs.get("heuristic_suggestion", ""),
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
                paper_essence=answer[:200] if answer else "",
                concept_bridging=ConceptBridging(),
                visual_verification="",
                relevance_score=0,
                relevance_reason="无法解析结构化输出",
                heuristic_suggestion="",
                thought_process=thought_process if thought_process else None,
            )

    def to_llm_analysis(self, result: DifyAnalysisResult) -> LLMAnalysis:
        """Convert DifyAnalysisResult to LLMAnalysis model."""
        # Format concept_bridging as a readable string
        concept_bridging_str = ""
        if result.concept_bridging:
            parts = []
            if result.concept_bridging.source_concept:
                parts.append(f"源概念: {result.concept_bridging.source_concept}")
            if result.concept_bridging.target_concept:
                parts.append(f"目标概念: {result.concept_bridging.target_concept}")
            if result.concept_bridging.mechanism_transfer:
                parts.append(f"迁移机制: {result.concept_bridging.mechanism_transfer}")
            if parts:
                concept_bridging_str = "\n".join(parts)

        analysis = LLMAnalysis(
            paper_essence=result.paper_essence,
            concept_bridging_str=concept_bridging_str,
            visual_verification=result.visual_verification,
            relevance_score=result.relevance_score,
            relevance_reason=result.relevance_reason,
            heuristic_suggestion=result.heuristic_suggestion,
        )

        return analysis


# Singleton instance
_dify_client: Optional[DifyClient] = None


def get_dify_client() -> DifyClient:
    """Get or create DifyClient singleton."""
    global _dify_client
    if _dify_client is None:
        _dify_client = DifyClient()
    return _dify_client
