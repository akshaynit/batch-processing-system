"""FastAPI application factory + composition root."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from app.api.dependencies import get_services
from app.api.middleware import ObservabilityMiddleware
from app.api.routers import jobs
from app.core.config import get_settings
from app.core.exceptions import JobNotFoundError, ValidationError
from app.core.logging import configure_logging, get_logger
from app.core.metrics import render as render_metrics
from app.core.observability import init_sentry
from app.infrastructure.db.session import get_engine

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    services = get_services()
    try:
        resumed = await services.job_service.resume_active()
        logger.info("startup complete: resumed %d interrupted job(s)", resumed)
    except Exception:  # noqa: BLE001 - never block startup on resume
        logger.exception("startup resume failed (continuing)")
    yield
    await services.client.aclose()
    await get_engine().dispose()


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    init_sentry(settings)

    app = FastAPI(
        title="Batch Processing System",
        description="Asynchronous batch evaluation engine.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(ObservabilityMiddleware)
    app.include_router(jobs.router)

    if settings.metrics_enabled:

        @app.get("/metrics", include_in_schema=False)
        async def metrics() -> Response:
            payload, content_type = render_metrics()
            return Response(content=payload, media_type=content_type)

    @app.exception_handler(JobNotFoundError)
    async def _job_not_found(_: Request, exc: JobNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": f"job not found: {exc}"})

    @app.exception_handler(ValidationError)
    async def _validation_error(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": exc.errors})

    @app.get("/health", tags=["meta"])
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
