"""DigitalOcean serverless inference client (OpenAI-compatible)."""
from __future__ import annotations

import time

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)

from app.core.exceptions import PermanentInferenceError, RetryableInferenceError
from app.domain.results import InferenceRequest, InferenceResponse
from app.interfaces.inference_client import InferenceClient

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class DOInferenceClient(InferenceClient):
    """Wraps AsyncOpenAI pointed at the DigitalOcean serverless endpoint."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 60.0) -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout)

    async def complete(self, request: InferenceRequest) -> InferenceResponse:
        start = time.monotonic()
        try:
            resp = await self._client.chat.completions.create(
                model=request.model,
                messages=[{"role": "user", "content": request.prompt}],
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                top_p=request.top_p,
            )
        except (
            RateLimitError,
            APITimeoutError,
            APIConnectionError,
            InternalServerError,
        ) as exc:
            raise RetryableInferenceError(str(exc)) from exc
        except APIStatusError as exc:
            if exc.status_code in _RETRYABLE_STATUS:
                raise RetryableInferenceError(str(exc)) from exc
            raise PermanentInferenceError(str(exc)) from exc

        latency_ms = int((time.monotonic() - start) * 1000)
        text = (resp.choices[0].message.content or "") if resp.choices else ""
        usage = resp.usage
        return InferenceResponse(
            text=text,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            latency_ms=latency_ms,
        )

    async def aclose(self) -> None:
        await self._client.close()
