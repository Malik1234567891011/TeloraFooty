# Combine frontend (main) and analysis backend (backend/malik) — Design

**Date:** 2026-06-06
**Status:** Approved
**Branch:** `combine` (off `main`), lands on `main` which becomes trunk

## Context

The repo holds two branches with **no common git ancestor**:

- **`main`** — the product frontend (React/Vite/TS: Library, Player, clips panel,
  export modal, Drive import) plus a flat MVP backend (`backend/main.py`,
  `store.py`, `importer.py`, `clipper.py`, `emailer.py`) that implements exactly
  the API the frontend needs. Its "processing" step generates **sample events**
  (`importer.generate_sample_events`) — a placeholder for real detection.
- **`backend/malik`** — a structured FastAPI app (`backend/app/{api,cv,services,models,schemas}`)
  containing the real video analysis: the two-stage whole-clip shot/goal
  detector (8/8 on the Dordt suite, ~30s/clip), the full-match scan funnel,
  jobs API, and the calibration/experiment lab under `scripts/`. No frontend.

Both branches define `backend/` with entirely different code, and their API
surfaces do not overlap where it matters: the frontend calls import / events
CRUD / clip+thumb URLs / email, none of which exist on malik's backend; malik's
backend has `POST /games/{id}/process` + jobs polling, which the frontend never
calls. This is an API reconciliation with a git merge attached.

### Decisions made

| Question | Decision |
|---|---|
| Is backend/malik still moving? | Frozen — absorb freely |
| Which backend shape survives? | Malik's structured app; MVP features ported into it |
| Detection UX | Auto-analyze on import (no button) |
| Trunk going forward | `main`; flip `origin/HEAD` back to it, archive `backend/malik` |
| API contract | The frontend's existing contract is the spec; backend implements it |

## Target architecture

```
TeloraFooty (main = trunk)
├── frontend/          ← from main, API contract unchanged
└── backend/           ← malik's app structure survives
    ├── app/
    │   ├── api/routes/    games.py, events.py(new), imports.py(new), email.py(new), health.py, jobs.py
    │   ├── cv/            ← malik's, untouched
    │   ├── services/      ← malik's + ported drive_service, email_service
    │   ├── models/        ← malik's; Event gains `verified: bool`
    │   └── schemas/       ← reshaped to the frontend's contract
    ├── scripts/           ← malik's calibration/experiment lab, kept
    └── tests/             ← malik's suite + ported MVP tests
```

### Git mechanics

1. Integration branch `combine` off `main`.
2. `git merge backend/malik --allow-unrelated-histories`. Resolve collisions
   (`backend/`, `.gitignore`, `README.md`, `docs/`) by taking malik's
   `backend/` wholesale. Main's MVP backend files stay reachable in history;
   they are deleted from the tree as each module is ported.
3. Both histories survive in the commit graph.
4. When complete: land `combine` on `main`, set `origin/HEAD` to `main`,
   archive `backend/malik`.

### Dropped

- Main's flat MVP backend files (after their features are ported).
- Malik's `seed_service` demo games — `enable_seed=false` once real import works.
- Main's clip window (30s pre / 10s post) — replaced by malik's calibrated
  `clip_service` window (8s pre / 4s post, 6s post for goals).
- Old `data/games/*` dev data — no migration; re-import (it holds sample
  events only).

## API contract implementation map

The frontend's `api.ts` is the spec. The backend implements it verbatim:

