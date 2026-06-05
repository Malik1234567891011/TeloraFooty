"""High-recall candidate generation (docs/newTips.md Layer 1).

Two jobs:
1. Build overlapping time windows that tile the clip, so the VLM judge is asked
   about short segments and cannot miss one quick action in a long clip.
2. Produce local "suspicious moment" candidate timestamps from cheap CV signals
   (motion peaks, audio spike, the player-attack peak). These are used to refine
   the VLM's timestamp and as a fallback when no VLM is available.

The guiding principle is recall: be generous; the judge/fusion layer decides.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Candidate:
    timestamp_seconds: float
    score: float
    source: str


@dataclass
class CandidateSet:
    windows: list[tuple[float, float]] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)

    @property
    def best(self) -> Candidate | None:
        return max(self.candidates, key=lambda c: c.score) if self.candidates else None


def _tile(duration: float, size: float, stride: float) -> list[tuple[float, float]]:
    windows: list[tuple[float, float]] = []
    start = 0.0
    while start < duration:
        end = min(duration, start + size)
        windows.append((round(start, 2), round(end, 2)))
        if end >= duration:
            break
        start += stride
    return windows


def create_windows(duration: float, size: float, stride: float, max_windows: int) -> list[tuple[float, float]]:
    """Tile the clip with overlapping windows of ``size`` advancing by ``stride``.

    If the natural tiling exceeds ``max_windows`` we WIDEN the stride so the whole
    clip stays covered with no gaps (a dropped window can hide a real shot — see
    docs/callibrations+results.md iter 1). We never leave holes in coverage.
    """
    if duration <= 0:
        return [(0.0, size)]

    windows = _tile(duration, size, stride)
    if len(windows) <= max_windows:
        return windows

    # Too many windows: grow the stride until the count fits, keeping contiguous
    # (still-overlapping) coverage rather than sampling sparsely.
    needed_stride = max(stride, (duration - size) / max(max_windows - 1, 1))
    return _tile(duration, size, needed_stride)


def generate_candidates(motion, attack, audio) -> list[Candidate]:
    """Collect suspicious timestamps from local signals (generously)."""
    candidates: list[Candidate] = []

    for peak in getattr(motion, "peaks", [])[:5]:
        candidates.append(Candidate(peak.timestamp_seconds, round(0.5 * peak.score, 4), "motion"))

    if getattr(attack, "available", False) and attack.timestamp_seconds is not None:
        candidates.append(Candidate(attack.timestamp_seconds, round(min(1.0, attack.confidence), 4), "players"))

    if getattr(audio, "has_audio", False) and audio.spike_timestamp is not None and audio.spike_score > 0.5:
        candidates.append(Candidate(audio.spike_timestamp, round(0.4 * audio.spike_score, 4), "audio"))

    return candidates
