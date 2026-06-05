from __future__ import annotations

from pathlib import Path

from tests.conftest import requires_ffmpeg


@requires_ffmpeg
def test_upload_valid_full_game(client, sample_5s: Path):
    with sample_5s.open("rb") as f:
        resp = client.post(
            "/api/videos/upload",
            files={"file": ("game.mp4", f, "video/mp4")},
            data={"video_type": "full_game", "team_name": "Our Team"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["video_id"].startswith("vid_")
    assert body["filename"] == "game.mp4"
    assert body["duration_seconds"] > 0
    assert body["game_id"] is not None
    assert body["video_url"].startswith("/media/uploads/")


def test_upload_invalid_file_type(client, tmp_path: Path):
    p = tmp_path / "notes.txt"
    p.write_text("hello")
    with p.open("rb") as f:
        resp = client.post(
            "/api/videos/upload",
            files={"file": ("notes.txt", f, "text/plain")},
            data={"video_type": "demo_clip"},
        )
    assert resp.status_code == 400
    body = resp.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "INVALID_FILE_TYPE"


def test_upload_empty_file(client):
    resp = client.post(
        "/api/videos/upload",
        files={"file": ("empty.mp4", b"", "video/mp4")},
        data={"video_type": "demo_clip"},
    )
    assert resp.status_code == 400
    assert resp.json()["status"] == "failed"


def test_upload_missing_file(client):
    resp = client.post("/api/videos/upload", data={"video_type": "demo_clip"})
    assert resp.status_code == 422  # FastAPI validation for required file
