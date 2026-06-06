# Combine Frontend + Analysis Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the `main` branch (React frontend + MVP backend) with `backend/malik` (FastAPI CV-analysis backend) into one codebase where malik's app implements the frontend's exact API contract, with auto-analyze on import.

**Architecture:** Git merge with `--allow-unrelated-histories` on branch `combine`; malik's `backend/app` survives, main's flat MVP backend is deleted and its features (import, Drive, events CRUD, clip/thumb serving, email) are ported into malik's structure as new routes/services. The frontend is untouched except that it now gets real detected events instead of `generate_sample_events` fakes.

**Tech Stack:** FastAPI + pydantic v2 + pydantic-settings, JsonStore (file-backed), ffmpeg/ffprobe, Gemini VLM detector (existing), gdown, smtplib, React/Vite/vitest (unchanged).

**Spec:** `docs/superpowers/specs/2026-06-06-combine-frontend-backend-design.md`

**Key contract rules (apply to every task):**
- The frontend's `frontend/src/api.ts` + `frontend/src/types.ts` define the API. Frontend vocabulary wins at the boundary; malik's models keep internal names.
- Frontend-facing routes raise `fastapi.HTTPException(status, detail=msg)` — the frontend reads `body.detail`. Malik's `AppError` envelope stays for internal routes only.
- Status map: `uploaded/processing→processing`, `downloading→downloading`, `completed→ready`, `failed→error`. Event source map: `model/hybrid→ai`; `manual`/`sample` pass through.
- Re-processing only deletes events with `source=='model' AND verified==False`.
- Backend commands run from `/Users/omarlahmimi/Documents/TeloraFooty/backend` with `.venv/bin/python -m pytest`. Frontend: `cd frontend && npm test`.

---

### Task 1: Merge unrelated histories

