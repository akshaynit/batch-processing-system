"""Concurrency limiter: a semaphore enforcing the in-flight call ceiling."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class ConcurrencyLimiter:
    """Hard cap on the number of simultaneous in-flight operations."""

    def __init__(self, max_concurrency: int) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self._sem = asyncio.Semaphore(max_concurrency)

    async def run(self, coro_factory: Callable[[], Awaitable[T]]) -> T:
        async with self._sem:
            return await coro_factory()
