"""Typed domain exceptions."""
from __future__ import annotations


class BatchEngineError(Exception):
    """Base class for all application errors."""


class JobNotFoundError(BatchEngineError):
    """Requested job id does not exist."""


class ValidationError(BatchEngineError):
    """Batch-fatal validation failure (rejected at submit time)."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


class RetryableInferenceError(BatchEngineError):
    """Transient inference failure that should be retried (e.g. 429/5xx/timeout)."""


class PermanentInferenceError(BatchEngineError):
    """Non-retryable inference failure (e.g. 400/401/403)."""
