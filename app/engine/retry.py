"""Retry policy: exponential back-off with full jitter."""
from __future__ import annotations

import random


class RetryPolicy:
    """Decides whether to retry and how long to wait.

    Delay uses "full jitter": delay = uniform(0, min(cap, base * factor**attempt)).
    `attempt` is 0-based (0 == first retry wait).
    """

    def __init__(
        self,
        base: float = 1.0,
        factor: float = 2.0,
        cap: float = 30.0,
        max_attempts: int = 5,
        retryable_status: set[int] | None = None,
    ) -> None:
        self.base = base
        self.factor = factor
        self.cap = cap
        self.max_attempts = max_attempts
        self.retryable_status = retryable_status or {429, 500, 502, 503, 504}

    def is_retryable_status(self, status_code: int) -> bool:
        return status_code in self.retryable_status

    def delay_for(self, attempt: int) -> float:
        ceiling = min(self.cap, self.base * (self.factor**attempt))
        return random.uniform(0, ceiling)
