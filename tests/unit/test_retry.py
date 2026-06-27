from app.engine.retry import RetryPolicy


def test_delay_within_full_jitter_bounds():
    policy = RetryPolicy(base=1.0, factor=2.0, cap=30.0)
    for attempt in range(6):
        ceiling = min(30.0, 1.0 * (2.0**attempt))
        for _ in range(50):
            delay = policy.delay_for(attempt)
            assert 0.0 <= delay <= ceiling


def test_delay_respects_cap():
    policy = RetryPolicy(base=1.0, factor=2.0, cap=5.0)
    for _ in range(100):
        assert policy.delay_for(attempt=10) <= 5.0


def test_retryable_status_mapping():
    policy = RetryPolicy()
    for code in (429, 500, 502, 503, 504):
        assert policy.is_retryable_status(code)
    for code in (200, 400, 401, 403, 404):
        assert not policy.is_retryable_status(code)
