"""Per-event media artifacts: thumbnails and highlight clips.

Thumbnails and lazily-cut clips are keyed by event id under the standard
storage folders. Detection-time clips recorded in the store are preferred
when present; otherwise clips are cut on demand and cached.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.config import settings
from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.core.logging import get_logger
from app.models import Clip, Event, Game
from app.services.clip_service import clip_window_for_event, generate_clip
from app.services.store import store

logger = get_logger(__name__)


def thumb_path(event_id: str) -> Path:
    return settings.thumbnails_dir / f"{event_id}.jpg"


def cached_clip_path(event_id: str) -> Path:
    return settings.clips_dir / f"{event_id}.mp4"


def extract_event_thumb(game: Game, event: Event) -> Path | None:
    """Best-effort single-frame thumbnail at the event timestamp."""
    video = store.get_video(game.video_id) if game.video_id else None
    if video is None or not Path(video.stored_path).exists() or shutil.which("ffmpeg") is None:
        return None
    out = thumb_path(event.id)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-ss", f"{event.timestamp_seconds:.3f}", "-i", video.stored_path,
        "-frames:v", "1", "-vf", "scale=320:-2", "-y", str(out),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.SubprocessError as exc:
        logger.warning("Thumbnail failed for %s: %s", event.id, exc)
        return None
    if res.returncode != 0 or not out.exists():
        logger.warning("Thumbnail failed for %s: %s", event.id, res.stderr[-200:])
        return None
    return out


def ensure_event_clip(game: Game, event: Event) -> Path:
    """Return a playable clip for the event, cutting and caching it if needed.

    Raises AppError subclasses (from clip_service) when cutting fails.
    """
    if event.clip_id:
        clip = store.clips.get(event.clip_id)
        if clip and clip.stored_path and Path(clip.stored_path).exists():
            return Path(clip.stored_path)
    cached = cached_clip_path(event.id)
    if cached.exists():
        return cached
    video = store.get_video(game.video_id) if game.video_id else None
    if video is None or not Path(video.stored_path).exists():
        raise NotFoundError("Video not found", code="VIDEO_NOT_FOUND")
    duration = game.duration_seconds or video.duration_seconds
    window = clip_window_for_event(event.event_type, event.timestamp_seconds, duration)
    generate_clip(video.stored_path, window.start_seconds, window.end_seconds, cached,
                  video_duration=video.duration_seconds)
    clip = Clip(
        id=new_id("clip"), event_id=event.id, game_id=game.id, video_id=game.video_id,
        event_type=event.event_type, timestamp_seconds=event.timestamp_seconds,
        start_seconds=window.start_seconds, end_seconds=window.end_seconds,
        stored_path=str(cached), public_url=f"/media/clips/{cached.name}",
    )
    event.clip_id = clip.id
    store.save_clip(clip)
    store.save_event(event)
    return cached


def drop_event_media(event: Event) -> None:
    """Delete cached artifacts for an event (thumb + clip file + clip record)."""
    thumb_path(event.id).unlink(missing_ok=True)
    cached_clip_path(event.id).unlink(missing_ok=True)
    if event.clip_id:
        clip = store.clips.get(event.clip_id)
        if clip:
            if clip.stored_path:
                Path(clip.stored_path).unlink(missing_ok=True)
            store.delete_clip(event.clip_id)
