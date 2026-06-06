from __future__ import annotations

import numpy as np

from app.cv.frame_extractor import ExtractedFrames
from app.cv.motion_analyzer import analyze_motion


def _frames(arrs: list[np.ndarray], fps: float = 6.0) -> ExtractedFrames:
    ts = [i / fps for i in range(len(arrs))]
    return ExtractedFrames(frames=arrs, timestamps=ts, fps_sampled=fps, duration_seconds=len(arrs) / fps)


def test_empty_frames_does_not_crash():
    res = analyze_motion(ExtractedFrames())
    assert res.peaks == []
    assert res.motion_curve == []


def test_single_frame_does_not_crash():
    res = analyze_motion(_frames([np.zeros((20, 20, 3), dtype=np.uint8)]))
    assert res.peaks == []


def test_static_clip_low_motion():
    frame = np.full((20, 20, 3), 100, dtype=np.uint8)
    res = analyze_motion(_frames([frame.copy() for _ in range(8)]))
    assert res.max_score == 0.0


def test_motion_spike_detected():
    frames = [np.zeros((20, 20, 3), dtype=np.uint8) for _ in range(8)]
    # Inject a bright flash in the middle to create a motion spike.
    frames[4] = np.full((20, 20, 3), 255, dtype=np.uint8)
    res = analyze_motion(_frames(frames))
    assert res.peaks
    assert res.peak_timestamp is not None
    assert res.max_score > 0
