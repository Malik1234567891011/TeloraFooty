import re
import shutil
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import clipper
import emailer
import importer
import store

emailer.load_env()

app = FastAPI(title="TeloraFooty")


class DriveRequest(BaseModel):
    url: str
    fileIds: list[str] | None = None


class EventCreate(BaseModel):
    type: Literal["shot", "goal"]
    timestamp: float


class EventPatch(BaseModel):
    type: Literal["shot", "goal"] | None = None
    timestamp: float | None = None
    verified: bool | None = None


class EmailRequest(BaseModel):
    to: str


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/games")
def list_games():
    games = store.list_games()
    for g in games:  # counts shown on library cards
        events = store.load_events(g["id"])
        g["goals"] = sum(1 for e in events if e["type"] == "goal")
        g["shots"] = sum(1 for e in events if e["type"] == "shot")
    return games


@app.get("/api/games/{game_id}")
def get_game(game_id: str):
    game = store.load_game(game_id)
    if game is None:
        raise HTTPException(404, "Game not found")
    return game


@app.delete("/api/games/{game_id}")
def delete_game(game_id: str):
    d = store.game_dir(game_id)
    if not d.exists():
        raise HTTPException(404, "Game not found")
    shutil.rmtree(d)
    return {"ok": True}


@app.post("/api/games/import")
async def import_file(file: UploadFile):
    name = Path(file.filename or "video.mp4")
    if name.suffix.lower() not in importer.VIDEO_EXTS:
        raise HTTPException(400, f"Unsupported file type: {name.suffix}")
    tmp = store.games_root() / f"upload_{uuid.uuid4().hex[:8]}_{name.name}"
    try:
        with tmp.open("wb") as out:
            while chunk := await file.read(1 << 20):
                out.write(chunk)
        return importer.import_local(tmp, name.stem)
    finally:
        tmp.unlink(missing_ok=True)  # no-op when import_local's move consumed it


@app.post("/api/drive/list")
def drive_list(body: DriveRequest):
    try:
        return importer.list_drive_folder(body.url)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/games/import-drive")
def import_drive(body: DriveRequest):
    try:
        return importer.import_drive(body.url, body.fileIds)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/games/{game_id}/video")
def stream_video(game_id: str):
    video = store.game_dir(game_id) / "video.mp4"
    if not video.exists():
        raise HTTPException(404, "Video not found")
    # Starlette FileResponse handles HTTP Range requests (seeking).
    return FileResponse(video, media_type="video/mp4")


def _require_game(game_id: str) -> dict:
    game = store.load_game(game_id)
    if game is None:
        raise HTTPException(404, "Game not found")
    return game


def _thumb_path(game_id: str, event_id: str) -> Path:
    return store.game_dir(game_id) / "thumbs" / f"{event_id}.jpg"


@app.get("/api/games/{game_id}/events")
def list_events(game_id: str):
    _require_game(game_id)
    return store.load_events(game_id)


@app.post("/api/games/{game_id}/events")
def create_event(game_id: str, body: EventCreate):
    _require_game(game_id)
    event = store.create_event(game_id, body.type, body.timestamp)
    video = store.game_dir(game_id) / "video.mp4"
    try:
        clipper.extract_thumb(video, event["timestamp"], _thumb_path(game_id, event["id"]))
    except RuntimeError:
        pass  # thumb is best-effort; the event itself is already persisted
    return event


@app.patch("/api/games/{game_id}/events/{event_id}")
def patch_event(game_id: str, event_id: str, body: EventPatch):
    _require_game(game_id)
    changes = body.model_dump(exclude_none=True)
    event = store.update_event(game_id, event_id, changes)
    if event is None:
        raise HTTPException(404, "Event not found")
    if "timestamp" in changes:
        video = store.game_dir(game_id) / "video.mp4"
        try:
            clipper.extract_thumb(video, event["timestamp"], _thumb_path(game_id, event_id))
        except RuntimeError:
            pass  # thumb is best-effort; the event itself is already persisted
    return event


@app.delete("/api/games/{game_id}/events/{event_id}")
def delete_event(game_id: str, event_id: str):
    _require_game(game_id)
    if not store.delete_event(game_id, event_id):
        raise HTTPException(404, "Event not found")
    _thumb_path(game_id, event_id).unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/games/{game_id}/events/{event_id}/thumb.jpg")
def event_thumb(game_id: str, event_id: str):
    _require_game(game_id)
    thumb = _thumb_path(game_id, event_id)
    if not thumb.exists():
        raise HTTPException(404, "Thumbnail not found")
    return FileResponse(thumb, media_type="image/jpeg")


def _ensure_clip(game_id: str, event_id: str) -> tuple[dict, dict, Path]:
    """Cut the event's clip if not already cached; return (game, event, path)."""
    game = _require_game(game_id)
    event = next((e for e in store.load_events(game_id) if e["id"] == event_id), None)
    if event is None:
        raise HTTPException(404, "Event not found")
    ts = event["timestamp"]
    stamp = f"{int(ts // 60):02d}{int(ts % 60):02d}"
    safe_title = re.sub(r"[^\w\-]", "_", game["title"])
    out = store.game_dir(game_id) / "exports" / f"{safe_title}_{event['type']}_{stamp}.mp4"
    if not out.exists():
        video = store.game_dir(game_id) / "video.mp4"
        try:
            clipper.export_clip(video, event["clipStart"], event["clipEnd"], out)
        except RuntimeError as exc:
            raise HTTPException(500, f"Export failed: {exc}")
    return game, event, out


@app.post("/api/games/{game_id}/events/{event_id}/export")
def export_event(game_id: str, event_id: str):
    _, _, out = _ensure_clip(game_id, event_id)
    return FileResponse(out, media_type="video/mp4", filename=out.name)


@app.get("/api/games/{game_id}/events/{event_id}/clip.mp4")
def event_clip(game_id: str, event_id: str):
    """Streamable clip for in-app preview (and direct download)."""
    _, _, out = _ensure_clip(game_id, event_id)
    return FileResponse(out, media_type="video/mp4")


@app.post("/api/games/{game_id}/events/{event_id}/email")
def email_clip(game_id: str, event_id: str, body: EmailRequest):
    if not re.fullmatch(r"\S+@\S+\.\S+", body.to.strip()):
        raise HTTPException(422, "Enter a valid email address")
    game, event, out = _ensure_clip(game_id, event_id)
    ts = event["timestamp"]
    when = f"{int(ts // 60)}:{int(ts % 60):02d}"
    subject = f"TeloraFooty clip: {game['title']} — {event['type']} at {when}"
    text = (f"Clip from {game['title']} ({game['date']}): {event['type']} at {when}.\n"
            f"30 seconds before → 10 seconds after the moment. Video attached.")
    try:
        emailer.send_clip_email(body.to.strip(), subject, text, out)
    except emailer.EmailNotConfigured as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Email failed: {exc}")
    return {"ok": True}
