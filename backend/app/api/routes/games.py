from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks

from app.core.errors import NotFoundError
from app.schemas.clip_schema import ClipOut, GameClipsResponse
from app.schemas.event_schema import EventOut, GameEventsResponse
from app.schemas.game_schema import GameSummary, ProcessGameResponse
from app.services import job_service, processing_service
from app.services.store import store
from app.services.video_storage_service import public_url_for_upload

router = APIRouter()


def _video_url_for_game(game) -> str | None:
    if game.video_filename:
        return public_url_for_upload(game.video_filename)
    return None


@router.get("")
def list_games() -> dict:
    games = store.list_games()
    return {
        "games": [
            GameSummary(
                game_id=g.id,
                title=g.title,
                video_url=_video_url_for_game(g),
                status=g.status,
                team_name=g.team_name,
                opponent_name=g.opponent_name,
                duration_seconds=g.duration_seconds,
                event_count=g.event_count,
            ).model_dump()
            for g in games
        ]
    }


@router.get("/{game_id}", response_model=GameSummary)
def get_game(game_id: str) -> GameSummary:
    game = store.get_game(game_id)
    if game is None:
        raise NotFoundError(f"Game '{game_id}' not found.", code="GAME_NOT_FOUND")
    return GameSummary(
        game_id=game.id,
        title=game.title,
        video_url=_video_url_for_game(game),
        status=game.status,
        team_name=game.team_name,
        opponent_name=game.opponent_name,
        duration_seconds=game.duration_seconds,
        event_count=game.event_count,
    )


@router.post("/{game_id}/process", response_model=ProcessGameResponse)
def process_game(game_id: str, background_tasks: BackgroundTasks) -> ProcessGameResponse:
    """Start full-game processing (loads manual annotations, generates clips)."""
    game = store.get_game(game_id)
    if game is None:
        raise NotFoundError(f"Game '{game_id}' not found.", code="GAME_NOT_FOUND")

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
    if store.get_game(game_id) is None:
        raise NotFoundError(f"Game '{game_id}' not found.", code="GAME_NOT_FOUND")
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
    if store.get_game(game_id) is None:
        raise NotFoundError(f"Game '{game_id}' not found.", code="GAME_NOT_FOUND")
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
