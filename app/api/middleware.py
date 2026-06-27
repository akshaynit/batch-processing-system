"""HTTP observability middleware: correlation id, access log, request metrics."""
from __future__ import annotations

import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger, set_request_id
from app.core.metrics import HTTP_LATENCY, HTTP_REQUESTS

logger = get_logger("app.api.access")


def _route_template(request: Request) -> str:
    """Low-cardinality path label (e.g. /job/{job_id}/status, not the raw id)."""
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or uuid4().hex
        set_request_id(request_id)
        start = time.perf_counter()
        method = request.method
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            duration = time.perf_counter() - start
            template = _route_template(request)
            HTTP_REQUESTS.labels(method, template, "500").inc()
            HTTP_LATENCY.labels(method, template).observe(duration)
            logger.exception(
                "request failed method=%s path=%s", method, request.url.path
            )
            raise

        duration = time.perf_counter() - start
        template = _route_template(request)
        HTTP_REQUESTS.labels(method, template, str(status)).inc()
        HTTP_LATENCY.labels(method, template).observe(duration)
        response.headers["x-request-id"] = request_id
        logger.info(
            "request method=%s path=%s status=%s duration_ms=%.1f",
            method,
            request.url.path,
            status,
            duration * 1000,
            extra={"http_status": status, "duration_ms": round(duration * 1000, 1)},
        )
        return response
