"""HTTP routes for job submission, status, and download. Skeleton."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_job_service
from app.domain.models import JobStatus, SubmitJobRequest
from app.services.job_service import JobService

router = APIRouter(tags=["jobs"])


@router.post("/jobs", status_code=202)
async def submit_job(
    req: SubmitJobRequest, service: JobService = Depends(get_job_service)
) -> dict:
    job_id = await service.submit(req)
    return {"job_id": str(job_id)}


@router.get("/job/{job_id}/status", response_model=JobStatus)
async def job_status(
    job_id: UUID, service: JobService = Depends(get_job_service)
) -> JobStatus:
    return await service.get_status(job_id)


@router.get("/job/{job_id}/download")
async def job_download(
    job_id: UUID, service: JobService = Depends(get_job_service)
) -> StreamingResponse:
    return StreamingResponse(
        service.stream_results(job_id), media_type="application/json"
    )
