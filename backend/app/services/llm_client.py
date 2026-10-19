"""OpenAI-compatible chat client used by every model-backed pipeline step.

Works with any endpoint speaking the Chat Completions API (DeepSeek, OpenAI, DashScope,
SiliconFlow, OpenRouter, Zhipu, Ollama, LM Studio, vLLM...). Reasoning tokens are
surfaced from `reasoning_content` / `reasoning` delta fields or inline <think> tags.
"""

from typing import Any, AsyncIterator, Dict, List, Literal, Optional, Tuple

import httpx
import openai
from openai import AsyncOpenAI

from app.logging_config import get_logger
from app.schemas import Provider
from app.services.errors import PipelineError

logger = get_logger("services.llm_client")

StreamKind = Literal["thinking", "answer"]

_clients: Dict[Tuple[str, str], AsyncOpenAI] = {}


def get_client(provider: Provider) -> AsyncOpenAI:
    if not provider.base_url:
        raise PipelineError("config_error", f"模型服务 “{provider.name or provider.id}” 未配置 Base URL")
    key = (provider.base_url.rstrip("/"), provider.api_key)
    client = _clients.get(key)
    if client is None:
        client = AsyncOpenAI(
            base_url=key[0],
            # Local servers (Ollama, LM Studio) accept any key, but the SDK requires one
            api_key=provider.api_key or "not-needed",
            timeout=httpx.Timeout(600.0, connect=20.0, read=300.0),
            max_retries=2,
        )
        _clients[key] = client
    return client


def clear_client_cache() -> None:
    """Drop cached clients (keys/proxy changed). Old clients are garbage collected."""
    _clients.clear()


class ThinkTagSplitter:
    """Split inline <think>...</think> reasoning out of streamed content.

    Tags may be cut across chunk boundaries, so a possible partial tag at the end of
    the buffer is held back until the next chunk arrives.
    """

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self.in_think = False
        self.buffer = ""

    def feed(self, text: str) -> List[Tuple[StreamKind, str]]:
        self.buffer += text
        out: List[Tuple[StreamKind, str]] = []
        while self.buffer:
            tag = self.CLOSE if self.in_think else self.OPEN
            kind: StreamKind = "thinking" if self.in_think else "answer"
            idx = self.buffer.find(tag)
            if idx >= 0:
                if idx:
                    out.append((kind, self.buffer[:idx]))
                self.buffer = self.buffer[idx + len(tag):]
                self.in_think = not self.in_think
                continue
            # Hold back a suffix that could be the start of the tag
            hold = 0
            for size in range(min(len(tag) - 1, len(self.buffer)), 0, -1):
                if tag.startswith(self.buffer[-size:]):
                    hold = size
                    break
            emit = self.buffer[: len(self.buffer) - hold]
            if emit:
                out.append((kind, emit))
            self.buffer = self.buffer[len(self.buffer) - hold:]
            break
        return out

    def flush(self) -> List[Tuple[StreamKind, str]]:
        if not self.buffer:
            return []
        kind: StreamKind = "thinking" if self.in_think else "answer"
        out = [(kind, self.buffer)]
        self.buffer = ""
        return out


