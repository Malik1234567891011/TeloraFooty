from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.services.clip_service import clip_window_for_event, generate_clip
from app.services.video_metadata_service import get_video_metadata
from tests.conftest import requires_ffmpeg


def test_clip_window_for_shot():
    # ~8s of build-up before, ~4s of aftermath after.
    w = clip_window_for_event("shot", 20.0, 100.0)
    assert w.start_seconds == 12.0
    assert w.end_seconds == 24.0


def test_clip_window_for_goal_is_wider():
    # Same build-up, a little extra aftermath for the celebration.
    w = clip_window_for_event("goal", 20.0, 100.0)
    assert w.start_seconds == 12.0
    assert w.end_seconds == 26.0


def test_clip_window_clamps_start_to_zero():
    w = clip_window_for_event("shot", 2.0, 100.0)
    assert w.start_seconds == 0.0


def test_clip_window_clamps_end_to_duration():
    # 98 + 4s aftermath = 102 > 100, so it must clamp to the video duration.
    w = clip_window_for_event("shot", 98.0, 100.0)
    assert w.end_seconds == 100.0


@requires_ffmpeg
def test_generate_normal_clip(sample_5s: Path, tmp_path: Path):
    out = tmp_path / "clip.mp4"
    generate_clip(sample_5s, 1, 4, out, video_duration=5)
    assert out.exists()
    meta = get_video_metadata(out)
    assert 2.0 <= meta.duration_seconds <= 4.0


@requires_ffmpeg
def test_generate_clip_start_below_zero(sample_5s: Path, tmp_path: Path):
    out = tmp_path / "clip.mp4"
    generate_clip(sample_5s, -5, 3, out, video_duration=5)
    assert out.exists()


@requires_ffmpeg
def test_generate_clip_end_beyond_duration(sample_5s: Path, tmp_path: Path):
    out = tmp_path / "clip.mp4"
    generate_clip(sample_5s, 2, 999, out, video_duration=5)
    assert out.exists()
    meta = get_video_metadata(out)
    assert meta.duration_seconds <= 4.0


def test_generate_clip_invalid_range_raises(sample_5s: Path, tmp_path: Path):
    out = tmp_path / "clip.mp4"
    with pytest.raises(ValidationError):
        generate_clip(sample_5s, 8, 3, out, video_duration=5)
    assert not out.exists()
