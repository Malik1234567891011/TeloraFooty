# TeloraFooty v1 — Soccer Footage Analyzer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Local web app to review soccer footage: game library, Veo-style player with a Clips panel (shots/goals), virtual clip playback (30s before → 10s after), manual tagging, public-Drive import, and ffmpeg clip export.

**Architecture:** Python FastAPI backend (flat modules: `store`, `clipper`, `importer`, `main`) persists games/events as JSON under `data/games/<id>/` and shells out to ffmpeg/ffprobe. React+Vite+TS frontend talks to it via `/api` (Vite dev proxy). Clip mode is purely client-side seek/pause.

**Tech Stack:** Python 3.14, FastAPI, uvicorn, gdown, pytest; ffmpeg/ffprobe 8.1 (system); React 18, Vite, TypeScript, react-router-dom, Vitest + React Testing Library.

**Spec:** `docs/superpowers/specs/2026-06-05-soccer-footage-analyzer-design.md`

**Environment (verified):** `python3` 3.14.2 at `/opt/homebrew/bin/python3`, Node v24, npm 11, ffmpeg/ffprobe 8.1 on PATH. No `uv` — use `python3 -m venv`.

**Conventions:**
- Backend commands run from `backend/`; use `.venv/bin/<tool>` directly (no activation).
- Frontend commands run from `frontend/`.
- All JSON keys camelCase as in the spec (`durationSec`, `clipStart`, `clipEnd`).
- Test fixture video is *generated* by ffmpeg at test time (10s testsrc clip), not committed — avoids a binary in git. It lives at `backend/tests/fixtures/sample.mp4` (gitignored).

## File structure

```
backend/
├── requirements.txt
├── main.py            # FastAPI app + all routes
├── store.py           # JSON persistence: games, events, clip clamping
├── clipper.py         # ffmpeg/ffprobe: probe, thumbs, export, H.264 ensure
├── importer.py        # local import, Drive URL parsing/listing/download, sample seeding
└── tests/
    ├── conftest.py    # sys.path, sample video fixture, tmp data dir
    ├── test_store.py
    ├── test_clipper.py
    ├── test_importer.py
    └── test_api.py
frontend/
├── vite.config.ts     # react plugin, /api proxy, vitest config
└── src/
    ├── types.ts       # Game, GameEvent
    ├── api.ts         # typed fetch client
    ├── playback.ts    # pure helpers: filter/sort/clipEnded/startTime/fmtTime/nextEvent
    ├── App.tsx        # router: / → Library, /games/:id → Player
    ├── index.css      # dark theme styles (single stylesheet)
    ├── pages/Library.tsx
    ├── pages/Player.tsx
    ├── components/VideoPlayer.tsx   # <video>, custom controls, timeline dots
    ├── components/ClipsPanel.tsx    # toggle, tabs, event cards, + Tag
    ├── components/EventCard.tsx
    └── tests/
        ├── playback.test.ts
        └── ClipsPanel.test.tsx
data/                  # gitignored — created at runtime
```

---

### Task 1: Backend scaffold, test fixture, health route

**Files:**
- Create: `backend/requirements.txt`, `backend/main.py`, `backend/tests/conftest.py`, `backend/tests/test_api.py`
- Modify: `.gitignore`

- [ ] **Step 1: Create venv and requirements**

```bash
mkdir -p backend/tests/fixtures
cd backend && python3 -m venv .venv
```

Create `backend/requirements.txt`:

```
fastapi
uvicorn[standard]
gdown
python-multipart
pytest
httpx
```

```bash
.venv/bin/pip install -r requirements.txt
```

Expected: installs succeed (fastapi pulls starlette ≥0.40, which has Range support in FileResponse).

- [ ] **Step 2: Add gitignore entries**

Append to repo-root `.gitignore`:

```
backend/.venv/
backend/tests/fixtures/
__pycache__/
node_modules/
frontend/dist/
```

- [ ] **Step 3: Write conftest with fixtures**

`backend/tests/conftest.py`:

```python
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # import backend modules

FIXTURE = Path(__file__).parent / "fixtures" / "sample.mp4"


@pytest.fixture(scope="session")
def sample_video() -> Path:
    """10-second H.264 test video, generated once per machine."""
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    if not FIXTURE.exists():
        subprocess.run(
            ["ffmpeg", "-f", "lavfi", "-i", "testsrc=duration=10:size=320x240:rate=24",
             "-pix_fmt", "yuv420p", "-y", str(FIXTURE)],
            check=True, capture_output=True,
        )
    return FIXTURE


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Point the app's data root at a temp dir."""
    monkeypatch.setenv("TELORA_DATA_DIR", str(tmp_path))
    return tmp_path
```

- [ ] **Step 4: Write the failing health test**

`backend/tests/test_api.py`:

```python
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"ok": True}
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 6: Write minimal app**

`backend/main.py`:

```python
from fastapi import FastAPI

app = FastAPI(title="TeloraFooty")


@app.get("/api/health")
def health():
    return {"ok": True}
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_api.py -v`
Expected: PASS (1 passed)

- [ ] **Step 8: Commit**

```bash
git add .gitignore backend/requirements.txt backend/main.py backend/tests/
git commit -m "feat: backend scaffold with health route and test fixtures"
```

---

### Task 2: store.py — games/events persistence and clip clamping

**Files:**
- Create: `backend/store.py`
- Test: `backend/tests/test_store.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_store.py`:

```python
import store


def make_game(duration=100.0):
    game = store.new_game("Test Game", {"kind": "local", "url": None})
    game["durationSec"] = duration
    game["status"] = "ready"
    store.save_game(game)
    return game


def test_clamp_clip_normal():
    assert store.clamp_clip(50.0, 100.0) == (20.0, 60.0)


def test_clamp_clip_near_start():
    assert store.clamp_clip(15.0, 100.0) == (0.0, 25.0)


def test_clamp_clip_near_end():
    assert store.clamp_clip(95.0, 100.0) == (65.0, 100.0)


def test_new_game_persists(data_dir):
    game = make_game()
    loaded = store.load_game(game["id"])
    assert loaded["title"] == "Test Game"
    assert loaded["status"] == "ready"
    assert store.list_games()[0]["id"] == game["id"]


def test_create_event_computes_clip_bounds(data_dir):
    game = make_game(duration=100.0)
    ev = store.create_event(game["id"], "goal", 50.0)
    assert ev["clipStart"] == 20.0
    assert ev["clipEnd"] == 60.0
    assert ev["source"] == "manual"
    assert store.load_events(game["id"]) == [ev]


def test_events_sorted_by_timestamp(data_dir):
    game = make_game()
    store.create_event(game["id"], "shot", 80.0)
    store.create_event(game["id"], "goal", 10.0)
    times = [e["timestamp"] for e in store.load_events(game["id"])]
    assert times == [10.0, 80.0]


def test_update_event_recomputes_bounds(data_dir):
    game = make_game()
    ev = store.create_event(game["id"], "shot", 50.0)
    updated = store.update_event(game["id"], ev["id"], {"type": "goal", "timestamp": 95.0})
    assert updated["type"] == "goal"
    assert updated["clipEnd"] == 100.0


def test_delete_event(data_dir):
    game = make_game()
    ev = store.create_event(game["id"], "shot", 50.0)
    assert store.delete_event(game["id"], ev["id"]) is True
    assert store.load_events(game["id"]) == []
    assert store.delete_event(game["id"], "evt_nope") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'store'`

- [ ] **Step 3: Implement store.py**

`backend/store.py`:

```python
import json
import os
import uuid
from datetime import date
from pathlib import Path

CLIP_BEFORE = 30.0
CLIP_AFTER = 10.0


def games_root() -> Path:
    base = os.environ.get("TELORA_DATA_DIR")
    root = Path(base) if base else Path(__file__).resolve().parent.parent / "data"
    p = root / "games"
    p.mkdir(parents=True, exist_ok=True)
    return p


def game_dir(game_id: str) -> Path:
    return games_root() / game_id


