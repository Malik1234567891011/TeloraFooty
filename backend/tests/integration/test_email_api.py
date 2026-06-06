from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.services import email_service
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
                        json={"type": "goal", "timestamp": 2.0}).json()
    return game_id, event["id"]


@requires_ffmpeg
def test_email_not_configured_returns_400(client, sample_5s: Path, monkeypatch):
    monkeypatch.setattr(settings, "smtp_user", "")
    game_id, event_id = _setup(client, sample_5s)
    resp = client.post(f"/api/games/{game_id}/events/{event_id}/email",
                       json={"to": "a@b.com"})
    assert resp.status_code == 400
    assert "configured" in resp.json()["detail"]


@requires_ffmpeg
def test_email_invalid_address_422(client, sample_5s: Path):
    game_id, event_id = _setup(client, sample_5s)
    resp = client.post(f"/api/games/{game_id}/events/{event_id}/email",
                       json={"to": "not-an-email"})
    assert resp.status_code == 422


@requires_ffmpeg
def test_email_sends_clip(client, sample_5s: Path, monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=30):
            sent["host"] = host

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, user, password):
            sent["user"] = user

        def send_message(self, msg):
            sent["to"] = msg["To"]
            sent["subject"] = msg["Subject"]

    monkeypatch.setattr(settings, "smtp_user", "tester@example.com")
    monkeypatch.setattr(settings, "smtp_pass", "secret")
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)

    game_id, event_id = _setup(client, sample_5s)
    resp = client.post(f"/api/games/{game_id}/events/{event_id}/email",
                       json={"to": "coach@example.com"})
    assert resp.json() == {"ok": True}
    assert sent["to"] == "coach@example.com"
    assert "goal" in sent["subject"]
