import re
import shutil
import threading
from pathlib import Path

import gdown

import clipper
import store

# Hardcoded sample events seeded into every imported game: (seconds, type).
# Timestamps beyond the video duration are skipped.
SAMPLE_EVENTS = [
    (310.0, "shot"),
    (760.0, "shot"),
    (1180.0, "goal"),
    (2120.0, "shot"),
    (2750.0, "goal"),
]

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
    files = gdown.download_folder(id=drive_id, skip_download=True, quiet=True)
    if files is None:
        raise RuntimeError(NOT_PUBLIC_MSG)
    return [
        {"id": f.id, "name": Path(f.path).name}
        for f in files
        if Path(f.path).suffix.lower() in VIDEO_EXTS
    ]


def finalize_game(game_id: str) -> None:
    """Validate/convert video, set duration, seed sample events, build thumbnails."""
    game = store.load_game(game_id)
    game["status"] = "processing"
    store.save_game(game)
    video = store.game_dir(game_id) / "video.mp4"
    clipper.ensure_h264(video)
    duration = clipper.probe_duration(video)
    game["durationSec"] = duration
    store.save_game(game)
    for ts, etype in SAMPLE_EVENTS:
        if ts < duration:
            store.create_event(game_id, etype, ts, source="sample")
    for event in store.load_events(game_id):
        clipper.extract_thumb(
            video, event["timestamp"],
            store.game_dir(game_id) / "thumbs" / f"{event['id']}.jpg",
        )
    game["status"] = "ready"
    store.save_game(game)


def _fail(game_id: str, message: str) -> None:
    game = store.load_game(game_id)
    game["status"] = "error"
    game["error"] = message
    store.save_game(game)
    (store.game_dir(game_id) / "video.mp4").unlink(missing_ok=True)


def import_local(src: Path, title: str) -> dict:
    """Synchronous local import: move file into library, then finalize."""
    game = store.new_game(title, {"kind": "local", "url": None})
    dest = store.game_dir(game["id"]) / "video.mp4"
    shutil.move(str(src), dest)
    try:
        finalize_game(game["id"])
    except Exception as exc:
        _fail(game["id"], str(exc))
    return store.load_game(game["id"])


def _import_drive_file(url: str, drive_id: str, name: str) -> dict:
    """Create the game, download + finalize in a background thread."""
    game = store.new_game(Path(name).stem, {"kind": "drive", "url": url})

    def work() -> None:
        try:
            dest = store.game_dir(game["id"]) / "video.mp4"
            out = gdown.download(id=drive_id, output=str(dest), quiet=True)
            if out is None:
                raise RuntimeError(NOT_PUBLIC_MSG)
            finalize_game(game["id"])
        except Exception as exc:
            _fail(game["id"], str(exc))

    threading.Thread(target=work, daemon=True).start()
    return game


def import_drive(url: str, file_ids: list[str] | None = None) -> list[dict]:
    """Import a Drive file link, or chosen videos from a folder link."""
    kind, drive_id = parse_drive_url(url)
    if kind == "file":
        return [_import_drive_file(url, drive_id, "Drive video")]
    files = list_drive_folder(url)
    if file_ids:
        files = [f for f in files if f["id"] in file_ids]
    return [_import_drive_file(url, f["id"], f["name"]) for f in files]
