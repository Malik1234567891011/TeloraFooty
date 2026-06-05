from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile

from app.core.ids import new_id
from app.models import Game
from app.schemas.video_schema import VideoUploadResponse
from app.services import video_storage_service
from app.services.store import store

router = APIRouter()


@router.post("/upload", response_model=VideoUploadResponse)
def upload_video(
    file: UploadFile = File(...),
    video_type: str = Form("full_game"),
    team_name: str | None = Form(None),
    opponent_name: str | None = Form(None),
) -> VideoUploadResponse:
    """Upload an MP4 video (full game or demo clip).

    Stores the file with a safe generated name, extracts metadata, and (for
    full games) creates a Game record ready for processing.
    """
    stored = video_storage_service.save_upload(file, video_type=video_type, prefix="upload")
    video = stored.video

    game_id = None
    if video_type == "full_game":
        game = Game(
            id=new_id("game"),
            title=team_name or video.original_filename or "Untitled Game",
            video_id=video.id,
            video_filename=video.stored_filename,
            team_name=team_name or "Our Team",
            opponent_name=opponent_name,
            status="uploaded",
            duration_seconds=video.duration_seconds,
        )
        store.save_game(game)
        game_id = game.id

    return VideoUploadResponse(
        video_id=video.id,
        filename=video.original_filename,
        video_type=video.video_type,
        status="uploaded",
        duration_seconds=video.duration_seconds,
        fps=video.fps,
        width=video.width,
        height=video.height,
        video_url=stored.public_url,
        game_id=game_id,
    )
