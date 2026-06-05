from __future__ import annotations

from app.cv.event_classifier import ClassifierInputs, classify_event
from app.cv.goal_classifier import GoalSignals, score_goal
from app.cv.motion_analyzer import MotionPeak, MotionResult


def _motion(
    peaks,
    curve,
    left=None,
    right=None,
    timestamps=None,
    left_band=None,
    right_band=None,
    frame_motion=None,
) -> MotionResult:
    n = len(curve)
    timestamps = timestamps or [i / 6.0 for i in range(n)]
    return MotionResult(
        motion_curve=curve,
        timestamps=timestamps,
        peaks=peaks,
        left_motion=left or [0.5] * n,
        right_motion=right or [0.5] * n,
        left_band=left_band or [0.0] * n,
        right_band=right_band or [0.0] * n,
        frame_motion=frame_motion or [1.0] * n,
        peak_timestamp=peaks[0].timestamp_seconds if peaks else None,
        max_score=max(curve) if curve else 0.0,
    )


def test_no_motion_returns_none():
    res = classify_event(ClassifierInputs(motion=_motion([], [])))
    assert res.event_type == "none"
    assert res.confidence == 0.0


def test_strong_shot_evidence():
    # Peak at t=3.0, away from the start/end boundary guard, with motion
    # strongly concentrated in the attacking (right) goal band.
    ts = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    peaks = [MotionPeak(3.0, 1.0), MotionPeak(2.0, 0.7), MotionPeak(4.0, 0.6)]
    curve = [0.1, 0.3, 0.7, 1.0, 0.6, 0.2, 0.1, 0.1]
    frame_motion = [1.0] * 8
    right_band = [0.0, 0.0, 0.3, 0.6, 0.5, 0.1, 0.0, 0.0]  # ~0.6 of frame at peak
    left_band = [0.0] * 8
    res = classify_event(
        ClassifierInputs(
            motion=_motion(
                peaks, curve, timestamps=ts, left_band=left_band, right_band=right_band, frame_motion=frame_motion
            ),
            attacking_direction="left_to_right",
        )
    )
    assert res.event_type in {"shot", "goal"}
    assert 0.0 <= res.confidence <= 1.0
    assert res.timestamp_seconds == 3.0
    assert res.explanation


def test_long_pass_midfield_returns_none():
    # Strong camera pan (high motion) but motion is spread across the frame, not
    # concentrated in the goal band -> must NOT be classified as a shot.
    ts = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    peaks = [MotionPeak(3.0, 1.0), MotionPeak(2.0, 0.9), MotionPeak(4.0, 0.8)]
    curve = [0.2, 0.5, 0.9, 1.0, 0.8, 0.4, 0.2, 0.1]
    frame_motion = [1.0] * 8
    # Goal band only carries ~its area fraction of motion (diffuse pan).
    right_band = [0.28] * 8
    left_band = [0.28] * 8
    res = classify_event(
        ClassifierInputs(
            motion=_motion(
                peaks, curve, timestamps=ts, left_band=left_band, right_band=right_band, frame_motion=frame_motion
            ),
            attacking_direction="left_to_right",
        )
    )
    assert res.event_type == "none"


def test_boundary_peak_ignored():
    # Strongest peak is at the very end (artifact); a weaker interior peak at
    # t=3.0 has real goal-band activity and should be chosen instead.
    ts = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    peaks = [MotionPeak(7.0, 1.0), MotionPeak(3.0, 0.8)]
    curve = [0.1, 0.2, 0.5, 0.8, 0.4, 0.2, 0.3, 1.0]
    frame_motion = [1.0] * 8
    right_band = [0.0, 0.0, 0.3, 0.6, 0.2, 0.0, 0.0, 0.0]
    left_band = [0.0] * 8
    res = classify_event(
        ClassifierInputs(
            motion=_motion(
                peaks, curve, timestamps=ts, left_band=left_band, right_band=right_band, frame_motion=frame_motion
            ),
            attacking_direction="left_to_right",
        )
    )
    # The end-of-clip peak (t=7.0) is ignored; classification keys off t=3.0.
    assert res.timestamp_seconds in {3.0, None}
    if res.event_type in {"shot", "goal"}:
        assert res.timestamp_seconds == 3.0


def test_weak_evidence_returns_none():
    peaks = [MotionPeak(2.0, 0.5)]
    curve = [0.4, 0.45, 0.5, 0.45, 0.4]
    res = classify_event(
        ClassifierInputs(motion=_motion(peaks, curve), attacking_direction="unknown")
    )
    assert res.event_type == "none"


def test_confidence_always_in_range():
    peaks = [MotionPeak(1.0, 1.0)]
    res = classify_event(
        ClassifierInputs(
            motion=_motion(peaks, [1.0, 1.0, 1.0]),
            attacking_direction="left_to_right",
            audio_spike_score=1.0,
        )
    )
    assert 0.0 <= res.confidence <= 1.0


def test_goal_score_bounds():
    assert score_goal(GoalSignals()) == 0.0
    full = GoalSignals(1.0, 1.0, 1.0, 1.0, 1.0)
    assert abs(score_goal(full) - 1.0) < 1e-6


def test_missing_optional_features_no_crash():
    peaks = [MotionPeak(1.0, 0.8)]
    res = classify_event(ClassifierInputs(motion=_motion(peaks, [0.2, 0.8, 0.3]), ball_tracks=[]))
    assert res.event_type in {"shot", "goal", "none"}
