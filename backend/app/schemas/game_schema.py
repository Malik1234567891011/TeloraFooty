from __future__ import annotations

from pydantic import BaseModel


class GameSummary(BaseModel):
    game_id: str
    title: str
    video_url: str | None = None
    status: str
    team_name: str
    opponent_name: str | None = None
    duration_seconds: float
    event_count: int


class ProcessGameResponse(BaseModel):
    job_id: str
    game_id: str
    status: str
    message: str
