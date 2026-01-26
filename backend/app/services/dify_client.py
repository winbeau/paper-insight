"""
Dify Workflow API Client with Streaming Support.

This module replaces the DeepSeek direct API calls with Dify Chatflow API,
supporting streaming responses for long-running R1 reasoning processes.
"""

import os
import json
import httpx
from typing import Optional, AsyncGenerator, Dict, Any
from dataclasses import dataclass
from dotenv import load_dotenv

from app.models import LLMAnalysis

load_dotenv()


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
    thought_process: Optional[str] = None  # R1 thinking process


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
    """Dify Chatflow API client with streaming support."""

    def __init__(self):
        self.api_key = os.getenv("DIFY_API_KEY")
        if not self.api_key:
            raise ValueError("DIFY_API_KEY environment variable is not set")

        self.base_url = os.getenv("DIFY_API_BASE", "http://82.157.209.193:8080/v1")
        self.endpoint = f"{self.base_url}/chat-messages"
        self.timeout = httpx.Timeout(120.0, connect=10.0)  # 2 min for R1 reasoning

    def _format_query(
        self,
        topic: str,
        background: str,
        method: str,
        contribution: str,
    ) -> str:
        """Format input according to Dify workflow variable specification."""
        return f"""研究主题：{topic}
技术背景：{background}
核心方法：{method}
预期贡献：{contribution}"""

    def _build_request_body(
        self,
        query: str,
        user_id: str = "paper-insight-user",
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build the request body for Dify API."""
        body = {
            "inputs": {
                "query": query,
            },
            "query": query,  # Also send as direct query for compatibility
            "response_mode": "streaming",
            "user": user_id,
        }

        if conversation_id:
            body["conversation_id"] = conversation_id

        return body

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def analyze_paper_stream(
        self,
        title: str,
        abstract: str,
        user_id: str = "paper-insight-user",
    ) -> AsyncGenerator[DifyStreamEvent, None]:
        """
        Analyze a paper using Dify workflow with streaming.

        Yields DifyStreamEvent objects for each SSE event received.
        """
        # Format the query using paper information
        query = self._format_query(
            topic=title,
            background="arXiv论文，需要分析其与DiT/KV Cache研究的相关性",
            method=abstract[:500] if len(abstract) > 500 else abstract,
            contribution="待分析",
        )

        body = self._build_request_body(query, user_id)
        headers = self._get_headers()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                async with client.stream(
                    "POST",
                    self.endpoint,
                    json=body,
                    headers=headers,
                ) as response:
                    # Handle error responses
                    if response.status_code == 413:
                        raise DifyEntityTooLargeError(
                            "Request payload too large. Consider shortening the abstract."
                        )
                    elif response.status_code == 429:
                        raise DifyRateLimitError(
                            "Rate limit exceeded. Please try again later."
                        )
                    elif response.status_code >= 400:
                        error_text = await response.aread()
                        raise DifyClientError(
                            f"Dify API error {response.status_code}: {error_text.decode()}"
                        )

                    # Parse SSE stream
                    buffer = ""
                    async for chunk in response.aiter_text():
                        buffer += chunk
                        # Process complete SSE events
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
        if "outputs" in data:
            event.outputs = data["outputs"]

        return event

    async def analyze_paper(
        self,
        title: str,
        abstract: str,
        user_id: str = "paper-insight-user",
    ) -> Optional[DifyAnalysisResult]:
        """
        Analyze a paper and return the complete result.

        This method consumes the entire stream and returns the final result.
        Use analyze_paper_stream() for real-time streaming updates.
        """
        thought_parts = []
        answer_parts = []
        final_outputs = None

        try:
            async for event in self.analyze_paper_stream(title, abstract, user_id):
                if event.thought:
                    thought_parts.append(event.thought)
                if event.answer:
                    answer_parts.append(event.answer)
                if event.outputs:
                    final_outputs = event.outputs

                # Check for workflow completion
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
        technical_mapping = TechnicalMapping()
        if "technical_mapping" in outputs:
            tm = outputs["technical_mapping"]
            if isinstance(tm, dict):
                technical_mapping = TechnicalMapping(
                    token_vs_patch=tm.get("token_vs_patch", ""),
                    temporal_logic=tm.get("temporal_logic", ""),
                    frequency_domain=tm.get("frequency_domain", ""),
                )

        return DifyAnalysisResult(
            summary_zh=outputs.get("summary_zh", ""),
            relevance_score=float(outputs.get("relevance_score", 0)),
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
            data = json.loads(answer)
            return self._parse_outputs(data, thought_process)
        except json.JSONDecodeError:
            # If not JSON, try to extract fields manually
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
        # Combine technical mapping into heuristic_idea for backward compatibility
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
