"""Research-direction auto-fill (plain-language description -> Research tab settings)."""

import asyncio
import contextlib
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.processing import SSE_HEADERS, sse
from app.database import get_sync_session
from app.logging_config import get_logger
from app.models import AppSettings
from app.schemas import Provider, get_provider, load_settings, unmask_providers
from app.services.errors import PipelineError
from app.services.research_agent import run_research_agent

logger = get_logger("api.research")

router = APIRouter(prefix="/research")

# Each direction can run its own agent; at most this many run at once (arXiv probes are
# additionally serialized in services.arxiv_probe)
MAX_CONCURRENT_AGENTS = 2
_agent_slots = asyncio.Semaphore(MAX_CONCURRENT_AGENTS)


class AutofillRequest(BaseModel):
    description: str
    # The reasoning provider/model shown in the (possibly unsaved) settings form;
    # falls back to the saved reasoning step
    provider: Optional[Provider] = None
    model: str = ""


@router.post("/autofill")
async def autofill(body: AutofillRequest):
    """Stream the agent: status, thinking, draft, round (per arXiv test), result, done/error."""
    with get_sync_session() as session:
        settings = load_settings(session.get(AppSettings, 1))
    if body.provider and body.model:
        provider = unmask_providers([body.provider], settings.providers)[0]
        model = body.model
    else:
        provider = get_provider(settings, settings.pipeline.reasoning.provider_id)
        model = settings.pipeline.reasoning.model

    async def generate_events():
        try:
            if provider is None or not model:
                raise PipelineError("config_error", "请先在「解析流程」中配置推理模型")
            if provider.needs_api_key:
                raise PipelineError("config_error", f"请先在「模型服务」中填写 {provider.name} 的 API Key")
            if _agent_slots.locked():
                yield sse("status", {"message": "排队中：其他研究方向的智能填写正在运行…"})
            async with _agent_slots:
                async with contextlib.aclosing(run_research_agent(body.description, provider, model)) as events:
                    async for event in events:
                        yield sse(event.type, event.data)
            yield sse("done", {"status": "completed"})
        except PipelineError as e:
            yield sse("error", {"error": e.code, "message": e.message})
        except Exception as e:
            logger.exception("Research agent failed")
            yield sse("error", {"error": "unknown", "message": str(e)})

    return StreamingResponse(generate_events(), media_type="text/event-stream", headers=SSE_HEADERS)
