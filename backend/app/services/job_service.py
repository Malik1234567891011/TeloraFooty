"""Job lifecycle helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.ids import new_id
from app.models import Job
from app.services.store import store


def create_job(job_type: str, game_id: str | None = None, message: str = "Queued.") -> Job:
    job = Job(id=new_id("job"), job_type=job_type, status="queued", progress=0, message=message, game_id=game_id)
    return store.save_job(job)


def update_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: int | None = None,
    message: str | None = None,
) -> Job | None:
    job = store.get_job(job_id)
    if job is None:
        return None
    if status is not None:
        job.status = status
        if status in {"completed", "failed"}:
            job.completed_at = datetime.now(timezone.utc)
    if progress is not None:
        job.progress = progress
    if message is not None:
        job.message = message
    return store.save_job(job)