def _delta_reasoning(delta: Any) -> Optional[str]:
    for field in ("reasoning_content", "reasoning"):
        value = getattr(delta, field, None)
        if value is None and getattr(delta, "model_extra", None):
            value = delta.model_extra.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def map_openai_error(exc: Exception, provider: Provider, model: str) -> PipelineError:
    where = f"{provider.name or provider.base_url} / {model}"
    if isinstance(exc, PipelineError):
        return exc
    if isinstance(exc, openai.RateLimitError):
        return PipelineError("rate_limit", f"{where}: 请求过于频繁或额度不足 ({exc.message})")
    if isinstance(exc, openai.APITimeoutError):
        return PipelineError("timeout", f"{where}: 请求超时")
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return PipelineError("config_error", f"{where}: API Key 无效或无权限 ({exc.message})")
    if isinstance(exc, openai.NotFoundError):
        return PipelineError("config_error", f"{where}: 模型或接口不存在 ({exc.message})")
    if isinstance(exc, openai.APIStatusError):
        message = str(exc.message)
        lowered = message.lower()
        if exc.status_code == 413 or any(
            hint in lowered for hint in ("context length", "context_length", "too long", "maximum context", "too large")
        ):
            return PipelineError("entity_too_large", f"{where}: 输入超出模型上下文 ({message})")
        return PipelineError("llm_error", f"{where}: HTTP {exc.status_code} {message}")
    if isinstance(exc, openai.APIConnectionError):
        return PipelineError("llm_error", f"{where}: 无法连接 {provider.base_url} ({exc})")
    return PipelineError("llm_error", f"{where}: {exc}")


def _unsupported_param(exc: openai.BadRequestError, param: str) -> bool:
    message = str(exc.message).lower()
    return param in message and any(
        hint in message for hint in ("unsupported", "not support", "invalid", "unrecognized", "not allowed")
    )


async def stream_chat(
    provider: Provider,
    model: str,
    messages: List[Dict[str, Any]],
    *,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    json_mode: bool = False,
) -> AsyncIterator[Tuple[StreamKind, str]]:
    """Stream a chat completion as ("thinking" | "answer", text) deltas."""
    client = get_client(provider)
    params: Dict[str, Any] = {"model": model, "messages": messages, "stream": True}
    if temperature is not None:
        params["temperature"] = temperature
    if max_tokens is not None:
        params["max_tokens"] = max_tokens
    if json_mode:
        params["response_format"] = {"type": "json_object"}

    stream = None
    # Some endpoints (e.g. OpenAI reasoning models) reject temperature / max_tokens:
    # retry with the offending parameter dropped or renamed.
    for _ in range(3):
        try:
            stream = await client.chat.completions.create(**params)
            break
        except openai.BadRequestError as exc:
            if "max_tokens" in params and _unsupported_param(exc, "max_tokens"):
                params["max_completion_tokens"] = params.pop("max_tokens")
            elif "temperature" in params and _unsupported_param(exc, "temperature"):
                params.pop("temperature")
            elif "response_format" in params and _unsupported_param(exc, "response_format"):
                params.pop("response_format")
            else:
                raise map_openai_error(exc, provider, model) from exc
            logger.info("Retrying %s without unsupported parameter: %s", model, exc.message)
        except Exception as exc:
            raise map_openai_error(exc, provider, model) from exc
    if stream is None:
        raise PipelineError("llm_error", f"{provider.name} / {model}: 请求参数不被接受")

    splitter = ThinkTagSplitter()
    finish_reason = None
    try:
        async for chunk in stream:
            if not chunk.choices:
                continue
            finish_reason = chunk.choices[0].finish_reason or finish_reason
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            reasoning = _delta_reasoning(delta)
            if reasoning:
                yield "thinking", reasoning
            if delta.content:
                for item in splitter.feed(delta.content):
                    yield item
        for item in splitter.flush():
            yield item
        if finish_reason == "length":
            raise PipelineError(
                "llm_error",
                f"{provider.name} / {model}: 输出达到最大 tokens 上限被截断，请在 设置 → 解析流程 中调大「最大输出 tokens」",
            )
    except PipelineError:
        raise
    except Exception as exc:
        raise map_openai_error(exc, provider, model) from exc
    finally:
        # Release the HTTP connection when the consumer stops early (client disconnect)
        await stream.close()


async def chat_text(
    provider: Provider,
    model: str,
    messages: List[Dict[str, Any]],
    **kwargs: Any,
) -> str:
    """Run a chat completion and return the final answer text (reasoning dropped)."""
    parts: List[str] = []
    async for kind, text in stream_chat(provider, model, messages, **kwargs):
        if kind == "answer":
            parts.append(text)
    return "".join(parts).strip()