def save_game(game: dict) -> None:
    d = game_dir(game["id"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "game.json").write_text(json.dumps(game, indent=2))


def load_game(game_id: str) -> dict | None:
    f = game_dir(game_id) / "game.json"
    return json.loads(f.read_text()) if f.exists() else None


def list_games() -> list[dict]:
    games = [json.loads(f.read_text()) for f in games_root().glob("*/game.json")]
    return sorted(games, key=lambda g: g.get("date", ""), reverse=True)


def new_game(title: str, source: dict) -> dict:
    game = {
        "id": f"game_{uuid.uuid4().hex[:8]}",
        "title": title,
        "date": date.today().isoformat(),
        "durationSec": 0.0,
        "source": source,
        "status": "downloading",
        "error": None,
    }
    save_game(game)
    return game


def load_events(game_id: str) -> list[dict]:
    f = game_dir(game_id) / "events.json"
    if not f.exists():
        return []
    return json.loads(f.read_text())["events"]


def save_events(game_id: str, events: list[dict]) -> None:
    events = sorted(events, key=lambda e: e["timestamp"])
    (game_dir(game_id) / "events.json").write_text(
        json.dumps({"events": events}, indent=2)
    )


def clamp_clip(timestamp: float, duration: float) -> tuple[float, float]:
    return max(0.0, timestamp - CLIP_BEFORE), min(duration, timestamp + CLIP_AFTER)


def create_event(game_id: str, etype: str, timestamp: float, source: str = "manual") -> dict:
    game = load_game(game_id)
    start, end = clamp_clip(timestamp, game["durationSec"])
    event = {
        "id": f"evt_{uuid.uuid4().hex[:8]}",
        "type": etype,
        "timestamp": timestamp,
        "source": source,
        "clipStart": start,
        "clipEnd": end,
    }
    events = load_events(game_id)
    events.append(event)
    save_events(game_id, events)
    return event


def update_event(game_id: str, event_id: str, changes: dict) -> dict | None:
    game = load_game(game_id)
    events = load_events(game_id)
    for e in events:
        if e["id"] == event_id:
            e.update({k: changes[k] for k in ("type", "timestamp") if k in changes})
            e["clipStart"], e["clipEnd"] = clamp_clip(e["timestamp"], game["durationSec"])
            save_events(game_id, events)
            return e
    return None


def delete_event(game_id: str, event_id: str) -> bool:
    events = load_events(game_id)
    kept = [e for e in events if e["id"] != event_id]
    if len(kept) == len(events):
        return False
    save_events(game_id, kept)
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_store.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/store.py backend/tests/test_store.py
git commit -m "feat: JSON store for games/events with clip clamping"
```

---

### Task 3: clipper.py — ffmpeg probe, thumbnails, export, H.264 ensure

**Files:**
- Create: `backend/clipper.py`
- Test: `backend/tests/test_clipper.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_clipper.py`:

```python
import pytest

import clipper


def test_probe_duration(sample_video):
    assert clipper.probe_duration(sample_video) == pytest.approx(10.0, abs=0.5)


def test_video_codec(sample_video):
    assert clipper.video_codec(sample_video) == "h264"


def test_extract_thumb(sample_video, tmp_path):
    out = tmp_path / "thumbs" / "evt_x.jpg"
    clipper.extract_thumb(sample_video, 3.0, out)
    assert out.exists() and out.stat().st_size > 0


def test_export_clip(sample_video, tmp_path):
    out = tmp_path / "clip.mp4"
    clipper.export_clip(sample_video, 2.0, 5.0, out)
    assert clipper.probe_duration(out) == pytest.approx(3.0, abs=0.6)


def test_export_clip_failure_cleans_up(tmp_path):
    out = tmp_path / "clip.mp4"
    with pytest.raises(RuntimeError):
        clipper.export_clip(tmp_path / "missing.mp4", 0.0, 1.0, out)
    assert not out.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/test_clipper.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'clipper'`

- [ ] **Step 3: Implement clipper.py**

`backend/clipper.py`:

```python
import subprocess
from pathlib import Path


def _run(args: list[str]) -> str:
    res = subprocess.run(args, capture_output=True, text=True)
    if res.returncode != 0:
        tail = res.stderr.strip().splitlines()[-1] if res.stderr.strip() else "ffmpeg failed"
        raise RuntimeError(tail)
    return res.stdout


def probe_duration(video: Path) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "csv=p=0", str(video)])
    return float(out.strip())


def video_codec(video: Path) -> str:
    out = _run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(video)])
    return out.strip()


def extract_thumb(video: Path, timestamp: float, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-ss", str(timestamp), "-i", str(video),
          "-frames:v", "1", "-vf", "scale=320:-2", "-y", str(out)])


def export_clip(video: Path, start: float, end: float, out: Path) -> None:
    """Stream-copy cut: fast, no re-encode."""
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run(["ffmpeg", "-ss", str(start), "-i", str(video),
              "-t", str(end - start), "-c", "copy", "-y", str(out)])
    except RuntimeError:
        out.unlink(missing_ok=True)
        raise


def ensure_h264(video: Path) -> None:
    """Re-encode in place if the codec isn't browser-playable (spec: HEVC handling)."""
    if video_codec(video) == "h264":
        return
    tmp = video.with_suffix(".h264.mp4")
    _run(["ffmpeg", "-i", str(video), "-c:v", "libx264", "-preset", "fast",
          "-c:a", "aac", "-movflags", "+faststart", "-y", str(tmp)])
    tmp.replace(video)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_clipper.py -v`
Expected: PASS (5 passed). First run generates the fixture video (a second or two).

- [ ] **Step 5: Commit**

```bash
git add backend/clipper.py backend/tests/test_clipper.py
git commit -m "feat: ffmpeg wrapper for probe, thumbs, clip export, h264 ensure"
```

---

### Task 4: importer.py — Drive URL parsing, local import pipeline, sample seeding

**Files:**
- Create: `backend/importer.py`
- Test: `backend/tests/test_importer.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_importer.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/test_importer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'importer'`

- [ ] **Step 3: Implement importer.py**

`backend/importer.py`:

```python
import re
import shutil
import threading
from pathlib import Path

import gdown

import clipper
import store

# Hardcoded sample events seeded into every imported game: (seconds, type).
# Timestamps beyond the video duration are skipped.
SAMPLE_EVENTS = [
    (310.0, "shot"),
    (760.0, "shot"),
    (1180.0, "goal"),
    (2120.0, "shot"),
    (2750.0, "goal"),
]

VIDEO_EXTS = {".mp4", ".mov", ".mkv"}

_FOLDER_RE = re.compile(r"drive\.google\.com/drive/(?:u/\d+/)?folders/([\w-]+)")
_FILE_RE = re.compile(r"drive\.google\.com/file/d/([\w-]+)")
_OPEN_RE = re.compile(r"drive\.google\.com/open\?id=([\w-]+)")

NOT_PUBLIC_MSG = ("Download failed — make sure the link is shared as "
                  "'anyone with the link'")


def parse_drive_url(url: str) -> tuple[str, str]:
    """Return ("folder" | "file", drive_id). Raises ValueError if unrecognizable."""
    if m := _FOLDER_RE.search(url):
        return "folder", m.group(1)
    if m := (_FILE_RE.search(url) or _OPEN_RE.search(url)):
        return "file", m.group(1)
    raise ValueError("Not a recognizable Google Drive link")


def list_drive_folder(url: str) -> list[dict]:
    """List video files in a public Drive folder without downloading."""
    kind, drive_id = parse_drive_url(url)
    if kind != "folder":
        raise ValueError("Not a folder link")
    files = gdown.download_folder(id=drive_id, skip_download=True, quiet=True)
    if files is None:
        raise RuntimeError(NOT_PUBLIC_MSG)
    return [
        {"id": f.id, "name": Path(f.path).name}
        for f in files
        if Path(f.path).suffix.lower() in VIDEO_EXTS
    ]


def finalize_game(game_id: str) -> None:
    """Validate/convert video, set duration, seed sample events, build thumbnails."""
    game = store.load_game(game_id)
    game["status"] = "processing"
    store.save_game(game)
    video = store.game_dir(game_id) / "video.mp4"
    clipper.ensure_h264(video)
    duration = clipper.probe_duration(video)
    game["durationSec"] = duration
    store.save_game(game)
    for ts, etype in SAMPLE_EVENTS:
        if ts < duration:
            store.create_event(game_id, etype, ts, source="sample")
    for event in store.load_events(game_id):
        clipper.extract_thumb(
            video, event["timestamp"],
            store.game_dir(game_id) / "thumbs" / f"{event['id']}.jpg",
        )
    game["status"] = "ready"
    store.save_game(game)


def _fail(game_id: str, message: str) -> None:
    game = store.load_game(game_id)
    game["status"] = "error"
    game["error"] = message
    store.save_game(game)
    (store.game_dir(game_id) / "video.mp4").unlink(missing_ok=True)


def import_local(src: Path, title: str) -> dict:
    """Synchronous local import: move file into library, then finalize."""
    game = store.new_game(title, {"kind": "local", "url": None})
    dest = store.game_dir(game["id"]) / "video.mp4"
    shutil.move(str(src), dest)
    try:
        finalize_game(game["id"])
    except Exception as exc:
        _fail(game["id"], str(exc))
    return store.load_game(game["id"])


