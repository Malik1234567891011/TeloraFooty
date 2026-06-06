"""Load and validate manual annotation JSON files.

Annotations live in ``storage/annotations/<game_id>.json`` (see docs/Plan.md
#9). Timestamps are normalized to seconds (supports mm:ss and hh:mm:ss strings)
and events are returned sorted by timestamp.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger

logger = get_logger(__name__)

VALID_EVENT_TYPES = {"shot", "goal"}


@dataclass
class AnnotationEvent:
    event_type: str
    timestamp_seconds: float
    team: str | None = None
    period: int | None = None
    notes: str | None = None


@dataclass
class GameAnnotations:
    game_id: str
    title: str
    team_name: str
    opponent_name: str | None
    video_filename: str | None
    events: list[AnnotationEvent] = field(default_factory=list)


def normalize_timestamp(value) -> float:
    """Convert a timestamp to seconds.

    Accepts numeric seconds or "mm:ss" / "hh:mm:ss" strings.
    """
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str):
        parts = value.strip().split(":")
        try:
            parts_f = [float(p) for p in parts]
        except ValueError as exc:
            raise ValidationError(f"Invalid timestamp: {value!r}", code="INVALID_TIMESTAMP") from exc
        if len(parts_f) == 1:
            seconds = parts_f[0]
        elif len(parts_f) == 2:
            seconds = parts_f[0] * 60 + parts_f[1]
        elif len(parts_f) == 3:
            seconds = parts_f[0] * 3600 + parts_f[1] * 60 + parts_f[2]
        else:
            raise ValidationError(f"Invalid timestamp: {value!r}", code="INVALID_TIMESTAMP")
    else:
        raise ValidationError(f"Invalid timestamp type: {type(value)}", code="INVALID_TIMESTAMP")

    if seconds < 0:
        raise ValidationError("timestamp_seconds must be >= 0.", code="INVALID_TIMESTAMP")
    return round(seconds, 3)


def annotation_path(game_id: str) -> Path:
    return settings.annotations_dir / f"{game_id}.json"


def parse_annotations(raw: dict) -> GameAnnotations:
    """Validate and normalize a raw annotation dict."""
    if not isinstance(raw, dict):
        raise ValidationError("Annotation file must be a JSON object.", code="INVALID_ANNOTATION")

    game_id = raw.get("game_id")
    if not game_id:
        raise ValidationError("Annotation missing 'game_id'.", code="INVALID_ANNOTATION")

    events_raw = raw.get("events", [])
    if not isinstance(events_raw, list):
        raise ValidationError("'events' must be a list.", code="INVALID_ANNOTATION")

    events: list[AnnotationEvent] = []
    for idx, ev in enumerate(events_raw):
        etype = ev.get("type")
        if etype not in VALID_EVENT_TYPES:
            raise ValidationError(
                f"Event {idx} has invalid type {etype!r}; expected one of {sorted(VALID_EVENT_TYPES)}.",
                code="INVALID_EVENT_TYPE",
            )
        if "timestamp_seconds" not in ev and "timestamp" not in ev:
            raise ValidationError(f"Event {idx} missing timestamp.", code="MISSING_TIMESTAMP")
        ts = normalize_timestamp(ev.get("timestamp_seconds", ev.get("timestamp")))
        events.append(
            AnnotationEvent(
                event_type=etype,
                timestamp_seconds=ts,
                team=ev.get("team", "our_team"),
                period=ev.get("period"),
                notes=ev.get("notes"),
            )
        )

    events.sort(key=lambda e: e.timestamp_seconds)
    return GameAnnotations(
        game_id=game_id,
        title=raw.get("title", game_id),
        team_name=raw.get("team_name", "Our Team"),
        opponent_name=raw.get("opponent_name"),
        video_filename=raw.get("video_filename"),
        events=events,
    )


def load_annotations(game_id: str) -> GameAnnotations:
    """Load and validate annotations for ``game_id``."""
    path = annotation_path(game_id)
    if not path.exists():
        raise NotFoundError(f"No annotation file for game '{game_id}'.", code="ANNOTATION_NOT_FOUND")
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"Annotation file for '{game_id}' contains invalid JSON.", code="INVALID_JSON"
        ) from exc
    return parse_annotations(raw)


def load_annotations_from_file(path: str | Path) -> GameAnnotations:
    path = Path(path)
    if not path.exists():
        raise NotFoundError(f"Annotation file not found: {path}", code="ANNOTATION_NOT_FOUND")
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValidationError("Annotation file contains invalid JSON.", code="INVALID_JSON") from exc
    return parse_annotations(raw)
