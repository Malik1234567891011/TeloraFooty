"""Event CRUD in the frontend's API contract (under /api/games/{game_id})."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.ids import new_id
from app.models import Event, Game
from app.schemas.frontend_api import event_out
from app.services import media_service
from app.services.store import store

router = APIRouter()


class EventCreate(BaseModel):
    type: Literal["shot", "goal"]
    timestamp: float


class EventPatch(BaseModel):
    type: Literal["shot", "goal"] | None = None
    timestamp: float | None = None
    verified: bool | None = None


def _require_game(game_id: str) -> Game:
    game = store.get_game(game_id)
    if game is None:
        raise HTTPException(404, "Game not found")
    return game


def _require_event(game_id: str, event_id: str) -> Event:
    event = store.events.get(event_id)
    if event is None or event.game_id != game_id:
        raise HTTPException(404, "Event not found")
    return event


def _sync_event_count(game: Game) -> None:
    game.event_count = len(store.events_for_game(game.id))
    store.save_game(game)


@router.get("/{game_id}/events")
def list_events(game_id: str) -> list[dict]:
    game = _require_game(game_id)
    return [event_out(e, game.duration_seconds).model_dump()
            for e in store.events_for_game(game_id)]


@router.post("/{game_id}/events")
def create_event(game_id: str, body: EventCreate) -> dict:
    game = _require_game(game_id)
    event = Event(
        id=new_id("evt"), game_id=game_id, video_id=game.video_id,
        event_type=body.type, timestamp_seconds=body.timestamp,
        confidence=1.0, source="manual", verified=False,
    )
    store.save_event(event)
    _sync_event_count(game)
    media_service.extract_event_thumb(game, event)  # best-effort
    return event_out(event, game.duration_seconds).model_dump()


@router.patch("/{game_id}/events/{event_id}")
def patch_event(game_id: str, event_id: str, body: EventPatch) -> dict:
    game = _require_game(game_id)
    event = _require_event(game_id, event_id)
    changes = body.model_dump(exclude_none=True)
    if "type" in changes:
        event.event_type = changes["type"]
    if "verified" in changes:
        event.verified = changes["verified"]
    if "timestamp" in changes:
        event.timestamp_seconds = changes["timestamp"]
    if "timestamp" in changes or "type" in changes:
        # The clip window moved: drop stale artifacts, re-cut lazily on demand.
        media_service.drop_event_media(event)
        event.clip_id = None
        media_service.extract_event_thumb(game, event)
    store.save_event(event)
    return event_out(event, game.duration_seconds).model_dump()


@router.delete("/{game_id}/events/{event_id}")
def delete_event(game_id: str, event_id: str) -> dict:
    game = _require_game(game_id)
    event = _require_event(game_id, event_id)
    media_service.drop_event_media(event)
    store.delete_event(event_id)
    _sync_event_count(game)
    return {"ok": True}
