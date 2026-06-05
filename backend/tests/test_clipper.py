import pytest

import clipper


def test_probe_duration(sample_video):
    assert clipper.probe_duration(sample_video) == pytest.approx(10.0, abs=0.5)


def test_video_codec(sample_video):
    assert clipper.video_codec(sample_video) == "h264"


def test_extract_thumb(sample_video, tmp_path):
    out = tmp_path / "thumbs" / "evt_x.jpg"
    clipper.extract_thumb(sample_video, 3.0, out)
    assert out.exists() and out.stat().st_size > 0


def test_export_clip(sample_video, tmp_path):
    out = tmp_path / "clip.mp4"
    clipper.export_clip(sample_video, 2.0, 5.0, out)
    assert clipper.probe_duration(out) == pytest.approx(3.0, abs=0.6)


def test_export_clip_failure_cleans_up(tmp_path):
    out = tmp_path / "clip.mp4"
    with pytest.raises(RuntimeError):
        clipper.export_clip(tmp_path / "missing.mp4", 0.0, 1.0, out)
    assert not out.exists()
