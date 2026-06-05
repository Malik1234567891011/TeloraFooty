from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class DemoClipResult(BaseModel):
    event_type: str  # shot | goal | none
    timestamp_seconds: float | None = None
    confidence: float
    team: str | None = None
    clip_url: str | None = None
    explanation: str = ""


class DemoClipResponse(BaseModel):
    analysis_id: str
    status: str
    result: DemoClipResult
    debug: dict[str, Any]
