"""BatchIngestor: stream-parse the input file, validate rows, bulk-insert.

  - streams items with ijson (no full file load)
  - runs each item through the ValidationPipeline
  - valid -> PENDING rows; invalid -> FAILED rows (isolated, still reported)
  - inserts in batches; records the job total
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

import ijson

from app.core.config import Settings
from app.core.logging import get_logger, set_job_id
from app.core.metrics import INGEST_ITEMS
from app.domain.enums import ItemStatus
from app.domain.models import IngestSummary, PromptItem
from app.domain.results import ResultRecord
from app.interfaces.repositories import JobRepository, WorkQueueRepository
from app.interfaces.validation import ValidationContext
from app.services.validation.pipeline import ValidationPipeline

logger = get_logger(__name__)

_INSERT_BATCH = 500


class BatchIngestor:
    def __init__(
        self,
        queue: WorkQueueRepository,
        job_repo: JobRepository,
        validator: ValidationPipeline,
        settings: Settings,
    ) -> None:
        self.queue = queue
        self.job_repo = job_repo
        self.validator = validator
        self.settings = settings

    @staticmethod
    def _to_item(obj: object, row_number: int) -> tuple[PromptItem | None, str | None]:
        if not isinstance(obj, dict):
            return None, f"row-{row_number}"
        raw_id = obj.get("id")
        external_id = str(raw_id) if raw_id not in (None, "") else f"row-{row_number}"
        prompt = obj.get("prompt")
        if not isinstance(prompt, str):
            return None, external_id
        return PromptItem(external_id=external_id, prompt=prompt), external_id

    async def ingest(self, job_id: UUID, input_path: str) -> IngestSummary:
        set_job_id(str(job_id))
        ctx = ValidationContext()
        total = accepted = rejected = 0
        items: list[PromptItem] = []
        failed: list[ResultRecord] = []

        async def flush() -> None:
            nonlocal items, failed
            if items or failed:
                await self.queue.bulk_insert(job_id, items, failed)
                items, failed = [], []

        path = Path(input_path)
        with path.open("rb") as fh:
            for obj in ijson.items(fh, "item"):
                total += 1
                item, external_id = self._to_item(obj, total)
                if item is None:
                    rejected += 1
                    failed.append(
                        ResultRecord(
                            external_id=external_id or f"row-{total}",
                            status=ItemStatus.FAILED,
                            error="validation: malformed item (missing/invalid prompt)",
                        )
                    )
                else:
                    outcome = self.validator.validate_item(item, ctx)
                    if outcome.ok:
                        accepted += 1
                        items.append(item)
                    else:
                        rejected += 1
                        failed.append(
                            ResultRecord(
                                external_id=item.external_id,
                                status=ItemStatus.FAILED,
                                error="validation: " + "; ".join(outcome.errors),
                            )
                        )
                if len(items) + len(failed) >= _INSERT_BATCH:
                    await flush()
        await flush()

        await self.job_repo.set_total(job_id, total)
        INGEST_ITEMS.labels("accepted").inc(accepted)
        INGEST_ITEMS.labels("rejected").inc(rejected)
        logger.info(
            "ingest job=%s total=%d accepted=%d rejected=%d",
            job_id,
            total,
            accepted,
            rejected,
        )
        return IngestSummary(total=total, accepted=accepted, rejected=rejected)
