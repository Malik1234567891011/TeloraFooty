from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile

from app.core.logging import get_logger
from app.schemas.analysis_schema import DemoClipResponse, DemoClipResult
from app.services import detection_service, video_storage_service

logger = get_logger(__name__)

router = APIRouter()

_VALID_DIRECTIONS = {"left_to_right", "right_to_left", "unknown"}


@router.post("/demo-clip", response_model=DemoClipResponse)
def analyze_demo_clip(
    file: UploadFile = File(...),
    team_name: str | None = Form(None),
    attacking_direction: str = Form("unknown"),
) -> DemoClipResponse:
    """Process a short demo clip and return whether it contains a shot/goal.

    The route stays thin: it saves the upload and delegates all CV work to the
    detection service (bestpractices.md #2).
    """
    if attacking_direction not in _VALID_DIRECTIONS:
        attacking_direction = "unknown"

    stored = video_storage_service.save_upload(file, video_type="demo_clip", prefix="demo")

    analysis = detection_service.analyze_demo_clip(
        stored.video.stored_path,
        team_name=team_name,
        attacking_direction=attacking_direction,
    )

    return DemoClipResponse(
        analysis_id=analysis.analysis_id,
        status="completed",
        result=DemoClipResult(
            event_type=analysis.event_type,
            timestamp_seconds=analysis.timestamp_seconds,
            confidence=analysis.confidence,
            team=analysis.team,
            clip_url=analysis.clip_url,
            explanation=analysis.explanation,
        ),
        debug=analysis.debug,
    )
