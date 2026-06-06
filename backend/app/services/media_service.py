"""Per-event media artifacts: thumbnails and highlight clips. (Filled in Task 4.)"""

from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.models import Event


def thumb_path(event_id: str) -> Path:
    return settings.thumbnails_dir / f"{event_id}.jpg"


def cached_clip_path(event_id: str) -> Path:
    return settings.clips_dir / f"{event_id}.mp4"


def drop_event_media(event: Event) -> None:
    """Delete cached artifacts for an event (thumb + clip file + clip record)."""
    from app.services.store import store

    thumb_path(event.id).unlink(missing_ok=True)
    cached_clip_path(event.id).unlink(missing_ok=True)
    if event.clip_id:
        clip = store.clips.get(event.clip_id)
        if clip:
            if clip.stored_path:
                Path(clip.stored_path).unlink(missing_ok=True)
            store.delete_clip(event.clip_id)
