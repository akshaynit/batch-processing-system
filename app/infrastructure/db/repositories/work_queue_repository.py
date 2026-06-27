"""Postgres implementation of WorkQueueRepository (the durable work queue)."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.domain.enums import ItemStatus
from app.domain.models import ClaimedItem, PromptItem
from app.domain.results import ResultRecord
from app.infrastructure.db.models import PromptItemORM
from app.interfaces.repositories import WorkQueueRepository

_CLAIM_SQL = text(
    """
    WITH claimed AS (
        SELECT id
        FROM prompt_items
        WHERE job_id = :job_id
          AND (status = 'PENDING'
               OR (status = 'CLAIMED' AND lease_until < now()))
        ORDER BY id
        FOR UPDATE SKIP LOCKED
        LIMIT :size
    )
    UPDATE prompt_items p
    SET status = 'CLAIMED',
        worker_id = :worker_id,
        lease_until = now() + make_interval(secs => :lease_seconds),
        attempts = p.attempts + 1,
        updated_at = now()
    FROM claimed
    WHERE p.id = claimed.id
    RETURNING p.id, p.external_id, p.prompt, p.attempts;
    """
)

_COMPLETE_SQL = text(
    """
    UPDATE prompt_items
    SET status = :status,
        result_ref = :result_ref,
        error = :error,
        attempts = :attempts,
        chunk_id = :chunk_id,
        updated_at = now()
    WHERE worker_id = :worker_id
      AND external_id = :external_id
      AND status = 'CLAIMED';
    """
)


class PgWorkQueueRepository(WorkQueueRepository):
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def bulk_insert(
        self, job_id: UUID, items: list[PromptItem], failed: list[ResultRecord]
    ) -> int:
        rows: list[dict] = []
        for it in items:
            rows.append(
                {
                    "job_id": job_id,
                    "external_id": it.external_id,
                    "prompt": it.prompt,
                    "status": ItemStatus.PENDING.value,
                }
            )
        for fr in failed:
            rows.append(
                {
                    "job_id": job_id,
                    "external_id": fr.external_id,
                    "prompt": None,
                    "status": ItemStatus.FAILED.value,
                    "error": fr.error,
                }
            )
        if not rows:
            return 0
        stmt = pg_insert(PromptItemORM).values(rows)
        stmt = stmt.on_conflict_do_nothing(
            constraint="uq_prompt_items_job_external"
        )
        async with self._sessionmaker() as session, session.begin():
            result = await session.execute(stmt)
        return result.rowcount or 0

    async def claim_chunk(
        self, job_id: UUID, worker_id: str, size: int, lease_seconds: int
    ) -> list[ClaimedItem]:
        async with self._sessionmaker() as session, session.begin():
            result = await session.execute(
                _CLAIM_SQL,
                {
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "size": size,
                    "lease_seconds": lease_seconds,
                },
            )
            return [
                ClaimedItem(
                    id=row.id,
                    external_id=row.external_id,
                    prompt=row.prompt or "",
                    attempts=row.attempts,
                )
                for row in result.all()
            ]

    async def complete_items(
        self, worker_id: str, results: list[ResultRecord], result_ref: str
    ) -> int:
        if not results:
            return 0
        async with self._sessionmaker() as session, session.begin():
            count = 0
            for r in results:
                res = await session.execute(
                    _COMPLETE_SQL,
                    {
                        "status": r.status.value,
                        "result_ref": result_ref,
                        "error": r.error,
                        "attempts": r.attempts,
                        "chunk_id": result_ref.rsplit("/", 1)[-1],
                        "worker_id": worker_id,
                        "external_id": r.external_id,
                    },
                )
                count += res.rowcount or 0
            return count

    async def renew_lease(self, worker_id: str, lease_seconds: int) -> None:
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                text(
                    """
                    UPDATE prompt_items
                    SET lease_until = now() + make_interval(secs => :lease_seconds)
                    WHERE worker_id = :worker_id AND status = 'CLAIMED';
                    """
                ),
                {"worker_id": worker_id, "lease_seconds": lease_seconds},
            )

    async def count_by_status(self, job_id: UUID) -> dict[ItemStatus, int]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(PromptItemORM.status, func.count())
                .where(PromptItemORM.job_id == job_id)
                .group_by(PromptItemORM.status)
            )
            return {ItemStatus(status): n for status, n in result.all()}

    async def has_open_work(self, job_id: UUID) -> bool:
        async with self._sessionmaker() as session:
            result = await session.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM prompt_items
                        WHERE job_id = :job_id
                          AND (status = 'PENDING'
                               OR (status = 'CLAIMED' AND lease_until < now()))
                    );
                    """
                ),
                {"job_id": job_id},
            )
            return bool(result.scalar())
