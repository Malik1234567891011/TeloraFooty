from __future__ import annotations

from pydantic import BaseModel


class ClipOut(BaseModel):
    clip_id: str
    event_type: str | None = None
    timestamp_seconds: float
    start_seconds: float
    end_seconds: float
    clip_url: str


class GameClipsResponse(BaseModel):
    game_id: str
    clips: list[ClipOut]
