"""S3-compatible storage backend (DigitalOcean Spaces). Skeleton.

Same interface as LocalFileStorage; swapping is config-only (STORAGE_BACKEND=s3).
Requires the optional `s3` extra (boto3).
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from app.domain.results import ResultRecord
from app.interfaces.storage_backend import StorageBackend


class S3SpacesStorage(StorageBackend):
    def __init__(
        self,
        bucket: str,
        endpoint: str,
        region: str,
        key: str,
        secret: str,
    ) -> None:
        self.bucket = bucket
        self.endpoint = endpoint
        self.region = region
        self.key = key
        self.secret = secret
        # TODO: lazy-create a boto3 client (run blocking calls in a thread executor).

    async def write_chunk(
        self, job_id: str, chunk_id: str, records: list[ResultRecord]
    ) -> str:
        raise NotImplementedError

    async def iter_results(self, job_id: str) -> AsyncIterator[ResultRecord]:
        raise NotImplementedError
        yield  # pragma: no cover
