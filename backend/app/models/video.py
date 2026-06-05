from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Video(BaseModel):
    id: str
    original_filename: str
    stored_filename: str
    stored_path: str
    video_type: str  # "full_game" | "demo_clip"
    duration_seconds: float = 0.0
    fps: float = 0.0
    width: int = 0
    height: int = 0
    uploaded_at: datetime = Field(default_factory=_now)
