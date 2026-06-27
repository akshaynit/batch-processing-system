"""Port: result storage contract (local filesystem now, S3/DO Spaces later)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.domain.results import ResultRecord


class StorageBackend(ABC):
    """Abstraction over progressive, chunk-wise result persistence."""

    @abstractmethod
    async def write_chunk(
        self, job_id: str, chunk_id: str, records: list[ResultRecord]
    ) -> str:
        """Persist one chunk's results; return an opaque reference/key."""

    @abstractmethod
    def iter_results(self, job_id: str) -> AsyncIterator[ResultRecord]:
        """Stream back all persisted results for a job (for /download)."""
