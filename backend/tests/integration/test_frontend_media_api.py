from __future__ import annotations

from pathlib import Path

import pytest

from app.services.store import store
from tests.conftest import requires_ffmpeg


@pytest.fixture(autouse=True)
def _clean_store():
    yield
    for gid in list(store.games):
        store.delete_game(gid)


def _setup(client, sample_5s: Path) -> tuple[str, str]:
    with sample_5s.open("rb") as f:
        up = client.post("/api/videos/upload",
                         files={"file": ("g.mp4", f, "video/mp4")},
                         data={"video_type": "full_game"})
    game_id = up.json()["game_id"]
    event = client.post(f"/api/games/{game_id}/events",
                        json={"type": "shot", "timestamp": 2.0}).json()
    return game_id, event["id"]


@requires_ffmpeg
def test_video_stream(client, sample_5s: Path):
    game_id, _ = _setup(client, sample_5s)
    resp = client.get(f"/api/games/{game_id}/video")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "video/mp4"


@requires_ffmpeg
def test_thumb_served(client, sample_5s: Path):
    game_id, event_id = _setup(client, sample_5s)
    resp = client.get(f"/api/games/{game_id}/events/{event_id}/thumb.jpg")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"


@requires_ffmpeg
def test_clip_cut_on_demand_and_cached(client, sample_5s: Path):
    game_id, event_id = _setup(client, sample_5s)
    resp = client.get(f"/api/games/{game_id}/events/{event_id}/clip.mp4")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "video/mp4"
    event = store.events.get(event_id)
    assert event.clip_id is not None  # cached as a Clip record
    assert client.get(f"/api/games/{game_id}/events/{event_id}/clip.mp4").status_code == 200


def test_media_404s(client):
    assert client.get("/api/games/none/video").status_code == 404
    assert client.get("/api/games/none/events/x/thumb.jpg").status_code == 404
    assert client.get("/api/games/none/events/x/clip.mp4").status_code == 404
