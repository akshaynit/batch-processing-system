"""Standalone worker-process entrypoint.

Runs independently of the API. Multiple instances can run concurrently (same or
different machines); they coordinate through the Postgres durable queue.

Usage:
    python workers/run_worker.py <job_id>
"""
from __future__ import annotations

import asyncio
import sys
from uuid import UUID

from app.composition import build_services
from app.core.logging import configure_logging


async def main(job_id: UUID) -> None:
    configure_logging()
    services = build_services()
    try:
        await services.engine.run(job_id)
    finally:
        await services.client.aclose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python workers/run_worker.py <job_id>")
        raise SystemExit(2)
    asyncio.run(main(UUID(sys.argv[1])))
