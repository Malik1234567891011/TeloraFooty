"""Auto-analyze: run the real shot/goal detector on an imported game.

Dispatch by duration: short clips go through the two-stage whole-clip detector
(detection_service.analyze_demo_clip); long videos through the full-match
funnel (full_match_service.analyze_full_match). Unexpected failures mark the
game `failed`; an unavailable detector (no GEMINI_API_KEY) completes with zero
events so manual tagging still works.

Re-processing preserves curated work: only source='model' events that are not
verified are cleared before a run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.core.ids import new_id
from app.core.logging import get_logger
from app.models import Event, Video
from app.services import job_service, media_service
from app.services.store import store
from app.services.video_storage_service import ensure_h264

logger = get_logger(__name__)


@dataclass
class DetectedEvent:
    event_type: str
    timestamp_seconds: float
    confidence: float
    notes: str = ""


def _detector_available() -> bool:
    try:
        from app.services.vlm_service import get_vlm_judge

        return get_vlm_judge().available
    except Exception:
        return False


def _detect(video: Video) -> list[DetectedEvent]:
    if not _detector_available():
        logger.warning("Detector unavailable (no GEMINI_API_KEY?) — completing with zero events.")
        return []
    if video.duration_seconds <= settings.short_clip_max_seconds:
        from app.services.detection_service import analyze_demo_clip

        res = analyze_demo_clip(video.stored_path)
        if res.event_type in ("shot", "goal") and res.timestamp_seconds is not None:
            return [DetectedEvent(res.event_type, res.timestamp_seconds, res.confidence, res.explanation)]
        return []
    from app.services.full_match_service import analyze_full_match

    result = analyze_full_match(video.stored_path)
    return [
        DetectedEvent(e.event_type, e.timestamp_seconds, e.confidence, e.explanation)
        for e in result.events
    ]


def _clear_unverified_model_events(game_id: str) -> None:
    for event in list(store.events_for_game(game_id)):
        if event.source == "model" and not event.verified:
            media_service.drop_event_media(event)
            store.delete_event(event.id)


def process_game(game_id: str, job_id: str | None = None) -> None:
    """Run detection for a game. Safe as a background task or thread."""
    game = store.get_game(game_id)
    if game is None:
        logger.warning("process_game: unknown game %s", game_id)
        if job_id:
            job_service.update_job(job_id, status="failed", message=f"Unknown game {game_id}.")
        return
    try:
        game.status = "processing"
        game.error = None
        store.save_game(game)
        if job_id:
            job_service.update_job(job_id, status="processing", progress=5, message="Preparing video.")

        video = store.get_video(game.video_id) if game.video_id else None
        if video is None or not Path(video.stored_path).exists():
            raise FileNotFoundError("Source video is missing.")
        video = ensure_h264(video)
        if not game.duration_seconds:
            game.duration_seconds = video.duration_seconds
            store.save_game(game)

        if job_id:
            job_service.update_job(job_id, progress=15, message="Detecting shots and goals.")
        detected = _detect(video)

        _clear_unverified_model_events(game_id)
        for d in detected:
            event = Event(
                id=new_id("evt"), game_id=game_id, video_id=video.id,
                event_type=d.event_type, timestamp_seconds=d.timestamp_seconds,
                confidence=d.confidence, source="model", verified=False,
                notes=d.notes or None,
            )
            store.save_event(event)
            try:
                media_service.ensure_event_clip(game, event)
                media_service.extract_event_thumb(game, event)
            except Exception as exc:  # one bad clip must not abort the game
                logger.warning("Media generation failed for %s: %s", event.id, exc)

        game.event_count = len(store.events_for_game(game_id))
        game.status = "completed"
        store.save_game(game)
        if job_id:
            job_service.update_job(job_id, status="completed", progress=100,
                                   message=f"Found {len(detected)} events.")
        logger.info("Game %s processed: %d events.", game_id, len(detected))
    except Exception as exc:
        logger.exception("Processing failed for game %s", game_id)
        game = store.get_game(game_id)
        if game:
            game.status = "failed"
            game.error = str(exc)
            store.save_game(game)
        if job_id:
            job_service.update_job(job_id, status="failed", message=str(exc))
