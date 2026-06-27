"""Live run against the real inference endpoint (uses LLM_API_KEY from .env).

Runs the full pipeline and prints status + downloaded results.

Usage:
    python scripts/run_live.py [input_path]
"""
from __future__ import annotations

import asyncio
import sys

from app.composition import build_services
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.domain.enums import JobState
from app.domain.models import SubmitJobRequest


async def main() -> int:
    configure_logging()
    input_path = sys.argv[1] if len(sys.argv) > 1 else "sample_batch.json"
    settings = get_settings()
    print(f"model={settings.llm_model} base_url={settings.llm_base_url}")

    services = build_services(settings=settings)  # real DOInferenceClient

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
        await asyncio.sleep(1.0)

    print("\n=== RESULTS ===")
    async for r in services.storage.iter_results(str(job_id)):
        d = r.model_dump()
        if d["status"] == "SUCCEEDED":
            print(f"[{d['external_id']}] OK ({d['latency_ms']}ms): {d['response']!r}")
        else:
            print(f"[{d['external_id']}] FAILED: {d['error']}")

    await services.client.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
