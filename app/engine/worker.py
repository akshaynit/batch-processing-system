"""Worker: claims chunks, processes rows with retry/backpressure, checkpoints results."""
from __future__ import annotations

import asyncio
import contextlib
import time
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.exceptions import PermanentInferenceError, RetryableInferenceError
from app.core.logging import get_logger, set_job_id, set_worker_id
from app.core.metrics import (
    CHUNKS_CLAIMED,
    INFERENCE_LATENCY,
    INFERENCE_REQUESTS,
    INFERENCE_RETRIES,
    INFLIGHT,
    ITEMS_PROCESSED,
)
from app.core.observability import capture_exception
from app.domain.enums import ItemStatus
from app.domain.models import ClaimedItem
from app.domain.results import InferenceRequest, ResultRecord
from app.engine.concurrency import ConcurrencyLimiter
from app.engine.retry import RetryPolicy
from app.interfaces.inference_client import InferenceClient
from app.interfaces.repositories import WorkQueueRepository
from app.interfaces.storage_backend import StorageBackend

logger = get_logger(__name__)


class Worker:
    def __init__(
        self,
        worker_id: str,
        queue: WorkQueueRepository,
        client: InferenceClient,
        storage: StorageBackend,
        retry: RetryPolicy,
        limiter: ConcurrencyLimiter,
        settings: Settings,
    ) -> None:
        self.worker_id = worker_id
        self.queue = queue
        self.client = client
        self.storage = storage
        self.retry = retry
        self.limiter = limiter
        self.settings = settings

    async def run(self, job_id: UUID) -> None:
        set_worker_id(self.worker_id)
        set_job_id(str(job_id))
        while True:
            chunk = await self.queue.claim_chunk(
                job_id,
                self.worker_id,
                self.settings.chunk_size,
                self.settings.lease_ttl_seconds,
            )
            if not chunk:
                break
            CHUNKS_CLAIMED.inc()

            chunk_id = uuid4().hex
            logger.info(
                "chunk claimed chunk=%s size=%d ext_ids=%s",
                chunk_id,
                len(chunk),
                [c.external_id for c in chunk],
            )
            heartbeat = asyncio.create_task(self._heartbeat())
            try:
                results = await self._process_chunk(chunk)
            finally:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat

            ref = await self.storage.write_chunk(str(job_id), chunk_id, results)
            completed = await self.queue.complete_items(self.worker_id, results, ref)
            ok = sum(1 for r in results if r.status == ItemStatus.SUCCEEDED)
            logger.info(
                "chunk done chunk=%s processed=%d ok=%d failed=%d committed=%d ref=%s",
                chunk_id,
                len(results),
                ok,
                len(results) - ok,
                completed,
                ref,
            )

    async def _process_chunk(self, chunk: list[ClaimedItem]) -> list[ResultRecord]:
        async def run_one(item: ClaimedItem) -> ResultRecord:
            return await self.limiter.run(lambda: self._process_row(item))

        return list(await asyncio.gather(*(run_one(i) for i in chunk)))

    async def _process_row(self, item: ClaimedItem) -> ResultRecord:
        start = time.monotonic()
        last_error: str | None = None
        attempt = 0
        model = self.settings.llm_model
        INFLIGHT.inc()
        logger.info(
            "row start ext_id=%s db_id=%d deliveries=%d",
            item.external_id,
            item.id,
            item.attempts,
        )
        try:
            for attempt in range(self.settings.retry_max_attempts):
                try:
                    request = InferenceRequest(
                        model=model,
                        prompt=item.prompt,
                        max_tokens=self.settings.max_output_tokens,
                    )
                    call_start = time.monotonic()
                    response = await self.client.complete(request)
                    INFERENCE_LATENCY.labels(model).observe(time.monotonic() - call_start)
                    INFERENCE_REQUESTS.labels(model, "success").inc()
                    ITEMS_PROCESSED.labels(ItemStatus.SUCCEEDED.value).inc()
                    latency_ms = int((time.monotonic() - start) * 1000)
                    logger.info(
                        "row ok ext_id=%s attempts=%d latency_ms=%d",
                        item.external_id,
                        attempt + 1,
                        latency_ms,
                    )
                    return ResultRecord(
                        external_id=item.external_id,
                        status=ItemStatus.SUCCEEDED,
                        response=response.text,
                        attempts=attempt + 1,
                        latency_ms=latency_ms,
                    )
                except RetryableInferenceError as exc:
                    last_error = str(exc)
                    INFERENCE_REQUESTS.labels(model, "retryable_error").inc()
                    if attempt < self.settings.retry_max_attempts - 1:
                        INFERENCE_RETRIES.labels(model).inc()
                        logger.warning(
                            "retryable failure ext_id=%s attempt=%d err=%s",
                            item.external_id,
                            attempt + 1,
                            last_error,
                        )
                        await asyncio.sleep(self.retry.delay_for(attempt))
                        continue
                except PermanentInferenceError as exc:
                    last_error = str(exc)
                    INFERENCE_REQUESTS.labels(model, "permanent_error").inc()
                    capture_exception(exc, external_id=item.external_id, model=model)
                    break
                except Exception as exc:  # unknown -> treat as permanent, isolated
                    last_error = f"unexpected: {exc}"
                    INFERENCE_REQUESTS.labels(model, "unexpected").inc()
                    capture_exception(exc, external_id=item.external_id, model=model)
                    break
        finally:
            INFLIGHT.dec()

        ITEMS_PROCESSED.labels(ItemStatus.FAILED.value).inc()
        logger.error(
            "row failed ext_id=%s attempts=%d err=%s",
            item.external_id,
            attempt + 1,
            last_error,
        )
        return ResultRecord(
            external_id=item.external_id,
            status=ItemStatus.FAILED,
            error=last_error,
            attempts=attempt + 1,
            latency_ms=int((time.monotonic() - start) * 1000),
        )

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(self.settings.heartbeat_seconds)
            await self.queue.renew_lease(self.worker_id, self.settings.lease_ttl_seconds)
