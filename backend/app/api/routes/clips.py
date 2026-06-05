from __future__ import annotations

from fastapi import APIRouter

from app.core.errors import NotFoundError
from app.schemas.clip_schema import ClipOut
from app.services.store import store

router = APIRouter()


@router.get("/{clip_id}", response_model=ClipOut)
def get_clip(clip_id: str) -> ClipOut:
    clip = store.clips.get(clip_id)
    if clip is None:
        raise NotFoundError(f"Clip '{clip_id}' not found.", code="CLIP_NOT_FOUND")
    return ClipOut(
        clip_id=clip.id,
        event_type=clip.event_type,
        timestamp_seconds=clip.timestamp_seconds,
        start_seconds=clip.start_seconds,
        end_seconds=clip.end_seconds,
        clip_url=clip.public_url,
    )
