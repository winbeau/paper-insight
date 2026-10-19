"""Model provider utilities: connection test and model listing."""

import time
from functools import lru_cache
from typing import Literal

import fitz  # pymupdf
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.dependencies import get_session
from app.models import AppSettings
from app.schemas import Provider, load_settings, unmask_providers
from app.services.errors import PipelineError
from app.services.llm_client import chat_text, get_client, map_openai_error

router = APIRouter()


class ProviderRequest(BaseModel):
    provider: Provider


class ProviderTestRequest(ProviderRequest):
    model: str
    kind: Literal["chat", "vision"] = "chat"


def _resolve(provider: Provider, session: Session) -> Provider:
    """Unsaved edits may carry a masked key: fill it in from the stored provider."""
    stored = load_settings(session.get(AppSettings, 1)).providers
    return unmask_providers([provider], stored)[0]


@lru_cache(maxsize=1)
def _test_image_uri() -> str:
    import base64

    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 64, 64), 0)
    pix.set_rect(pix.irect, (220, 38, 38))
    return "data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode("ascii")


@router.post("/providers/test")
async def test_provider(body: ProviderTestRequest, session: Session = Depends(get_session)):
    provider = _resolve(body.provider, session)
    if body.kind == "vision":
        content = [
            {"type": "text", "text": "What color is this image? Answer with one word."},
            {"type": "image_url", "image_url": {"url": _test_image_uri()}},
        ]
    else:
        content = "Reply with the single word: pong"
    started = time.perf_counter()
    try:
        reply = await chat_text(
            provider, body.model, [{"role": "user", "content": content}], max_tokens=512
        )
    except PipelineError as e:
        return {"ok": False, "error": e.message, "code": e.code}
    return {
        "ok": True,
        "reply": reply[:200],
        "latency_ms": round((time.perf_counter() - started) * 1000),
    }


@router.post("/providers/models")
async def list_models(body: ProviderRequest, session: Session = Depends(get_session)):
    provider = _resolve(body.provider, session)
    try:
        client = get_client(provider)
        page = await client.models.list()
        models = sorted({m.id for m in page.data})
    except PipelineError as e:
        return {"ok": False, "models": [], "error": e.message}
    except Exception as e:
        return {"ok": False, "models": [], "error": map_openai_error(e, provider, "models").message}
    return {"ok": True, "models": models}
