"""Optional error tracking (Sentry).

Entirely opt-in: with no SENTRY_DSN configured, every function here is a no-op
and `sentry-sdk` is never imported. When a DSN is set, unhandled API errors are
captured automatically and background (worker) failures can be reported
explicitly via `capture_exception`.
"""
from __future__ import annotations

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_enabled = False


def init_sentry(settings: Settings) -> bool:
    """Initialise Sentry if a DSN is configured. Returns True if active."""
    global _enabled
    if not settings.sentry_dsn:
        return False
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            release=f"{settings.service_name}@0.1.0",
        )
        _enabled = True
        logger.info("sentry error tracking enabled")
    except Exception:  # noqa: BLE001 - never let telemetry break startup
        logger.exception("failed to initialise sentry (continuing without it)")
        _enabled = False
    return _enabled


def capture_exception(exc: BaseException, **context: object) -> None:
    """Report a handled/background exception with optional tags."""
    if not _enabled:
        return
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            for key, value in context.items():
                scope.set_tag(key, str(value))
            sentry_sdk.capture_exception(exc)
    except Exception:  # noqa: BLE001
        logger.debug("sentry capture failed", exc_info=True)
