import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import importer
import store

app = FastAPI(title="TeloraFooty")


class DriveRequest(BaseModel):
    url: str
    fileIds: list[str] | None = None


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
