from __future__ import annotations

from pydantic import BaseModel


class EventOut(BaseModel):
    event_id: str
    type: str
    team: str | None = None
    timestamp_seconds: float
    period: int | None = None
    confidence: float
    source: str
    clip_id: str | None = None


class GameEventsResponse(BaseModel):
    game_id: str
    events: list[EventOut]
