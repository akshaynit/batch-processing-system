"""Full pipeline against real Postgres using the mock client (no token cost)."""
from __future__ import annotations

import asyncio
import json

import pytest

from app.composition import build_services
from app.core.config import get_settings
from app.domain.enums import JobState
from app.domain.models import SubmitJobRequest
from app.infrastructure.inference.mock_client import MockInferenceClient

pytestmark = pytest.mark.integration


async def _wait_terminal(services, job_id, tries=60):
    status = await services.job_service.get_status(job_id)
    for _ in range(tries):
        status = await services.job_service.get_status(job_id)
        if status.state in (JobState.COMPLETED, JobState.FAILED):
            return status
        await asyncio.sleep(0.2)
    return status


async def test_pipeline_isolated_failure(tmp_path):
    inp = tmp_path / "in.json"
    inp.write_text(
        json.dumps(
            [
                {"id": "ok-1", "prompt": "hello"},
                {"id": "ok-2", "prompt": "world"},
                {"id": "bad-1", "prompt": "trigger DNA failure"},
            ]
        )
    )
    settings = get_settings().model_copy(
        update={
            "storage_local_root": str(tmp_path / "results"),
            "worker_pool_size": 2,
            "max_concurrency": 4,
            "chunk_size": 5,
        }
    )
    # "DNA" prompt fails permanently -> exercises isolated per-row failure.
    client = MockInferenceClient(fail_substring="DNA")
    services = build_services(settings=settings, client=client)

    job_id = await services.job_service.submit(SubmitJobRequest(input_path=str(inp)))
    status = await _wait_terminal(services, job_id)

    assert status.state == JobState.COMPLETED
    assert status.total == 3
    assert status.succeeded == 2
    assert status.failed == 1

    results = [r async for r in services.storage.iter_results(str(job_id))]
    assert len(results) == 3
    await services.client.aclose()
