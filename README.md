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
- Events are seeded with random placeholder timestamps on import
  (`backend/importer.py: generate_sample_events`) plus manual tagging.
  The `source` field is ready for a future AI detector.
