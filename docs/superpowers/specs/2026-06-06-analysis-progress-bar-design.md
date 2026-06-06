# Analysis Progress Bar — Design

**Date:** 2026-06-06
**Status:** Approved
**Branch:** `main`

## Context

Importing a game auto-runs the shot/goal detector as a FastAPI background task.
Today the user gets no feedback beyond a static "Processing…" on the Library
card, and three things make that painful:

1. The frontend never surfaces analysis progress, even though the backend
   already has a `Job` model (`progress` 0–100, `message`, `status`) and a
   `GET /api/jobs/{id}` endpoint.
2. The games API (`game_out`) doesn't expose the job, so the frontend can't
   reach the progress it would need.
3. Detection emits only coarse progress — `match_processing_service.process_game`
   sets 5 (prep) → 15 (detecting) → 100 (done) and **sits at 15% for the entire
   scan**, which on a 2-hour match is minutes of apparent freeze.
4. A server restart kills in-flight background tasks, leaving games stuck in
   `processing` forever (this happened to a real upload during this session).

### Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Where does the bar show? | Library card (replaces "Processing…") |
| Detail level | Progress bar + live status message |
| Restart-orphaned jobs | Mark `interrupted` on startup + Retry button |

## Architecture

Progress rides the **existing 2-second games poll** — no new endpoint, no
separate `/api/jobs` polling, no WebSocket/SSE. The detector writes fine-grained
progress to its `Job`; `GET /api/games` reads the game's latest job and includes
`progress`/`progressMessage` in each game; the Library renders a bar from those
fields.

```
detector (on_progress callback) → job_service.update_job(progress, message)
        → Job persisted in store
GET /api/games  →  game_out(game, progress=…, progressMessage=…)   [latest job]
        → Library polls every 2s → ProgressBar fills + shows message
```

## Components

### 1. Store: latest job lookup
`backend/app/services/store.py` — add:
```python
def latest_job_for_game(self, game_id: str) -> Job | None:
    jobs = [j for j in self.jobs.values() if j.game_id == game_id]
    return max(jobs, key=lambda j: j.created_at) if jobs else None
```

### 2. Schema: expose progress
`backend/app/schemas/frontend_api.py`:
- `GameOut` gains `progress: int | None = None` and `progressMessage: str | None = None`.
- `game_out(game, *, goals=None, shots=None, progress=None, progress_message=None)`
  passes them through.
- `_STATUS_TO_FRONTEND` gains `"interrupted": "interrupted"`.

`backend/app/api/routes/games.py` — `list_games` and `get_game` look up
`store.latest_job_for_game(g.id)` and pass `progress`/`progress_message` when the
game is mid-run (`status in {downloading, processing}`); otherwise `None`.

### 3. Fine-grained detector progress (the core fix)
A uniform callback `on_progress: Callable[[int, str], None] | None` threaded into
both detectors. `match_processing_service.process_game` builds a closure
`lambda p, m: job_service.update_job(job_id, progress=p, message=m)` (no-op when
`job_id` is None) and passes it down. The game status stays `processing`
throughout; only the job's `progress`/`message` change.

- **Full match** — `full_match_service.analyze_full_match(..., on_progress=None)`:
  inside the existing `as_completed` window loop, call
  `on_progress(15 + int(75 * done/total), f"Scanning {done}/{total} windows")`;
  before verification in `_finalize`, `on_progress(92, "Verifying candidates")`.
- **Short clips** — `wholeclip_detector.analyze(..., on_progress=None)`:
  `on_progress(20, "Localizing shots")` before stage 1,
  `on_progress(60, "Verifying candidates")` before stage 2,
  `on_progress(90, "Selecting highlights")` before `_select`.
- `detection_service.analyze_demo_clip(..., on_progress=None)` forwards the
  callback to the whole-clip detector.

