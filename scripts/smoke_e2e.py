"""End-to-end smoke test using the MockInferenceClient (no live provider calls).

Exercises the full pipeline against the real local Postgres + local storage:
ingest -> scatter/claim -> process (with a transient failure + one permanent
failure injected) -> gather -> status -> download.

Usage:
    python scripts/smoke_e2e.py [input_path]
"""
from __future__ import annotations

import asyncio
import sys

from app.composition import build_services
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.domain.enums import JobState
from app.domain.models import SubmitJobRequest
from app.infrastructure.inference.mock_client import MockInferenceClient


async def main() -> int:
    configure_logging()
    input_path = sys.argv[1] if len(sys.argv) > 1 else "sample_batch.json"
    settings = get_settings()

    # Inject mock: every prompt fails once (tests retry), and any prompt mentioning
    # "DNA" fails permanently (tests isolated failure).
    client = MockInferenceClient(fail_substring="DNA", transient_fail=1)
    services = build_services(settings=settings, client=client)

    job_id = await services.job_service.submit(SubmitJobRequest(input_path=input_path))
    print(f"submitted job: {job_id}")

    for _ in range(120):
        status = await services.job_service.get_status(job_id)
        print(
            f"  state={status.state.value} total={status.total} "
            f"pending={status.pending} in_progress={status.in_progress} "
            f"succeeded={status.succeeded} failed={status.failed}"
        )
        if status.state in (JobState.COMPLETED, JobState.FAILED):
            break
        await asyncio.sleep(0.5)

    results = [r async for r in services.storage.iter_results(str(job_id))]
    print(f"downloaded {len(results)} results")
    for r in results[:3]:
        print("  ", r.model_dump())
    failures = [r for r in results if r.status.value == "FAILED"]
    print(f"isolated failures: {len(failures)}")
    if failures:
        print("  example failure:", failures[0].model_dump())

    await services.client.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
