from __future__ import annotations

import tempfile
from pathlib import Path

from app.models import Clip, Event, Game, Video
from app.services.store import JsonStore


def _store() -> JsonStore:
    return JsonStore(data_dir=Path(tempfile.mkdtemp(prefix="telora_store_test_")))


def test_delete_event():
    s = _store()
    s.save_event(Event(id="e1", game_id="g1", event_type="shot", timestamp_seconds=1.0))
    assert s.delete_event("e1") is True
    assert s.delete_event("e1") is False
    assert s.events_for_game("g1") == []


def test_delete_clip():
    s = _store()
    s.save_clip(Clip(id="c1", game_id="g1"))
    s.delete_clip("c1")
    assert s.clips_for_game("g1") == []


def test_delete_game_cascades():
    s = _store()
    s.save_video(Video(id="v1", original_filename="a.mp4", stored_filename="a.mp4",
                       stored_path="/tmp/a.mp4", video_type="full_game"))
    s.save_game(Game(id="g1", title="T", video_id="v1"))
    s.save_event(Event(id="e1", game_id="g1", event_type="shot", timestamp_seconds=1.0))
    s.save_clip(Clip(id="c1", game_id="g1"))
    assert s.delete_game("g1") is True
    assert s.get_game("g1") is None
    assert s.get_video("v1") is None
    assert s.events_for_game("g1") == []
    assert s.clips_for_game("g1") == []
    assert s.delete_game("g1") is False
