from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Clip(BaseModel):
    id: str
    event_id: str | None = None
    game_id: str | None = None
    video_id: str | None = None
    event_type: str | None = None
    timestamp_seconds: float = 0.0
    start_seconds: float = 0.0
    end_seconds: float = 0.0
    stored_path: str = ""
    public_url: str = ""
    created_at: datetime = Field(default_factory=_now)
