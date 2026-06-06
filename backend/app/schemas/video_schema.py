from __future__ import annotations

from pydantic import BaseModel


class VideoUploadResponse(BaseModel):
    video_id: str
    filename: str
    video_type: str
    status: str = "uploaded"
    duration_seconds: float
    fps: float
    width: int
    height: int
    video_url: str
    game_id: str | None = None
