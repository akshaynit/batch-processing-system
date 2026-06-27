"""Durable work-queue behaviour against real Postgres (no inference calls)."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.domain.enums import ItemStatus, JobState
from app.domain.models import JobRecord, PromptItem
from app.infrastructure.db.repositories.job_repository import PgJobRepository
from app.infrastructure.db.repositories.work_queue_repository import (
    PgWorkQueueRepository,
)
from app.infrastructure.db.session import get_sessionmaker

pytestmark = pytest.mark.integration


async def _seed_job(items: int) -> tuple[PgWorkQueueRepository, object]:
    sm = get_sessionmaker()
    jobs = PgJobRepository(sm)
    queue = PgWorkQueueRepository(sm)
    job_id = uuid4()
    await jobs.create(
        JobRecord(id=job_id, state=JobState.PENDING, input_path="x", model="m")
    )
    payload = [PromptItem(external_id=f"e{i}", prompt="p") for i in range(items)]
    inserted = await queue.bulk_insert(job_id, payload, [])
    assert inserted == items
    return queue, job_id


async def test_bulk_insert_is_idempotent():
    queue, job_id = await _seed_job(10)
    again = await queue.bulk_insert(
        job_id, [PromptItem(external_id=f"e{i}", prompt="p") for i in range(10)], []
    )
    assert again == 0  # ON CONFLICT DO NOTHING


async def test_concurrent_claims_never_overlap():
    queue, job_id = await _seed_job(20)
    r1, r2 = await asyncio.gather(
        queue.claim_chunk(job_id, "worker-1", 20, 60),
        queue.claim_chunk(job_id, "worker-2", 20, 60),
    )
    ids1 = {c.external_id for c in r1}
    ids2 = {c.external_id for c in r2}
    assert ids1.isdisjoint(ids2)  # SKIP LOCKED: no row claimed twice
    assert len(ids1) + len(ids2) == 20


async def test_complete_items_marks_succeeded():
    from app.domain.results import ResultRecord

    queue, job_id = await _seed_job(3)
    claimed = await queue.claim_chunk(job_id, "worker-1", 3, 60)
    results = [
        ResultRecord(external_id=c.external_id, status=ItemStatus.SUCCEEDED, response="ok")
        for c in claimed
    ]
    committed = await queue.complete_items("worker-1", results, "jobs/x/chunks/c.jsonl")
    assert committed == 3
    counts = await queue.count_by_status(job_id)
    assert counts.get(ItemStatus.SUCCEEDED) == 3
    assert await queue.has_open_work(job_id) is False
