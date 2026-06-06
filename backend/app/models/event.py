from __future__ import annotations

from pydantic import BaseModel


class Event(BaseModel):
    id: str
    game_id: str | None = None
    video_id: str | None = None
    event_type: str  # "shot" | "goal" | "none"
    team: str | None = None  # our_team | opponent | unknown
    timestamp_seconds: float
    period: int | None = None
    confidence: float = 1.0
    source: str = "manual"  # manual | model | hybrid
    verified: bool = False
    notes: str | None = None
    clip_id: str | None = None
