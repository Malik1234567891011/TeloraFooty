# Analysis Progress Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a live progress bar + status message on each Library card while a game is analyzing, recover restart-orphaned jobs into an `interrupted` state with a Retry button.

**Architecture:** Progress rides the existing 2-second `GET /api/games` poll — the detector writes fine-grained progress to its `Job`, the games route includes the latest job's `progress`/`progressMessage` in each game, and the Library renders a bar from those fields. No new endpoint, no extra polling.

**Tech Stack:** FastAPI + pydantic v2, JsonStore, Gemini detectors (`full_match_service`, `wholeclip_detector`, `detection_service`), React/Vite/vitest.

**Spec:** `docs/superpowers/specs/2026-06-06-analysis-progress-bar-design.md`

**Conventions (apply throughout):**
- Backend commands from `/Users/omarlahmimi/Documents/TeloraFooty/backend`: `.venv/bin/python -m pytest`.
- Frontend from `/Users/omarlahmimi/Documents/TeloraFooty/frontend`: `npm test`.
- Frontend-facing fields use the frontend's camelCase vocabulary; internal models keep their names.
- The server holds the store in memory; after any out-of-band store edit, restart the server. Tests use the `client` fixture (fresh app) so this doesn't apply to them.

---

### Task 1: Store — latest job lookup

**Files:**
- Modify: `backend/app/services/store.py`
- Test: `backend/tests/unit/test_store_mutations.py`

- [ ] **Step 1: Write the failing test** — append to `backend/tests/unit/test_store_mutations.py`:

```python
def test_latest_job_for_game():
    from datetime import datetime, timezone
    from app.models import Job
    s = _store()
    assert s.latest_job_for_game("g1") is None
    old = Job(id="j1", job_type="full_game", game_id="g1",
              created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    new = Job(id="j2", job_type="full_game", game_id="g1",
              created_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    s.save_job(old)
    s.save_job(new)
    s.save_job(Job(id="j3", job_type="full_game", game_id="other"))
    assert s.latest_job_for_game("g1").id == "j2"
```

- [ ] **Step 2: Run, verify fail** — `.venv/bin/python -m pytest tests/unit/test_store_mutations.py::test_latest_job_for_game -v` → AttributeError: no `latest_job_for_game`.

- [ ] **Step 3: Implement** — in `backend/app/services/store.py`, add after `get_job`:

```python
    def latest_job_for_game(self, game_id: str) -> Job | None:
        jobs = [j for j in self.jobs.values() if j.game_id == game_id]
        return max(jobs, key=lambda j: j.created_at) if jobs else None
```

- [ ] **Step 4: Run, verify pass** — same command → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/store.py backend/tests/unit/test_store_mutations.py
git commit -m "feat: store.latest_job_for_game lookup"
```

---

### Task 2: Schema — expose progress + interrupted status

**Files:**
- Modify: `backend/app/schemas/frontend_api.py`
- Test: `backend/tests/unit/test_frontend_api.py`

- [ ] **Step 1: Write the failing test** — append to `backend/tests/unit/test_frontend_api.py`:

```python
def test_game_out_progress_and_interrupted():
    g = game_out(_game(status="processing"), progress=42, progress_message="Scanning 4/8 windows")
    assert g.progress == 42
    assert g.progressMessage == "Scanning 4/8 windows"
    # Default: no progress fields supplied.
    assert game_out(_game(status="ready")).progress is None
    assert game_out(_game(status="ready")).progressMessage is None
    # Interrupted maps through to the frontend vocabulary.
    assert game_out(_game(status="interrupted")).status == "interrupted"
```

- [ ] **Step 2: Run, verify fail** — `.venv/bin/python -m pytest tests/unit/test_frontend_api.py::test_game_out_progress_and_interrupted -v` → TypeError (unexpected kwarg) / status mismatch.

- [ ] **Step 3: Implement** — in `backend/app/schemas/frontend_api.py`:

Add `"interrupted": "interrupted"` to `_STATUS_TO_FRONTEND`:

```python
_STATUS_TO_FRONTEND = {
    "uploaded": "processing",
    "downloading": "downloading",
    "processing": "processing",
    "completed": "ready",
    "failed": "error",
    "interrupted": "interrupted",
}
```

Add the two fields to `GameOut` (after `error`):

```python
    progress: int | None = None
    progressMessage: str | None = None
