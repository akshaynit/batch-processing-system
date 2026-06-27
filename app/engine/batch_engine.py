"""BatchEngine: spawns and supervises the bounded worker pool for a job."""
from __future__ import annotations

import asyncio
import os
import socket
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.logging import get_logger
from app.domain.enums import JobState
from app.engine.concurrency import ConcurrencyLimiter
from app.engine.retry import RetryPolicy
from app.engine.worker import Worker
from app.interfaces.inference_client import InferenceClient
from app.interfaces.repositories import JobRepository, WorkQueueRepository
from app.interfaces.storage_backend import StorageBackend

logger = get_logger(__name__)


class BatchEngine:
    def __init__(
        self,
        queue: WorkQueueRepository,
        job_repo: JobRepository,
        client: InferenceClient,
        storage: StorageBackend,
        retry: RetryPolicy,
        limiter: ConcurrencyLimiter,
        settings: Settings,
    ) -> None:
        self.queue = queue
        self.job_repo = job_repo
        self.client = client
        self.storage = storage
        self.retry = retry
        self.limiter = limiter
        self.settings = settings

    def _worker_id(self, index: int) -> str:
        return f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}-w{index}"

    async def run(self, job_id: UUID) -> None:
        workers = [
            Worker(
                self._worker_id(i),
                self.queue,
                self.client,
                self.storage,
                self.retry,
                self.limiter,
                self.settings,
            )
            for i in range(self.settings.worker_pool_size)
        ]
        logger.info(
            "engine starting job=%s pool=%d max_concurrency=%d chunk=%d",
            job_id,
            self.settings.worker_pool_size,
            self.settings.max_concurrency,
            self.settings.chunk_size,
        )
        await asyncio.gather(*(w.run(job_id) for w in workers))
        await self.job_repo.set_state(job_id, JobState.COMPLETED)
        logger.info("engine finished job=%s", job_id)