def _import_drive_file(url: str, drive_id: str, name: str) -> dict:
    """Create the game, download + finalize in a background thread."""
    game = store.new_game(Path(name).stem, {"kind": "drive", "url": url})

    def work() -> None:
        try:
            dest = store.game_dir(game["id"]) / "video.mp4"
            out = gdown.download(id=drive_id, output=str(dest), quiet=True)
            if out is None:
                raise RuntimeError(NOT_PUBLIC_MSG)
            finalize_game(game["id"])
        except Exception as exc:
            _fail(game["id"], str(exc))

    threading.Thread(target=work, daemon=True).start()
    return game


def import_drive(url: str, file_ids: list[str] | None = None) -> list[dict]:
    """Import a Drive file link, or chosen videos from a folder link."""
    kind, drive_id = parse_drive_url(url)
    if kind == "file":
        return [_import_drive_file(url, drive_id, "Drive video")]
    files = list_drive_folder(url)
    if file_ids:
        files = [f for f in files if f["id"] in file_ids]
    return [_import_drive_file(url, f["id"], f["name"]) for f in files]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_importer.py -v`
Expected: PASS (6 passed). Note `list_drive_folder`/`import_drive` network paths are not unit-tested (require live Drive) — covered by the final smoke test.

- [ ] **Step 5: Commit**

```bash
git add backend/importer.py backend/tests/test_importer.py
git commit -m "feat: importer with Drive URL parsing, local pipeline, sample seeding"
```

---

### Task 5: API — games, import routes, video streaming

**Files:**
- Modify: `backend/main.py` (replace entire file)
- Test: `backend/tests/test_api.py` (extend)

- [ ] **Step 1: Add failing API tests**

Replace `backend/tests/test_api.py` with:

```python
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
```

- [ ] **Step 2: Run tests to verify new ones fail**

Run: `cd backend && .venv/bin/pytest tests/test_api.py -v`
Expected: `test_health` PASSES; all others FAIL with 404 (routes don't exist).

- [ ] **Step 3: Implement the routes**

Replace `backend/main.py` with:

```python
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import importer
import store

app = FastAPI(title="TeloraFooty")


class DriveRequest(BaseModel):
    url: str
    fileIds: list[str] | None = None


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/games")
def list_games():
    games = store.list_games()
    for g in games:  # counts shown on library cards
        events = store.load_events(g["id"])
        g["goals"] = sum(1 for e in events if e["type"] == "goal")
        g["shots"] = sum(1 for e in events if e["type"] == "shot")
    return games


@app.get("/api/games/{game_id}")
def get_game(game_id: str):
    game = store.load_game(game_id)
    if game is None:
        raise HTTPException(404, "Game not found")
    return game


@app.delete("/api/games/{game_id}")
def delete_game(game_id: str):
    d = store.game_dir(game_id)
    if not d.exists():
        raise HTTPException(404, "Game not found")
    shutil.rmtree(d)
    return {"ok": True}


@app.post("/api/games/import")
async def import_file(file: UploadFile):
    name = Path(file.filename or "video.mp4")
    if name.suffix.lower() not in importer.VIDEO_EXTS:
        raise HTTPException(400, f"Unsupported file type: {name.suffix}")
    tmp = store.games_root() / f"upload_{name.name}"
    with tmp.open("wb") as out:
        while chunk := await file.read(1 << 20):
            out.write(chunk)
    return importer.import_local(tmp, name.stem)


@app.post("/api/drive/list")
def drive_list(body: DriveRequest):
    try:
        return importer.list_drive_folder(body.url)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/games/import-drive")
def import_drive(body: DriveRequest):
    try:
        return importer.import_drive(body.url, body.fileIds)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/games/{game_id}/video")
def stream_video(game_id: str):
    video = store.game_dir(game_id) / "video.mp4"
    if not video.exists():
        raise HTTPException(404, "Video not found")
    # Starlette FileResponse handles HTTP Range requests (seeking).
    return FileResponse(video, media_type="video/mp4")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_api.py -v`
Expected: PASS (7 passed). If `test_video_streaming_supports_range` returns 200 instead of 206, the installed starlette is too old — run `.venv/bin/pip install "starlette>=0.37"` and re-run.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_api.py
git commit -m "feat: games API with import routes and range-capable video streaming"
```

---

### Task 6: API — events CRUD, thumbnails, clip export

**Files:**
- Modify: `backend/main.py` (append routes)
- Test: `backend/tests/test_api.py` (extend)

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_api.py`:

```python
def test_list_events(ready_game):
    events = client.get(f"/api/games/{ready_game['id']}/events").json()
    assert [e["type"] for e in events] == ["shot", "goal"]


def test_create_event_tag(ready_game):
    res = client.post(f"/api/games/{ready_game['id']}/events",
                      json={"type": "goal", "timestamp": 7.0})
    assert res.status_code == 200
    ev = res.json()
    assert ev["clipStart"] == 0.0          # 7 - 30 clamped
    assert ev["clipEnd"] == pytest.approx(10.0, abs=0.5)  # 7 + 10 clamped to duration
    assert ev["source"] == "manual"
    thumb = store.game_dir(ready_game["id"]) / "thumbs" / f"{ev['id']}.jpg"
    assert thumb.exists()


def test_create_event_rejects_bad_type(ready_game):
    res = client.post(f"/api/games/{ready_game['id']}/events",
                      json={"type": "corner", "timestamp": 3.0})
    assert res.status_code == 422


def test_patch_event(ready_game):
    ev = client.get(f"/api/games/{ready_game['id']}/events").json()[0]
    res = client.patch(f"/api/games/{ready_game['id']}/events/{ev['id']}",
                       json={"type": "goal", "timestamp": 6.0})
    assert res.status_code == 200
    assert res.json()["type"] == "goal"
    assert res.json()["timestamp"] == 6.0


def test_delete_event_api(ready_game):
    ev = client.get(f"/api/games/{ready_game['id']}/events").json()[0]
    assert client.delete(f"/api/games/{ready_game['id']}/events/{ev['id']}").status_code == 200
    remaining = client.get(f"/api/games/{ready_game['id']}/events").json()
    assert ev["id"] not in [e["id"] for e in remaining]


def test_event_thumbnail(ready_game):
    ev = client.get(f"/api/games/{ready_game['id']}/events").json()[0]
    res = client.get(f"/api/games/{ready_game['id']}/events/{ev['id']}/thumb.jpg")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"


def test_export_clip_endpoint(ready_game):
    ev = client.get(f"/api/games/{ready_game['id']}/events").json()[0]
    res = client.post(f"/api/games/{ready_game['id']}/events/{ev['id']}/export")
    assert res.status_code == 200
    assert res.headers["content-type"] == "video/mp4"
    assert "attachment" in res.headers["content-disposition"]
    assert len(res.content) > 0
```

- [ ] **Step 2: Run tests to verify new ones fail**

Run: `cd backend && .venv/bin/pytest tests/test_api.py -v`
Expected: previous 7 PASS; the 7 new ones FAIL (404s / wrong status codes).

- [ ] **Step 3: Implement event routes**

Append to `backend/main.py` (also add `from typing import Literal` and `import clipper` to the imports at the top):

```python
class EventCreate(BaseModel):
    type: Literal["shot", "goal"]
    timestamp: float


class EventPatch(BaseModel):
    type: Literal["shot", "goal"] | None = None
    timestamp: float | None = None


def _require_game(game_id: str) -> dict:
    game = store.load_game(game_id)
    if game is None:
        raise HTTPException(404, "Game not found")
    return game


def _thumb_path(game_id: str, event_id: str) -> Path:
    return store.game_dir(game_id) / "thumbs" / f"{event_id}.jpg"


@app.get("/api/games/{game_id}/events")
def list_events(game_id: str):
    _require_game(game_id)
    return store.load_events(game_id)


@app.post("/api/games/{game_id}/events")
def create_event(game_id: str, body: EventCreate):
    _require_game(game_id)
    event = store.create_event(game_id, body.type, body.timestamp)
    video = store.game_dir(game_id) / "video.mp4"
    clipper.extract_thumb(video, event["timestamp"], _thumb_path(game_id, event["id"]))
    return event


@app.patch("/api/games/{game_id}/events/{event_id}")
def patch_event(game_id: str, event_id: str, body: EventPatch):
    _require_game(game_id)
    changes = body.model_dump(exclude_none=True)
    event = store.update_event(game_id, event_id, changes)
    if event is None:
        raise HTTPException(404, "Event not found")
    if "timestamp" in changes:
        video = store.game_dir(game_id) / "video.mp4"
        clipper.extract_thumb(video, event["timestamp"], _thumb_path(game_id, event_id))
    return event


@app.delete("/api/games/{game_id}/events/{event_id}")
def delete_event(game_id: str, event_id: str):
    _require_game(game_id)
    if not store.delete_event(game_id, event_id):
        raise HTTPException(404, "Event not found")
    _thumb_path(game_id, event_id).unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/games/{game_id}/events/{event_id}/thumb.jpg")
