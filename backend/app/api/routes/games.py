from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.schemas.clip_schema import ClipOut, GameClipsResponse
from app.schemas.event_schema import EventOut, GameEventsResponse
from app.schemas.frontend_api import game_out
from app.schemas.game_schema import ProcessGameResponse
from app.services import job_service, media_service, processing_service
from app.services.store import store

router = APIRouter()


def _require_game(game_id: str):
    game = store.get_game(game_id)
    if game is None:
        raise HTTPException(404, "Game not found")
    return game


@router.get("")
def list_games() -> list[dict]:
    out = []
    for g in sorted(store.list_games(), key=lambda g: g.created_at, reverse=True):
        events = store.events_for_game(g.id)
        out.append(
            game_out(
                g,
                goals=sum(1 for e in events if e.event_type == "goal"),
                shots=sum(1 for e in events if e.event_type == "shot"),
            ).model_dump()
        )
    return out


@router.get("/{game_id}")
def get_game(game_id: str) -> dict:
    return game_out(_require_game(game_id)).model_dump()


@router.delete("/{game_id}")
def delete_game(game_id: str) -> dict:
    game = _require_game(game_id)
    video = store.get_video(game.video_id) if game.video_id else None
    for event in store.events_for_game(game_id):
        media_service.drop_event_media(event)
    if video and video.stored_path:
        Path(video.stored_path).unlink(missing_ok=True)
    store.delete_game(game_id)
    return {"ok": True}


@router.post("/{game_id}/process", response_model=ProcessGameResponse)
def process_game(game_id: str, background_tasks: BackgroundTasks) -> ProcessGameResponse:
    """Start full-game processing (loads manual annotations, generates clips)."""
    _require_game(game_id)

    job = job_service.create_job("full_game", game_id=game_id, message="Full game processing queued.")
    background_tasks.add_task(processing_service.process_game_from_annotations, game_id, job.id)

    return ProcessGameResponse(
        job_id=job.id,
        game_id=game_id,
        status="processing",
        message="Full game processing started. Results will be available shortly.",
    )


@router.get("/{game_id}/events", response_model=GameEventsResponse)
def get_game_events(game_id: str) -> GameEventsResponse:
    """Temporary internal shape — replaced by the frontend-contract events router in Task 4."""
    _require_game(game_id)
    events = store.events_for_game(game_id)
    return GameEventsResponse(
        game_id=game_id,
        events=[
            EventOut(
                event_id=e.id,
                type=e.event_type,
                team=e.team,
                timestamp_seconds=e.timestamp_seconds,
                period=e.period,
                confidence=e.confidence,
                source=e.source,
                clip_id=e.clip_id,
            )
            for e in events
        ],
    )


@router.get("/{game_id}/clips", response_model=GameClipsResponse)
def get_game_clips(game_id: str) -> GameClipsResponse:
    _require_game(game_id)
    clips = store.clips_for_game(game_id)
    return GameClipsResponse(
        game_id=game_id,
        clips=[
            ClipOut(
                clip_id=c.id,
                event_type=c.event_type,
                timestamp_seconds=c.timestamp_seconds,
                start_seconds=c.start_seconds,
                end_seconds=c.end_seconds,
                clip_url=c.public_url,
            )
            for c in clips
            if c.public_url
        ],
    )
