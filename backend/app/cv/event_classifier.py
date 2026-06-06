"""Evidence-combining shot/goal classifier.

This is a transparent scoring system (docs/Plan.md Modules 6 & 7), not a single
black-box model. It combines whatever signals are available and degrades to
motion-only analysis when detectors return nothing. It always returns a
structured result and never raises for missing optional features.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.cv.ball_detector import BallDetection
from app.cv.goal_classifier import GoalSignals, score_goal
from app.cv.motion_analyzer import MotionResult
from app.core.logging import get_logger

logger = get_logger(__name__)

SHOT_THRESHOLD = 0.62
GOAL_THRESHOLD = 0.70

# Peaks within this many seconds of the clip start/end are treated as camera
# resets / boundary artifacts, not real events.
BOUNDARY_GUARD_SECONDS = 1.5

# Minimum concentration of motion in the attacking goal band required before we
# will even consider a motion peak to be a shot. A long pass across midfield
# produces a strong camera pan but very little motion in the goal-mouth band, so
# this gate rejects it.
MIN_GOAL_BAND_ACTIVITY = 0.20

# Audio spikes only corroborate a goal if they occur within this many seconds of
# the candidate event timestamp.
AUDIO_ALIGN_SECONDS = 3.0


@dataclass
class ClassifierInputs:
    motion: MotionResult
    ball_tracks: list[BallDetection] = field(default_factory=list)
    players_detected: int = 0
    attacking_direction: str = "unknown"  # left_to_right | right_to_left | unknown
    audio_spike_score: float = 0.0
    audio_spike_timestamp: float | None = None
    duration_seconds: float = 0.0


@dataclass
class ClassificationResult:
    event_type: str  # shot | goal | none
    timestamp_seconds: float | None
    confidence: float
    explanation: str
    scores: dict[str, Any] = field(default_factory=dict)


def _goal_band_activity(motion: MotionResult, attacking_direction: str, index: int) -> float:
    """How concentrated motion is in the attacking goal-area band (0..1).

    Compares motion inside the outer goal band against the whole-frame motion at
    the same instant. A value near the band's area fraction (~0.28) means motion
    is spread out (e.g. a midfield pass); a high value means the action is packed
    into the goal mouth (a real shot/goal).

    The raw fraction is rescaled so ~0.25 -> 0 and ~0.55 -> 1.0.
    """
    if not motion.left_band or index >= len(motion.left_band):
        return 0.0
    left_band = motion.left_band[index]
    right_band = motion.right_band[index]
    frame_total = motion.frame_motion[index] if index < len(motion.frame_motion) else 0.0
    if frame_total <= 1e-6:
        return 0.0

    if attacking_direction == "left_to_right":
        band = right_band
    elif attacking_direction == "right_to_left":
        band = left_band
    else:
        # Unknown direction: take the more active edge as a weak proxy.
        band = max(left_band, right_band)

    fraction = band / frame_total
    return float(min(1.0, max(0.0, (fraction - 0.25) / 0.30)))


def _select_event_peak(motion: MotionResult):
    """Pick the strongest motion peak that is not a start/end boundary artifact."""
    if not motion.peaks:
        return None
    last_ts = motion.timestamps[-1] if motion.timestamps else 0.0
    interior = [
        p
        for p in motion.peaks
        if p.timestamp_seconds >= BOUNDARY_GUARD_SECONDS
        and (last_ts <= 0 or p.timestamp_seconds <= last_ts - BOUNDARY_GUARD_SECONDS)
    ]
    candidates = interior or motion.peaks
    return max(candidates, key=lambda p: p.score)


def _nearest_index(timestamps: list[float], target: float) -> int:
    if not timestamps:
        return 0
    return min(range(len(timestamps)), key=lambda i: abs(timestamps[i] - target))


def classify_event(inputs: ClassifierInputs) -> ClassificationResult:
    motion = inputs.motion

    if not motion.peaks:
        return ClassificationResult(
            event_type="none",
            timestamp_seconds=None,
            confidence=0.0,
            explanation="No motion detected; unable to identify an event.",
            scores={"shot_score": 0.0, "goal_score": 0.0},
        )

    top_peak = _select_event_peak(motion)
    if top_peak is None:
        return ClassificationResult(
            event_type="none",
            timestamp_seconds=None,
            confidence=0.0,
            explanation="No usable motion peak (only start/end artifacts).",
            scores={"shot_score": 0.0, "goal_score": 0.0},
        )
    peak_ts = top_peak.timestamp_seconds
    peak_strength = top_peak.score  # 0..1
    peak_index = _nearest_index(motion.timestamps, peak_ts)

    # --- Shot evidence ---------------------------------------------------
    camera_motion_peak = peak_strength
    # Real, goal-area-aware proxy (not just "more motion on the right half").
    ball_near_goal = _goal_band_activity(motion, inputs.attacking_direction, peak_index)

    ball_speed_toward_goal = 0.0
    has_ball = bool(inputs.ball_tracks)
    if has_ball:
        ball_speed_toward_goal = _ball_speed_score(inputs.ball_tracks, inputs.attacking_direction)

    # The action must actually reach the goal area. Without a ball detector this
    # gate is what separates a shot from a long pass / normal possession.
    if ball_near_goal < MIN_GOAL_BAND_ACTIVITY and ball_speed_toward_goal < 0.3:
        return ClassificationResult(
            event_type="none",
            timestamp_seconds=None,
            confidence=round(0.3 * ball_near_goal, 4),
            explanation=(
                "Motion detected (likely a pass or open play), but it does not "
                "concentrate in the goal area — not classified as a shot."
            ),
            scores={
                "shot_score": 0.0,
                "goal_score": 0.0,
                "camera_motion_peak": round(camera_motion_peak, 4),
                "goal_band_activity": round(ball_near_goal, 4),
                "ball_speed_toward_goal": round(ball_speed_toward_goal, 4),
                "gate": "below_goal_band_threshold",
            },
        )

    # Goal-area concentration is now the dominant signal; camera motion only
    # corroborates (it follows passes too, so it cannot fire on its own).
    shot_score = (
        0.50 * ball_near_goal
        + 0.20 * ball_speed_toward_goal
        + 0.20 * camera_motion_peak
        + 0.10 * min(1.0, (len(motion.peaks) - 1) * 0.2)
    )
    multi_peak_bonus = min(1.0, (len(motion.peaks) - 1) * 0.2)
    shot_score = round(min(1.0, shot_score), 4)

    # Audio only corroborates a goal if the spike happens *near* the event.
    # A loud moment elsewhere in the clip (e.g. a whistle at kickoff) must not
    # inflate the goal score.
    audio_near_event = 0.0
    if (
        inputs.audio_spike_timestamp is not None
        and abs(inputs.audio_spike_timestamp - peak_ts) <= AUDIO_ALIGN_SECONDS
    ):
        audio_near_event = inputs.audio_spike_score

    # --- Goal evidence (only meaningful if a shot is plausible) ---------
    goal_signals = GoalSignals(
        ball_reaches_goal_area=ball_near_goal,
        play_stops_or_resets=_play_reset_score(motion, peak_index),
        camera_tracks_celebration=peak_strength,
        audio_spike=audio_near_event,
        sustained_motion_after_peak=_post_peak_activity(motion, peak_index),
    )
    goal_score = round(score_goal(goal_signals), 4)

    scores = {
        "shot_score": shot_score,
        "goal_score": goal_score,
        "camera_motion_peak": round(camera_motion_peak, 4),
        "goal_band_activity": round(ball_near_goal, 4),
        "ball_speed_toward_goal": round(ball_speed_toward_goal, 4),
        "audio_near_event": round(audio_near_event, 4),
        "multi_peak_bonus": round(multi_peak_bonus, 4),
        "shot_threshold": SHOT_THRESHOLD,
        "goal_threshold": GOAL_THRESHOLD,
    }

    if shot_score >= SHOT_THRESHOLD and goal_score >= GOAL_THRESHOLD:
        return ClassificationResult(
            event_type="goal",
            timestamp_seconds=peak_ts,
            confidence=round(min(0.95, 0.55 + 0.4 * goal_score), 4),
            explanation=(
                "Strong motion toward the attacking goal with a follow-up reaction"
                + (" and an audio spike" if inputs.audio_spike_score > 0.5 else "")
                + " — consistent with a goal."
            ),
            scores=scores,
        )

    if shot_score >= SHOT_THRESHOLD:
        return ClassificationResult(
            event_type="shot",
            timestamp_seconds=peak_ts,
            confidence=round(min(0.92, 0.45 + 0.45 * shot_score), 4),
            explanation=(
                "Fast motion directed toward the goal area around the strongest peak"
                + (", supported by ball trajectory" if inputs.ball_tracks else " (motion-based)")
                + "."
            ),
            scores=scores,
        )

    return ClassificationResult(
        event_type="none",
        timestamp_seconds=None,
        confidence=round(shot_score, 4),
        explanation="Motion present but not strongly directed toward goal; likely normal play.",
        scores=scores,
    )


def _ball_speed_score(tracks: list[BallDetection], attacking_direction: str) -> float:
    if len(tracks) < 2:
        return 0.0
    tracks = sorted(tracks, key=lambda t: t.timestamp_seconds)
    best = 0.0
    for a, b in zip(tracks, tracks[1:]):
        dt = max(1e-3, b.timestamp_seconds - a.timestamp_seconds)
        dx = b.x - a.x
        dy = b.y - a.y
        speed = (dx * dx + dy * dy) ** 0.5 / dt
        directional = speed
        if attacking_direction == "left_to_right" and dx <= 0:
            directional *= 0.4
        elif attacking_direction == "right_to_left" and dx >= 0:
            directional *= 0.4
        best = max(best, directional)
    return float(min(1.0, best / 2.0))


def _play_reset_score(motion: MotionResult, peak_index: int) -> float:
    """Lower motion well after the peak suggests play stopped (celebration/reset)."""
    curve = motion.motion_curve
    if not curve or peak_index >= len(curve) - 2:
        return 0.0
    tail = curve[peak_index + 1 :]
    if not tail:
        return 0.0
    avg_tail = sum(tail) / len(tail)
    return float(max(0.0, 1.0 - avg_tail))


def _post_peak_activity(motion: MotionResult, peak_index: int) -> float:
    """Some sustained motion right after the peak = players running/celebrating."""
    curve = motion.motion_curve
    if not curve:
        return 0.0
    window = curve[peak_index + 1 : peak_index + 6]
    if not window:
        return 0.0
    return float(min(1.0, sum(window) / len(window)))
