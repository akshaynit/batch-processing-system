"""FastAPI dependency providers (single composition point for the API layer)."""
from __future__ import annotations

from functools import lru_cache

from app.composition import Services, build_services
from app.services.job_service import JobService


@lru_cache(maxsize=1)
def get_services() -> Services:
    return build_services()


def get_job_service() -> JobService:
    return get_services().job_service
