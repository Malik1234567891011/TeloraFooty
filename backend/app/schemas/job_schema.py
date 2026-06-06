from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class JobOut(BaseModel):
    job_id: str
    status: str
    progress: int
    message: str
    created_at: datetime
    completed_at: datetime | None = None
