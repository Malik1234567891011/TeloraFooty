import shutil

import pytest

import importer
import store


def test_parse_drive_folder_url():
    url = "https://drive.google.com/drive/folders/1uM7_sUErhr75zCwpgccvrJYvgEiFYF_a"
    assert importer.parse_drive_url(url) == ("folder", "1uM7_sUErhr75zCwpgccvrJYvgEiFYF_a")


def test_parse_drive_file_url():
    url = "https://drive.google.com/file/d/abc123XYZ_-/view?usp=sharing"
    assert importer.parse_drive_url(url) == ("file", "abc123XYZ_-")


def test_parse_drive_open_url():
    assert importer.parse_drive_url("https://drive.google.com/open?id=abc123") == ("file", "abc123")


def test_parse_drive_url_rejects_garbage():
    with pytest.raises(ValueError):
        importer.parse_drive_url("https://example.com/video.mp4")


def test_import_local_full_pipeline(sample_video, data_dir, tmp_path, monkeypatch):
    # Sample events that fit inside the 10s fixture
    monkeypatch.setattr(importer, "SAMPLE_EVENTS", [(2.0, "shot"), (5.0, "goal"), (999.0, "shot")])
    src = tmp_path / "upload.mp4"
    shutil.copy(sample_video, src)

    game = importer.import_local(src, "My Game")

    assert game["status"] == "ready"
    assert game["durationSec"] == pytest.approx(10.0, abs=0.5)
    events = store.load_events(game["id"])
    assert [e["type"] for e in events] == ["shot", "goal"]  # 999.0 skipped (beyond duration)
    assert all(e["source"] == "sample" for e in events)
    for e in events:
        assert (store.game_dir(game["id"]) / "thumbs" / f"{e['id']}.jpg").exists()


def test_import_local_bad_file_sets_error(data_dir, tmp_path):
    src = tmp_path / "bad.mp4"
    src.write_text("not a video")
    game = importer.import_local(src, "Broken")
    assert game["status"] == "error"
    assert game["error"]
    assert not (store.game_dir(game["id"]) / "video.mp4").exists()  # partial cleaned up


def test_list_drive_folder_not_public_message(monkeypatch):
    import gdown

    def boom(**kwargs):
        raise gdown.exceptions.DownloadError("Cannot retrieve the folder information")

    monkeypatch.setattr(gdown, "download_folder", boom)
    with pytest.raises(RuntimeError, match="anyone with the link"):
        importer.list_drive_folder("https://drive.google.com/drive/folders/abc123")


def test_import_local_missing_source_sets_error(data_dir, tmp_path):
    game = importer.import_local(tmp_path / "nonexistent.mp4", "Gone")
    assert game["status"] == "error"
    assert game["error"]
