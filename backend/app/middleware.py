"""ASGI middleware: request logging + local-only request guard.

Written as plain ASGI (not BaseHTTPMiddleware) so client disconnects reach streaming
(SSE) endpoints and their generators get cancelled.
"""

import time
from typing import Iterable
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.logging_config import get_logger

logger = get_logger("middleware.request")

LOCAL_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}
QUIET_PATHS = {"/api/health", "/openapi.json", "/docs", "/redoc"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return ""


def _hostname(host_header: str) -> str:
    if host_header.startswith("["):  # [::1]:port
        return host_header[1:].split("]", 1)[0]
    return host_header.rsplit(":", 1)[0] if host_header.count(":") == 1 else host_header


class LocalOnlyMiddleware:
    """Reject requests that don't come from the app's own (localhost) origin.

    The API listens on 127.0.0.1 without auth, so guard against DNS rebinding (Host check)
    and cross-site requests from pages open in a browser (Origin / Sec-Fetch-Site).
    """

    def __init__(self, app: ASGIApp, extra_hosts: Iterable[str] = ()) -> None:
        self.app = app
        self.allowed_hosts = LOCAL_HOSTNAMES | set(extra_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        reason = None
        host = _hostname(_header(scope, b"host"))
        if host and host not in self.allowed_hosts:
            reason = f"host {host!r} not allowed"

        fetch_site = _header(scope, b"sec-fetch-site")
        if not reason and fetch_site in ("cross-site", "same-site"):
            reason = f"cross-site request ({fetch_site})"

        origin = _header(scope, b"origin")
        if not reason and origin and scope["method"] not in SAFE_METHODS:
            origin_host = urlsplit(origin).hostname or ""
            if origin_host not in self.allowed_hosts:
                reason = f"origin {origin!r} not allowed"

        if reason:
            logger.warning("Blocked %s %s: %s", scope["method"], scope["path"], reason)
            await send({
                "type": "http.response.start",
                "status": 403,
                "headers": [(b"content-type", b"text/plain; charset=utf-8")],
            })
            await send({"type": "http.response.body", "body": b"Forbidden"})
            return

        await self.app(scope, receive, send)


class RequestLoggingMiddleware:
    """Log every API request with method, path, status, and time to first byte."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or path in QUIET_PATHS or not path.startswith("/api"):
            return await self.app(scope, receive, send)

        start_time = time.perf_counter()
        method = scope["method"]
        query = scope.get("query_string", b"").decode("latin-1")
        label = f"{method} {path}" + (f"?{query}" if query else "")
        status_holder = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status = message["status"]
                status_holder["status"] = status
                duration_ms = (time.perf_counter() - start_time) * 1000
                log_msg = f"{label} -> {status} ({duration_ms:.0f}ms)"
                if status >= 500:
                    logger.error(log_msg)
                elif status >= 400:
                    logger.warning(log_msg)
                else:
                    logger.info(log_msg)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"{label} -> EXCEPTION ({duration_ms:.0f}ms): {exc}")
            raise