def event_thumb(game_id: str, event_id: str):
    thumb = _thumb_path(game_id, event_id)
    if not thumb.exists():
        raise HTTPException(404, "Thumbnail not found")
    return FileResponse(thumb, media_type="image/jpeg")


@app.post("/api/games/{game_id}/events/{event_id}/export")
def export_event(game_id: str, event_id: str):
    game = _require_game(game_id)
    event = next((e for e in store.load_events(game_id) if e["id"] == event_id), None)
    if event is None:
        raise HTTPException(404, "Event not found")
    video = store.game_dir(game_id) / "video.mp4"
    ts = event["timestamp"]
    stamp = f"{int(ts // 60):02d}{int(ts % 60):02d}"
    filename = f"{game['title'].replace(' ', '_')}_{event['type']}_{stamp}.mp4"
    out = store.game_dir(game_id) / "exports" / filename
    try:
        clipper.export_clip(video, event["clipStart"], event["clipEnd"], out)
    except RuntimeError as exc:
        raise HTTPException(500, f"Export failed: {exc}")
    return FileResponse(out, media_type="video/mp4", filename=filename)
```

- [ ] **Step 4: Run the full backend suite**

Run: `cd backend && .venv/bin/pytest -v`
Expected: PASS (all tests — store 8, clipper 5, importer 6, api 14)

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_api.py
git commit -m "feat: events CRUD, thumbnails, and clip export endpoints"
```

---

### Task 7: Frontend scaffold — Vite, proxy, types, API client, playback utils

**Files:**
- Create: `frontend/` (Vite scaffold), `frontend/src/types.ts`, `frontend/src/api.ts`, `frontend/src/playback.ts`, `frontend/src/test-setup.ts`, placeholder `frontend/src/pages/Library.tsx`, `frontend/src/pages/Player.tsx`
- Modify: `frontend/vite.config.ts`, `frontend/src/App.tsx`, `frontend/package.json`
- Test: `frontend/src/tests/playback.test.ts`

- [ ] **Step 1: Scaffold and install**

```bash
cd /Users/omarlahmimi/Documents/TeloraFooty
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install
npm install react-router-dom
npm install -D vitest jsdom @testing-library/react @testing-library/jest-dom
npm pkg set scripts.test="vitest run"
rm src/App.css src/assets/react.svg public/vite.svg
```

- [ ] **Step 2: Configure Vite (proxy + vitest)**

Replace `frontend/vite.config.ts`:

```ts
/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  test: { environment: 'jsdom', setupFiles: './src/test-setup.ts' },
})
```

Create `frontend/src/test-setup.ts`:

```ts
import '@testing-library/jest-dom'
```

- [ ] **Step 3: Write types and API client**

`frontend/src/types.ts`:

```ts
export type EventType = 'shot' | 'goal'

export interface GameEvent {
  id: string
  type: EventType
  timestamp: number
  source: 'manual' | 'sample' | 'ai'
  clipStart: number
  clipEnd: number
}

export interface Game {
  id: string
  title: string
  date: string
  durationSec: number
  source: { kind: 'local' | 'drive'; url: string | null }
  status: 'downloading' | 'processing' | 'ready' | 'error'
  error: string | null
  goals?: number // present on GET /api/games
  shots?: number
}

export interface DriveFile {
  id: string
  name: string
}
```

`frontend/src/api.ts`:

```ts
import type { DriveFile, EventType, Game, GameEvent } from './types'

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail ?? `Request failed (${res.status})`)
  }
  return res.json()
}

const post = (url: string, body: unknown) =>
  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

export const api = {
  listGames: () => fetch('/api/games').then((r) => asJson<Game[]>(r)),
  getGame: (id: string) => fetch(`/api/games/${id}`).then((r) => asJson<Game>(r)),
  deleteGame: (id: string) =>
    fetch(`/api/games/${id}`, { method: 'DELETE' }).then((r) => asJson<{ ok: boolean }>(r)),
  importFile: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch('/api/games/import', { method: 'POST', body: form }).then((r) => asJson<Game>(r))
  },
  listDriveFolder: (url: string) => post('/api/drive/list', { url }).then((r) => asJson<DriveFile[]>(r)),
  importDrive: (url: string, fileIds?: string[]) =>
    post('/api/games/import-drive', { url, fileIds }).then((r) => asJson<Game[]>(r)),
  listEvents: (gameId: string) =>
    fetch(`/api/games/${gameId}/events`).then((r) => asJson<GameEvent[]>(r)),
  createEvent: (gameId: string, type: EventType, timestamp: number) =>
    post(`/api/games/${gameId}/events`, { type, timestamp }).then((r) => asJson<GameEvent>(r)),
  patchEvent: (gameId: string, eventId: string, changes: { type?: EventType; timestamp?: number }) =>
    fetch(`/api/games/${gameId}/events/${eventId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(changes),
    }).then((r) => asJson<GameEvent>(r)),
  deleteEvent: (gameId: string, eventId: string) =>
    fetch(`/api/games/${gameId}/events/${eventId}`, { method: 'DELETE' }).then((r) =>
      asJson<{ ok: boolean }>(r),
    ),
  exportClip: async (gameId: string, eventId: string): Promise<Blob> => {
    const res = await fetch(`/api/games/${gameId}/events/${eventId}/export`, { method: 'POST' })
    if (!res.ok) throw new Error('Export failed')
    return res.blob()
  },
  videoUrl: (gameId: string) => `/api/games/${gameId}/video`,
  thumbUrl: (gameId: string, eventId: string) => `/api/games/${gameId}/events/${eventId}/thumb.jpg`,
}
```

- [ ] **Step 4: Write failing playback util tests**

`frontend/src/tests/playback.test.ts`:

```ts
import { describe, expect, test } from 'vitest'
import { clipEnded, filterEvents, fmtTime, nextEvent, sortEvents, startTime } from '../playback'
import type { GameEvent } from '../types'

const ev = (id: string, type: 'shot' | 'goal', timestamp: number): GameEvent => ({
  id,
  type,
  timestamp,
  source: 'manual',
  clipStart: Math.max(0, timestamp - 30),
  clipEnd: timestamp + 10,
})

const events = [ev('e2', 'goal', 200), ev('e1', 'shot', 100), ev('e3', 'shot', 300)]

describe('filterEvents', () => {
  test('all returns everything', () => expect(filterEvents(events, 'all')).toHaveLength(3))
  test('goals filters to goal type', () =>
    expect(filterEvents(events, 'goals').map((e) => e.id)).toEqual(['e2']))
  test('shots filters to shot type', () =>
    expect(filterEvents(events, 'shots').map((e) => e.id)).toEqual(['e1', 'e3']))
})

test('sortEvents orders by timestamp without mutating', () => {
  expect(sortEvents(events).map((e) => e.id)).toEqual(['e1', 'e2', 'e3'])
  expect(events[0].id).toBe('e2')
})

describe('clipEnded', () => {
  const e = ev('x', 'goal', 100) // clip 70 → 110
  test('true at/after clipEnd in clip mode', () => {
    expect(clipEnded(110, 'clip', e)).toBe(true)
    expect(clipEnded(115, 'clip', e)).toBe(true)
  })
  test('false before clipEnd', () => expect(clipEnded(109.5, 'clip', e)).toBe(false))
  test('false in full mode or with no selection', () => {
    expect(clipEnded(115, 'full', e)).toBe(false)
    expect(clipEnded(115, 'clip', null)).toBe(false)
  })
})

test('startTime: clipStart in clip mode, timestamp in full mode', () => {
  const e = ev('x', 'shot', 100)
  expect(startTime('clip', e)).toBe(70)
  expect(startTime('full', e)).toBe(100)
})

describe('nextEvent', () => {
  test('finds next after current time', () => expect(nextEvent(events, 150, 1)?.id).toBe('e2'))
  test('finds previous before current time', () => expect(nextEvent(events, 150, -1)?.id).toBe('e1'))
  test('null at the edges', () => {
    expect(nextEvent(events, 300, 1)).toBeNull()
    expect(nextEvent(events, 100, -1)).toBeNull()
  })
})

test('fmtTime formats m:ss', () => {
  expect(fmtTime(0)).toBe('0:00')
  expect(fmtTime(65)).toBe('1:05')
  expect(fmtTime(3380)).toBe('56:20')
})
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `cd frontend && npm test`
Expected: FAIL — cannot resolve `../playback`

- [ ] **Step 6: Implement playback.ts**

`frontend/src/playback.ts`:

