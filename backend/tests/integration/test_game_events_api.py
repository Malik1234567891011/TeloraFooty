from __future__ import annotations

import json
from pathlib import Path

from app.config import settings
from app.models import Game
from app.services import processing_service
from app.services.store import store
from tests.conftest import requires_ffmpeg


def _register_game(game_id: str, video_id: str | None, video_filename: str | None, duration: float):
    settings.ensure_dirs()
    annotation = {
        "game_id": game_id,
        "title": "Test Game",
        "team_name": "Our Team",
        "opponent_name": "Test Opp",
        "video_filename": video_filename,
        "events": [
            {"type": "shot", "timestamp_seconds": 1.0, "period": 1},
            {"type": "goal", "timestamp_seconds": 3.0, "period": 1},
        ],
    }
    (settings.annotations_dir / f"{game_id}.json").write_text(json.dumps(annotation))
    store.save_game(
        Game(
            id=game_id,
            title="Test Game",
            video_id=video_id,
            video_filename=video_filename,
            team_name="Our Team",
            opponent_name="Test Opp",
            duration_seconds=duration,
        )
    )


def test_events_nonexistent_game(client):
    resp = client.get("/api/games/does_not_exist/events")
    assert resp.status_code == 404


@requires_ffmpeg
def test_full_game_processing_integration(client, sample_5s: Path):
    # Upload a fixture video as a full game.
    with sample_5s.open("rb") as f:
        up = client.post(
            "/api/videos/upload",
            files={"file": ("g.mp4", f, "video/mp4")},
            data={"video_type": "full_game"},
        )
    assert up.status_code == 200
    video_id = up.json()["video_id"]
    video = store.get_video(video_id)

    game_id = "test_game_int"
    _register_game(game_id, video_id, video.stored_filename, video.duration_seconds)

    # Process synchronously for a deterministic test.
    processing_service.process_game_from_annotations(game_id)

    events = client.get(f"/api/games/{game_id}/events").json()["events"]
    assert len(events) == 2
    # Sorted by timestamp.
    assert events[0]["timestamp_seconds"] <= events[1]["timestamp_seconds"]
    # Goal not double-tagged as shot.
    types = [e["type"] for e in events]
    assert types == ["shot", "goal"]
    for e in events:
        assert e["source"] == "manual"
        assert e["confidence"] == 1.0

    clips = client.get(f"/api/games/{game_id}/clips").json()["clips"]
    assert len(clips) == 2
    for c in clips:
        assert c["clip_url"].startswith("/media/clips/")
        assert Path(settings.clips_dir / Path(c["clip_url"]).name).exists()


def test_process_nonexistent_game(client):
    resp = client.post("/api/games/nope/process")
    assert resp.status_code == 404