`process_game` calls `on_progress(5, "Preparing video")` before `ensure_h264`,
passes the callback into `_detect`, then `on_progress(100, …)` is implied by the
existing terminal `update_job(status="completed", progress=100)`.

### 4. Interrupted state + startup recovery
- Internal status `interrupted` → frontend `interrupted`.
- `backend/app/services/recovery_service.py` — `recover_orphaned_jobs()`: for every
  game with `status in {"downloading","processing"}`, set `status="interrupted"`,
  `error="Analysis was interrupted (server restart). Retry to resume."`, and mark
  its running jobs `failed`. Called from `app/main.py` lifespan startup (after
  `ensure_dirs`, before seeding).
- **Retry** reuses the existing `POST /api/games/{id}/process`
  (`match_processing_service.process_game`), which already preserves curated
  events. No new endpoint.

### 5. Frontend
- `frontend/src/types.ts`: `Game.status` union adds `'interrupted'`; `Game` gains
  `progress?: number` and `progressMessage?: string | null`.
- `frontend/src/api.ts`: add `retryAnalysis(id) → POST /api/games/{id}/process`.
- `frontend/src/components/ProgressBar.tsx`: presentational — props
  `{ value: number; label?: string }`; renders a track, a fill at `value%`, and
  the label. `value` clamps to 0–100; missing value → indeterminate styling.
- `frontend/src/pages/Library.tsx`: in the card's `thumb` area —
  - `downloading`/`processing` → `<ProgressBar value={g.progress ?? 0} label={g.progressMessage ?? (status==='downloading' ? 'Downloading…' : 'Processing…')} />`
  - `interrupted` → message + **Retry** button (calls `retryAnalysis` then `refresh`)
  - `error` → existing error text + **Retry** button
  - `ready` → existing video thumbnail
- `frontend/src/index.css`: `.progress-track` / `.progress-fill` / `.progress-label`.

## Data flow (worked example, 2-hour match)
1. Import → game `processing`, job created at 0%.
2. `process_game` → `on_progress(5,"Preparing video")` → job 5%.
3. `analyze_full_match` scans 480 windows → job ticks 15%→90% with
   "Scanning N/480 windows" as each window's Gemini call returns.
4. Verification → job 92% "Verifying candidates".
5. Clips/thumbs cut → terminal `update_job(completed, 100)`; game `completed`.
6. Library poll at any point shows the live bar + message; at step 5 the card
   flips to the video thumbnail.

## Error handling
- Detection failure → game `error` (existing) with message in `game.error`;
  card shows error + Retry.
- Missing/!available detector → completes `ready` with 0 events (existing);
  the bar simply runs to 100 quickly.
- A `processing` game with no job (shouldn't occur post-recovery) → `progress`
  null → bar shows indeterminate "Processing…".
- `on_progress` is best-effort: a callback raising must never abort detection
  (wrap the closure body so detector exceptions are the only thing that fail a
  run).

## Testing
- **Backend unit**
  - `game_out` includes `progress`/`progressMessage`; `interrupted` maps through.
  - `process_game` advances job progress past 15% via the callback (stub `_detect`
    to invoke `on_progress(50,"…")`; assert the job reached 50).
  - `recover_orphaned_jobs()` flips `processing`/`downloading` games to
    `interrupted` and marks their jobs failed; leaves `completed`/`ready` alone.
- **Backend integration**
  - `GET /api/games` for a game with an in-flight job returns its progress; a
    `ready` game returns `progress=None`.
  - Retry: `POST /api/games/{id}/process` on an `interrupted` game returns a job
    and re-runs (stubbed detector).
- **Frontend (vitest)**
  - `ProgressBar` renders fill width = value% and shows the label; clamps >100/<0.
  - Library shows a progress bar while `processing` and a Retry button when
    `interrupted`.

## Out of scope (YAGNI)
- Progress on the Player page (Library card only).
- WebSocket/SSE streaming (2s poll suffices).
- Per-frame / sub-window granularity.
- Cancelling a running analysis.
