"""Local MinerU runtime management (install / pull models / server)."""

from typing import Literal

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.processing import SSE_HEADERS, sse
from app.services.mineru_runtime import get_mineru_runtime

router = APIRouter(prefix="/mineru")


class InstallRequest(BaseModel):
    tier: Literal["basic", "standard"] = "standard"
    source: Literal["huggingface", "modelscope"] = "huggingface"


# Endpoints are async: the runtime schedules tasks on the server's event loop


@router.get("/status")
async def mineru_status():
    return get_mineru_runtime().status()


@router.post("/install")
async def start_install(body: InstallRequest):
    runtime = get_mineru_runtime()
    runtime.start_install(body.tier, body.source)
    return runtime.status()


@router.get("/install/stream")
async def follow_install():
    """Stream install log lines; can be (re)attached at any time."""
    runtime = get_mineru_runtime()

    async def generate_events():
        async for kind, payload in runtime.follow_install():
            if kind == "log":
                yield sse("log", {"line": payload})
            elif kind == "ping":
                yield sse("ping", {})
            else:
                yield sse("done", {**payload, "status": runtime.status()})

    return StreamingResponse(generate_events(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/install/cancel")
async def cancel_install():
    runtime = get_mineru_runtime()
    await runtime.cancel_install()
    return runtime.status()


@router.post("/uninstall")
async def uninstall():
    runtime = get_mineru_runtime()
    await runtime.uninstall()
    return runtime.status()


@router.post("/server/stop")
async def stop_server():
    runtime = get_mineru_runtime()
    await runtime.stop_server()
    return runtime.status()
