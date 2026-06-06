from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Job(BaseModel):
    id: str
    job_type: str  # "full_game" | "demo_clip"
    status: str = "queued"  # queued | processing | completed | failed
    progress: int = 0
    message: str = ""
    game_id: str | None = None
    created_at: datetime = Field(default_factory=_now)
    completed_at: datetime | None = None
