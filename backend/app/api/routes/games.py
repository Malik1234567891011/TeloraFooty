from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.schemas.clip_schema import ClipOut, GameClipsResponse
from app.schemas.frontend_api import game_out
from app.schemas.game_schema import ProcessGameResponse
from app.services import job_service, match_processing_service, media_service
from app.services.store import store

router = APIRouter()


def _require_game(game_id: str):
    game = store.get_game(game_id)
    if game is None:
        raise HTTPException(404, "Game not found")
    return game


def _progress_for(game):
    """Live job progress, only while the game is mid-run."""
    if game.status not in {"downloading", "processing"}:
        return None, None
    job = store.latest_job_for_game(game.id)
    if job is None:
        return None, None
    return job.progress, job.message


@router.get("")
def list_games() -> list[dict]:
    out = []
    for g in sorted(store.list_games(), key=lambda g: g.created_at, reverse=True):
        events = store.events_for_game(g.id)
        progress, message = _progress_for(g)
        out.append(
            game_out(
                g,
                goals=sum(1 for e in events if e.event_type == "goal"),
                shots=sum(1 for e in events if e.event_type == "shot"),
                progress=progress,
                progress_message=message,
            ).model_dump()
        )
    return out


@router.get("/{game_id}")
def get_game(game_id: str) -> dict:
    game = _require_game(game_id)
    progress, message = _progress_for(game)
    return game_out(game, progress=progress, progress_message=message).model_dump()


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
    """Re-run shot/goal detection for a game (manual + verified events survive)."""
    _require_game(game_id)

    job = job_service.create_job("full_game", game_id=game_id, message="Auto-analysis queued.")
    background_tasks.add_task(match_processing_service.process_game, game_id, job.id)

    return ProcessGameResponse(
        job_id=job.id,
        game_id=game_id,
        status="processing",
        message="Detection started. Results will be available shortly.",
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
