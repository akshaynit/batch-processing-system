"""Local filesystem storage backend.

Writes one JSONL object per chunk under:
    {root}/jobs/{job_id}/chunks/{chunk_id}.jsonl
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from app.domain.results import ResultRecord
from app.interfaces.storage_backend import StorageBackend


class LocalFileStorage(StorageBackend):
    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def _chunks_dir(self, job_id: str) -> Path:
        return self.root / "jobs" / job_id / "chunks"

    async def write_chunk(
        self, job_id: str, chunk_id: str, records: list[ResultRecord]
    ) -> str:
        chunks_dir = self._chunks_dir(job_id)
        rel = f"jobs/{job_id}/chunks/{chunk_id}.jsonl"
        payload = "\n".join(r.model_dump_json() for r in records) + "\n"

        def _write() -> None:
            chunks_dir.mkdir(parents=True, exist_ok=True)
            (chunks_dir / f"{chunk_id}.jsonl").write_text(payload, encoding="utf-8")

        await asyncio.to_thread(_write)
        return rel

    async def iter_results(self, job_id: str) -> AsyncIterator[ResultRecord]:
        chunks_dir = self._chunks_dir(job_id)

        def _list() -> list[Path]:
            if not chunks_dir.exists():
                return []
            return sorted(chunks_dir.glob("*.jsonl"))

        files = await asyncio.to_thread(_list)
        for fp in files:
            lines = await asyncio.to_thread(
                lambda p=fp: p.read_text(encoding="utf-8").splitlines()
            )
            for line in lines:
                if line.strip():
                    yield ResultRecord(**json.loads(line))
