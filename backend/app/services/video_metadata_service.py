"""Extract video metadata (duration, fps, width, height).

Prefers ffprobe (fast, no full decode). Falls back to OpenCV if ffprobe is
unavailable. Raises ``InvalidVideoError`` for missing or unreadable files.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import InvalidVideoError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class VideoMetadata:
    duration_seconds: float
    fps: float
    width: int
    height: int

    def as_dict(self) -> dict:
        return {
            "duration_seconds": round(self.duration_seconds, 3),
            "fps": round(self.fps, 3),
            "width": self.width,
            "height": self.height,
        }


def _parse_fraction(value: str) -> float:
    try:
        if "/" in value:
            num, den = value.split("/")
            den_f = float(den)
            return float(num) / den_f if den_f else 0.0
        return float(value)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _probe_with_ffprobe(path: Path) -> VideoMetadata | None:
    if shutil.which("ffprobe") is None:
        return None
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("ffprobe failed for %s: %s", path, exc)
        return None
    if out.returncode != 0:
        logger.warning("ffprobe returned %s for %s: %s", out.returncode, path, out.stderr[:200])
        return None

    try:
        info = json.loads(out.stdout)
    except json.JSONDecodeError:
        return None

    video_stream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"), None
    )
    if video_stream is None:
        return None

    fmt = info.get("format", {})
    duration = float(fmt.get("duration") or video_stream.get("duration") or 0.0)
    fps = _parse_fraction(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "0")
    if fps == 0.0:
        fps = _parse_fraction(video_stream.get("r_frame_rate") or "0")
    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    return VideoMetadata(duration_seconds=duration, fps=fps, width=width, height=height)


def _probe_with_opencv(path: Path) -> VideoMetadata | None:
    try:
        import cv2  # imported lazily so metadata works even if cv2 missing
    except ImportError:
        return None

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration = frame_count / fps if fps else 0.0
        return VideoMetadata(duration_seconds=duration, fps=fps, width=width, height=height)
    finally:
        cap.release()


def get_video_metadata(video_path: str | Path) -> VideoMetadata:
    path = Path(video_path)
    if not path.exists():
        raise InvalidVideoError(f"Video file not found: {path.name}", code="VIDEO_NOT_FOUND")

    meta = _probe_with_ffprobe(path) or _probe_with_opencv(path)
    if meta is None:
        raise InvalidVideoError(
            "Could not read video. The file may be corrupt or not a valid video.",
            code="INVALID_VIDEO",
        )
    return meta