```ts
import type { EventType, GameEvent } from './types'

export type Mode = 'clip' | 'full'
export type FilterTab = 'all' | 'goals' | 'shots'

export function filterEvents(events: GameEvent[], tab: FilterTab): GameEvent[] {
  if (tab === 'all') return events
  const type: EventType = tab === 'goals' ? 'goal' : 'shot'
  return events.filter((e) => e.type === type)
}

export function sortEvents(events: GameEvent[]): GameEvent[] {
  return [...events].sort((a, b) => a.timestamp - b.timestamp)
}

/** True when clip-mode playback has reached the end of the selected event's window. */
export function clipEnded(time: number, mode: Mode, selected: GameEvent | null): boolean {
  return mode === 'clip' && selected !== null && time >= selected.clipEnd
}

/** Where to seek when an event is selected. */
export function startTime(mode: Mode, event: GameEvent): number {
  return mode === 'clip' ? event.clipStart : event.timestamp
}

/** Next (dir=1) or previous (dir=-1) event relative to the current time. */
export function nextEvent(events: GameEvent[], currentTime: number, dir: 1 | -1): GameEvent | null {
  const sorted = sortEvents(events)
  if (dir === 1) return sorted.find((e) => e.timestamp > currentTime + 0.5) ?? null
  return [...sorted].reverse().find((e) => e.timestamp < currentTime - 0.5) ?? null
}

export function fmtTime(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd frontend && npm test`
Expected: PASS (12 passed)

- [ ] **Step 8: Router + placeholder pages**

Replace `frontend/src/App.tsx`:

```tsx
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Library from './pages/Library'
import Player from './pages/Player'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Library />} />
        <Route path="/games/:id" element={<Player />} />
      </Routes>
    </BrowserRouter>
  )
}
```

Create `frontend/src/pages/Library.tsx` (placeholder, replaced in Task 8):

```tsx
export default function Library() {
  return <div className="page">Library</div>
}
```

Create `frontend/src/pages/Player.tsx` (placeholder, replaced in Task 9):

```tsx
export default function Player() {
  return <div className="page">Player</div>
}
```

- [ ] **Step 9: Verify build and dev server**

```bash
cd frontend && npm run build
```

Expected: tsc + vite build succeed.

```bash
npm run dev &
sleep 2 && curl -s http://localhost:5173 | head -5
kill %1
```

Expected: HTML containing the Vite/React root div.

- [ ] **Step 10: Commit**

```bash
git add frontend
git commit -m "feat: frontend scaffold with router, API client, tested playback utils"
```

---

### Task 8: Dark theme stylesheet + Library page

**Files:**
- Modify: `frontend/src/index.css` (replace), `frontend/src/pages/Library.tsx` (replace placeholder)

- [ ] **Step 1: Write the stylesheet (used by all later tasks)**

Replace `frontend/src/index.css`:

```css
:root {
  --bg: #0d1117;
  --panel: #161b22;
  --line: #30363d;
  --text: #e6edf3;
  --muted: #8b949e;
  --blue: #1f6feb;
  --green: #3fb950;
  --amber: #d29922;
  --red: #f85149;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, system-ui, sans-serif;
}

button { font: inherit; cursor: pointer; }
a { color: inherit; text-decoration: none; }

.page { max-width: 1280px; margin: 0 auto; padding: 16px; }

.topbar {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  background: var(--panel); border-radius: 8px; padding: 10px 16px; margin-bottom: 14px;
}
.topbar .title { font-weight: 700; }
.topbar .sub { color: var(--muted); font-size: 13px; }

.btn {
  background: var(--panel); color: var(--text); border: 1px solid var(--line);
  border-radius: 6px; padding: 6px 14px;
}
.btn:hover { border-color: var(--muted); }
.btn-primary { background: var(--blue); border-color: var(--blue); color: #fff; }
.btn-danger { color: var(--red); }

.error-banner {
  background: rgba(248, 81, 73, 0.15); border: 1px solid var(--red);
  border-radius: 6px; padding: 8px 12px; margin-bottom: 12px; color: var(--red);
}

/* Library */
.library-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px;
}
.game-card {
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  overflow: hidden; position: relative;
}
.game-card:hover { border-color: var(--muted); }
.game-card .thumb {
  height: 150px; background: #000; display: flex;
  align-items: center; justify-content: center; color: var(--muted);
}
.game-card .thumb video { width: 100%; height: 100%; object-fit: cover; }
.game-card .info { padding: 10px 12px; }
.game-card .info .meta { color: var(--muted); font-size: 12px; margin-top: 4px; }
.game-card .delete {
  position: absolute; top: 8px; right: 8px; background: rgba(0,0,0,0.6);
  border: none; color: var(--text); border-radius: 4px; padding: 2px 8px;
}
.status-error { color: var(--red); font-size: 13px; padding: 0 12px; text-align: center; }

/* Modal (Drive folder picker) */
.modal-backdrop {
  position: fixed; inset: 0; background: rgba(0,0,0,0.6);
  display: flex; align-items: center; justify-content: center; z-index: 10;
}
.modal {
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 18px; width: 420px; max-height: 70vh; overflow-y: auto;
}
.modal h3 { margin-top: 0; }
.modal label { display: block; padding: 6px 0; }
.modal .actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 14px; }

/* Player */
.player-layout { display: flex; gap: 12px; align-items: flex-start; }
.video-col { flex: 2.7; min-width: 0; }
.video-wrap { background: #000; border-radius: 8px; position: relative; overflow: hidden; }
.video-wrap video { width: 100%; display: block; }
.mode-badge {
  position: absolute; top: 10px; left: 10px; background: rgba(31, 111, 235, 0.9);
  color: #fff; border-radius: 4px; padding: 2px 10px; font-size: 12px;
}

.controls {
  display: flex; align-items: center; gap: 10px;
  background: var(--panel); border-radius: 8px; padding: 8px 14px; margin-top: 8px;
}
.controls button { background: none; border: none; color: var(--text); font-size: 16px; padding: 2px 6px; }
.controls button:hover { color: var(--blue); }
.controls .time { color: var(--muted); font-size: 13px; margin-left: auto; }
.controls select {
  background: var(--bg); color: var(--text); border: 1px solid var(--line); border-radius: 4px;
}

.timeline { position: relative; height: 18px; flex: 1; display: flex; align-items: center; cursor: pointer; }
.timeline .track { position: relative; height: 5px; width: 100%; background: var(--line); border-radius: 3px; }
.timeline .fill { position: absolute; left: 0; top: 0; height: 5px; background: var(--blue); border-radius: 3px; }
.timeline .dot {
  position: absolute; top: -3px; width: 11px; height: 11px; border-radius: 50%;
  background: #fff; border: 1px solid var(--bg); transform: translateX(-50%); cursor: pointer;
}
.timeline .dot.goal { background: var(--green); }
.timeline .dot.selected { outline: 2px solid var(--blue); }

/* Clips panel */
.clips-panel {
  flex: 1.15; background: var(--panel); border-radius: 8px; padding: 12px;
  max-height: calc(100vh - 120px); overflow-y: auto; min-width: 300px;
}
.clips-panel .head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.clips-panel .head h3 { margin: 0; font-size: 15px; }

.toggle { display: flex; background: var(--bg); border-radius: 6px; padding: 2px; font-size: 12px; }
.toggle button { border: none; background: none; color: var(--muted); border-radius: 5px; padding: 3px 10px; }
.toggle button.active { background: var(--blue); color: #fff; }

.tabs { display: flex; gap: 6px; align-items: center; margin-bottom: 10px; }
.tab {
  background: none; border: 1px solid var(--line); color: var(--text);
  border-radius: 12px; padding: 2px 12px; font-size: 12px;
}
.tab.active { background: var(--text); color: var(--bg); border-color: var(--text); font-weight: 600; }
.tabs .tag-btn { margin-left: auto; }

.event-card {
  display: flex; gap: 10px; align-items: center; border: 1px solid transparent;
  border-radius: 8px; padding: 6px; margin-bottom: 6px; cursor: pointer; position: relative;
}
.event-card:hover { background: var(--bg); }
.event-card.selected { background: var(--bg); border-color: var(--blue); }
.event-card .ethumb { width: 86px; height: 50px; border-radius: 5px; object-fit: cover; background: #000; position: relative; flex-shrink: 0; }
.event-card .tbadge {
  position: absolute; bottom: 4px; left: 4px; background: rgba(0,0,0,0.75); color: #fff;
  border-radius: 3px; padding: 0 4px; font-size: 11px;
}
.event-card .ttl { font-weight: 700; font-size: 13px; }
.event-card .ttl.goal { color: var(--green); }
.event-card .ttl.shot { color: var(--amber); }
.event-card .src { color: var(--muted); font-size: 11px; margin-top: 2px; }
.event-card .actions { margin-left: auto; display: flex; gap: 4px; }
.event-card .actions button { background: none; border: none; color: var(--muted); font-size: 14px; }
.event-card .actions button:hover { color: var(--text); }

.menu {
  position: absolute; right: 6px; top: 36px; background: var(--bg); border: 1px solid var(--line);
  border-radius: 6px; z-index: 5; min-width: 160px;
}
.menu button { display: block; width: 100%; text-align: left; background: none; border: none; color: var(--text); padding: 8px 12px; font-size: 13px; }
.menu button:hover { background: var(--panel); }

.tag-menu { position: relative; }
.tag-menu .menu { top: 28px; }
```

