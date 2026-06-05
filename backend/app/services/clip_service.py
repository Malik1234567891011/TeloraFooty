"""FFmpeg-based clip generation.

``generate_clip`` clamps the requested window to the video's bounds, validates
the range, and writes a playable MP4. Designed to never crash on boundary
inputs (start < 0, end > duration) and to raise a clear validation error for
genuinely invalid ranges (start >= end).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import ProcessingError, ValidationError
from app.core.logging import get_logger
from app.services.video_metadata_service import get_video_metadata

logger = get_logger(__name__)


@dataclass
class ClipWindow:
    start_seconds: float
    end_seconds: float


def clip_window_for_event(
    event_type: str, timestamp_seconds: float, video_duration: float
) -> ClipWindow:
    """Compute a clip window around an event per docs/Plan.md #8."""
    if event_type == "goal":
        pre, post = 8.0, 12.0
    else:
        pre, post = 6.0, 8.0
    start = max(0.0, timestamp_seconds - pre)
    end = timestamp_seconds + post
    if video_duration > 0:
        end = min(video_duration, end)
    # Guarantee a non-empty window even near the very end of the video.
    if end <= start:
        end = min(video_duration, start + 2.0) if video_duration > 0 else start + 2.0
    return ClipWindow(start_seconds=round(start, 3), end_seconds=round(end, 3))


def generate_clip(
    video_path: str | Path,
    start_seconds: float,
    end_seconds: float,
    output_path: str | Path,
    *,
    video_duration: float | None = None,
) -> Path:
    """Generate a clip from ``video_path`` between start and end seconds.

    - ``start_seconds`` below 0 is clamped to 0.
    - ``end_seconds`` beyond the video duration is clamped to the duration.
    - Raises ``ValidationError`` if the (clamped) range is invalid.
    """
    video_path = Path(video_path)
    output_path = Path(output_path)

    if not video_path.exists():
        raise ValidationError(f"Source video not found: {video_path.name}", code="VIDEO_NOT_FOUND")
    if shutil.which("ffmpeg") is None:
        raise ProcessingError("ffmpeg is not installed.", code="FFMPEG_MISSING")

    if video_duration is None:
        try:
            video_duration = get_video_metadata(video_path).duration_seconds
        except Exception:
            video_duration = 0.0

    start = max(0.0, float(start_seconds))
    end = float(end_seconds)
    if video_duration and video_duration > 0:
        end = min(end, video_duration)

    if end <= start:
        raise ValidationError(
            f"Invalid clip range: start ({start}) must be less than end ({end}).",
            code="INVALID_CLIP_RANGE",
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = end - start

    # -ss before -i for fast seek; re-encode for frame-accurate, broadly
    # playable output (Veo footage + web players).
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(video_path),
        "-t",
        f"{duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.SubprocessError as exc:
        raise ProcessingError(f"ffmpeg failed: {exc}", code="FFMPEG_ERROR") from exc

    if result.returncode != 0 or not output_path.exists():
        logger.error("ffmpeg error: %s", result.stderr[-500:])
        raise ProcessingError("Failed to generate clip.", code="CLIP_GENERATION_FAILED")

    logger.info("Clip generated: %s (%.1fs-%.1fs)", output_path.name, start, end)
    return output_path
