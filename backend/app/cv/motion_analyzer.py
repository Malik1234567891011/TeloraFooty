"""Motion analysis over extracted frames.

Computes a per-frame motion magnitude curve using frame differencing (fast and
dependency-light), smooths it, and identifies peaks. Also splits motion into
left/right halves of the frame so the classifier can reason about which side of
the pitch the action is on (a proxy for "toward goal").
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.cv.frame_extractor import ExtractedFrames
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class MotionPeak:
    timestamp_seconds: float
    score: float


# Fraction of frame width treated as the goal-area band at each edge
# (docs/Plan.md Module 5: "likely goal area = left/right 25% of frame").
GOAL_BAND_FRACTION = 0.28


@dataclass
class MotionResult:
    motion_curve: list[float] = field(default_factory=list)
    timestamps: list[float] = field(default_factory=list)
    peaks: list[MotionPeak] = field(default_factory=list)
    left_motion: list[float] = field(default_factory=list)
    right_motion: list[float] = field(default_factory=list)
    # Motion concentrated in the outer goal-area band on each side.
    left_band: list[float] = field(default_factory=list)
    right_band: list[float] = field(default_factory=list)
    # Total per-frame motion magnitude (mean abs diff), unnormalized.
    frame_motion: list[float] = field(default_factory=list)
    peak_timestamp: float | None = None
    max_score: float = 0.0


def _smooth(values: np.ndarray, window: int = 3) -> np.ndarray:
    if len(values) < window or window <= 1:
        return values
    kernel = np.ones(window) / window
    return np.convolve(values, kernel, mode="same")


def analyze_motion(extracted: ExtractedFrames) -> MotionResult:
    """Compute a motion curve and peaks. Never raises on empty/short input."""
    frames = extracted.frames
    timestamps = extracted.timestamps
    if len(frames) < 2:
        return MotionResult(timestamps=list(timestamps))

    try:
        import cv2

        def to_gray(f):
            return cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
    except ImportError:  # pragma: no cover - cv2 expected in tests

        def to_gray(f):
            return f.mean(axis=2) if f.ndim == 3 else f

    raw: list[float] = [0.0]
    left: list[float] = [0.0]
    right: list[float] = [0.0]
    left_band: list[float] = [0.0]
    right_band: list[float] = [0.0]
    prev = to_gray(frames[0]).astype(np.float32)
    width = prev.shape[1]
    band_w = max(1, int(width * GOAL_BAND_FRACTION))
    for frame in frames[1:]:
        gray = to_gray(frame).astype(np.float32)
        diff = np.abs(gray - prev)
        raw.append(float(diff.mean()))
        mid = diff.shape[1] // 2
        left.append(float(diff[:, :mid].mean()))
        right.append(float(diff[:, mid:].mean()))
        left_band.append(float(diff[:, :band_w].mean()))
        right_band.append(float(diff[:, -band_w:].mean()))
        prev = gray

    arr = np.asarray(raw, dtype=np.float32)
    smoothed = _smooth(arr)

    max_raw = float(smoothed.max()) if smoothed.size else 0.0
    norm = (smoothed / max_raw) if max_raw > 0 else smoothed

    peaks = _find_peaks(norm, timestamps)
    peak_ts = peaks[0].timestamp_seconds if peaks else None

    return MotionResult(
        motion_curve=[round(float(v), 4) for v in norm],
        timestamps=list(timestamps),
        peaks=peaks,
        left_motion=[round(v, 4) for v in left],
        right_motion=[round(v, 4) for v in right],
        left_band=[round(v, 4) for v in left_band],
        right_band=[round(v, 4) for v in right_band],
        frame_motion=[round(v, 4) for v in raw],
        peak_timestamp=peak_ts,
        max_score=round(max_raw, 4),
    )


def _find_peaks(norm: np.ndarray, timestamps: list[float], min_prominence: float = 0.45) -> list[MotionPeak]:
    peaks: list[MotionPeak] = []
    n = len(norm)
    for i in range(1, n - 1):
        if norm[i] >= norm[i - 1] and norm[i] >= norm[i + 1] and norm[i] >= min_prominence:
            ts = timestamps[i] if i < len(timestamps) else float(i)
            peaks.append(MotionPeak(timestamp_seconds=round(ts, 3), score=round(float(norm[i]), 4)))
    # Fall back to the global max if no clear peak met the threshold.
    if not peaks and n:
        i = int(np.argmax(norm))
        ts = timestamps[i] if i < len(timestamps) else float(i)
        peaks.append(MotionPeak(timestamp_seconds=round(ts, 3), score=round(float(norm[i]), 4)))
    peaks.sort(key=lambda p: p.score, reverse=True)
    return peaks
