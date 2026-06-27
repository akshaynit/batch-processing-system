"""Factory selecting the configured storage backend."""
from __future__ import annotations

from app.core.config import Settings
from app.interfaces.storage_backend import StorageBackend


def build_storage(settings: Settings) -> StorageBackend:
    backend = settings.storage_backend.lower()
    if backend == "local":
        from app.infrastructure.storage.local_storage import LocalFileStorage

        return LocalFileStorage(settings.storage_local_root)
    if backend == "s3":
        from app.infrastructure.storage.s3_storage import S3SpacesStorage

        return S3SpacesStorage(
            bucket=settings.spaces_bucket,
            endpoint=settings.spaces_endpoint,
            region=settings.spaces_region,
            key=settings.spaces_key,
            secret=settings.spaces_secret,
        )
    raise ValueError(f"unknown storage backend: {settings.storage_backend}")