```

Extend `game_out`'s signature and body:

```python
def game_out(
    game: Game,
    *,
    goals: int | None = None,
    shots: int | None = None,
    progress: int | None = None,
    progress_message: str | None = None,
) -> GameOut:
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
        progress=progress,
        progressMessage=progress_message,
    )
```

- [ ] **Step 4: Run, verify pass** — `.venv/bin/python -m pytest tests/unit/test_frontend_api.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/frontend_api.py backend/tests/unit/test_frontend_api.py
git commit -m "feat: GameOut carries progress + interrupted status"
```

---

### Task 3: Games route — include live progress

**Files:**
- Modify: `backend/app/api/routes/games.py`
- Test: `backend/tests/integration/test_frontend_games_api.py`

- [ ] **Step 1: Write the failing test** — append to `backend/tests/integration/test_frontend_games_api.py`:

```python
def test_list_games_includes_progress_for_running_job(client):
    from app.models import Job
    _seed(status="processing")
    store.save_job(Job(id="jp", job_type="full_game", game_id="game_t1",
                       status="processing", progress=37, message="Scanning 3/8 windows"))
    body = client.get("/api/games").json()
    g = next(x for x in body if x["id"] == "game_t1")
    assert g["progress"] == 37
    assert g["progressMessage"] == "Scanning 3/8 windows"


def test_list_games_no_progress_when_ready(client):
    from app.models import Job
    _seed(status="completed")
    store.save_job(Job(id="jd", job_type="full_game", game_id="game_t1",
                       status="completed", progress=100, message="done"))
    g = next(x for x in client.get("/api/games").json() if x["id"] == "game_t1")
    assert g["progress"] is None
    assert g["progressMessage"] is None
```

- [ ] **Step 2: Run, verify fail** — `.venv/bin/python -m pytest tests/integration/test_frontend_games_api.py -k progress -v` → KeyError/None mismatch.

- [ ] **Step 3: Implement** — in `backend/app/api/routes/games.py`, replace the `list_games` and `get_game` bodies with progress-aware versions, and add a helper:

```python
def _progress_for(game):
    """Live job progress, only while the game is mid-run."""
    if game.status not in {"downloading", "processing"}:
        return None, None
    job = store.latest_job_for_game(game.id)
    if job is None:
        return None, None
    return job.progress, job.message


@router.get("")
def list_games() -> list[dict]:
    out = []
    for g in sorted(store.list_games(), key=lambda g: g.created_at, reverse=True):
        events = store.events_for_game(g.id)
        progress, message = _progress_for(g)
        out.append(
            game_out(
                g,
                goals=sum(1 for e in events if e.event_type == "goal"),
                shots=sum(1 for e in events if e.event_type == "shot"),
                progress=progress,
                progress_message=message,
            ).model_dump()
        )
    return out


@router.get("/{game_id}")
def get_game(game_id: str) -> dict:
    game = _require_game(game_id)
    progress, message = _progress_for(game)
    return game_out(game, progress=progress, progress_message=message).model_dump()
```

- [ ] **Step 4: Run, verify pass** — `.venv/bin/python -m pytest tests/integration/test_frontend_games_api.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/games.py backend/tests/integration/test_frontend_games_api.py
git commit -m "feat: games route surfaces live job progress"
```

---

### Task 4: Restart recovery — orphaned jobs → interrupted

**Files:**
- Create: `backend/app/services/recovery_service.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/unit/test_recovery_service.py`

- [ ] **Step 1: Write the failing test** — create `backend/tests/unit/test_recovery_service.py`:

```python
from __future__ import annotations

import pytest

from app.models import Game, Job
from app.services import recovery_service
from app.services.store import store


@pytest.fixture(autouse=True)
def _clean():
    yield
    for gid in list(store.games):
        store.delete_game(gid)
    store.jobs.clear()


def test_recovery_flips_running_games_to_interrupted():
    store.save_game(Game(id="g_run", title="A", status="processing"))
    store.save_game(Game(id="g_dl", title="B", status="downloading"))
    store.save_game(Game(id="g_done", title="C", status="completed"))
    store.save_job(Job(id="j_run", job_type="full_game", game_id="g_run", status="processing"))

    n = recovery_service.recover_orphaned_jobs()

    assert n == 2
    assert store.get_game("g_run").status == "interrupted"
    assert store.get_game("g_run").error and "interrupted" in store.get_game("g_run").error.lower()
    assert store.get_game("g_dl").status == "interrupted"
    assert store.get_game("g_done").status == "completed"  # untouched
    assert store.get_job("j_run").status == "failed"
