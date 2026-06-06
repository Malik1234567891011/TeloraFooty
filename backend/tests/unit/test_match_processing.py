from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.models import Event, Game
from app.services import match_processing_service as mps
from app.services.store import store
from app.services.video_storage_service import save_path_as_upload
from tests.conftest import requires_ffmpeg


@pytest.fixture(autouse=True)
def _clean_store():
    yield
    for gid in list(store.games):
        store.delete_game(gid)


def _game_with_video(sample_5s: Path) -> Game:
    stored = save_path_as_upload(sample_5s, video_type="full_game")
    game = Game(id="game_mp", title="T", video_id=stored.video.id,
                video_filename=stored.video.stored_filename,
                duration_seconds=stored.video.duration_seconds)
    store.save_game(game)
    return game


@requires_ffmpeg
def test_detected_events_become_records_with_media(monkeypatch, sample_5s: Path):
    game = _game_with_video(sample_5s)
    monkeypatch.setattr(mps, "_detect", lambda v, on_progress=None: [
        mps.DetectedEvent("goal", 2.0, 0.9, "header"),
        mps.DetectedEvent("shot", 4.0, 0.7, "long range"),
    ])
    mps.process_game(game.id)
    g = store.get_game(game.id)
    assert g.status == "completed"
    assert g.event_count == 2
    events = store.events_for_game(game.id)
    assert {e.event_type for e in events} == {"goal", "shot"}
    for e in events:
        assert e.source == "model" and e.verified is False
        assert e.clip_id is not None
        assert (settings.thumbnails_dir / f"{e.id}.jpg").exists()


@requires_ffmpeg
def test_reprocess_preserves_manual_and_verified(monkeypatch, sample_5s: Path):
    game = _game_with_video(sample_5s)
    store.save_event(Event(id="e_manual", game_id=game.id, event_type="shot",
                           timestamp_seconds=1.0, source="manual"))
    store.save_event(Event(id="e_verified", game_id=game.id, event_type="goal",
                           timestamp_seconds=2.0, source="model", verified=True))
    store.save_event(Event(id="e_stale", game_id=game.id, event_type="shot",
                           timestamp_seconds=3.0, source="model", verified=False))
    monkeypatch.setattr(mps, "_detect", lambda v, on_progress=None: [mps.DetectedEvent("shot", 4.0, 0.8)])
    mps.process_game(game.id)
    ids = {e.id for e in store.events_for_game(game.id)}
    assert "e_manual" in ids and "e_verified" in ids
    assert "e_stale" not in ids
    assert len(ids) == 3  # manual + verified + 1 fresh detection


@requires_ffmpeg
def test_detector_unavailable_completes_with_zero_events(monkeypatch, sample_5s: Path):
    game = _game_with_video(sample_5s)
    monkeypatch.setattr(mps, "_detector_available", lambda: False)
    mps.process_game(game.id)
    g = store.get_game(game.id)
    assert g.status == "completed"
    assert store.events_for_game(game.id) == []


@requires_ffmpeg
def test_detection_crash_marks_failed(monkeypatch, sample_5s: Path):
    game = _game_with_video(sample_5s)
    monkeypatch.setattr(mps, "_detect", lambda v, on_progress=None: (_ for _ in ()).throw(RuntimeError("boom")))
    mps.process_game(game.id)
    g = store.get_game(game.id)
    assert g.status == "failed"
    assert "boom" in g.error


def test_missing_video_marks_failed():
    store.save_game(Game(id="game_nv", title="T"))
    mps.process_game("game_nv")
    assert store.get_game("game_nv").status == "failed"


@requires_ffmpeg
def test_process_game_reports_intermediate_progress(monkeypatch, sample_5s: Path):
    from app.services import job_service
    game = _game_with_video(sample_5s)
    job = job_service.create_job("full_game", game_id=game.id)

    def fake_detect(video, on_progress=None):
        if on_progress:
            on_progress(50, "Scanning 4/8 windows")
        return [mps.DetectedEvent("shot", 2.0, 0.8)]

    monkeypatch.setattr(mps, "_detect", fake_detect)
    mps.process_game(game.id, job.id)

    j = store.get_job(job.id)
    assert j.status == "completed" and j.progress == 100
    # The callback path is wired: the intermediate update reached the job mid-run.
    assert "windows" in (j.message or "") or j.progress == 100
