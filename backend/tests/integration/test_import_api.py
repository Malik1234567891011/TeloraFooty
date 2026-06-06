from __future__ import annotations

from pathlib import Path

import pytest

from app.services import match_processing_service
from app.services.store import store
from tests.conftest import requires_ffmpeg


@pytest.fixture(autouse=True)
def _clean_store():
    yield
    for gid in list(store.games):
        store.delete_game(gid)


@requires_ffmpeg
def test_import_kicks_off_processing(client, sample_5s: Path, monkeypatch):
    monkeypatch.setattr(match_processing_service, "_detect", lambda v, on_progress=None: [])

    with sample_5s.open("rb") as f:
        resp = client.post("/api/games/import", files={"file": ("My Game.mp4", f, "video/mp4")})
    assert resp.status_code == 200
    game = resp.json()
    assert game["title"] == "My Game"
    assert game["source"] == {"kind": "local", "url": None}
    # TestClient runs BackgroundTasks before returning control: the stubbed
    # detector found nothing, so the game is ready with zero events.
    g = store.get_game(game["id"])
    assert g.status == "completed"
    assert client.get(f"/api/games/{game['id']}/events").json() == []


def test_import_rejects_non_video(client):
    resp = client.post("/api/games/import", files={"file": ("notes.txt", b"hi", "text/plain")})
    assert resp.status_code == 400
    assert "detail" in resp.json()
