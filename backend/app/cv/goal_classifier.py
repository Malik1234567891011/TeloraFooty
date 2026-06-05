"""Goal scoring helper.

Goal classification runs after a shot is plausible (docs/Plan.md Module 7). It
is deliberately conservative: prefer reporting a shot unless goal evidence is
strong. Kept as a small, testable scoring function.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GoalSignals:
    ball_reaches_goal_area: float = 0.0  # 0..1
    play_stops_or_resets: float = 0.0  # 0..1
    camera_tracks_celebration: float = 0.0  # 0..1
    audio_spike: float = 0.0  # 0..1
    sustained_motion_after_peak: float = 0.0  # 0..1


def score_goal(signals: GoalSignals) -> float:
    score = (
        0.30 * signals.ball_reaches_goal_area
        + 0.20 * signals.play_stops_or_resets
        + 0.20 * signals.camera_tracks_celebration
        + 0.15 * signals.audio_spike
        + 0.15 * signals.sustained_motion_after_peak
    )
    return float(min(1.0, score))
