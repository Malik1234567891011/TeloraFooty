"""Per-game media serving in the frontend's API contract."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api.routes.events import _require_event, _require_game
from app.core.errors import AppError
from app.services import media_service
from app.services.store import store

router = APIRouter()


@router.get("/{game_id}/video")
def stream_video(game_id: str) -> FileResponse:
    game = _require_game(game_id)
    video = store.get_video(game.video_id) if game.video_id else None
    if video is None or not Path(video.stored_path).exists():
        raise HTTPException(404, "Video not found")
    # Starlette FileResponse handles HTTP Range requests (seeking).
    return FileResponse(video.stored_path, media_type="video/mp4")


@router.get("/{game_id}/events/{event_id}/thumb.jpg")
def event_thumb(game_id: str, event_id: str) -> FileResponse:
    game = _require_game(game_id)
    event = _require_event(game_id, event_id)
    thumb = media_service.thumb_path(event_id)
    if not thumb.exists():
        media_service.extract_event_thumb(game, event)
    if not thumb.exists():
        raise HTTPException(404, "Thumbnail not found")
    return FileResponse(thumb, media_type="image/jpeg")


@router.get("/{game_id}/events/{event_id}/clip.mp4")
def event_clip(game_id: str, event_id: str) -> FileResponse:
    """Streamable clip for in-app preview (and direct download)."""
    game = _require_game(game_id)
    event = _require_event(game_id, event_id)
    try:
        path = media_service.ensure_event_clip(game, event)
    except AppError as exc:
        raise HTTPException(exc.status_code, exc.message)
    return FileResponse(path, media_type="video/mp4")
