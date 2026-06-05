from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Game(BaseModel):
    id: str
    title: str
    video_id: str | None = None
    video_filename: str | None = None
    team_name: str = "Our Team"
    opponent_name: str | None = None
    status: str = "uploaded"  # uploaded | processing | completed | failed
    duration_seconds: float = 0.0
    event_count: int = 0
    created_at: datetime = Field(default_factory=_now)