| Frontend call | Implementation |
|---|---|
| `GET /api/games`, `GET /api/games/{id}` | malik's `games.py`, response reshaped to frontend `Game` (adds `source`, `error`, `date`; goals/shots counts on list; status mapped) |
| `DELETE /api/games/{id}` | new in `games.py`: remove game + its video/events/clips/thumbs |
| `POST /api/games/import` (multipart file) | new `imports.py` → `video_storage_service`, then detection job |
| `POST /api/drive/list` | ported `drive_service` (from MVP `importer.py`) |
| `POST /api/games/import-drive` | `drive_service`: create game(s) `status=downloading`, background download thread, then detection job |
| `GET /api/games/{id}/events` | new `events.py` over malik's store, schema-mapped |
| `POST /api/games/{id}/events` | create with `source='manual'`, `verified=false`; clip window + clip/thumb generated |
| `PATCH .../events/{id}` | update `type`/`timestamp`/`verified`; recompute clip window on timestamp change |
| `DELETE .../events/{id}` | delete event + its clip/thumb artifacts |
| `GET /api/games/{id}/video` | serve stored upload (FileResponse, range requests) |
| `GET .../events/{id}/clip.mp4`, `.../thumb.jpg` | malik's `clip_service` + thumbnails, served at the frontend's URLs |
| `POST .../events/{id}/email` | ported `email_service` (MVP `emailer.py`); SMTP settings move into `Settings` |
| `GET /api/jobs/{id}` | kept (already exists); unused by frontend today, available for progress UI later |

### Field/status mapping (schema layer; malik's models stay internal)

- Game status: `downloading→downloading`, `uploaded/processing→processing`,
  `completed→ready`, `failed→error`. Frontend vocabulary wins at the API.
- Event: `event_type→type`, `timestamp_seconds→timestamp`, source `model→ai`;
  `clipStart`/`clipEnd` computed via `clip_service.clip_window_for_event`;
  `confidence` included in responses (frontend ignores it today).
- `Event` model gains `verified: bool = False`.

## Auto-analyze data flow

```
import (file or Drive)
  → game created: status=downloading (drive) / processing (file)
  → video stored in storage/uploads
  → detection job (FastAPI background task via job_service)
      → duration-based dispatch (reuse detection_service):
        full-match funnel for long videos, whole-clip detector for short clips
      → events written: source='ai', verified=false, confidence
      → clip + thumbnail per event (clip_service)
  → status=ready (or error with message)
  → Library already polls every 2s → state appears without frontend changes
```

- Player page fetches once on mount; opening a game mid-analysis shows events
  on reload. Light polling there is a later nice-to-have, not in scope.
- **Re-processing preserves curated work:** the idempotent reset
  (`clear_events_for_game`) is narrowed to delete only `source='ai' AND
  verified=false` events. Manual and verified events survive re-runs. This is
  a deliberate behavior change to malik's reset logic.

## Runtime requirements

- `GEMINI_API_KEY` in `backend/.env` (detector is Gemini VLM based).
- `ffmpeg` on PATH; YOLO weights (`yolov8n.pt`) for the player-detection path.
- **Graceful degradation:** without an API key (or other missing optional
  config), import still works; the detection job logs a warning and the game
  lands `status=ready` with zero events — manual tagging still functions.
  Unexpected pipeline crashes land `status=error` with the message in
  `game.error`. Detection never produces a stuck `processing` state.

## Error handling

- Detection job failures → `game.error` + log; API never crashes.
- Per-clip generation failures stay non-fatal (existing malik behavior).
- Drive download failures → `status=error` with message (existing MVP behavior,
  ported).

## Testing

- **Frontend tests run unchanged** — the contract is preserved; this is the
  regression net for the whole merge.
- Malik's unit/integration suites keep passing.
- MVP backend tests (`test_store`, `test_importer`, `test_clipper`, `test_api`)
  are ported to the new module homes.
- New integration test: import → stubbed VLM detector → events appear with the
  frontend's exact shape, game reaches `ready`.

## Rollout order (on `combine`)

1. Merge histories (`--allow-unrelated-histories`, take malik's `backend/`).
2. Malik's backend serves the read-only contract (games list/get, video);
   frontend boots against it.
3. Port events CRUD + clip/thumb serving.
4. Port import (file, then Drive).
5. Wire auto-analyze detection job; narrow the re-processing reset rule.
6. Port email.
7. Delete remaining MVP backend files; disable seed service.
8. Full test pass (frontend + backend) → land on `main`, flip `origin/HEAD`,
   archive `backend/malik`.
