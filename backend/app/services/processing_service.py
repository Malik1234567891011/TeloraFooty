"""Full-game processing pipeline (Mode A).

For the MVP this loads manual annotations and generates one clip per event,
mimicking the "overnight processing" story described in docs/Plan.md. The job
status is advanced so the frontend can poll progress.
"""

from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.core.ids import new_id
from app.core.logging import get_logger
from app.models import Clip, Event
from app.services import job_service
from app.services.annotation_service import GameAnnotations, load_annotations
from app.services.clip_service import clip_window_for_event, generate_clip
from app.services.store import store

logger = get_logger(__name__)


def _clip_filename(game_id: str, event_type: str, timestamp_seconds: float) -> str:
    ts = f"{timestamp_seconds:.1f}".replace(".", "_")
    return f"{game_id}_{event_type}_{ts}.mp4"


def process_game_from_annotations(game_id: str, job_id: str | None = None) -> None:
    """Generate clips and events for a game from its annotation file.

    Safe to run as a FastAPI background task. Updates job + game status.
    """
    game = store.get_game(game_id)
    if game is None:
        logger.warning("process_game_from_annotations: unknown game %s", game_id)
        if job_id:
            job_service.update_job(job_id, status="failed", message=f"Unknown game {game_id}.")
        return

    try:
        if job_id:
            job_service.update_job(job_id, status="processing", progress=5, message="Loading annotations.")
        game.status = "processing"
        store.save_game(game)

        annotations: GameAnnotations = load_annotations(game_id)

        video = store.get_video(game.video_id) if game.video_id else None
        video_path = Path(video.stored_path) if video else None
        video_duration = video.duration_seconds if video else game.duration_seconds

        # Reset any prior events/clips for idempotent re-processing.
        store.clear_events_for_game(game_id)

        total = len(annotations.events) or 1
        created = 0
        for idx, ann in enumerate(annotations.events):
            event = Event(
                id=new_id("evt"),
                game_id=game_id,
                video_id=game.video_id,
                event_type=ann.event_type,
                team=ann.team or "our_team",
                timestamp_seconds=ann.timestamp_seconds,
                period=ann.period,
                confidence=1.0,
                source="manual",
                notes=ann.notes,
            )

            window = clip_window_for_event(ann.event_type, ann.timestamp_seconds, video_duration)
            clip_id = new_id("clip")
            clip_filename = _clip_filename(game_id, ann.event_type, ann.timestamp_seconds)
            clip_path = settings.clips_dir / clip_filename

            public_url = ""
            if video_path and video_path.exists():
                try:
                    generate_clip(
                        video_path,
                        window.start_seconds,
                        window.end_seconds,
                        clip_path,
                        video_duration=video_duration,
                    )
                    public_url = f"/media/clips/{clip_filename}"
                except Exception as exc:  # one bad clip should not abort the game
                    logger.warning("Clip generation failed for event %s: %s", event.id, exc)
            else:
                logger.info("No source video on disk for game %s; storing event without clip.", game_id)

            clip = Clip(
                id=clip_id,
                event_id=event.id,
                game_id=game_id,
                video_id=game.video_id,
                event_type=ann.event_type,
                timestamp_seconds=ann.timestamp_seconds,
                start_seconds=window.start_seconds,
                end_seconds=window.end_seconds,
                stored_path=str(clip_path) if public_url else "",
                public_url=public_url,
            )
            event.clip_id = clip.id
            store.save_event(event)
            store.save_clip(clip)
            created += 1

            if job_id:
                progress = 5 + int(90 * (idx + 1) / total)
                job_service.update_job(job_id, progress=progress, message=f"Generated {created}/{total} clips.")

        game.status = "completed"
        game.event_count = created
        if not game.duration_seconds:
            game.duration_seconds = video_duration
        store.save_game(game)

        if job_id:
            job_service.update_job(job_id, status="completed", progress=100, message="Processing completed.")
        logger.info("Game %s processed: %d events.", game_id, created)

    except Exception as exc:
        logger.exception("Processing failed for game %s", game_id)
        game.status = "failed"
        store.save_game(game)
        if job_id:
            job_service.update_job(job_id, status="failed", message=f"Processing failed: {exc}")
