"""Core domain models (transport/value objects) shared across layers."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import JobState


class PromptItem(BaseModel):
    """A single prompt row parsed from the input batch file."""

    external_id: str
    prompt: str
    overrides: dict | None = None  # optional per-row model/max_tokens/etc.


class ClaimedItem(BaseModel):
    """A work item a worker has claimed and is now processing."""

    id: int
    external_id: str
    prompt: str
    attempts: int = 0


class SubmitJobRequest(BaseModel):
    """Payload for POST /jobs."""

    input_path: str
    model: str | None = None
    config: dict = Field(default_factory=dict)


class JobRecord(BaseModel):
    """Persisted job summary."""

    id: UUID
    state: JobState
    input_path: str
    model: str
    total_items: int = 0
    config: dict = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class JobStatus(BaseModel):
    """Response for GET /job/{id}/status."""

    job_id: UUID
    state: JobState
    total: int = 0
    pending: int = 0
    in_progress: int = 0
    succeeded: int = 0
    failed: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class IngestSummary(BaseModel):
    """Outcome of ingesting a batch file."""

    total: int
    accepted: int
    rejected: int
