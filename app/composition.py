"""Composition root: builds the object graph from configuration.

Used by the API (via dependencies) and by standalone entrypoints (worker, smoke
test). Concrete adapters are chosen here and injected into the core services.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.engine.batch_engine import BatchEngine
from app.engine.concurrency import ConcurrencyLimiter
from app.engine.retry import RetryPolicy
from app.infrastructure.db.repositories.job_repository import PgJobRepository
from app.infrastructure.db.repositories.work_queue_repository import (
    PgWorkQueueRepository,
)
from app.infrastructure.db.session import get_sessionmaker
from app.infrastructure.inference.factory import build_inference_client
from app.infrastructure.storage.factory import build_storage
from app.interfaces.inference_client import InferenceClient
from app.interfaces.repositories import JobRepository, WorkQueueRepository
from app.interfaces.storage_backend import StorageBackend
from app.services.ingestor import BatchIngestor
from app.services.job_service import JobService
from app.services.validation.pipeline import ValidationPipeline
from app.services.validation.rules import (
    MaxPromptTokens,
    NonEmptyExternalId,
    NonEmptyPrompt,
    UniqueExternalId,
)


def build_validation_pipeline(settings: Settings) -> ValidationPipeline:
    rules = [
        NonEmptyExternalId(),
        NonEmptyPrompt(min_chars=settings.min_prompt_chars),
        MaxPromptTokens(max_tokens=settings.max_prompt_tokens),
    ]
    if settings.reject_duplicate_ids:
        rules.append(UniqueExternalId())
    return ValidationPipeline(rules)


@dataclass
class Services:
    settings: Settings
    job_repo: JobRepository
    queue: WorkQueueRepository
    storage: StorageBackend
    client: InferenceClient
    engine: BatchEngine
    ingestor: BatchIngestor
    job_service: JobService


def build_services(
    settings: Settings | None = None,
    client: InferenceClient | None = None,
) -> Services:
    settings = settings or get_settings()
    sessionmaker = get_sessionmaker()

    job_repo = PgJobRepository(sessionmaker)
    queue = PgWorkQueueRepository(sessionmaker)
    storage = build_storage(settings)
    client = client or build_inference_client(settings)

    retry = RetryPolicy(
        base=settings.retry_base,
        factor=settings.retry_factor,
        cap=settings.retry_cap,
        max_attempts=settings.retry_max_attempts,
    )
    limiter = ConcurrencyLimiter(settings.max_concurrency)

    validator = build_validation_pipeline(settings)
    ingestor = BatchIngestor(queue, job_repo, validator, settings)
    engine = BatchEngine(queue, job_repo, client, storage, retry, limiter, settings)
    job_service = JobService(job_repo, queue, ingestor, engine, storage, settings)

    return Services(
        settings=settings,
        job_repo=job_repo,
        queue=queue,
        storage=storage,
        client=client,
        engine=engine,
        ingestor=ingestor,
        job_service=job_service,
    )