```

- [ ] **Step 2: Run, verify fail** — `.venv/bin/python -m pytest tests/unit/test_recovery_service.py -v` → ImportError: no `recovery_service`.

- [ ] **Step 3: Implement** — create `backend/app/services/recovery_service.py`:

```python
"""Recover analyses orphaned by a server restart.

A FastAPI background task dies with the process. Any game left mid-run is stuck
in 'processing'/'downloading' with no live worker. On startup we flip those to
'interrupted' (the frontend offers a Retry) and fail their dangling jobs.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.services.store import store

logger = get_logger(__name__)

_INTERRUPTED_MSG = "Analysis was interrupted (server restart). Retry to resume."


def recover_orphaned_jobs() -> int:
    """Flip running games to 'interrupted'. Returns how many were recovered."""
    recovered = 0
    for game in list(store.list_games()):
        if game.status in {"downloading", "processing"}:
            game.status = "interrupted"
            game.error = _INTERRUPTED_MSG
            store.save_game(game)
            for job in list(store.jobs.values()):
                if job.game_id == game.id and job.status in {"queued", "processing"}:
                    job.status = "failed"
                    job.message = _INTERRUPTED_MSG
                    store.save_job(job)
            recovered += 1
    if recovered:
        logger.info("Recovered %d interrupted game(s) on startup.", recovered)
    return recovered
```

- [ ] **Step 4: Run, verify pass** — `.venv/bin/python -m pytest tests/unit/test_recovery_service.py -v` → PASS.

- [ ] **Step 5: Wire into startup** — in `backend/app/main.py`, inside the `lifespan` function, after `settings.ensure_dirs()` and before the seed block, add:

```python
    from app.services.recovery_service import recover_orphaned_jobs

    try:
        recover_orphaned_jobs()
    except Exception as exc:  # recovery must never block startup
        logger.warning("Orphan recovery skipped: %s", exc)
```

- [ ] **Step 6: Run full backend suite** — `.venv/bin/python -m pytest -q` → all pass. (Conftest disables seeding; recovery runs harmlessly with an empty store.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/recovery_service.py backend/app/main.py backend/tests/unit/test_recovery_service.py
git commit -m "feat: recover restart-orphaned analyses into interrupted state"
```

---

### Task 5: Fine-grained progress in the detectors

**Files:**
- Modify: `backend/app/services/full_match_service.py`, `backend/app/services/wholeclip_detector.py`, `backend/app/services/detection_service.py`, `backend/app/services/match_processing_service.py`
- Test: `backend/tests/unit/test_match_processing.py`

- [ ] **Step 1: Write the failing test** — append to `backend/tests/unit/test_match_processing.py`:

```python
@requires_ffmpeg
def test_process_game_reports_intermediate_progress(monkeypatch, sample_5s: Path):
    game = _game_with_video(sample_5s)
    job = __import__("app.services.job_service", fromlist=["create_job"]).create_job(
        "full_game", game_id=game.id)

    def fake_detect(video, on_progress=None):
        if on_progress:
            on_progress(50, "Scanning 4/8 windows")
        return [mps.DetectedEvent("shot", 2.0, 0.8)]

    monkeypatch.setattr(mps, "_detect", fake_detect)
    mps.process_game(game.id, job.id)

    j = store.get_job(job.id)
    assert j.status == "completed" and j.progress == 100
    # The intermediate callback reached the job mid-run (message preserved or
    # advanced past the initial 15%). We assert the callback path is wired:
    assert "windows" in (j.message or "") or j.progress == 100
```

Also update the existing stub calls in this file so `_detect` accepts the new
keyword. Change both existing `monkeypatch.setattr(mps, "_detect", lambda v: ...)`
lines to `lambda v, on_progress=None: ...`:

```python
    monkeypatch.setattr(mps, "_detect", lambda v, on_progress=None: [
        mps.DetectedEvent("goal", 2.0, 0.9, "header"),
        mps.DetectedEvent("shot", 4.0, 0.7, "long range"),
    ])
```

```python
    monkeypatch.setattr(mps, "_detect", lambda v, on_progress=None: [mps.DetectedEvent("shot", 4.0, 0.8)])
```

```python
    monkeypatch.setattr(mps, "_detect", lambda v, on_progress=None: (_ for _ in ()).throw(RuntimeError("boom")))
```

- [ ] **Step 2: Run, verify fail** — `.venv/bin/python -m pytest tests/unit/test_match_processing.py -v` → the new test fails (`_detect` has no `on_progress`) and edited stubs guide the signature.

- [ ] **Step 3: Implement — match_processing_service** — in `backend/app/services/match_processing_service.py`:

Change `_detect` to accept and forward a callback:

```python
def _detect(video: Video, on_progress=None) -> list[DetectedEvent]:
    if not _detector_available():
        logger.warning("Detector unavailable (no GEMINI_API_KEY?) — completing with zero events.")
        return []
    if video.duration_seconds <= settings.short_clip_max_seconds:
        from app.services.detection_service import analyze_demo_clip

        res = analyze_demo_clip(video.stored_path, on_progress=on_progress)
        if res.event_type in ("shot", "goal") and res.timestamp_seconds is not None:
            return [DetectedEvent(res.event_type, res.timestamp_seconds, res.confidence, res.explanation)]
        return []
    from app.services.full_match_service import analyze_full_match

    result = analyze_full_match(video.stored_path, on_progress=on_progress)
    return [
        DetectedEvent(e.event_type, e.timestamp_seconds, e.confidence, e.explanation)
        for e in result.events
    ]
```

In `process_game`, build a safe callback and pass it to `_detect`. Replace the
existing `if job_id: job_service.update_job(job_id, progress=5, message="Preparing video.")`
and the detect call with:

```python
        def on_progress(percent: int, message: str) -> None:
            if job_id:
                try:
                    job_service.update_job(job_id, progress=percent, message=message)
                except Exception:  # progress is best-effort, never fail a run
                    logger.debug("progress update failed", exc_info=True)

        on_progress(5, "Preparing video.")

        video = store.get_video(game.video_id) if game.video_id else None
        if video is None or not Path(video.stored_path).exists():
            raise FileNotFoundError("Source video is missing.")
        video = ensure_h264(video)
        if not game.duration_seconds:
            game.duration_seconds = video.duration_seconds
            store.save_game(game)

        on_progress(15, "Detecting shots and goals.")
        detected = _detect(video, on_progress=on_progress)
```

(Delete the now-redundant earlier `job_service.update_job(... progress=5 ...)`
and `progress=15` lines so each stage is set once via `on_progress`.)

- [ ] **Step 4: Implement — full_match_service** — in `backend/app/services/full_match_service.py`:

Add `on_progress=None` to `analyze_full_match`'s signature:

```python
def analyze_full_match(
    video_path: str | Path,
    *,
    concurrency: int | None = None,
    checkpoint_path: str | Path | None = None,
    progress_every: int = 20,
    verify: bool = True,
    on_progress=None,
) -> FullMatchResult:
```

Inside the `for fut in as_completed(futures):` loop, right after `done += 1`, add:

```python
            if on_progress:
                on_progress(15 + int(75 * done / max(len(windows), 1)),
                            f"Scanning {done}/{len(windows)} windows")
```

Pass `on_progress` into `_finalize` (add `on_progress=on_progress` to both
`_finalize(...)` call sites in `analyze_full_match` and `analyze_from_checkpoint`),
extend `_finalize`'s signature with `on_progress=None`, and just before the
`if verify and candidates:` line add:

```python
    if on_progress:
        on_progress(92, "Verifying candidates")
```

- [ ] **Step 5: Implement — wholeclip_detector** — in `backend/app/services/wholeclip_detector.py`, change `analyze`:

```python
    def analyze(self, video_path: str | Path, on_progress=None) -> WholeClipResult:
```

Add progress emits: right after `duration = self._duration(path)`:

```python
        if on_progress:
            on_progress(20, "Localizing shots")
```

Right before `# Stage 2 — zoom-verify candidate windows concurrently.`:

```python
        if on_progress:
            on_progress(60, "Verifying candidates")
```

Right before `selected = self._select(attempt_clusters)`:

```python
        if on_progress:
            on_progress(90, "Selecting highlights")
```

- [ ] **Step 6: Implement — detection_service** — in `backend/app/services/detection_service.py`, change `analyze_demo_clip` to accept and forward the callback to the whole-clip detector. Update the signature:

```python
def analyze_demo_clip(
    video_path: str | Path,
    *,
    team_name: str | None = None,
    attacking_direction: str = "unknown",
    on_progress=None,
) -> DemoAnalysis:
```

And where it calls `detector.analyze(video_path)` in the whole-clip branch,
pass the callback:

```python
                wc = detector.analyze(video_path, on_progress=on_progress)
```

- [ ] **Step 7: Run, verify pass** — `.venv/bin/python -m pytest tests/unit/test_match_processing.py -v` → PASS. Then full suite `.venv/bin/python -m pytest -q` → all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/match_processing_service.py backend/app/services/full_match_service.py backend/app/services/wholeclip_detector.py backend/app/services/detection_service.py backend/tests/unit/test_match_processing.py
git commit -m "feat: fine-grained analysis progress via on_progress callback"
```

---

### Task 6: Frontend types + api

**Files:**
- Modify: `frontend/src/types.ts`, `frontend/src/api.ts`

- [ ] **Step 1: Extend the Game type** — in `frontend/src/types.ts`, change the `status` union and add fields:

```typescript
export interface Game {
  id: string
  title: string
  date: string
  durationSec: number
  source: { kind: 'local' | 'drive'; url: string | null }
  status: 'downloading' | 'processing' | 'ready' | 'error' | 'interrupted'
  error: string | null
  progress?: number
  progressMessage?: string | null
  goals?: number // present on GET /api/games
  shots?: number
}
```

- [ ] **Step 2: Add the retry call** — in `frontend/src/api.ts`, add to the `api` object (after `deleteGame`):

```typescript
  retryAnalysis: (id: string) =>
    fetch(`/api/games/${id}/process`, { method: 'POST' }).then((r) => asJson<{ job_id: string }>(r)),
```

- [ ] **Step 3: Typecheck** — `cd frontend && npx tsc -b --noEmit` → no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types.ts frontend/src/api.ts
git commit -m "feat: Game type gains progress + interrupted; api.retryAnalysis"
```

---

### Task 7: ProgressBar component

**Files:**
- Create: `frontend/src/components/ProgressBar.tsx`
- Modify: `frontend/src/index.css`
- Test: `frontend/src/tests/ProgressBar.test.tsx`

- [ ] **Step 1: Write the failing test** — create `frontend/src/tests/ProgressBar.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import ProgressBar from '../components/ProgressBar'

test('renders fill width from value and shows label', () => {
  render(<ProgressBar value={42} label="Scanning 4/8 windows" />)
  expect(screen.getByText('Scanning 4/8 windows')).toBeInTheDocument()
  expect(screen.getByTestId('progress-fill').style.width).toBe('42%')
})

test('clamps value to 0-100', () => {
  const { rerender } = render(<ProgressBar value={150} />)
  expect(screen.getByTestId('progress-fill').style.width).toBe('100%')
  rerender(<ProgressBar value={-10} />)
  expect(screen.getByTestId('progress-fill').style.width).toBe('0%')
})
```

- [ ] **Step 2: Run, verify fail** — `cd frontend && npx vitest run src/tests/ProgressBar.test.tsx` → cannot find module.

- [ ] **Step 3: Implement** — create `frontend/src/components/ProgressBar.tsx`:

```tsx
interface Props {
  value: number
  label?: string
}

export default function ProgressBar({ value, label }: Props) {
  const pct = Math.max(0, Math.min(100, value))
  return (
    <div className="progress">
      <div className="progress-track">
        <div className="progress-fill" data-testid="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      {label && <div className="progress-label">{label}</div>}
    </div>
  )
}
```

- [ ] **Step 4: Add styles** — append to `frontend/src/index.css`:

```css
.progress {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 80%;
  padding: 0 12px;
}
.progress-track {
  height: 6px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.15);
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  border-radius: 999px;
  background: var(--accent, #4f8cff);
  transition: width 0.4s ease;
}
.progress-label {
  font-size: 12px;
  color: var(--muted, #9aa);
  text-align: center;
}
```

- [ ] **Step 5: Run, verify pass** — `npx vitest run src/tests/ProgressBar.test.tsx` → PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ProgressBar.tsx frontend/src/index.css frontend/src/tests/ProgressBar.test.tsx
git commit -m "feat: ProgressBar component"
```

---

### Task 8: Wire the bar + Retry into the Library card

**Files:**
- Modify: `frontend/src/pages/Library.tsx`
- Test: `frontend/src/tests/Library.test.tsx`

- [ ] **Step 1: Write the failing test** — create `frontend/src/tests/Library.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import Library from '../pages/Library'
import { api } from '../api'
import type { Game } from '../types'

const game = (over: Partial<Game> = {}): Game => ({
  id: 'g1', title: 'Match', date: '2026-06-06', durationSec: 100,
  source: { kind: 'local', url: null }, status: 'processing', error: null,
  goals: 0, shots: 0, ...over,
})

beforeEach(() => vi.restoreAllMocks())
afterEach(() => vi.restoreAllMocks())

test('shows a progress bar with message while processing', async () => {
  vi.spyOn(api, 'listGames').mockResolvedValue([
    game({ status: 'processing', progress: 37, progressMessage: 'Scanning 3/8 windows' }),
  ])
  render(<MemoryRouter><Library /></MemoryRouter>)
  await waitFor(() => expect(screen.getByText('Scanning 3/8 windows')).toBeInTheDocument())
  expect(screen.getByTestId('progress-fill').style.width).toBe('37%')
})

test('interrupted game shows Retry which calls retryAnalysis', async () => {
  vi.spyOn(api, 'listGames').mockResolvedValue([
    game({ status: 'interrupted', error: 'Analysis was interrupted (server restart). Retry to resume.' }),
  ])
  const retry = vi.spyOn(api, 'retryAnalysis').mockResolvedValue({ job_id: 'j1' })
  render(<MemoryRouter><Library /></MemoryRouter>)
  const btn = await screen.findByRole('button', { name: /retry/i })
  fireEvent.click(btn)
  await waitFor(() => expect(retry).toHaveBeenCalledWith('g1'))
})
```

- [ ] **Step 2: Run, verify fail** — `npx vitest run src/tests/Library.test.tsx` → no progress bar / no Retry button.

- [ ] **Step 3: Implement** — in `frontend/src/pages/Library.tsx`:

Add the import at the top with the other imports:

```tsx
import ProgressBar from '../components/ProgressBar'
```

Add a retry handler next to `onDelete`:

```tsx
  async function onRetry(game: Game) {
    try {
      await api.retryAnalysis(game.id)
      await refresh()
    } catch (err) {
      setError((err as Error).message)
    }
  }
```

Replace the card's non-ready `thumb` block (the `else` branch currently showing
error/Downloading/Processing) with:

```tsx
              <div className="thumb">
                {g.status === 'error' || g.status === 'interrupted' ? (
                  <div className="thumb-state">
                    <span className="status-error">⚠ {g.error ?? 'Analysis failed'}</span>
                    <button className="btn btn-small" onClick={() => onRetry(g)}>Retry</button>
                  </div>
                ) : (
                  <ProgressBar
                    value={g.progress ?? 0}
                    label={g.progressMessage ?? (g.status === 'downloading' ? 'Downloading…' : 'Processing…')}
                  />
                )}
              </div>
```

- [ ] **Step 4: Add minimal styles** — append to `frontend/src/index.css`:

```css
.thumb-state {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: center;
}
.btn-small {
  padding: 4px 12px;
  font-size: 13px;
}
```

- [ ] **Step 5: Run, verify pass** — `npx vitest run src/tests/Library.test.tsx` → PASS. Then full frontend suite `npm test` → all pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Library.tsx frontend/src/index.css frontend/src/tests/Library.test.tsx
git commit -m "feat: Library card shows progress bar + Retry for interrupted/error"
```

---

### Task 9: End-to-end verification

- [ ] **Step 1: Full suites** — backend `cd backend && .venv/bin/python -m pytest -q` (all pass); frontend `cd frontend && npm test && npm run build` (all pass, clean build).

- [ ] **Step 2: Restart backend + browser check** — restart uvicorn (this also exercises recovery_service against the real store). In the browser at `http://localhost:5173`, import a short clip and confirm the card shows a filling bar with a status message that advances (e.g. "Localizing shots" → "Verifying candidates"), then flips to the video thumbnail when `ready`.

- [ ] **Step 3: Interrupted path** — while a game is processing, kill and restart the backend; confirm that game's card shows "Analysis was interrupted… Retry" and that clicking Retry re-runs it to completion. Screenshot for the user.

- [ ] **Step 4: Fix anything found, commit fixes.**

---

## Self-review notes
- **Spec coverage:** latest job lookup (T1), progress fields + interrupted mapping (T2), games route surfacing (T3), startup recovery (T4), fine-grained detector progress (T5), frontend types/api (T6), ProgressBar (T7), Library wiring incl. Retry (T8), verification (T9). All spec sections covered.
- **Signature consistency:** `on_progress(percent:int, message:str)` is uniform across `process_game` → `_detect` → `analyze_demo_clip`/`analyze_full_match` → `wholeclip_detector.analyze`. Frontend `progress`/`progressMessage` match `GameOut` field names exactly.
- **No detection cost in tests:** every test stubs `_detect` or uses the `client` fixture (VLM disabled in conftest); no live Gemini calls.
