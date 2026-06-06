from __future__ import annotations

from fastapi import APIRouter

from app.core.errors import NotFoundError
from app.schemas.job_schema import JobOut
from app.services.store import store

router = APIRouter()


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str) -> JobOut:
    job = store.get_job(job_id)
    if job is None:
        raise NotFoundError(f"Job '{job_id}' not found.", code="JOB_NOT_FOUND")
    return JobOut(
        job_id=job.id,
        status=job.status,
        progress=job.progress,
        message=job.message,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )
