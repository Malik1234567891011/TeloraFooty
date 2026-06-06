from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.services import drive_service, match_processing_service
from app.services.store import store


@pytest.fixture(autouse=True)
def _clean_store():
    yield
    for gid in list(store.games):
        store.delete_game(gid)


class _InlineThread:
    """Run thread targets synchronously so tests are deterministic."""

    def __init__(self, target=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


def test_parse_drive_url():
    assert drive_service.parse_drive_url(
        "https://drive.google.com/drive/folders/abc_123")[0] == "folder"
    assert drive_service.parse_drive_url(
        "https://drive.google.com/file/d/xyz-9/view") == ("file", "xyz-9")
    with pytest.raises(ValueError):
        drive_service.parse_drive_url("https://example.com/nope")


def test_drive_list_bad_url_400(client):
    resp = client.post("/api/drive/list", json={"url": "https://example.com/x"})
    assert resp.status_code == 400
    assert "detail" in resp.json()


def test_import_drive_file_success(client, sample_5s: Path, monkeypatch):
    def fake_download(id=None, output=None, quiet=True):
        shutil.copy2(sample_5s, output)

    monkeypatch.setattr(drive_service.gdown, "download", fake_download)
    monkeypatch.setattr(drive_service.threading, "Thread", _InlineThread)
    monkeypatch.setattr(match_processing_service, "_detect", lambda v: [])

    resp = client.post("/api/games/import-drive",
                       json={"url": "https://drive.google.com/file/d/abc123/view"})
    assert resp.status_code == 200
    games = resp.json()
    assert len(games) == 1
    g = store.get_game(games[0]["id"])
    assert g.status == "completed"
    assert g.source_kind == "drive"
    assert g.duration_seconds > 0


def test_import_drive_download_failure_marks_error(client, monkeypatch):
    def fail_download(id=None, output=None, quiet=True):
        raise drive_service.gdown.exceptions.DownloadError("nope")

    monkeypatch.setattr(drive_service.gdown, "download", fail_download)
    monkeypatch.setattr(drive_service.threading, "Thread", _InlineThread)

    resp = client.post("/api/games/import-drive",
                       json={"url": "https://drive.google.com/file/d/abc123/view"})
    g = store.get_game(resp.json()[0]["id"])
    assert g.status == "failed"
    assert "shared" in g.error
