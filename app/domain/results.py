"""Inference request/response and per-row result models."""
from __future__ import annotations

from pydantic import BaseModel

from app.domain.enums import ItemStatus


class InferenceRequest(BaseModel):
    model: str
    prompt: str
    max_tokens: int = 2048
    temperature: float = 0.7
    top_p: float = 1.0


class InferenceResponse(BaseModel):
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0


class ResultRecord(BaseModel):
    """One entry in a chunk object and in the final /download array."""

    external_id: str
    status: ItemStatus
    response: str | None = None
    error: str | None = None
    attempts: int = 0
    latency_ms: int | None = None