**Files:**
- Modify: `.gitignore` (union), `backend/requirements.txt` (union+gdown), `backend/tests/conftest.py` (take malik's)
- Delete: `backend/main.py`, `backend/store.py`, `backend/importer.py`, `backend/clipper.py`, `backend/emailer.py`, `backend/tests/test_api.py`, `backend/tests/test_clipper.py`, `backend/tests/test_importer.py`, `backend/tests/test_store.py`

- [ ] **Step 1: Merge**

```bash
cd /Users/omarlahmimi/Documents/TeloraFooty
git merge backend/malik --allow-unrelated-histories --no-commit
git status   # expect add/add conflicts: .gitignore, backend/requirements.txt, backend/tests/conftest.py
```

- [ ] **Step 2: Resolve conflicts**

`backend/tests/conftest.py`: `git checkout --theirs backend/tests/conftest.py`

`.gitignore` — write this union:

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.coverage
htmlcov/

# Virtual environments
.venv/
venv/
backend/.venv/

# Environment
.env
backend/.env

# OS
.DS_Store

# Node / frontend
node_modules/
frontend/dist/

# Legacy MVP data dir + superpowers scratch
data/
.superpowers/

# Local storage / generated media (do NOT commit large videos or generated clips)
backend/storage/uploads/*
backend/storage/clips/*
backend/storage/processed/*
backend/storage/thumbnails/*
!backend/storage/**/.gitkeep
backend/storage/annotations/*.tmp

# Local runtime DB / data snapshots
backend/app/data/*.json
!backend/app/data/.gitkeep

# Test fixtures
backend/tests/fixtures/

# Large sample/test videos (do NOT commit large videos)
*.mp4
/clips/

# Logs
*.log

# Model weights (auto-downloaded by ultralytics on first use)
*.pt
```

`backend/requirements.txt` — malik's plus gdown:

```
# Core backend
fastapi==0.115.6
uvicorn[standard]==0.34.0
python-multipart==0.0.20
pydantic==2.10.4
pydantic-settings==2.7.1
python-dotenv==1.0.1

# Video processing / CV
opencv-python-headless==4.11.0.86
numpy==2.2.1
ffmpeg-python==0.2.0

# Google Drive imports (public links)
gdown

# Video-language-model judge (Gemini) — vlm_service.py imports `from google import genai`
google-genai

# Testing
pytest==8.3.4
httpx==0.28.1

# Optional ML detectors (install separately; pipeline runs without them)
# ultralytics
# torch
# torchvision
# supervision
# scikit-learn
```

- [ ] **Step 3: Delete the MVP backend (stays in history)**

```bash
git rm backend/main.py backend/store.py backend/importer.py backend/clipper.py backend/emailer.py \
       backend/tests/test_api.py backend/tests/test_clipper.py backend/tests/test_importer.py backend/tests/test_store.py
git add -A
git commit -m "merge: combine frontend (main) with analysis backend (backend/malik)

Unrelated histories joined. Malik's backend/app survives; the MVP flat
backend is removed (features will be ported per the design spec)."
```

- [ ] **Step 4: Python env + deps**

```bash
cd backend
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
which ffmpeg ffprobe   # both must exist
```

- [ ] **Step 5: Verify both worlds still pass**

```bash
cd backend && .venv/bin/python -m pytest          # expect: malik's suite passes
cd ../frontend && npm install && npm test          # expect: frontend suite passes
```

---

### Task 2: Model extensions, store mutations, frontend-contract schemas

**Files:**
- Modify: `backend/app/models/game.py`, `backend/app/models/event.py`, `backend/app/services/store.py`, `backend/app/config.py`
- Create: `backend/app/schemas/frontend_api.py`
- Test: `backend/tests/unit/test_frontend_api.py`, `backend/tests/unit/test_store_mutations.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/unit/test_frontend_api.py`:

```python
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
```

`backend/tests/unit/test_store_mutations.py`:

```python
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
```

- [ ] **Step 2: Run, verify fail** — `cd backend && .venv/bin/python -m pytest tests/unit/test_frontend_api.py tests/unit/test_store_mutations.py -v` → import errors (no `frontend_api`, no `delete_event`).

- [ ] **Step 3: Implement**

`backend/app/models/game.py` — replace the Game class body fields with:

```python
class Game(BaseModel):
    id: str
    title: str
    video_id: str | None = None
    video_filename: str | None = None
    team_name: str = "Our Team"
    opponent_name: str | None = None
    status: str = "uploaded"  # uploaded | downloading | processing | completed | failed
    error: str | None = None
    source_kind: str = "local"  # local | drive
    source_url: str | None = None
    duration_seconds: float = 0.0
    event_count: int = 0
    created_at: datetime = Field(default_factory=_now)
```

`backend/app/models/event.py` — add after `source`:

```python
    verified: bool = False
```

`backend/app/services/store.py` — add to JsonStore after `clear_events_for_game`:

```python
    def delete_event(self, event_id: str) -> bool:
        with self._lock:
            if self.events.pop(event_id, None) is None:
                return False
            self._save_collection("events", self.events.values())
        return True

    def delete_clip(self, clip_id: str) -> None:
        with self._lock:
            if self.clips.pop(clip_id, None) is not None:
                self._save_collection("clips", self.clips.values())

    def delete_game(self, game_id: str) -> bool:
        with self._lock:
            game = self.games.pop(game_id, None)
            if game is None:
                return False
            if game.video_id:
                self.videos.pop(game.video_id, None)
            self.events = {k: v for k, v in self.events.items() if v.game_id != game_id}
            self.clips = {k: v for k, v in self.clips.items() if v.game_id != game_id}
            self.jobs = {k: v for k, v in self.jobs.items() if v.game_id != game_id}
            self._persist()
        return True
```

Create `backend/app/schemas/frontend_api.py`:

```python
"""Schemas matching the frontend's API contract (frontend/src/types.ts).

The frontend's vocabulary wins at the API boundary; internal models keep
their own field names. These helpers translate between the two.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.models import Event, Game
from app.services.clip_service import clip_window_for_event

_STATUS_TO_FRONTEND = {
    "uploaded": "processing",
    "downloading": "downloading",
    "processing": "processing",
    "completed": "ready",
    "failed": "error",
}

_SOURCE_TO_FRONTEND = {"model": "ai", "hybrid": "ai"}  # manual/sample pass through


class GameOut(BaseModel):
    id: str
    title: str
    date: str
    durationSec: float
    source: dict  # {"kind": "local"|"drive", "url": str|None}
    status: str  # downloading | processing | ready | error
    error: str | None = None
    goals: int | None = None
    shots: int | None = None


class EventOut(BaseModel):
    id: str
    type: str
    timestamp: float
    source: str  # manual | sample | ai
    verified: bool
    confidence: float
    clipStart: float
    clipEnd: float


def game_out(game: Game, *, goals: int | None = None, shots: int | None = None) -> GameOut:
    return GameOut(
        id=game.id,
        title=game.title,
        date=game.created_at.date().isoformat(),
        durationSec=game.duration_seconds,
        source={"kind": game.source_kind, "url": game.source_url},
        status=_STATUS_TO_FRONTEND.get(game.status, "processing"),
        error=game.error,
        goals=goals,
        shots=shots,
    )


def event_out(event: Event, video_duration: float) -> EventOut:
    window = clip_window_for_event(event.event_type, event.timestamp_seconds, video_duration)
    return EventOut(
        id=event.id,
        type=event.event_type,
        timestamp=event.timestamp_seconds,
        source=_SOURCE_TO_FRONTEND.get(event.source, event.source),
        verified=event.verified,
        confidence=event.confidence,
        clipStart=window.start_seconds,
        clipEnd=window.end_seconds,
    )
```

`backend/app/config.py` — add to Settings (after the clip window settings):

```python
    # Auto-analysis dispatch: videos at or below this duration go through the
    # whole-clip detector; longer ones through the full-match funnel.
    short_clip_max_seconds: float = 180.0

    # SMTP clip emailing (ported from the MVP backend). For Gmail use an app
    # password from https://myaccount.google.com/apppasswords.
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_from: str = ""
```

- [ ] **Step 4: Run, verify pass** — same pytest command, then the full suite: `.venv/bin/python -m pytest`. Expected: all pass.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: frontend-contract schema layer, model extensions, store mutations"`

---

### Task 3: Games routes → frontend contract

**Files:**
- Modify: `backend/app/api/routes/games.py`
- Test: `backend/tests/integration/test_frontend_games_api.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/integration/test_frontend_games_api.py`:

```python
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
```

- [ ] **Step 2: Run, verify fail** — `.venv/bin/python -m pytest tests/integration/test_frontend_games_api.py -v` → shape mismatches/404 envelope mismatch.

- [ ] **Step 3: Implement** — rewrite `backend/app/api/routes/games.py` (keep `/process` and `/clips` as they are for now; `/process` is rewired in Task 6; `/{game_id}/events` GET is REMOVED here and reborn in Task 4's `events.py`):

```python
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.schemas.clip_schema import ClipOut, GameClipsResponse
from app.schemas.frontend_api import game_out
from app.schemas.game_schema import ProcessGameResponse
from app.services import job_service, media_service, processing_service
from app.services.store import store

router = APIRouter()


def _require_game(game_id: str):
    game = store.get_game(game_id)
    if game is None:
        raise HTTPException(404, "Game not found")
    return game


@router.get("")
def list_games() -> list[dict]:
    out = []
    for g in sorted(store.list_games(), key=lambda g: g.created_at, reverse=True):
        events = store.events_for_game(g.id)
        out.append(
            game_out(
                g,
                goals=sum(1 for e in events if e.event_type == "goal"),
                shots=sum(1 for e in events if e.event_type == "shot"),
            ).model_dump()
        )
    return out


@router.get("/{game_id}")
def get_game(game_id: str) -> dict:
    return game_out(_require_game(game_id)).model_dump()


@router.delete("/{game_id}")
def delete_game(game_id: str) -> dict:
    game = _require_game(game_id)
    video = store.get_video(game.video_id) if game.video_id else None
    for event in store.events_for_game(game_id):
        media_service.drop_event_media(event)
    if video and video.stored_path:
        Path(video.stored_path).unlink(missing_ok=True)
    store.delete_game(game_id)
    return {"ok": True}


@router.post("/{game_id}/process", response_model=ProcessGameResponse)
def process_game(game_id: str, background_tasks: BackgroundTasks) -> ProcessGameResponse:
    """Start full-game processing (loads manual annotations, generates clips)."""
    game = _require_game(game_id)

    job = job_service.create_job("full_game", game_id=game_id, message="Full game processing queued.")
    background_tasks.add_task(processing_service.process_game_from_annotations, game_id, job.id)

    return ProcessGameResponse(
        job_id=job.id,
        game_id=game_id,
        status="processing",
        message="Full game processing started. Results will be available shortly.",
    )


@router.get("/{game_id}/clips", response_model=GameClipsResponse)
def get_game_clips(game_id: str) -> GameClipsResponse:
    _require_game(game_id)
    clips = store.clips_for_game(game_id)
    return GameClipsResponse(
        game_id=game_id,
        clips=[
            ClipOut(
                clip_id=c.id,
                event_type=c.event_type,
                timestamp_seconds=c.timestamp_seconds,
                start_seconds=c.start_seconds,
                end_seconds=c.end_seconds,
                clip_url=c.public_url,
            )
            for c in clips
            if c.public_url
        ],
    )
```

NOTE: this imports `media_service` which is created in Task 4. To keep Task 3 self-contained and green, create the service file in Task 4 BUT for this task stub the import by creating `backend/app/services/media_service.py` now with just:

```python
"""Per-event media artifacts: thumbnails and highlight clips. (Filled in Task 4.)"""

from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.models import Event


def thumb_path(event_id: str) -> Path:
    return settings.thumbnails_dir / f"{event_id}.jpg"


def cached_clip_path(event_id: str) -> Path:
    return settings.clips_dir / f"{event_id}.mp4"


def drop_event_media(event: Event) -> None:
    """Delete cached artifacts for an event (thumb + clip file + clip record)."""
    from app.services.store import store

    thumb_path(event.id).unlink(missing_ok=True)
    cached_clip_path(event.id).unlink(missing_ok=True)
    if event.clip_id:
        clip = store.clips.get(event.clip_id)
        if clip:
            if clip.stored_path:
                Path(clip.stored_path).unlink(missing_ok=True)
            store.delete_clip(event.clip_id)
```

- [ ] **Step 4: Run, verify pass** — task tests, then full backend suite. `tests/integration/test_game_events_api.py` may still pass (its events route is untouched until Task 4); if anything referenced the old `{"games": [...]}` shape, update it to the array shape.

- [ ] **Step 5: Commit** — `git commit -am "feat: games routes speak the frontend contract (list/get/delete)"`

---

### Task 4: media_service + events CRUD routes

**Files:**
- Modify: `backend/app/services/media_service.py` (complete it), `backend/app/main.py`, `backend/app/api/routes/games.py` (no event routes left there), `backend/tests/integration/test_game_events_api.py`
- Create: `backend/app/api/routes/events.py`
- Test: `backend/tests/integration/test_frontend_events_api.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/integration/test_frontend_events_api.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.models import Game
from app.services.store import store
from tests.conftest import requires_ffmpeg


@pytest.fixture(autouse=True)
def _clean_store():
    yield
    for gid in list(store.games):
        store.delete_game(gid)


def _game_with_video(client, sample_5s: Path) -> str:
    with sample_5s.open("rb") as f:
        up = client.post("/api/videos/upload",
                         files={"file": ("g.mp4", f, "video/mp4")},
                         data={"video_type": "full_game"})
    assert up.status_code == 200
    return up.json()["game_id"]


@requires_ffmpeg
def test_event_crud_roundtrip(client, sample_5s: Path):
    game_id = _game_with_video(client, sample_5s)

    created = client.post(f"/api/games/{game_id}/events",
                          json={"type": "shot", "timestamp": 2.0}).json()
    assert created["type"] == "shot"
    assert created["source"] == "manual"
    assert created["verified"] is False
    assert created["clipStart"] < 2.0 < created["clipEnd"]
    event_id = created["id"]

    listed = client.get(f"/api/games/{game_id}/events").json()
    assert isinstance(listed, list) and listed[0]["id"] == event_id
    assert store.get_game(game_id).event_count == 1

    patched = client.patch(f"/api/games/{game_id}/events/{event_id}",
                           json={"type": "goal", "verified": True}).json()
    assert patched["type"] == "goal" and patched["verified"] is True

    assert client.delete(f"/api/games/{game_id}/events/{event_id}").json() == {"ok": True}
    assert client.get(f"/api/games/{game_id}/events").json() == []
    assert store.get_game(game_id).event_count == 0


@requires_ffmpeg
def test_create_event_writes_thumb(client, sample_5s: Path):
    game_id = _game_with_video(client, sample_5s)
    event = client.post(f"/api/games/{game_id}/events",
                        json={"type": "shot", "timestamp": 1.0}).json()
    assert (settings.thumbnails_dir / f"{event['id']}.jpg").exists()


def test_events_404s(client):
    assert client.get("/api/games/none/events").status_code == 404
    store.save_game(Game(id="g_e404", title="T"))
    assert client.patch("/api/games/g_e404/events/missing", json={"verified": True}).status_code == 404
    assert client.delete("/api/games/g_e404/events/missing").status_code == 404
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement**

Complete `backend/app/services/media_service.py` (replace the stub's docstring and add the remaining functions; keep `thumb_path`, `cached_clip_path`, `drop_event_media`, moving the imports to the top):

```python
"""Per-event media artifacts: thumbnails and highlight clips.

Thumbnails and lazily-cut clips are keyed by event id under the standard
storage folders. Detection-time clips recorded in the store are preferred
when present; otherwise clips are cut on demand and cached.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.config import settings
from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.core.logging import get_logger
from app.models import Clip, Event, Game
from app.services.clip_service import clip_window_for_event, generate_clip
from app.services.store import store

logger = get_logger(__name__)


def thumb_path(event_id: str) -> Path:
    return settings.thumbnails_dir / f"{event_id}.jpg"


def cached_clip_path(event_id: str) -> Path:
    return settings.clips_dir / f"{event_id}.mp4"


def extract_event_thumb(game: Game, event: Event) -> Path | None:
    """Best-effort single-frame thumbnail at the event timestamp."""
    video = store.get_video(game.video_id) if game.video_id else None
    if video is None or not Path(video.stored_path).exists() or shutil.which("ffmpeg") is None:
        return None
    out = thumb_path(event.id)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-ss", f"{event.timestamp_seconds:.3f}", "-i", video.stored_path,
        "-frames:v", "1", "-vf", "scale=320:-2", "-y", str(out),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.SubprocessError as exc:
        logger.warning("Thumbnail failed for %s: %s", event.id, exc)
        return None
    if res.returncode != 0 or not out.exists():
        logger.warning("Thumbnail failed for %s: %s", event.id, res.stderr[-200:])
        return None
    return out


def ensure_event_clip(game: Game, event: Event) -> Path:
    """Return a playable clip for the event, cutting and caching it if needed.

    Raises AppError subclasses (from clip_service) when cutting fails.
    """
    if event.clip_id:
        clip = store.clips.get(event.clip_id)
        if clip and clip.stored_path and Path(clip.stored_path).exists():
            return Path(clip.stored_path)
    cached = cached_clip_path(event.id)
    if cached.exists():
        return cached
    video = store.get_video(game.video_id) if game.video_id else None
    if video is None or not Path(video.stored_path).exists():
        raise NotFoundError("Video not found", code="VIDEO_NOT_FOUND")
    duration = game.duration_seconds or video.duration_seconds
    window = clip_window_for_event(event.event_type, event.timestamp_seconds, duration)
    generate_clip(video.stored_path, window.start_seconds, window.end_seconds, cached,
                  video_duration=video.duration_seconds)
    clip = Clip(
        id=new_id("clip"), event_id=event.id, game_id=game.id, video_id=game.video_id,
        event_type=event.event_type, timestamp_seconds=event.timestamp_seconds,
        start_seconds=window.start_seconds, end_seconds=window.end_seconds,
        stored_path=str(cached), public_url=f"/media/clips/{cached.name}",
    )
    event.clip_id = clip.id
    store.save_clip(clip)
    store.save_event(event)
    return cached


def drop_event_media(event: Event) -> None:
    """Delete cached artifacts for an event (thumb + clip file + clip record)."""
    thumb_path(event.id).unlink(missing_ok=True)
    cached_clip_path(event.id).unlink(missing_ok=True)
    if event.clip_id:
        clip = store.clips.get(event.clip_id)
        if clip:
            if clip.stored_path:
                Path(clip.stored_path).unlink(missing_ok=True)
            store.delete_clip(event.clip_id)
```

Create `backend/app/api/routes/events.py`:

```python
"""Event CRUD in the frontend's API contract (under /api/games/{game_id})."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.ids import new_id
from app.models import Event, Game
from app.schemas.frontend_api import event_out
from app.services import media_service
from app.services.store import store

router = APIRouter()


class EventCreate(BaseModel):
    type: Literal["shot", "goal"]
    timestamp: float


class EventPatch(BaseModel):
    type: Literal["shot", "goal"] | None = None
    timestamp: float | None = None
    verified: bool | None = None


def _require_game(game_id: str) -> Game:
    game = store.get_game(game_id)
    if game is None:
        raise HTTPException(404, "Game not found")
    return game


def _require_event(game_id: str, event_id: str) -> Event:
    event = store.events.get(event_id)
    if event is None or event.game_id != game_id:
        raise HTTPException(404, "Event not found")
    return event


def _sync_event_count(game: Game) -> None:
    game.event_count = len(store.events_for_game(game.id))
    store.save_game(game)


@router.get("/{game_id}/events")
def list_events(game_id: str) -> list[dict]:
    game = _require_game(game_id)
    return [event_out(e, game.duration_seconds).model_dump()
            for e in store.events_for_game(game_id)]


@router.post("/{game_id}/events")
def create_event(game_id: str, body: EventCreate) -> dict:
    game = _require_game(game_id)
    event = Event(
        id=new_id("evt"), game_id=game_id, video_id=game.video_id,
        event_type=body.type, timestamp_seconds=body.timestamp,
        confidence=1.0, source="manual", verified=False,
    )
    store.save_event(event)
    _sync_event_count(game)
    media_service.extract_event_thumb(game, event)  # best-effort
    return event_out(event, game.duration_seconds).model_dump()


@router.patch("/{game_id}/events/{event_id}")
def patch_event(game_id: str, event_id: str, body: EventPatch) -> dict:
    game = _require_game(game_id)
    event = _require_event(game_id, event_id)
    changes = body.model_dump(exclude_none=True)
    if "type" in changes:
        event.event_type = changes["type"]
    if "verified" in changes:
        event.verified = changes["verified"]
    if "timestamp" in changes:
        event.timestamp_seconds = changes["timestamp"]
    if "timestamp" in changes or "type" in changes:
        # The clip window moved: drop stale artifacts, re-cut lazily on demand.
        media_service.drop_event_media(event)
        event.clip_id = None
        media_service.extract_event_thumb(game, event)
    store.save_event(event)
    return event_out(event, game.duration_seconds).model_dump()


@router.delete("/{game_id}/events/{event_id}")
def delete_event(game_id: str, event_id: str) -> dict:
    game = _require_game(game_id)
    event = _require_event(game_id, event_id)
    media_service.drop_event_media(event)
    store.delete_event(event_id)
    _sync_event_count(game)
    return {"ok": True}
```

In `backend/app/api/routes/games.py`: delete the `get_game_events` route and its now-unused imports (`EventOut`, `GameEventsResponse`).

In `backend/app/main.py`: add `events` to the routes import and register after games:

```python
app.include_router(events.router, prefix="/api/games", tags=["events"])
```

Update `backend/tests/integration/test_game_events_api.py` — the events assertions move to the frontend shape. Replace the block from `events = client.get(...)` to the end of the events checks with:

```python
    events = client.get(f"/api/games/{game_id}/events").json()
    assert len(events) == 2
    # Sorted by timestamp.
    assert events[0]["timestamp"] <= events[1]["timestamp"]
    # Goal not double-tagged as shot.
    types = [e["type"] for e in events]
    assert types == ["shot", "goal"]
    for e in events:
        assert e["source"] == "manual"
        assert e["confidence"] == 1.0
        assert e["verified"] is False
```

- [ ] **Step 4: Run, verify pass** — task tests + full backend suite.

- [ ] **Step 5: Commit** — `git commit -am "feat: events CRUD + media service in the frontend contract"`

---

### Task 5: Media routes (video, thumb.jpg, clip.mp4)

**Files:**
- Create: `backend/app/api/routes/media.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_frontend_media_api.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/integration/test_frontend_media_api.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

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
                        json={"type": "shot", "timestamp": 2.0}).json()
    return game_id, event["id"]


@requires_ffmpeg
def test_video_stream(client, sample_5s: Path):
    game_id, _ = _setup(client, sample_5s)
    resp = client.get(f"/api/games/{game_id}/video")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "video/mp4"


@requires_ffmpeg
def test_thumb_served(client, sample_5s: Path):
    game_id, event_id = _setup(client, sample_5s)
    resp = client.get(f"/api/games/{game_id}/events/{event_id}/thumb.jpg")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"


@requires_ffmpeg
def test_clip_cut_on_demand_and_cached(client, sample_5s: Path):
    game_id, event_id = _setup(client, sample_5s)
    resp = client.get(f"/api/games/{game_id}/events/{event_id}/clip.mp4")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "video/mp4"
    event = store.events.get(event_id)
    assert event.clip_id is not None  # cached as a Clip record
    assert client.get(f"/api/games/{game_id}/events/{event_id}/clip.mp4").status_code == 200


def test_media_404s(client):
    assert client.get("/api/games/none/video").status_code == 404
    assert client.get("/api/games/none/events/x/thumb.jpg").status_code == 404
    assert client.get("/api/games/none/events/x/clip.mp4").status_code == 404
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** — create `backend/app/api/routes/media.py`:

```python
"""Per-game media serving in the frontend's API contract."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.errors import AppError
from app.api.routes.events import _require_event, _require_game
from app.services import media_service
from app.services.store import store

router = APIRouter()


@router.get("/{game_id}/video")
def stream_video(game_id: str) -> FileResponse:
    game = _require_game(game_id)
    video = store.get_video(game.video_id) if game.video_id else None
    if video is None or not Path(video.stored_path).exists():
        raise HTTPException(404, "Video not found")
    # Starlette FileResponse handles HTTP Range requests (seeking).
    return FileResponse(video.stored_path, media_type="video/mp4")


@router.get("/{game_id}/events/{event_id}/thumb.jpg")
def event_thumb(game_id: str, event_id: str) -> FileResponse:
    game = _require_game(game_id)
    event = _require_event(game_id, event_id)
    thumb = media_service.thumb_path(event_id)
    if not thumb.exists():
        media_service.extract_event_thumb(game, event)
    if not thumb.exists():
        raise HTTPException(404, "Thumbnail not found")
    return FileResponse(thumb, media_type="image/jpeg")


@router.get("/{game_id}/events/{event_id}/clip.mp4")
def event_clip(game_id: str, event_id: str) -> FileResponse:
    """Streamable clip for in-app preview (and direct download)."""
    game = _require_game(game_id)
    event = _require_event(game_id, event_id)
    try:
        path = media_service.ensure_event_clip(game, event)
    except AppError as exc:
        raise HTTPException(exc.status_code, exc.message)
    return FileResponse(path, media_type="video/mp4")
```

In `backend/app/main.py`: add `media` to the routes import and register:

```python
app.include_router(media.router, prefix="/api/games", tags=["media"])
```

- [ ] **Step 4: Run, verify pass** — task tests + full suite.
- [ ] **Step 5: Commit** — `git commit -am "feat: video/thumb/clip media routes in the frontend contract"`

---

### Task 6: Video prep (ensure_h264) + match_processing_service (auto-analyze job)

**Files:**
- Modify: `backend/app/services/video_storage_service.py`, `backend/app/api/routes/games.py` (rewire `/process`)
- Create: `backend/app/services/match_processing_service.py`
- Test: `backend/tests/unit/test_match_processing.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/unit/test_match_processing.py`:

```python
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
    monkeypatch.setattr(mps, "_detect", lambda v: [
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
    monkeypatch.setattr(mps, "_detect", lambda v: [mps.DetectedEvent("shot", 4.0, 0.8)])
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
    monkeypatch.setattr(mps, "_detect", lambda v: (_ for _ in ()).throw(RuntimeError("boom")))
    mps.process_game(game.id)
    g = store.get_game(game.id)
    assert g.status == "failed"
    assert "boom" in g.error


def test_missing_video_marks_failed():
    store.save_game(Game(id="game_nv", title="T"))
    mps.process_game("game_nv")
    assert store.get_game("game_nv").status == "failed"
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement**

Add to `backend/app/services/video_storage_service.py` (top: `import subprocess`; the rest after `public_url_for_upload`):

```python
def _video_codec(path: Path) -> str:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    return out.stdout.strip()


def ensure_h264(video: Video) -> Video:
    """Re-encode in place when the codec isn't browser-playable (HEVC handling).

    Refreshes the stored metadata after conversion. Codec probe failures are
    non-fatal (detection can still run); conversion failures raise.
    """
    from app.core.errors import ProcessingError

    path = Path(video.stored_path)
    try:
        codec = _video_codec(path)
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("Codec probe failed for %s (%s); leaving as-is.", path.name, exc)
        return video
    if codec == "h264" or not codec:
        return video
    logger.info("Re-encoding %s (%s -> h264).", path.name, codec)
    tmp = path.with_suffix(".h264.mp4")
    res = subprocess.run(
        ["ffmpeg", "-i", str(path), "-c:v", "libx264", "-preset", "fast",
         "-c:a", "aac", "-movflags", "+faststart", "-y", str(tmp)],
        capture_output=True, text=True, timeout=3600,
    )
    if res.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise ProcessingError("Could not convert video to a playable format.",
                              code="CONVERSION_FAILED")
    tmp.replace(path)
    meta = get_video_metadata(path)
    video.duration_seconds = meta.duration_seconds
    video.fps = meta.fps
    video.width = meta.width
    video.height = meta.height
    return store.save_video(video)
```

Create `backend/app/services/match_processing_service.py`:

```python
"""Auto-analyze: run the real shot/goal detector on an imported game.

Dispatch by duration: short clips go through the two-stage whole-clip detector
(detection_service.analyze_demo_clip); long videos through the full-match
funnel (full_match_service.analyze_full_match). Unexpected failures mark the
game `failed`; an unavailable detector (no GEMINI_API_KEY) completes with zero
events so manual tagging still works.

Re-processing preserves curated work: only source='model' events that are not
verified are cleared before a run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.core.ids import new_id
from app.core.logging import get_logger
from app.models import Event, Video
from app.services import job_service, media_service
from app.services.store import store
from app.services.video_storage_service import ensure_h264

logger = get_logger(__name__)


@dataclass
class DetectedEvent:
    event_type: str
    timestamp_seconds: float
    confidence: float
    notes: str = ""


def _detector_available() -> bool:
    try:
        from app.services.vlm_service import get_vlm_judge

        return get_vlm_judge().available
    except Exception:
        return False


def _detect(video: Video) -> list[DetectedEvent]:
    if not _detector_available():
        logger.warning("Detector unavailable (no GEMINI_API_KEY?) — completing with zero events.")
        return []
    if video.duration_seconds <= settings.short_clip_max_seconds:
        from app.services.detection_service import analyze_demo_clip

        res = analyze_demo_clip(video.stored_path)
        if res.event_type in ("shot", "goal") and res.timestamp_seconds is not None:
            return [DetectedEvent(res.event_type, res.timestamp_seconds, res.confidence, res.explanation)]
        return []
    from app.services.full_match_service import analyze_full_match

    result = analyze_full_match(video.stored_path)
    return [
        DetectedEvent(e.event_type, e.timestamp_seconds, e.confidence, e.explanation)
        for e in result.events
    ]


def _clear_unverified_model_events(game_id: str) -> None:
    for event in list(store.events_for_game(game_id)):
        if event.source == "model" and not event.verified:
            media_service.drop_event_media(event)
            store.delete_event(event.id)


def process_game(game_id: str, job_id: str | None = None) -> None:
    """Run detection for a game. Safe as a background task or thread."""
    game = store.get_game(game_id)
    if game is None:
        logger.warning("process_game: unknown game %s", game_id)
        if job_id:
            job_service.update_job(job_id, status="failed", message=f"Unknown game {game_id}.")
        return
    try:
        game.status = "processing"
        game.error = None
        store.save_game(game)
        if job_id:
            job_service.update_job(job_id, status="processing", progress=5, message="Preparing video.")

        video = store.get_video(game.video_id) if game.video_id else None
        if video is None or not Path(video.stored_path).exists():
            raise FileNotFoundError("Source video is missing.")
        video = ensure_h264(video)
        if not game.duration_seconds:
            game.duration_seconds = video.duration_seconds
            store.save_game(game)

        if job_id:
            job_service.update_job(job_id, progress=15, message="Detecting shots and goals.")
        detected = _detect(video)

        _clear_unverified_model_events(game_id)
        for d in detected:
            event = Event(
                id=new_id("evt"), game_id=game_id, video_id=video.id,
                event_type=d.event_type, timestamp_seconds=d.timestamp_seconds,
                confidence=d.confidence, source="model", verified=False,
                notes=d.notes or None,
            )
            store.save_event(event)
            try:
                media_service.ensure_event_clip(game, event)
                media_service.extract_event_thumb(game, event)
            except Exception as exc:  # one bad clip must not abort the game
                logger.warning("Media generation failed for %s: %s", event.id, exc)

        game.event_count = len(store.events_for_game(game_id))
        game.status = "completed"
        store.save_game(game)
        if job_id:
            job_service.update_job(job_id, status="completed", progress=100,
                                   message=f"Found {len(detected)} events.")
        logger.info("Game %s processed: %d events.", game_id, len(detected))
    except Exception as exc:
        logger.exception("Processing failed for game %s", game_id)
        game = store.get_game(game_id)
        if game:
            game.status = "failed"
            game.error = str(exc)
            store.save_game(game)
        if job_id:
            job_service.update_job(job_id, status="failed", message=str(exc))
```

Rewire `/process` in `backend/app/api/routes/games.py` — replace the body's task line and message (this gives the user re-analyze for free):

```python
from app.services import job_service, match_processing_service, media_service
...
@router.post("/{game_id}/process", response_model=ProcessGameResponse)
def process_game(game_id: str, background_tasks: BackgroundTasks) -> ProcessGameResponse:
    """Re-run shot/goal detection for a game (manual + verified events survive)."""
    game = _require_game(game_id)

    job = job_service.create_job("full_game", game_id=game_id, message="Auto-analysis queued.")
    background_tasks.add_task(match_processing_service.process_game, game_id, job.id)

    return ProcessGameResponse(
        job_id=job.id,
        game_id=game_id,
        status="processing",
        message="Detection started. Results will be available shortly.",
    )
```

Remove the now-unused `processing_service` import from games.py. Check `tests/integration/test_game_events_api.py::test_full_game_processing_integration` — it calls `processing_service.process_game_from_annotations` directly (not via the route), so it still passes.

- [ ] **Step 4: Run, verify pass** — task tests + full suite.
- [ ] **Step 5: Commit** — `git commit -am "feat: auto-analyze processing service with curated-event-preserving reset"`

---

### Task 7: File import endpoint

**Files:**
- Create: `backend/app/api/routes/imports.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_import_api.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/integration/test_import_api.py`:

```python
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
    monkeypatch.setattr(match_processing_service, "_detect", lambda v: [])

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
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** — create `backend/app/api/routes/imports.py` (the drive routes arrive in Task 8; this file starts with just the file import):

```python
"""Game imports in the frontend's API contract."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile

from app.core.errors import AppError
from app.core.ids import new_id
from app.models import Game
from app.schemas.frontend_api import game_out
from app.services import job_service, match_processing_service, video_storage_service
from app.services.store import store

router = APIRouter()        # mounted at /api/games


@router.post("/import")
def import_file(file: UploadFile, background_tasks: BackgroundTasks) -> dict:
    try:
        stored = video_storage_service.save_upload(file, video_type="full_game", prefix="upload")
    except AppError as exc:
        raise HTTPException(400, exc.message)
    video = stored.video
    game = Game(
        id=new_id("game"),
        title=Path(file.filename or video.original_filename).stem,
        video_id=video.id,
        video_filename=video.stored_filename,
        status="processing",
        source_kind="local",
        source_url=None,
        duration_seconds=video.duration_seconds,
    )
    store.save_game(game)
    job = job_service.create_job("full_game", game_id=game.id, message="Auto-analysis queued.")
    background_tasks.add_task(match_processing_service.process_game, game.id, job.id)
    return game_out(game).model_dump()
```

In `backend/app/main.py`: add `imports` to the routes import and register BEFORE games (so nothing shadows it; method+path are distinct anyway):

```python
app.include_router(imports.router, prefix="/api/games", tags=["imports"])
```

- [ ] **Step 4: Run, verify pass** — task tests + full suite.
- [ ] **Step 5: Commit** — `git commit -am "feat: file import endpoint with auto-analyze"`

---

### Task 8: Drive import

**Files:**
- Create: `backend/app/services/drive_service.py`
- Modify: `backend/app/api/routes/imports.py`, `backend/app/main.py`, `backend/app/services/video_storage_service.py`
- Test: `backend/tests/integration/test_drive_api.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/integration/test_drive_api.py`:

```python
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
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement**

Add to `backend/app/services/video_storage_service.py` (after `save_path_as_upload`):

```python
def register_local_file(
    src_path: str | Path, *, original_name: str | None = None,
    video_type: str = "full_game", prefix: str = "drive",
) -> Video:
    """Move an already-downloaded local file into uploads and record a Video."""
    src = Path(src_path)
    if not src.exists():
        raise InvalidVideoError(f"Source file not found: {src}", code="VIDEO_NOT_FOUND")
    settings.ensure_dirs()
    stored_filename = safe_video_filename(prefix=prefix)
    dest = settings.uploads_dir / stored_filename
    shutil.move(str(src), dest)
    meta = get_video_metadata(dest)
    video = Video(
        id=new_id("vid"),
        original_filename=original_name or src.name,
        stored_filename=stored_filename,
        stored_path=str(dest),
        video_type=video_type,
        duration_seconds=meta.duration_seconds,
        fps=meta.fps,
        width=meta.width,
        height=meta.height,
    )
    return store.save_video(video)
```

Create `backend/app/services/drive_service.py`:

```python
"""Google Drive imports (public links) via gdown.

Ported from the MVP backend's importer.py: parse share links, list folder
videos without downloading, and import files in background threads so the
frontend can poll game status (downloading -> processing -> ready).
"""

from __future__ import annotations

import re
import threading
import uuid
from pathlib import Path

import gdown

from app.config import settings
from app.core.ids import new_id
from app.core.logging import get_logger
from app.models import Game
from app.services import job_service, match_processing_service
from app.services.store import store
from app.services.video_storage_service import register_local_file

logger = get_logger(__name__)

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
    try:
        files = gdown.download_folder(id=drive_id, skip_download=True, quiet=True)
    except gdown.exceptions.DownloadError:
        raise RuntimeError(NOT_PUBLIC_MSG)
    return [
        {"id": f.id, "name": Path(f.path).name}
        for f in files
        if Path(f.path).suffix.lower() in VIDEO_EXTS
    ]


def import_drive(url: str, file_ids: list[str] | None = None) -> list[Game]:
    """Import a Drive file link, or chosen videos from a folder link."""
    kind, drive_id = parse_drive_url(url)
    if kind == "file":
        return [_import_drive_file(url, drive_id, "Drive video")]
    files = list_drive_folder(url)
    if file_ids:
        files = [f for f in files if f["id"] in file_ids]
    return [_import_drive_file(url, f["id"], f["name"]) for f in files]


def _import_drive_file(url: str, drive_id: str, name: str) -> Game:
    """Create the game, then download + analyze in a background thread."""
    game = Game(id=new_id("game"), title=Path(name).stem, status="downloading",
                source_kind="drive", source_url=url)
    store.save_game(game)
    job = job_service.create_job("full_game", game_id=game.id, message="Downloading from Drive.")

    def work() -> None:
        settings.ensure_dirs()
        tmp = settings.uploads_dir / f"drive_tmp_{uuid.uuid4().hex[:8]}.mp4"
        try:
            try:
                gdown.download(id=drive_id, output=str(tmp), quiet=True)
            except gdown.exceptions.DownloadError:
                raise RuntimeError(NOT_PUBLIC_MSG)
            if not tmp.exists() or tmp.stat().st_size == 0:
                raise RuntimeError(NOT_PUBLIC_MSG)
            video = register_local_file(tmp, original_name=name)
            g = store.get_game(game.id)
            g.video_id = video.id
            g.video_filename = video.stored_filename
            g.duration_seconds = video.duration_seconds
            store.save_game(g)
            match_processing_service.process_game(game.id, job.id)
        except Exception as exc:
            logger.exception("Drive import failed for %s", game.id)
            tmp.unlink(missing_ok=True)
            g = store.get_game(game.id)
            if g:
                g.status = "failed"
                g.error = str(exc)
                store.save_game(g)
            job_service.update_job(job.id, status="failed", message=str(exc))

    threading.Thread(target=work, daemon=True).start()
    return game
```

Add to `backend/app/api/routes/imports.py`:

```python
from pydantic import BaseModel

from app.services import drive_service

drive_router = APIRouter()  # mounted at /api/drive


class DriveRequest(BaseModel):
    url: str
    fileIds: list[str] | None = None


@drive_router.post("/list")
def drive_list(body: DriveRequest) -> list[dict]:
    try:
        return drive_service.list_drive_folder(body.url)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))


@router.post("/import-drive")
def import_drive(body: DriveRequest) -> list[dict]:
    try:
        games = drive_service.import_drive(body.url, body.fileIds)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    return [game_out(g).model_dump() for g in games]
```

In `backend/app/main.py`:

```python
app.include_router(imports.drive_router, prefix="/api/drive", tags=["imports"])
```

- [ ] **Step 4: Run, verify pass** — task tests + full suite.
- [ ] **Step 5: Commit** — `git commit -am "feat: Google Drive import (list folder, background download, auto-analyze)"`

---

### Task 9: Email

**Files:**
- Create: `backend/app/services/email_service.py`
- Modify: `backend/app/api/routes/media.py`
- Test: `backend/tests/integration/test_email_api.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/integration/test_email_api.py`:

```python
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
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement**

Create `backend/app/services/email_service.py`:

```python
"""SMTP clip emailing (ported from the MVP backend's emailer.py).

Requires SMTP_USER and SMTP_PASS in backend/.env (for Gmail, an app password
from https://myaccount.google.com/apppasswords). Optional: SMTP_HOST
(default smtp.gmail.com), SMTP_PORT (587), SMTP_FROM.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path

from app.config import settings


class EmailNotConfigured(RuntimeError):
    pass


def send_clip_email(to: str, subject: str, body: str, attachment: Path) -> None:
    """Send a clip as an email attachment via SMTP (Gmail by default)."""
    if not settings.smtp_user or not settings.smtp_pass:
        raise EmailNotConfigured(
            "Email isn't configured — add SMTP_USER and SMTP_PASS to backend/.env "
            "(for Gmail, create an app password at myaccount.google.com/apppasswords)"
        )
    sender = settings.smtp_from or settings.smtp_user
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    msg.add_attachment(
        attachment.read_bytes(), maintype="video", subtype="mp4", filename=attachment.name
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_pass)
        smtp.send_message(msg)
```

Add to `backend/app/api/routes/media.py` (top: `import re`, `from pydantic import BaseModel`, `from app.services import email_service`):

```python
class EmailRequest(BaseModel):
    to: str


@router.post("/{game_id}/events/{event_id}/email")
def email_clip(game_id: str, event_id: str, body: EmailRequest) -> dict:
    if not re.fullmatch(r"\S+@\S+\.\S+", body.to.strip()):
        raise HTTPException(422, "Enter a valid email address")
    game = _require_game(game_id)
    event = _require_event(game_id, event_id)
    try:
        clip = media_service.ensure_event_clip(game, event)
    except AppError as exc:
        raise HTTPException(500, f"Export failed: {exc.message}")
    ts = event.timestamp_seconds
    when = f"{int(ts // 60)}:{int(ts % 60):02d}"
    subject = f"TeloraFooty clip: {game.title} — {event.event_type} at {when}"
    text = (f"Clip from {game.title} ({game.created_at.date().isoformat()}): "
            f"{event.event_type} at {when}. Video attached.")
    try:
        email_service.send_clip_email(body.to.strip(), subject, text, clip)
    except email_service.EmailNotConfigured as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Email failed: {exc}")
    return {"ok": True}
```

- [ ] **Step 4: Run, verify pass** — task tests + full suite.
- [ ] **Step 5: Commit** — `git commit -am "feat: SMTP clip email in the frontend contract"`

---

### Task 10: Cleanup — seed off, env example, README

**Files:**
- Modify: `backend/app/config.py` (`enable_seed: bool = False`), `backend/.env.example`, `README.md`

- [ ] **Step 1: Flip seed default** — in `backend/app/config.py`: `enable_seed: bool = False` (comment: real imports replace demo seeding).

- [ ] **Step 2: Update `backend/.env.example`** — make sure it documents both detector and SMTP config:

```
# Gemini VLM detector (required for automatic shot/goal detection;
# without it, imports still work and events can be tagged manually)
GEMINI_API_KEY=

# SMTP clip emailing (optional; for Gmail use an app password from
# https://myaccount.google.com/apppasswords)
SMTP_USER=
SMTP_PASS=
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_FROM=
```

(Keep any other documented keys already present in malik's .env.example.)

- [ ] **Step 3: Update `README.md`** — replace the backend run instructions with the combined setup:

```markdown
## Running

Backend (FastAPI, port 8000):

    cd backend
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    cp .env.example .env   # add GEMINI_API_KEY for detection, SMTP_* for email
    .venv/bin/uvicorn app.main:app --reload

Frontend (Vite dev server, proxies /api to :8000):

    cd frontend
    npm install
    npm run dev
```

(Adapt to the existing README structure — edit the relevant sections, don't blindly replace unrelated content.)

- [ ] **Step 4: Run full suites, commit** — backend + frontend tests pass → `git commit -am "chore: disable demo seeding, document combined setup"`

---

### Task 11: End-to-end verification

- [ ] **Step 1: Full test suites**

```bash
cd backend && .venv/bin/python -m pytest        # all pass
cd ../frontend && npm test && npm run build      # all pass, build clean
```

- [ ] **Step 2: Boot both servers**

```bash
cd backend && .venv/bin/uvicorn app.main:app --port 8000 &   # background
cd frontend && npm run dev &                                  # background
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/games
```

- [ ] **Step 3: Curl smoke through the whole contract** (generate a tiny test video with ffmpeg first):

```bash
ffmpeg -f lavfi -i testsrc=size=320x240:rate=15:duration=5 -pix_fmt yuv420p /tmp/smoke.mp4
# import → game id
curl -s -F "file=@/tmp/smoke.mp4" http://127.0.0.1:8000/api/games/import
# poll until status ready (detector likely unavailable without key → ready, 0 events)
curl -s http://127.0.0.1:8000/api/games/<id>
# manual event → thumb → clip → patch verified → delete
curl -s -X POST -H 'Content-Type: application/json' -d '{"type":"shot","timestamp":2}' http://127.0.0.1:8000/api/games/<id>/events
curl -s -o /tmp/t.jpg -w "%{http_code}" http://127.0.0.1:8000/api/games/<id>/events/<eid>/thumb.jpg
curl -s -o /tmp/c.mp4 -w "%{http_code}" http://127.0.0.1:8000/api/games/<id>/events/<eid>/clip.mp4
curl -s -X PATCH -H 'Content-Type: application/json' -d '{"verified":true}' http://127.0.0.1:8000/api/games/<id>/events/<eid>
curl -s -X DELETE http://127.0.0.1:8000/api/games/<id>
```

- [ ] **Step 4: Browser check** — open the Vite dev URL with Playwright, confirm the Library renders, the imported game appears, and the Player opens. Take a screenshot for the user.

- [ ] **Step 5: Fix anything found, commit fixes.**

---

### Task 12: Land on main

- [ ] **Step 1:** `git checkout main && git merge combine` (fast-forward expected).
- [ ] **Step 2:** ASK THE USER before pushing: pushing `main` and flipping `origin/HEAD` to `main` (`git remote set-head origin main` after changing the default branch on the host) affects the shared remote. Get explicit confirmation, then push.
- [ ] **Step 3:** Suggest archiving `backend/malik` (e.g. tag `archive/backend-malik` at its tip) — user's call.
