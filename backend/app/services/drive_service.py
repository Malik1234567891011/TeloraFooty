"""Google Drive imports (public links) via gdown.

Ported from the MVP backend's importer.py: parse share links, list folder
videos without downloading, and import files in background threads so the
frontend can poll game status (downloading -> processing -> ready).
"""

from __future__ import annotations

import re
import threading
import uuid
from pathlib import Path

import gdown

from app.config import settings
from app.core.ids import new_id
from app.core.logging import get_logger
from app.models import Game
from app.services import job_service, match_processing_service
from app.services.store import store
from app.services.video_storage_service import register_local_file

logger = get_logger(__name__)

VIDEO_EXTS = {".mp4", ".mov", ".mkv"}

_FOLDER_RE = re.compile(r"drive\.google\.com/drive/(?:u/\d+/)?folders/([\w-]+)")
_FILE_RE = re.compile(r"drive\.google\.com/file/d/([\w-]+)")
_OPEN_RE = re.compile(r"drive\.google\.com/open\?id=([\w-]+)")

NOT_PUBLIC_MSG = ("Download failed — make sure the link is shared as "
                  "'anyone with the link'")


def parse_drive_url(url: str) -> tuple[str, str]:
    """Return ("folder" | "file", drive_id). Raises ValueError if unrecognizable."""
    if m := _FOLDER_RE.search(url):
        return "folder", m.group(1)
    if m := (_FILE_RE.search(url) or _OPEN_RE.search(url)):
        return "file", m.group(1)
    raise ValueError("Not a recognizable Google Drive link")


def list_drive_folder(url: str) -> list[dict]:
    """List video files in a public Drive folder without downloading."""
    kind, drive_id = parse_drive_url(url)
    if kind != "folder":
        raise ValueError("Not a folder link")
    try:
        files = gdown.download_folder(id=drive_id, skip_download=True, quiet=True)
    except gdown.exceptions.DownloadError:
        raise RuntimeError(NOT_PUBLIC_MSG)
    return [
        {"id": f.id, "name": Path(f.path).name}
        for f in files
        if Path(f.path).suffix.lower() in VIDEO_EXTS
    ]


def import_drive(url: str, file_ids: list[str] | None = None) -> list[Game]:
    """Import a Drive file link, or chosen videos from a folder link."""
    kind, drive_id = parse_drive_url(url)
    if kind == "file":
        return [_import_drive_file(url, drive_id, "Drive video")]
    files = list_drive_folder(url)
    if file_ids:
        files = [f for f in files if f["id"] in file_ids]
    return [_import_drive_file(url, f["id"], f["name"]) for f in files]


def _import_drive_file(url: str, drive_id: str, name: str) -> Game:
    """Create the game, then download + analyze in a background thread."""
    game = Game(id=new_id("game"), title=Path(name).stem, status="downloading",
                source_kind="drive", source_url=url)
    store.save_game(game)
    job = job_service.create_job("full_game", game_id=game.id, message="Downloading from Drive.")

    def work() -> None:
        settings.ensure_dirs()
        tmp = settings.uploads_dir / f"drive_tmp_{uuid.uuid4().hex[:8]}.mp4"
        try:
            try:
                gdown.download(id=drive_id, output=str(tmp), quiet=True)
            except gdown.exceptions.DownloadError:
                raise RuntimeError(NOT_PUBLIC_MSG)
            if not tmp.exists() or tmp.stat().st_size == 0:
                raise RuntimeError(NOT_PUBLIC_MSG)
            video = register_local_file(tmp, original_name=name)
            g = store.get_game(game.id)
            g.video_id = video.id
            g.video_filename = video.stored_filename
            g.duration_seconds = video.duration_seconds
            store.save_game(g)
            match_processing_service.process_game(game.id, job.id)
        except Exception as exc:
            logger.exception("Drive import failed for %s", game.id)
            tmp.unlink(missing_ok=True)
            g = store.get_game(game.id)
            if g:
                g.status = "failed"
                g.error = str(exc)
                store.save_game(g)
            job_service.update_job(job.id, status="failed", message=str(exc))

    threading.Thread(target=work, daemon=True).start()
    return game
