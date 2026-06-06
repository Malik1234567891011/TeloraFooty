from __future__ import annotations

from datetime import datetime, timezone

from app.models import Event, Game
from app.schemas.frontend_api import event_out, game_out


def _game(**kw) -> Game:
    base = dict(id="game_1", title="Test", duration_seconds=100.0,
                created_at=datetime(2026, 6, 6, tzinfo=timezone.utc))
    base.update(kw)
    return Game(**base)


def test_game_out_maps_statuses():
    assert game_out(_game(status="uploaded")).status == "processing"
    assert game_out(_game(status="processing")).status == "processing"
    assert game_out(_game(status="downloading")).status == "downloading"
    assert game_out(_game(status="completed")).status == "ready"
    assert game_out(_game(status="failed", error="boom")).error == "boom"
    assert game_out(_game(status="failed")).status == "error"


def test_game_out_shape():
    g = game_out(_game(source_kind="drive", source_url="http://x"), goals=2, shots=5)
    assert g.id == "game_1"
    assert g.date == "2026-06-06"
    assert g.durationSec == 100.0
    assert g.source == {"kind": "drive", "url": "http://x"}
    assert g.goals == 2 and g.shots == 5


def test_event_out_maps_source_and_window():
    e = Event(id="evt_1", game_id="game_1", event_type="goal",
              timestamp_seconds=50.0, confidence=0.9, source="model")
    out = event_out(e, video_duration=100.0)
    assert out.source == "ai"
    assert out.type == "goal"
    assert out.timestamp == 50.0
    assert out.verified is False
    assert out.clipStart < 50.0 < out.clipEnd
    assert event_out(Event(id="e2", event_type="shot", timestamp_seconds=1.0,
                           source="manual"), 100.0).source == "manual"