- [ ] **Step 2: Implement the Library page**

Replace `frontend/src/pages/Library.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { DriveFile, Game } from '../types'

export default function Library() {
  const [games, setGames] = useState<Game[]>([])
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [drivePick, setDrivePick] = useState<{ url: string; files: DriveFile[] } | null>(null)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const fileInput = useRef<HTMLInputElement>(null)

  const refresh = () => api.listGames().then(setGames).catch((e: Error) => setError(e.message))

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 2000) // poll while downloads/processing run
    return () => clearInterval(t)
  }, [])

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      await api.importFile(file)
      await refresh()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  async function onDrive() {
    const url = window.prompt('Paste a public Google Drive file or folder link:')
    if (!url) return
    setError(null)
    try {
      if (url.includes('/folders/')) {
        const files = await api.listDriveFolder(url)
        if (files.length === 0) {
          setError('No videos found in that folder')
          return
        }
        setChecked(new Set(files.map((f) => f.id)))
        setDrivePick({ url, files })
      } else {
        await api.importDrive(url)
        await refresh()
      }
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function confirmDrivePick() {
    if (!drivePick) return
    try {
      await api.importDrive(drivePick.url, [...checked])
      setDrivePick(null)
      await refresh()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function onDelete(game: Game) {
    if (!window.confirm(`Delete "${game.title}"?`)) return
    await api.deleteGame(game.id)
    await refresh()
  }

  return (
    <div className="page">
      <div className="topbar">
        <span className="title">TeloraFooty</span>
        <span>
          <button className="btn" onClick={() => fileInput.current?.click()} disabled={uploading}>
            {uploading ? 'Uploading…' : 'Import video'}
          </button>{' '}
          <button className="btn btn-primary" onClick={onDrive}>Import from Drive</button>
          <input ref={fileInput} type="file" accept=".mp4,.mov,.mkv" hidden onChange={onFile} />
        </span>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="library-grid">
        {games.map((g) => (
          <div key={g.id} className="game-card">
            {g.status === 'ready' ? (
              <Link to={`/games/${g.id}`}>
                <div className="thumb">
                  <video src={api.videoUrl(g.id)} preload="metadata" muted />
                </div>
              </Link>
            ) : (
              <div className="thumb">
                {g.status === 'error' ? (
                  <span className="status-error">⚠ {g.error ?? 'Import failed'}</span>
                ) : (
                  <span>{g.status === 'downloading' ? 'Downloading…' : 'Processing…'}</span>
                )}
              </div>
            )}
            <div className="info">
              <strong>{g.title}</strong>
              <div className="meta">
                {g.date} · {g.goals ?? 0} goals · {g.shots ?? 0} shots
              </div>
            </div>
            <button className="delete" onClick={() => onDelete(g)} title="Delete game">✕</button>
          </div>
        ))}
        {games.length === 0 && <p style={{ color: 'var(--muted)' }}>No games yet — import one to get started.</p>}
      </div>

      {drivePick && (
        <div className="modal-backdrop" onClick={() => setDrivePick(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Choose videos to import</h3>
            {drivePick.files.map((f) => (
              <label key={f.id}>
                <input
                  type="checkbox"
                  checked={checked.has(f.id)}
                  onChange={(e) => {
                    const next = new Set(checked)
                    if (e.target.checked) next.add(f.id)
                    else next.delete(f.id)
                    setChecked(next)
                  }}
                />{' '}
                {f.name}
              </label>
            ))}
            <div className="actions">
              <button className="btn" onClick={() => setDrivePick(null)}>Cancel</button>
              <button className="btn btn-primary" onClick={confirmDrivePick} disabled={checked.size === 0}>
                Import {checked.size} video{checked.size === 1 ? '' : 's'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Verify build and manual check**

```bash
cd frontend && npm run build
```

Expected: build succeeds.

Manual check: run `cd backend && .venv/bin/uvicorn main:app --port 8000` and `cd frontend && npm run dev`, open http://localhost:5173 — empty library renders with both import buttons; importing a small local video produces a card with counts.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/index.css frontend/src/pages/Library.tsx
git commit -m "feat: dark theme styles and library page with file/Drive import"
```

---

### Task 9: Player page + VideoPlayer (timeline dots, controls, clip-mode playback)

**Files:**
- Create: `frontend/src/components/VideoPlayer.tsx`
- Modify: `frontend/src/pages/Player.tsx` (replace placeholder)

ClipsPanel arrives in Task 10; this task renders the video column with a temporary empty sidebar div so the page works standalone.

- [ ] **Step 1: Implement VideoPlayer**

`frontend/src/components/VideoPlayer.tsx`:

```tsx
import { useRef, useState } from 'react'
import { api } from '../api'
import { fmtTime, nextEvent, type Mode } from '../playback'
import type { GameEvent } from '../types'

interface Props {
  gameId: string
  duration: number
  events: GameEvent[]
  mode: Mode
  selected: GameEvent | null
  videoRef: React.RefObject<HTMLVideoElement | null>
  onTimeUpdate: (time: number) => void
  onSelectEvent: (event: GameEvent) => void
}

export default function VideoPlayer({
  gameId, duration, events, mode, selected, videoRef, onTimeUpdate, onSelectEvent,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)

  const video = () => videoRef.current

  function togglePlay() {
    const v = video()
    if (!v) return
    if (v.paused) v.play()
    else v.pause()
  }

  function skip(delta: number) {
    const v = video()
    if (v) v.currentTime = Math.max(0, Math.min(duration, v.currentTime + delta))
  }

  function jumpEvent(dir: 1 | -1) {
    const ev = nextEvent(events, time, dir)
    if (ev) onSelectEvent(ev)
  }

  function onScrub(e: React.MouseEvent<HTMLDivElement>) {
    const v = video()
    if (!v || duration === 0) return
    const rect = e.currentTarget.getBoundingClientRect()
    const frac = (e.clientX - rect.left) / rect.width
    v.currentTime = Math.max(0, Math.min(duration, frac * duration))
  }

  function changeSpeed(value: number) {
    setSpeed(value)
    const v = video()
    if (v) v.playbackRate = value
  }

  const badge = selected
    ? `${mode === 'clip' ? 'CLIP' : 'FULL'} · ${selected.type.toUpperCase()} ${fmtTime(selected.timestamp)}`
    : mode === 'clip' ? 'CLIP MODE' : 'FULL GAME'

  return (
    <div className="video-col">
      <div className="video-wrap" ref={wrapRef}>
        <video
          ref={videoRef}
          src={api.videoUrl(gameId)}
          onClick={togglePlay}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onTimeUpdate={(e) => {
            const t = e.currentTarget.currentTime
            setTime(t)
            onTimeUpdate(t)
          }}
        />
        <div className="mode-badge">{badge}</div>
      </div>

      <div className="controls">
        <button onClick={togglePlay} title="Play/pause">{playing ? '❚❚' : '▶'}</button>
        <button onClick={() => jumpEvent(-1)} title="Previous event">⇤</button>
        <button onClick={() => jumpEvent(1)} title="Next event">⇥</button>
        <button onClick={() => skip(-5)} title="Back 5s">↺5</button>
        <button onClick={() => skip(5)} title="Forward 5s">5↻</button>

        <div className="timeline" onClick={onScrub}>
          <div className="track">
            <div className="fill" style={{ width: duration ? `${(time / duration) * 100}%` : '0%' }} />
            {events.map((ev) => (
              <span
                key={ev.id}
                className={`dot ${ev.type}${selected?.id === ev.id ? ' selected' : ''}`}
                style={{ left: duration ? `${(ev.timestamp / duration) * 100}%` : '0%' }}
                title={`${ev.type} ${fmtTime(ev.timestamp)}`}
                onClick={(e) => {
                  e.stopPropagation()
                  onSelectEvent(ev)
                }}
              />
            ))}
          </div>
        </div>

        <span className="time">{fmtTime(time)} / {fmtTime(duration)}</span>
        <select value={speed} onChange={(e) => changeSpeed(Number(e.target.value))} title="Speed">
          {[0.5, 1, 1.5, 2].map((s) => <option key={s} value={s}>{s}x</option>)}
        </select>
        <button onClick={() => wrapRef.current?.requestFullscreen()} title="Fullscreen">⛶</button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Implement the Player page**

Replace `frontend/src/pages/Player.tsx`:

```tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import VideoPlayer from '../components/VideoPlayer'
import { clipEnded, startTime, type FilterTab, type Mode } from '../playback'
import type { Game, GameEvent } from '../types'

