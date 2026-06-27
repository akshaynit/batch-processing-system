"""Postgres implementation of JobRepository."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.domain.enums import ItemStatus, JobState
from app.domain.models import JobRecord, JobStatus
from app.infrastructure.db.models import JobORM, PromptItemORM
from app.interfaces.repositories import JobRepository


class PgJobRepository(JobRepository):
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def create(self, job: JobRecord) -> None:
        async with self._sessionmaker() as session, session.begin():
            session.add(
                JobORM(
                    id=job.id,
                    state=job.state.value,
                    input_path=job.input_path,
                    model=job.model,
                    total_items=job.total_items,
                    config=job.config or {},
                    error=job.error,
                )
            )

    async def get(self, job_id: UUID) -> JobRecord | None:
        async with self._sessionmaker() as session:
            row = await session.get(JobORM, job_id)
            if row is None:
                return None
            return JobRecord(
                id=row.id,
                state=JobState(row.state),
                input_path=row.input_path,
                model=row.model,
                total_items=row.total_items,
                config=row.config or {},
                error=row.error,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    async def set_state(
        self, job_id: UUID, state: JobState, error: str | None = None
    ) -> None:
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                update(JobORM)
                .where(JobORM.id == job_id)
                .values(state=state.value, error=error)
            )

    async def set_total(self, job_id: UUID, total: int) -> None:
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                update(JobORM).where(JobORM.id == job_id).values(total_items=total)
            )

    async def list_active(self) -> list[tuple[UUID, str]]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(JobORM.id, JobORM.input_path).where(
                    JobORM.state.in_(
                        [JobState.INGESTING.value, JobState.RUNNING.value]
                    )
                )
            )
            return [(row.id, row.input_path) for row in result.all()]

    async def get_status(self, job_id: UUID) -> JobStatus:
        async with self._sessionmaker() as session:
            job = await session.get(JobORM, job_id)
            if job is None:
                raise KeyError(job_id)
            result = await session.execute(
                select(PromptItemORM.status, func.count())
                .where(PromptItemORM.job_id == job_id)
                .group_by(PromptItemORM.status)
            )
            counts = {ItemStatus(status): n for status, n in result.all()}
            return JobStatus(
                job_id=job.id,
                state=JobState(job.state),
                total=job.total_items,
                pending=counts.get(ItemStatus.PENDING, 0),
                in_progress=counts.get(ItemStatus.CLAIMED, 0),
                succeeded=counts.get(ItemStatus.SUCCEEDED, 0),
                failed=counts.get(ItemStatus.FAILED, 0),
                created_at=job.created_at,
                updated_at=job.updated_at,
            )
