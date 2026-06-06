from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import InvalidVideoError
from app.services.video_metadata_service import get_video_metadata
from tests.conftest import requires_ffmpeg


@requires_ffmpeg
def test_metadata_valid_video(sample_5s: Path):
    meta = get_video_metadata(sample_5s)
    assert 4.0 <= meta.duration_seconds <= 6.0
    assert meta.width == 320
    assert meta.height == 240
    assert meta.fps > 0


def test_metadata_missing_file(tmp_path: Path):
    with pytest.raises(InvalidVideoError):
        get_video_metadata(tmp_path / "missing.mp4")


def test_metadata_corrupt_file(tmp_path: Path):
    bad = tmp_path / "corrupt.mp4"
    bad.write_bytes(b"this is not a video")
    with pytest.raises(InvalidVideoError):
        get_video_metadata(bad)
