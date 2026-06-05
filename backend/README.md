# TeloraFooty Backend

Soccer video analysis backend for coaches. Built with FastAPI + OpenCV + FFmpeg.

It runs in two modes (see `docs/Plan.md`):

- **Mode A — Full game processing:** loads manual annotations for 90-minute Veo
  games and generates one shot/goal clip per event ("overnight processing").
- **Mode B — 30-second live demo:** actually analyzes a short uploaded clip
  (motion + optional ball/player/audio cues) and returns whether it contains a
  `shot`, `goal`, or `none`, with a generated highlight clip.

## Requirements

- Python 3.11+ (developed on 3.12)
- FFmpeg + ffprobe on `PATH`

## Setup

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional; defaults work out of the box
```

## Run

```bash
cd backend
uvicorn app.main:app --reload
```

- API docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/api/health
- Media (videos/clips): served under `/media/...`

On first boot the server seeds three demo games (`game_001..003`). If a local
sample video is present (`g17cunetestingfilmmidland.mp4` at the repo root, or
`backend/storage/uploads/sample_demo.mp4`) it is used as the source so the
seeded games get real, playable clips. Seeded data persists in
`backend/app/data/*.json`, so later startups are instant.

## API overview

| Method | Path | Purpose |
| ------ | ---- | ------- |
| GET  | `/api/health` | Liveness check |
| POST | `/api/videos/upload` | Upload an MP4 (`full_game` or `demo_clip`) |
| GET  | `/api/games` | List games |
| GET  | `/api/games/{game_id}` | Game details |
| POST | `/api/games/{game_id}/process` | Start full-game processing (async) |
| GET  | `/api/games/{game_id}/events` | Events (shots/goals) for a game |
| GET  | `/api/games/{game_id}/clips` | Generated clips for a game |
| GET  | `/api/clips/{clip_id}` | Single clip metadata |
| POST | `/api/analysis/demo-clip` | Analyze a short clip live |
| GET  | `/api/jobs/{job_id}` | Poll a processing job |

### Demo clip example

```bash
curl -X POST http://127.0.0.1:8000/api/analysis/demo-clip \
  -F "file=@clip.mp4" \
  -F "team_name=Our Team" \
  -F "attacking_direction=left_to_right"
```

Returns:

```json
{
  "analysis_id": "analysis_8b382b14",
  "status": "completed",
  "result": {
    "event_type": "shot",
    "timestamp_seconds": 13.8,
    "confidence": 0.74,
    "team": "Our Team",
    "clip_url": "/media/clips/demo_analysis_8b382b14.mp4",
    "explanation": "Fast motion directed toward the goal area ..."
  },
  "debug": { "frames_analyzed": 180, "motion_peaks": [], "score_breakdown": {} }
}
```

Error responses follow a consistent envelope:

```json
{ "status": "failed", "data": null, "error": { "message": "...", "code": "INVALID_VIDEO" } }
```

## Architecture

```
app/
  main.py            FastAPI app, error handlers, static media, startup seeding
  config.py          Env-driven settings
  core/              logging, errors, id/filename helpers
  models/            Pydantic domain models (Game, Video, Event, Clip, Job)
  schemas/           API request/response schemas
  services/          storage, metadata, annotations, clips, processing,
                     detection, jobs, seed, JSON store
  cv/                frame_extractor, motion_analyzer, ball/player detectors,
                     audio_analyzer, event/goal classifiers
```

Routes stay thin and delegate to services; CV logic lives in `cv/` behind
stable interfaces so detectors can be swapped (e.g. a fine-tuned YOLO ball
model) without touching the API. The pipeline is fault-tolerant: if ball,
player, or audio analysis fails, it falls back to motion-only analysis and
still returns a valid result.

### Optional ML detectors

Disabled by default. To enable, install `ultralytics` (+ `torch`) and set in
`.env`:

```
ENABLE_ML_DETECTORS=true
BALL_MODEL_PATH=/path/to/ball.pt
PLAYER_MODEL_PATH=/path/to/player.pt
```

## Manual annotations

Full games are driven by JSON in `backend/storage/annotations/<game_id>.json`:

```json
{
  "game_id": "game_001",
  "title": "Demo Game 1",
  "team_name": "Our Team",
  "opponent_name": "Opponent",
  "video_filename": "game1.mp4",
  "events": [
    { "type": "shot", "team": "our_team", "timestamp_seconds": 418.2, "period": 1, "notes": "Blocked shot" },
    { "type": "goal", "team": "our_team", "timestamp_seconds": 1044.7, "period": 1, "notes": "Goal after cross" }
  ]
}
```

Timestamps may be seconds or `mm:ss` / `hh:mm:ss`; they are normalized to
seconds. Goals are not double-tagged as shots.

## Tests

```bash
cd backend
pytest
```

Tests use tiny FFmpeg-generated fixture videos (nothing binary is committed),
run against an isolated temp storage dir, and do not require a GPU.
```
