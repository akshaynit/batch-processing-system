"""Live inference smoke test — ONE real call, minimal prompt/tokens.

Marked `live`: runs only when LLM_API_KEY is set (e.g. via a CI secret), and
self-skips otherwise. Kept to a single prompt with a tiny output budget to keep
token consumption negligible.
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest

from app.composition import build_services
from app.core.config import get_settings
from app.domain.enums import JobState
from app.domain.models import SubmitJobRequest

pytestmark = [pytest.mark.integration, pytest.mark.live]


async def test_single_live_inference_call(tmp_path):
    if not os.getenv("LLM_API_KEY"):
        pytest.skip("LLM_API_KEY not set; skipping live inference test")

    inp = tmp_path / "in.json"
    inp.write_text(json.dumps([{"id": "q1", "prompt": "Reply with one word: ok."}]))

    settings = get_settings().model_copy(
        update={
            "storage_local_root": str(tmp_path / "results"),
            "worker_pool_size": 1,
            "max_concurrency": 1,
            "chunk_size": 1,
            "max_output_tokens": 8,   # keep the response tiny
            "retry_max_attempts": 2,  # at most 2 calls if a transient hiccup occurs
            "retry_base": 0.5,
        }
    )
    services = build_services(settings=settings)  # real inference client

    job_id = await services.job_service.submit(SubmitJobRequest(input_path=str(inp)))
    status = await services.job_service.get_status(job_id)
    for _ in range(60):
        status = await services.job_service.get_status(job_id)
        if status.state in (JobState.COMPLETED, JobState.FAILED):
            break
        await asyncio.sleep(0.5)

    await services.client.aclose()
    assert status.total == 1
    assert status.succeeded == 1, f"live inference did not succeed: state={status.state}"
