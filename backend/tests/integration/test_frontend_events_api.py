from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.models import Game
from app.services.store import store
from tests.conftest import requires_ffmpeg


@pytest.fixture(autouse=True)
def _clean_store():
    yield
    for gid in list(store.games):
        store.delete_game(gid)


def _game_with_video(client, sample_5s: Path) -> str:
    with sample_5s.open("rb") as f:
        up = client.post("/api/videos/upload",
                         files={"file": ("g.mp4", f, "video/mp4")},
                         data={"video_type": "full_game"})
    assert up.status_code == 200
    return up.json()["game_id"]


@requires_ffmpeg
def test_event_crud_roundtrip(client, sample_5s: Path):
    game_id = _game_with_video(client, sample_5s)

    created = client.post(f"/api/games/{game_id}/events",
                          json={"type": "shot", "timestamp": 2.0}).json()
    assert created["type"] == "shot"
    assert created["source"] == "manual"
    assert created["verified"] is False
    assert created["clipStart"] < 2.0 < created["clipEnd"]
    event_id = created["id"]

    listed = client.get(f"/api/games/{game_id}/events").json()
    assert isinstance(listed, list) and listed[0]["id"] == event_id
    assert store.get_game(game_id).event_count == 1

    patched = client.patch(f"/api/games/{game_id}/events/{event_id}",
                           json={"type": "goal", "verified": True}).json()
    assert patched["type"] == "goal" and patched["verified"] is True

    assert client.delete(f"/api/games/{game_id}/events/{event_id}").json() == {"ok": True}
    assert client.get(f"/api/games/{game_id}/events").json() == []
    assert store.get_game(game_id).event_count == 0


@requires_ffmpeg
def test_create_event_writes_thumb(client, sample_5s: Path):
    game_id = _game_with_video(client, sample_5s)
    event = client.post(f"/api/games/{game_id}/events",
                        json={"type": "shot", "timestamp": 1.0}).json()
    assert (settings.thumbnails_dir / f"{event['id']}.jpg").exists()


def test_events_404s(client):
    assert client.get("/api/games/none/events").status_code == 404
    store.save_game(Game(id="g_e404", title="T"))
    assert client.patch("/api/games/g_e404/events/missing", json={"verified": True}).status_code == 404
    assert client.delete("/api/games/g_e404/events/missing").status_code == 404
