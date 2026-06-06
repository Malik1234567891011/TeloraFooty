import subprocess

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


def test_ensure_h264_transcodes_non_h264(tmp_path):
    src = tmp_path / "old_codec.mp4"
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=24",
         "-c:v", "mpeg4", "-y", str(src)],
        check=True, capture_output=True,
    )
    assert clipper.video_codec(src) == "mpeg4"
    clipper.ensure_h264(src)
    assert clipper.video_codec(src) == "h264"
    assert not src.with_suffix(".h264.mp4").exists()  # no temp left behind
