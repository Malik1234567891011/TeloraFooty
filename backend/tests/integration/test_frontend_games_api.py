from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import Event, Game
from app.services.store import store


@pytest.fixture(autouse=True)
def _clean_store():
    yield
    for gid in list(store.games):
        store.delete_game(gid)


def _seed(game_id: str = "game_t1", status: str = "completed") -> Game:
    game = Game(id=game_id, title="Match", status=status, duration_seconds=120.0,
                created_at=datetime(2026, 6, 6, tzinfo=timezone.utc))
    store.save_game(game)
    return game


def test_list_games_is_frontend_array(client):
    _seed()
    store.save_event(Event(id="e1", game_id="game_t1", event_type="goal",
                           timestamp_seconds=10.0, source="model"))
    store.save_event(Event(id="e2", game_id="game_t1", event_type="shot",
                           timestamp_seconds=20.0, source="model"))
    body = client.get("/api/games").json()
    assert isinstance(body, list)
    g = next(x for x in body if x["id"] == "game_t1")
    assert g["status"] == "ready"
    assert g["durationSec"] == 120.0
    assert g["goals"] == 1 and g["shots"] == 1
    assert g["source"] == {"kind": "local", "url": None}


def test_get_game_frontend_shape(client):
    _seed(status="failed")
    g = client.get("/api/games/game_t1").json()
    assert g["status"] == "error"
    assert "date" in g


def test_get_game_404_detail(client):
    resp = client.get("/api/games/nope")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Game not found"


def test_delete_game(client):
    _seed()
    assert client.delete("/api/games/game_t1").json() == {"ok": True}
    assert client.get("/api/games/game_t1").status_code == 404
    assert client.delete("/api/games/game_t1").status_code == 404
