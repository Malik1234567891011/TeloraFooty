# TeloraFooty

Local web app for analyzing soccer footage: import a game (local file or public
Google Drive link), let the AI detector find shots and goals automatically,
review them in a Veo-style player, and export or email clips (8s of build-up →
4–6s of aftermath around each moment).

## Requirements

- Python 3.12+, Node 20+, ffmpeg/ffprobe on PATH
- A Gemini API key for automatic detection (https://aistudio.google.com/apikey).
  Without one, imports still work and events can be tagged manually.

## Run

Backend (terminal 1):

    cd backend
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # first time
    cp .env.example .env   # add GEMINI_API_KEY for detection, SMTP_* for email
    .venv/bin/uvicorn app.main:app --port 8000

Frontend (terminal 2):

    cd frontend
    npm install        # first time
    npm run dev

Open http://localhost:5173

## How it works

Importing a game stores the video, then auto-runs the shot/goal detector in
the background (short clips: two-stage whole-clip detector; full matches: the
windowed scan funnel — see `backend/docs/`). The library card shows
Downloading…/Processing… until events appear. Detected events arrive as
unverified `ai` events; manual tags and ✓-verified events always survive
re-analysis (`POST /api/games/{id}/process`).

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
card) and ✗ (bad call — removes the event instantly). Verified events are
protected from re-analysis and feed the detector's accuracy tracking.

## Notes

- Game/event data lives in `backend/app/data/`, media in `backend/storage/`
  (both gitignored).
- Drive links must be shared as "anyone with the link".

## Emailing clips

The export popup can email a clip as an attachment. Configure once in
`backend/.env`:

    SMTP_USER=you@gmail.com
    SMTP_PASS=your-gmail-app-password

For Gmail, create an app password at https://myaccount.google.com/apppasswords
(requires 2-step verification). Other providers: also set SMTP_HOST/SMTP_PORT.
Restart the backend after editing .env.
