"""Structured logging with correlation context.

Emits machine-parseable JSON in production (one object per line) so logs can be
shipped to Loki / Elasticsearch / Datadog and queried by `request_id`, `job_id`,
or `worker_id`. A human-friendly console formatter is available for local dev.

Correlation IDs are stored in contextvars so every log line emitted while
handling a request (or processing a job/worker) is automatically tagged — you
never have to thread the id through function signatures.
"""
from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
from datetime import UTC, datetime
from pathlib import Path

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
job_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "job_id", default=None
)
worker_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "worker_id", default=None
)

_CONTEXT_VARS = {
    "request_id": request_id_var,
    "job_id": job_id_var,
    "worker_id": worker_id_var,
}

# Standard LogRecord attributes we should not treat as user-supplied extras.
_RESERVED = set(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime", "taskName"}


def set_request_id(value: str | None) -> None:
    request_id_var.set(value)


def set_job_id(value: str | None) -> None:
    job_id_var.set(value)


def set_worker_id(value: str | None) -> None:
    worker_id_var.set(value)


def _context_fields() -> dict[str, str]:
    fields = {}
    for name, var in _CONTEXT_VARS.items():
        value = var.get()
        if value is not None:
            fields[name] = value
    return fields


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(_context_fields())
        # Any structured extras passed via logger.info(..., extra={...}).
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s :: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        ctx = _context_fields()
        if ctx:
            base += " " + " ".join(f"{k}={v}" for k, v in ctx.items())
        return base


def configure_logging(level: str | int | None = None, fmt: str | None = None) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    level = level if level is not None else settings.log_level
    fmt = fmt if fmt is not None else settings.log_format

    def _formatter() -> logging.Formatter:
        return JsonFormatter() if fmt == "json" else ConsoleFormatter()

    handlers: list[logging.Handler] = [logging.StreamHandler()]

    # Optional rotating file handler: write logs to disk in addition to stdout.
    if settings.log_file:
        log_path = Path(settings.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_path,
                maxBytes=settings.log_file_max_bytes,
                backupCount=settings.log_file_backup_count,
                encoding="utf-8",
            )
        )

    for handler in handlers:
        handler.setFormatter(_formatter())

    root = logging.getLogger()
    root.handlers = handlers
    root.setLevel(level)

    # Route uvicorn's own loggers through our handler/formatter for consistency.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.handlers = []
        uv.propagate = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