export default function Player() {
  const { id } = useParams<{ id: string }>()
  const gameId = id!
  const [game, setGame] = useState<Game | null>(null)
  const [events, setEvents] = useState<GameEvent[]>([])
  const [mode, setMode] = useState<Mode>('clip')
  const [tab, setTab] = useState<FilterTab>('all')
  const [selected, setSelected] = useState<GameEvent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const lastTimeRef = useRef(0)

  const refreshEvents = useCallback(
    () => api.listEvents(gameId).then(setEvents).catch((e: Error) => setError(e.message)),
    [gameId],
  )

  useEffect(() => {
    api.getGame(gameId).then(setGame).catch((e: Error) => setError(e.message))
    refreshEvents()
  }, [gameId, refreshEvents])

  function selectEvent(ev: GameEvent) {
    setSelected(ev)
    const v = videoRef.current
    if (!v) return
    v.currentTime = startTime(mode, ev)
    v.play()
  }

  function switchMode(m: Mode) {
    setMode(m)
    const v = videoRef.current
    if (m === 'clip' && selected && v) {
      v.currentTime = selected.clipStart
      v.play()
    }
  }

  function onTimeUpdate(t: number) {
    const last = lastTimeRef.current
    lastTimeRef.current = t
    // Pause exactly once when playback crosses the clip's end.
    if (clipEnded(t, mode, selected) && !clipEnded(last, mode, selected)) {
      videoRef.current?.pause()
    }
  }

  if (!game) return <div className="page">{error ?? 'Loading…'}</div>

  return (
    <div className="page">
      <div className="topbar">
        <Link to="/">← Library</Link>
        <span>
          <span className="title">{game.title}</span> <span className="sub">· {game.date}</span>
        </span>
        <span className="sub">{events.length} events</span>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="player-layout">
        <VideoPlayer
          gameId={gameId}
          duration={game.durationSec}
          events={events}
          mode={mode}
          selected={selected}
          videoRef={videoRef}
          onTimeUpdate={onTimeUpdate}
          onSelectEvent={selectEvent}
        />
        {/* ClipsPanel mounts here in Task 10 */}
        <div className="clips-panel" data-placeholder />
      </div>
    </div>
  )
}
```

Note: `tab`/`setTab` and `switchMode`/`refreshEvents` are wired into ClipsPanel in Task 10 — TypeScript will flag them as unused until then; that's expected and resolved next task. If `npm run build` fails on `noUnusedLocals`, prefix them with void statements temporarily: add `void tab; void switchMode; void refreshEvents;` above the `if (!game)` line and remove that line in Task 10.

- [ ] **Step 3: Verify build and manual check**

```bash
cd frontend && npm run build
```

Expected: build succeeds.

Manual check: with backend + frontend running, import a video, open its card → player shows video, timeline dots for the seeded sample events, prev/next event arrows jump between them, ±5s works, clip badge updates, and in clip mode playback pauses at the event's clipEnd.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/VideoPlayer.tsx frontend/src/pages/Player.tsx
git commit -m "feat: player page with custom video controls, timeline dots, clip-mode pause"
```

---

### Task 10: ClipsPanel — tabs, event cards, toggle, tagging, export

**Files:**
- Create: `frontend/src/components/EventCard.tsx`, `frontend/src/components/ClipsPanel.tsx`
- Modify: `frontend/src/pages/Player.tsx` (mount panel)
- Test: `frontend/src/tests/ClipsPanel.test.tsx`

- [ ] **Step 1: Write the failing component tests**

`frontend/src/tests/ClipsPanel.test.tsx`:

```tsx
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import ClipsPanel, { type ClipsPanelProps } from '../components/ClipsPanel'
import type { GameEvent } from '../types'

const ev = (id: string, type: 'shot' | 'goal', timestamp: number): GameEvent => ({
  id,
  type,
  timestamp,
  source: 'sample',
  clipStart: Math.max(0, timestamp - 30),
  clipEnd: timestamp + 10,
})

const events = [ev('e1', 'shot', 100), ev('e2', 'goal', 200)]

function setup(overrides: Partial<ClipsPanelProps> = {}) {
  const props: ClipsPanelProps = {
    gameId: 'g1',
    events,
    tab: 'all',
    onTab: vi.fn(),
    mode: 'clip',
    onMode: vi.fn(),
    selected: null,
    onSelect: vi.fn(),
    onTag: vi.fn(),
    onDelete: vi.fn(),
    onSwitchType: vi.fn(),
    onSetTimeToPlayhead: vi.fn(),
    onExport: vi.fn(),
    ...overrides,
  }
  render(<ClipsPanel {...props} />)
  return props
}

test('renders all events on the all tab', () => {
  setup()
  expect(screen.getByText('Shot on goal')).toBeInTheDocument()
  expect(screen.getByText('Goal')).toBeInTheDocument()
})

test('goals tab shows only goals', () => {
  setup({ tab: 'goals' })
  expect(screen.queryByText('Shot on goal')).not.toBeInTheDocument()
  expect(screen.getByText('Goal')).toBeInTheDocument()
})

test('shots tab shows only shots', () => {
  setup({ tab: 'shots' })
  expect(screen.getByText('Shot on goal')).toBeInTheDocument()
  expect(screen.queryByText('Goal')).not.toBeInTheDocument()
})

test('clicking a tab calls onTab', () => {
  const props = setup()
  fireEvent.click(screen.getByRole('button', { name: 'Goals' }))
  expect(props.onTab).toHaveBeenCalledWith('goals')
})

test('clicking the toggle calls onMode', () => {
  const props = setup()
  fireEvent.click(screen.getByRole('button', { name: 'Full game' }))
  expect(props.onMode).toHaveBeenCalledWith('full')
})

test('clicking a card calls onSelect with the event', () => {
  const props = setup()
  fireEvent.click(screen.getByText('Goal'))
  expect(props.onSelect).toHaveBeenCalledWith(events[1])
})

test('tag menu offers shot and goal and calls onTag', () => {
  const props = setup()
  fireEvent.click(screen.getByRole('button', { name: '+ Tag' }))
  fireEvent.click(screen.getByRole('button', { name: 'Tag goal' }))
  expect(props.onTag).toHaveBeenCalledWith('goal')
})

test('export button calls onExport with the event', () => {
  const props = setup()
  fireEvent.click(screen.getAllByTitle('Export clip')[0])
  expect(props.onExport).toHaveBeenCalledWith(events[0])
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test`
Expected: playback tests PASS; ClipsPanel tests FAIL — cannot resolve `../components/ClipsPanel`

- [ ] **Step 3: Implement EventCard**

`frontend/src/components/EventCard.tsx`:

```tsx
import { useState } from 'react'
import { api } from '../api'
import { fmtTime } from '../playback'
import type { GameEvent } from '../types'

interface Props {
  gameId: string
  event: GameEvent
  selected: boolean
  onSelect: () => void
  onDelete: () => void
  onSwitchType: () => void
  onSetTimeToPlayhead: () => void
  onExport: () => void
}

export default function EventCard({
  gameId, event, selected, onSelect, onDelete, onSwitchType, onSetTimeToPlayhead, onExport,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false)
  const title = event.type === 'goal' ? 'Goal' : 'Shot on goal'

  return (
    <div className={`event-card${selected ? ' selected' : ''}`} onClick={onSelect}>
      <span style={{ position: 'relative' }}>
        <img className="ethumb" src={api.thumbUrl(gameId, event.id)} alt={title} />
        <span className="tbadge">{fmtTime(event.timestamp)}</span>
      </span>
      <span>
        <div className={`ttl ${event.type}`}>{title}</div>
        <div className="src">{event.source}</div>
      </span>
      <span className="actions" onClick={(e) => e.stopPropagation()}>
        <button title="Export clip" onClick={onExport}>⤓</button>
        <button title="More" onClick={() => setMenuOpen(!menuOpen)}>⋮</button>
      </span>
      {menuOpen && (
        <div className="menu" onClick={(e) => e.stopPropagation()}>
          <button onClick={() => { setMenuOpen(false); onSwitchType() }}>
            Switch to {event.type === 'goal' ? 'shot' : 'goal'}
          </button>
          <button onClick={() => { setMenuOpen(false); onSetTimeToPlayhead() }}>
            Set time to playhead
          </button>
          <button onClick={() => { setMenuOpen(false); onDelete() }}>Delete</button>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Implement ClipsPanel**

`frontend/src/components/ClipsPanel.tsx`:

```tsx
import { useState } from 'react'
import { filterEvents, sortEvents, type FilterTab, type Mode } from '../playback'
import type { EventType, GameEvent } from '../types'
import EventCard from './EventCard'

