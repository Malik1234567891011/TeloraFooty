"""Seed preloaded demo games (docs/Plan.md Task 7.3).

Creates three demo games with manual annotations so the frontend has content
immediately. If a sample video is available locally, it is used as the source
so clips are actually generated and playable. Without a video, games + events
are still created (clips are added later when a real game video is processed).

Seeding is idempotent: it does nothing if games already exist.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config import BACKEND_DIR, settings
from app.core.ids import new_id
from app.core.logging import get_logger
from app.models import Game
from app.services import processing_service, video_storage_service
from app.services.store import store

logger = get_logger(__name__)

# Candidate locations for a local sample video to back the demo games.
_SAMPLE_VIDEO_CANDIDATES = [
    BACKEND_DIR.parent / "g17cunetestingfilmmidland.mp4",
    settings.uploads_dir / "sample_demo.mp4",
]


def _find_sample_video() -> Path | None:
    for candidate in _SAMPLE_VIDEO_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def _demo_annotation(game_id: str, title: str, opponent: str, duration: float, video_filename: str | None) -> dict:
    """Build an annotation dict with timestamps that fit within ``duration``."""
    # Spread a few events across the available duration (works for short
    # sample clips and full games alike).
    d = duration if duration and duration > 6 else 44.0
    events = [
        {"type": "shot", "team": "our_team", "timestamp_seconds": round(d * 0.18, 1), "period": 1, "notes": "Early shot from edge of box"},
        {"type": "goal", "team": "our_team", "timestamp_seconds": round(d * 0.5, 1), "period": 1, "notes": "Goal after a quick break"},
        {"type": "shot", "team": "our_team", "timestamp_seconds": round(d * 0.8, 1), "period": 2, "notes": "Long-range effort saved"},
    ]
    return {
        "game_id": game_id,
        "title": title,
        "team_name": "Our Team",
        "opponent_name": opponent,
        "video_filename": video_filename,
        "events": events,
    }


def seed_demo_games() -> None:
    if store.list_games():
        logger.info("Demo games already present; skipping seed.")
        return

    settings.ensure_dirs()
    sample = _find_sample_video()

    sample_video_record = None
    duration = 44.0
    if sample is not None:
        try:
            stored = video_storage_service.save_path_as_upload(sample, video_type="full_game", prefix="seed")
            sample_video_record = stored.video
            duration = stored.video.duration_seconds or duration
            logger.info("Seeded sample video %s (%.1fs).", stored.video.id, duration)
        except Exception as exc:
            logger.warning("Could not load sample video for seeding (%s).", exc)

    demos = [
        ("game_001", "TeloraFooty Demo Game 1", "Riverside FC"),
        ("game_002", "TeloraFooty Demo Game 2", "Northgate United"),
        ("game_003", "TeloraFooty Demo Game 3", "Lakeside Athletic"),
    ]

    for game_id, title, opponent in demos:
        video_filename = sample_video_record.stored_filename if sample_video_record else None
        annotation = _demo_annotation(game_id, title, opponent, duration, video_filename)
        ann_path = settings.annotations_dir / f"{game_id}.json"
        ann_path.write_text(json.dumps(annotation, indent=2))

        game = Game(
            id=game_id,
            title=title,
            video_id=sample_video_record.id if sample_video_record else None,
            video_filename=video_filename,
            team_name="Our Team",
            opponent_name=opponent,
            status="uploaded",
            duration_seconds=duration,
        )
        store.save_game(game)

        # If we have a backing video, process now so clips exist for the demo.
        if sample_video_record is not None:
            try:
                processing_service.process_game_from_annotations(game_id)
            except Exception as exc:
                logger.warning("Seed processing failed for %s (%s).", game_id, exc)

    logger.info("Seeded %d demo games.", len(demos))
