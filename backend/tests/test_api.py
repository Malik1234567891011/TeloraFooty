import shutil

import pytest
from fastapi.testclient import TestClient

import importer
import store
from main import app

client = TestClient(app)


@pytest.fixture()
def ready_game(sample_video, data_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "SAMPLE_EVENTS", [(2.0, "shot"), (5.0, "goal")])
    src = tmp_path / "upload.mp4"
    shutil.copy(sample_video, src)
    return importer.import_local(src, "API Game")


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_list_and_get_games(ready_game):
    games = client.get("/api/games").json()
    assert [g["id"] for g in games] == [ready_game["id"]]
    assert games[0]["goals"] == 1 and games[0]["shots"] == 1  # library card counts
    game = client.get(f"/api/games/{ready_game['id']}").json()
    assert game["title"] == "API Game"
    assert game["status"] == "ready"


def test_get_missing_game_404(data_dir):
    assert client.get("/api/games/game_nope").status_code == 404


def test_import_file_upload(sample_video, data_dir, monkeypatch):
    monkeypatch.setattr(importer, "SAMPLE_EVENTS", [(2.0, "shot")])
    with sample_video.open("rb") as f:
        res = client.post("/api/games/import",
                          files={"file": ("my game.mp4", f, "video/mp4")})
    assert res.status_code == 200
    game = res.json()
    assert game["title"] == "my game"
    assert game["status"] == "ready"


def test_import_rejects_unsupported_extension(data_dir):
    res = client.post("/api/games/import",
                      files={"file": ("notes.txt", b"hello", "text/plain")})
    assert res.status_code == 400


def test_video_streaming_supports_range(ready_game):
    res = client.get(f"/api/games/{ready_game['id']}/video",
                     headers={"Range": "bytes=0-99"})
    assert res.status_code == 206
    assert len(res.content) == 100


def test_delete_game(ready_game):
    assert client.delete(f"/api/games/{ready_game['id']}").status_code == 200
    assert client.get(f"/api/games/{ready_game['id']}").status_code == 404