export interface ClipsPanelProps {
  gameId: string
  events: GameEvent[]
  tab: FilterTab
  onTab: (tab: FilterTab) => void
  mode: Mode
  onMode: (mode: Mode) => void
  selected: GameEvent | null
  onSelect: (event: GameEvent) => void
  onTag: (type: EventType) => void
  onDelete: (event: GameEvent) => void
  onSwitchType: (event: GameEvent) => void
  onSetTimeToPlayhead: (event: GameEvent) => void
  onExport: (event: GameEvent) => void
}

const TABS: { key: FilterTab; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'goals', label: 'Goals' },
  { key: 'shots', label: 'Shots' },
]

export default function ClipsPanel({
  gameId, events, tab, onTab, mode, onMode, selected,
  onSelect, onTag, onDelete, onSwitchType, onSetTimeToPlayhead, onExport,
}: ClipsPanelProps) {
  const [tagOpen, setTagOpen] = useState(false)
  const visible = sortEvents(filterEvents(events, tab))

  return (
    <div className="clips-panel">
      <div className="head">
        <h3>Clips</h3>
        <div className="toggle">
          <button className={mode === 'clip' ? 'active' : ''} onClick={() => onMode('clip')}>
            Clip
          </button>
          <button className={mode === 'full' ? 'active' : ''} onClick={() => onMode('full')}>
            Full game
          </button>
        </div>
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`tab${tab === t.key ? ' active' : ''}`}
            onClick={() => onTab(t.key)}
          >
            {t.label}
          </button>
        ))}
        <span className="tag-btn tag-menu">
          <button className="tab" onClick={() => setTagOpen(!tagOpen)}>+ Tag</button>
          {tagOpen && (
            <div className="menu">
              <button onClick={() => { setTagOpen(false); onTag('shot') }}>Tag shot</button>
              <button onClick={() => { setTagOpen(false); onTag('goal') }}>Tag goal</button>
            </div>
          )}
        </span>
      </div>

      {visible.map((ev) => (
        <EventCard
          key={ev.id}
          gameId={gameId}
          event={ev}
          selected={selected?.id === ev.id}
          onSelect={() => onSelect(ev)}
          onDelete={() => onDelete(ev)}
          onSwitchType={() => onSwitchType(ev)}
          onSetTimeToPlayhead={() => onSetTimeToPlayhead(ev)}
          onExport={() => onExport(ev)}
        />
      ))}
      {visible.length === 0 && (
        <p style={{ color: 'var(--muted)', fontSize: 13 }}>
          No events — use + Tag while watching to add one.
        </p>
      )}
    </div>
  )
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm test`
Expected: PASS (12 playback + 8 ClipsPanel)

- [ ] **Step 6: Mount the panel in Player**

In `frontend/src/pages/Player.tsx`:

Add to the imports:

```tsx
import ClipsPanel from '../components/ClipsPanel'
import { fmtTime } from '../playback'
import type { EventType } from '../types'
```

(adjust the existing `playback` import to include `fmtTime` rather than duplicating the line, and remove any temporary `void` statements from Task 9).

Add these handlers inside the `Player` component, after `onTimeUpdate`:

```tsx
  async function tagEvent(type: EventType) {
    const t = videoRef.current?.currentTime ?? 0
    try {
      const ev = await api.createEvent(gameId, type, t)
      await refreshEvents()
      setSelected(ev)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function deleteEvent(ev: GameEvent) {
    if (!window.confirm(`Delete this ${ev.type}?`)) return
    await api.deleteEvent(gameId, ev.id)
    if (selected?.id === ev.id) setSelected(null)
    await refreshEvents()
  }

  async function switchType(ev: GameEvent) {
    await api.patchEvent(gameId, ev.id, { type: ev.type === 'goal' ? 'shot' : 'goal' })
    await refreshEvents()
  }

  async function setTimeToPlayhead(ev: GameEvent) {
    const t = videoRef.current?.currentTime ?? ev.timestamp
    await api.patchEvent(gameId, ev.id, { timestamp: t })
    await refreshEvents()
  }

  async function exportEvent(ev: GameEvent) {
    try {
      const blob = await api.exportClip(gameId, ev.id)
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `${game!.title.replaceAll(' ', '_')}_${ev.type}_${fmtTime(ev.timestamp).replace(':', '')}.mp4`
      a.click()
      URL.revokeObjectURL(a.href)
    } catch (e) {
      setError((e as Error).message)
    }
  }
```

Replace `<div className="clips-panel" data-placeholder />` with:

```tsx
        <ClipsPanel
          gameId={gameId}
          events={events}
          tab={tab}
          onTab={setTab}
          mode={mode}
          onMode={switchMode}
          selected={selected}
          onSelect={selectEvent}
          onTag={tagEvent}
          onDelete={deleteEvent}
          onSwitchType={switchType}
          onSetTimeToPlayhead={setTimeToPlayhead}
          onExport={exportEvent}
        />
```

- [ ] **Step 7: Verify build + full frontend suite**

```bash
cd frontend && npm test && npm run build
```

Expected: all tests PASS, build succeeds with no unused-variable errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/ frontend/src/pages/Player.tsx frontend/src/tests/ClipsPanel.test.tsx
git commit -m "feat: clips panel with filters, tagging, edit/delete, and clip export"
```

---

### Task 11: README, full verification, manual smoke test (KPI check)

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the README**

`README.md`:

```markdown
# TeloraFooty

Local web app for reviewing soccer footage: import a game (local file or public
Google Drive link), review shots and goals in a Veo-style player, and export
clips (30s before → 10s after each event).

## Requirements

- Python 3.12+, Node 20+, ffmpeg/ffprobe on PATH

## Run

Backend (terminal 1):

    cd backend
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # first time
    .venv/bin/uvicorn main:app --port 8000

Frontend (terminal 2):

    cd frontend
    npm install        # first time
    npm run dev

Open http://localhost:5173

## Tests

    cd backend && .venv/bin/pytest
    cd frontend && npm test

## Notes

- Library data lives in `data/games/` (gitignored).
- Drive links must be shared as "anyone with the link".
- Events are seeded from hardcoded samples (`backend/importer.py: SAMPLE_EVENTS`)
  plus manual tagging. The `source` field is ready for a future AI detector.
```

- [ ] **Step 2: Run both full test suites**

```bash
cd backend && .venv/bin/pytest -v
cd ../frontend && npm test && npm run build
```

Expected: backend all green, frontend all green, build clean.

- [ ] **Step 3: Manual smoke test — the KPI check**

With backend (`.venv/bin/uvicorn main:app --port 8000`) and frontend (`npm run dev`) running:

1. Import from Drive: paste the real folder link (`https://drive.google.com/drive/folders/1uM7_sUErhr75zCwpgccvrJYvgEiFYF_a`), pick a video, watch the card progress from Downloading → Processing → ready.
2. Open the game — sample events appear with thumbnails; dots show on the timeline.
3. Clip mode: click a goal — playback starts 30s before, pauses 10s after.
4. Full game mode: toggle, click the same event — seeks the full video and keeps playing.
5. Tabs: Goals / Shots filter the panel.
6. Tag: pause at any shot, + Tag → Tag shot — card and dot appear immediately.
7. Export: hit ⤓ on an event — an .mp4 of the clip downloads and plays.
8. Error path: paste a non-public Drive link — clear error message appears.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README with run, test, and smoke-test instructions"
```

---

## Plan self-review notes

- **Spec coverage:** library (Task 8), import file/Drive incl. folder picker (Tasks 4, 5, 8), player + timeline dots + prev/next (Task 9), Clips panel + tabs + toggle + tagging + edit/delete + export (Tasks 6, 10), clip clamping (Task 2), thumbnails (Tasks 3, 4, 6), H.264 ensure (Task 3), error states (Tasks 4, 5, 8), counts on cards (Task 5), README/smoke (Task 11). Drive network paths are smoke-tested, not unit-tested.
- **Known deviation from spec:** import routes are split (`/api/games/import`, `/api/games/import-drive`, `/api/drive/list`) instead of a single `/api/games/import` — cleaner contracts, same capability. Local import is synchronous (fast, no download step); Drive import is background with status polling.
- **Type consistency check:** `store` event keys (`clipStart`/`clipEnd`/`timestamp`/`type`/`source`) match `types.ts`; `ClipsPanelProps` matches the Task 10 test and the Player wiring; `playback.ts` exports match both test and component imports.





