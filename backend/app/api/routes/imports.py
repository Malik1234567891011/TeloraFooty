"""Game imports in the frontend's API contract."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.errors import AppError
from app.core.ids import new_id
from app.models import Game
from app.schemas.frontend_api import game_out
from app.services import drive_service, job_service, match_processing_service, video_storage_service
from app.services.store import store

router = APIRouter()        # mounted at /api/games
drive_router = APIRouter()  # mounted at /api/drive


class DriveRequest(BaseModel):
    url: str
    fileIds: list[str] | None = None


@router.post("/import")
def import_file(file: UploadFile, background_tasks: BackgroundTasks) -> dict:
    try:
        stored = video_storage_service.save_upload(file, video_type="full_game", prefix="upload")
    except AppError as exc:
        raise HTTPException(400, exc.message)
    video = stored.video
    game = Game(
        id=new_id("game"),
        title=Path(file.filename or video.original_filename).stem,
        video_id=video.id,
        video_filename=video.stored_filename,
        status="processing",
        source_kind="local",
        source_url=None,
        duration_seconds=video.duration_seconds,
    )
    store.save_game(game)
    job = job_service.create_job("full_game", game_id=game.id, message="Auto-analysis queued.")
    background_tasks.add_task(match_processing_service.process_game, game.id, job.id)
    return game_out(game).model_dump()


@drive_router.post("/list")
def drive_list(body: DriveRequest) -> list[dict]:
    try:
        return drive_service.list_drive_folder(body.url)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))


@router.post("/import-drive")
def import_drive(body: DriveRequest) -> list[dict]:
    try:
        games = drive_service.import_drive(body.url, body.fileIds)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    return [game_out(g).model_dump() for g in games]
