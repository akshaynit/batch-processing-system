import asyncio

from app.engine.concurrency import ConcurrencyLimiter


async def test_limiter_never_exceeds_max():
    max_conc = 5
    limiter = ConcurrencyLimiter(max_conc)
    current = 0
    peak = 0

    async def task():
        nonlocal current, peak
        async def work():
            nonlocal current, peak
            current += 1
            peak = max(peak, current)
            await asyncio.sleep(0.01)
            current -= 1
            return True

        return await limiter.run(work)

    await asyncio.gather(*(task() for _ in range(50)))
    assert peak <= max_conc


def test_invalid_max_concurrency():
    import pytest

    with pytest.raises(ValueError):
        ConcurrencyLimiter(0)
