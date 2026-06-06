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

## Keyboard shortcuts (player)

| Key | Action |
|---|---|
| `Space` / `K` | Play / pause |
| `←` / `→` | Back / forward 5s |
| `H` | Tag a shot at the playhead (Veo's clip key) |
| `G` | Tag a goal at the playhead |
| `N` / `P` | Next / previous event |
| `+` / `-` | Playback speed up / down (0.5x–4x) |
| `F` | Fullscreen |

## Rating calls

Each event card has ✓ (correct call — stores `verified: true`, shown on the
card) and ✗ (bad call — removes the event instantly). Verified flags will be
used to judge the future AI detector's accuracy.

## Notes

- Library data lives in `data/games/` (gitignored).
- Drive links must be shared as "anyone with the link".
- Events are seeded with random placeholder timestamps on import
  (`backend/importer.py: generate_sample_events`) plus manual tagging.
  The `source` field is ready for a future AI detector.

## Emailing clips

The export popup can email a clip as an attachment. Configure once in
`backend/.env`:

    SMTP_USER=you@gmail.com
    SMTP_PASS=your-gmail-app-password

For Gmail, create an app password at https://myaccount.google.com/apppasswords
(requires 2-step verification). Other providers: also set SMTP_HOST/SMTP_PORT.
Restart the backend after editing .env.
