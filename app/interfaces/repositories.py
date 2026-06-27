"""Ports: data-access contracts for jobs and the durable work queue."""
from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.enums import ItemStatus, JobState
from app.domain.models import ClaimedItem, JobRecord, JobStatus, PromptItem
from app.domain.results import ResultRecord


class JobRepository(ABC):
    @abstractmethod
    async def create(self, job: JobRecord) -> None: ...

    @abstractmethod
    async def get(self, job_id: UUID) -> JobRecord | None: ...

    @abstractmethod
    async def set_state(
        self, job_id: UUID, state: JobState, error: str | None = None
    ) -> None: ...

    @abstractmethod
    async def set_total(self, job_id: UUID, total: int) -> None: ...

    @abstractmethod
    async def get_status(self, job_id: UUID) -> JobStatus: ...

    @abstractmethod
    async def list_active(self) -> list[tuple[UUID, str]]:
        """Return (job_id, input_path) for jobs still INGESTING/RUNNING (for resume)."""


class WorkQueueRepository(ABC):
    """The durable, multi-worker queue backed by prompt_items."""

    @abstractmethod
    async def bulk_insert(
        self, job_id: UUID, items: list[PromptItem], failed: list[ResultRecord]
    ) -> int:
        """Insert valid items as PENDING and invalid ones as FAILED (idempotent)."""

    @abstractmethod
    async def claim_chunk(
        self, job_id: UUID, worker_id: str, size: int, lease_seconds: int
    ) -> list[ClaimedItem]:
        """Atomically claim up to `size` claimable rows (FOR UPDATE SKIP LOCKED)."""

    @abstractmethod
    async def complete_items(
        self, worker_id: str, results: list[ResultRecord], result_ref: str
    ) -> int:
        """Mark processed rows SUCCEEDED/FAILED (guarded by worker_id)."""

    @abstractmethod
    async def renew_lease(self, worker_id: str, lease_seconds: int) -> None: ...

    @abstractmethod
    async def count_by_status(self, job_id: UUID) -> dict[ItemStatus, int]: ...

    @abstractmethod
    async def has_open_work(self, job_id: UUID) -> bool: ...
