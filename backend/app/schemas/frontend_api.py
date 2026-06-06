"""Schemas matching the frontend's API contract (frontend/src/types.ts).

The frontend's vocabulary wins at the API boundary; internal models keep
their own field names. These helpers translate between the two.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.models import Event, Game
from app.services.clip_service import clip_window_for_event

_STATUS_TO_FRONTEND = {
    "uploaded": "processing",
    "downloading": "downloading",
    "processing": "processing",
    "completed": "ready",
    "failed": "error",
    "interrupted": "interrupted",
}

_SOURCE_TO_FRONTEND = {"model": "ai", "hybrid": "ai"}  # manual/sample pass through


class GameOut(BaseModel):
    id: str
    title: str
    date: str
    durationSec: float
    source: dict  # {"kind": "local"|"drive", "url": str|None}
    status: str  # downloading | processing | ready | error | interrupted
    error: str | None = None
    progress: int | None = None
    progressMessage: str | None = None
    goals: int | None = None
    shots: int | None = None


class EventOut(BaseModel):
    id: str
    type: str
    timestamp: float
    source: str  # manual | sample | ai
    verified: bool
    confidence: float
    clipStart: float
    clipEnd: float


def game_out(
    game: Game,
    *,
    goals: int | None = None,
    shots: int | None = None,
    progress: int | None = None,
    progress_message: str | None = None,
) -> GameOut:
    return GameOut(
        id=game.id,
        title=game.title,
        date=game.created_at.date().isoformat(),
        durationSec=game.duration_seconds,
        source={"kind": game.source_kind, "url": game.source_url},
        status=_STATUS_TO_FRONTEND.get(game.status, "processing"),
        error=game.error,
        progress=progress,
        progressMessage=progress_message,
        goals=goals,
        shots=shots,
    )


def event_out(event: Event, video_duration: float) -> EventOut:
    window = clip_window_for_event(event.event_type, event.timestamp_seconds, video_duration)
    return EventOut(
        id=event.id,
        type=event.event_type,
        timestamp=event.timestamp_seconds,
        source=_SOURCE_TO_FRONTEND.get(event.source, event.source),
        verified=event.verified,
        confidence=event.confidence,
        clipStart=window.start_seconds,
        clipEnd=window.end_seconds,
    )
