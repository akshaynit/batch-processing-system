"""JobService: orchestrates submit / status / download.

Depends only on interfaces (DIP). `submit` performs batch-fatal validation,
creates the job, returns the id immediately, and schedules ingestion + execution
in the background (non-blocking).
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.exceptions import JobNotFoundError, ValidationError
from app.core.logging import get_logger, set_job_id
from app.core.metrics import JOBS_COMPLETED, JOBS_SUBMITTED
from app.core.observability import capture_exception
from app.domain.enums import JobState
from app.domain.models import JobRecord, JobStatus, SubmitJobRequest
from app.engine.batch_engine import BatchEngine
from app.interfaces.repositories import JobRepository, WorkQueueRepository
from app.interfaces.storage_backend import StorageBackend
from app.services.ingestor import BatchIngestor

logger = get_logger(__name__)


class JobService:
    def __init__(
        self,
        job_repo: JobRepository,
        queue: WorkQueueRepository,
        ingestor: BatchIngestor,
        engine: BatchEngine,
        storage: StorageBackend,
        settings: Settings,
    ) -> None:
        self.job_repo = job_repo
        self.queue = queue
        self.ingestor = ingestor
        self.engine = engine
        self.storage = storage
        self.settings = settings
        self._tasks: set[asyncio.Task] = set()

    def _validate_submit(self, req: SubmitJobRequest) -> list[str]:
        errors: list[str] = []
        path = Path(req.input_path)
        if not path.exists() or not path.is_file():
            errors.append(f"input file not found: {req.input_path}")
        else:
            try:
                with path.open("rb") as fh:
                    head = fh.read(64).lstrip()
                if not head.startswith(b"["):
                    errors.append("input file must be a JSON array")
            except OSError as exc:
                errors.append(f"cannot read input file: {exc}")
        model = req.model or self.settings.llm_model
        if not model:
            errors.append("no model configured")
        return errors

    async def submit(self, req: SubmitJobRequest) -> UUID:
        errors = self._validate_submit(req)
        if errors:
            raise ValidationError(errors)

        job_id = uuid4()
        job = JobRecord(
            id=job_id,
            state=JobState.PENDING,
            input_path=str(Path(req.input_path)),
            model=req.model or self.settings.llm_model,
            config=req.config,
        )
        await self.job_repo.create(job)
        JOBS_SUBMITTED.inc()

        task = asyncio.create_task(self._execute(job_id, job.input_path))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        logger.info("submitted job=%s input=%s", job_id, job.input_path)
        return job_id

    async def resume_active(self) -> int:
        """Reschedule jobs left INGESTING/RUNNING by a previous (crashed) process.

        Re-ingestion is idempotent (ON CONFLICT DO NOTHING) and the engine only
        processes still-claimable rows, so resuming is safe and lossless.
        """
        active = await self.job_repo.list_active()
        for job_id, input_path in active:
            task = asyncio.create_task(self._execute(job_id, input_path))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            logger.info("resuming interrupted job=%s", job_id)
        return len(active)

    async def _execute(self, job_id: UUID, input_path: str) -> None:
        set_job_id(str(job_id))
        try:
            await self.job_repo.set_state(job_id, JobState.INGESTING)
            await self.ingestor.ingest(job_id, input_path)
            await self.job_repo.set_state(job_id, JobState.RUNNING)
            await self.engine.run(job_id)
            JOBS_COMPLETED.labels(JobState.COMPLETED.value).inc()
        except Exception as exc:  # noqa: BLE001 - record failure on the job
            logger.exception("job=%s failed", job_id)
            JOBS_COMPLETED.labels(JobState.FAILED.value).inc()
            capture_exception(exc, job_id=str(job_id))
            await self.job_repo.set_state(job_id, JobState.FAILED, str(exc))

    async def get_status(self, job_id: UUID) -> JobStatus:
        try:
            return await self.job_repo.get_status(job_id)
        except KeyError as exc:
            raise JobNotFoundError(str(job_id)) from exc

    async def stream_results(self, job_id: UUID) -> AsyncIterator[bytes]:
        job = await self.job_repo.get(job_id)
        if job is None:
            raise JobNotFoundError(str(job_id))
        yield b"["
        first = True
        async for record in self.storage.iter_results(str(job_id)):
            yield (b"" if first else b",") + record.model_dump_json().encode()
            first = False
        yield b"]"
