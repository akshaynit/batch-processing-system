"""In-memory mock inference client for tests / local smoke runs.

Supports deterministic behaviour plus injectable failures so the worker's retry,
back-off, and isolated-failure paths can be exercised without a live endpoint.
"""
from __future__ import annotations

import asyncio

from app.core.exceptions import PermanentInferenceError, RetryableInferenceError
from app.domain.results import InferenceRequest, InferenceResponse
from app.interfaces.inference_client import InferenceClient


class MockInferenceClient(InferenceClient):
    def __init__(
        self,
        *,
        fail_substring: str | None = None,
        transient_fail: int = 0,
        latency_ms: int = 0,
    ) -> None:
        self.fail_substring = fail_substring
        self.transient_fail = transient_fail
        self.latency_ms = latency_ms
        self._seen: dict[str, int] = {}

    async def complete(self, request: InferenceRequest) -> InferenceResponse:
        prompt = request.prompt
        if self.latency_ms:
            await asyncio.sleep(self.latency_ms / 1000)
        if self.fail_substring and self.fail_substring in prompt:
            raise PermanentInferenceError("mock permanent failure")
        seen = self._seen.get(prompt, 0)
        if seen < self.transient_fail:
            self._seen[prompt] = seen + 1
            raise RetryableInferenceError("mock transient failure")
        return InferenceResponse(
            text=f"[mock] {prompt}",
            prompt_tokens=max(1, len(prompt) // 4),
            completion_tokens=5,
            latency_ms=self.latency_ms,
        )

    async def aclose(self) -> None:
        return None
