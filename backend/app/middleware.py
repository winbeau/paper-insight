"""FastAPI middleware for request/response logging."""

import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import get_logger

logger = get_logger("middleware.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with method, path, status, and duration."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.perf_counter()
        method = request.method
        path = request.url.path
        query = str(request.url.query) if request.url.query else ""

        # Skip noisy endpoints
        if path in ("/health", "/openapi.json", "/docs", "/redoc"):
            return await call_next(request)

        try:
            response: Response = await call_next(request)
            duration_ms = (time.perf_counter() - start_time) * 1000
            status = response.status_code

            log_msg = f"{method} {path}"
            if query:
                log_msg += f"?{query}"
            log_msg += f" -> {status} ({duration_ms:.0f}ms)"

            if status >= 500:
                logger.error(log_msg)
            elif status >= 400:
                logger.warning(log_msg)
            else:
                logger.info(log_msg)

            return response

        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"{method} {path} -> EXCEPTION ({duration_ms:.0f}ms): {exc}")
            raise
