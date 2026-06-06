from __future__ import annotations

from pathlib import Path

from tests.conftest import requires_ffmpeg


@requires_ffmpeg
def test_demo_clip_returns_structured_result(client, sample_motion: Path):
    with sample_motion.open("rb") as f:
        resp = client.post(
            "/api/analysis/demo-clip",
            files={"file": ("clip.mp4", f, "video/mp4")},
            data={"team_name": "Our Team", "attacking_direction": "left_to_right"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis_id"].startswith("analysis_")
    assert body["status"] == "completed"

    result = body["result"]
    assert result["event_type"] in {"shot", "goal", "none"}
    assert 0.0 <= result["confidence"] <= 1.0
    assert "explanation" in result

    debug = body["debug"]
    assert debug["frames_analyzed"] > 0
    assert "method" in debug
    assert "primary_signal" in debug
    assert "vlm_available" in debug

    # If an event was found, it must include a timestamp and a clip URL.
    if result["event_type"] in {"shot", "goal"}:
        assert result["timestamp_seconds"] is not None
        assert result["clip_url"] is not None


@requires_ffmpeg
def test_demo_clip_static_video_no_crash(client, sample_static: Path):
    with sample_static.open("rb") as f:
        resp = client.post(
            "/api/analysis/demo-clip",
            files={"file": ("static.mp4", f, "video/mp4")},
            data={"attacking_direction": "unknown"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["event_type"] in {"shot", "goal", "none"}


def test_demo_clip_invalid_file(client, tmp_path: Path):
    p = tmp_path / "bad.mp4"
    p.write_bytes(b"not a video")
    with p.open("rb") as f:
        resp = client.post(
            "/api/analysis/demo-clip",
            files={"file": ("bad.mp4", f, "video/mp4")},
        )
    # Stored but unreadable -> clean 400, not a crash.
    assert resp.status_code == 400
    assert resp.json()["status"] == "failed"
