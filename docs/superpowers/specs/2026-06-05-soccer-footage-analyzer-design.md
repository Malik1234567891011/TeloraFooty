# TeloraFooty — Soccer Footage Analyzer (v1) Design

**Date:** 2026-06-05
**Status:** Approved

## Overview

A local web app for reviewing soccer game footage. The user imports a game video
(local file or public Google Drive link), opens it in a Veo-inspired player, and
reviews **shots** and **goals** via an event panel with timestamps. Events can be
viewed as clips (30s before → 10s after the event) or jumped to in the full game,
and exported as standalone .mp4 files.

**KPI:** every shot and goal in a game is captured as an event and easy to find/clip.

**v1 explicitly has no AI/vision.** Events come from hardcoded samples and manual
tagging. The event data model is designed so a future detection model fills the
same shape (`source: "ai"`).

## Decisions made

| Question | Decision |
|---|---|
| Platform | Local web app (localhost, opens in browser) |
| Stack | Python FastAPI backend + React/Vite/TypeScript frontend (Approach A) |
| Why Python | Future vision models (OpenCV/PyTorch) plug into the backend without a rewrite; `gdown` for Drive downloads |
| Game management | Game library home screen; click a game to open the player |
| Clip window | 30 seconds before the event → 10 seconds after (clamped to video bounds) |
| Clipping | Virtual in-app playback + per-event .mp4 export button (ffmpeg stream copy) |
| Drive import | Public "anyone with the link" file or folder links, downloaded server-side; no OAuth |
| Events | Timestamp + type (`shot` \| `goal`) only; no team/player/notes in v1 |
| Event entry | Hardcoded sample events seeded on import + manual tagging UI (add/edit/delete) |
| Design inspiration | Veo match player (dark theme, Clips panel, filter tabs, timeline event dots) |

## UI

Two screens, dark theme throughout.

### Library screen

- Grid of game cards: thumbnail (first frame), title, date, counts ("2 goals · 5 shots").
- **Import video** button → local file picker (mp4/mov/mkv).
- **Import from Drive** button → paste a public Drive file or folder link. Folder
  links list the contained videos with checkboxes to choose which to import.
- Imports run in the background; the game card shows download progress and becomes
  playable when ready.
- Clicking a card opens the Player screen.

### Player screen (Veo-inspired, approved via mockup)

Layout: video player dominant on the left, **Clips panel** on the right.

**Video player:**
- Timeline scrubber overlaid on the video with **event dots** (green = goal,
  white = shot); dots are clickable to jump to that event.
- Controls: play/pause, **prev/next event arrows**, ±5s skip, elapsed/total time,
  playback speed, fullscreen.
- A badge in the corner shows current mode and event (e.g., "CLIP · GOAL 56:20").

**Clips panel (right sidebar):**
- Header with **Clip / Full game** toggle:
  - **Clip mode:** selecting an event plays only its window (seek to `clipStart`,
    pause at `clipEnd`). Virtual — no files created.
  - **Full game mode:** selecting an event seeks the full video to the event
    timestamp and keeps playing.
- **Filter tabs: All / Goals / Shots.**
- **Event cards:** thumbnail (real frame extracted at the event timestamp) with a
  timestamp badge, event title ("Goal" / "Shot on goal"), source label
  (manual/sample), and an **export icon** that downloads the clip as .mp4.
- **+ Tag** button: captures the current playhead time, user picks shot or goal;
  the event and its thumbnail appear immediately. Events can be edited
  (type/time) and deleted.

Navigation: Library ⇄ Player only.

## Architecture

```
TeloraFooty/
├── backend/          # Python FastAPI
│   ├── main.py       # API routes
│   ├── importer.py   # local file copy + Drive download (gdown) + validation
│   ├── clipper.py    # ffmpeg: clip export + thumbnail extraction
│   └── store.py      # JSON persistence for games/events
├── frontend/         # React + Vite + TypeScript
│   └── src/
│       ├── pages/        # Library, Player
│       └── components/   # VideoPlayer, ClipsPanel, EventCard, Timeline...
└── data/             # local library (gitignored)
    └── games/<game-id>/
        ├── video.mp4     # imported game video
        ├── game.json     # title, date, duration, source, import status
        ├── events.json   # event list
        └── thumbs/       # generated thumbnails (<event-id>.jpg)
```

External binaries: `ffmpeg`/`ffprobe` (clipping, thumbnails, probing). Python
deps: FastAPI, uvicorn, gdown.

## Data model

`game.json`:

```json
{
  "id": "game_20260601_ab12",
  "title": "L2 Hawks vs West Ottawa",
  "date": "2026-06-01",
  "durationSec": 8011.0,
  "source": { "kind": "drive", "url": "https://drive.google.com/..." },
  "status": "ready"        // "downloading" | "processing" | "ready" | "error"
}
```

`events.json`:

```json
{
  "events": [
    {
      "id": "evt_001",
      "type": "goal",          // "goal" | "shot"
      "timestamp": 3380.0,      // seconds into the video
      "source": "manual",       // "manual" | "sample" | "ai" (future)
      "clipStart": 3350.0,      // timestamp - 30, clamped to 0
      "clipEnd": 3390.0         // timestamp + 10, clamped to durationSec
    }
  ]
}
```

`clipStart`/`clipEnd` are computed server-side on event create/update.

## API surface

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/games` | List library |
| POST | `/api/games/import` | Import local file upload or Drive URL (file/folder) |
| GET | `/api/games/{id}` | Game details + status |
| DELETE | `/api/games/{id}` | Remove game from library |
| GET | `/api/games/{id}/video` | Video stream with HTTP Range support |
| GET | `/api/games/{id}/events` | List events |
| POST | `/api/games/{id}/events` | Create event (tag) |
| PATCH | `/api/games/{id}/events/{eid}` | Edit event |
| DELETE | `/api/games/{id}/events/{eid}` | Delete event |
| GET | `/api/games/{id}/events/{eid}/thumb.jpg` | Event thumbnail |
| POST | `/api/games/{id}/events/{eid}/export` | Cut clip via ffmpeg, return file download |

## Key flows

**Import (Drive):** paste link → backend resolves file vs folder (folder: list
videos, user picks) → `gdown` downloads to `data/games/<id>/` → `ffprobe`
validates and reads duration → seed hardcoded sample events → generate
thumbnails → status `ready`.

**Import (local):** file upload → copy into library → same validate/seed/thumbs
pipeline.

**Clip playback:** clip mode is purely client-side — seek to `clipStart`, pause
at `clipEnd`. Switching events or modes is instant.

**Export:** `ffmpeg -ss clipStart -to clipEnd -i video.mp4 -c copy` (stream
copy, no re-encode) → browser downloads `<game-title>_<type>_<mmss>.mp4`.
Roughly ~1s per export.

**Tagging:** "+ Tag" posts the playhead time + chosen type → server computes
clip bounds, extracts thumbnail → panel updates.

## Error handling

- **Drive download fails** (not public, quota, network): game card shows error
  state with reason ("Link isn't shared publicly — set it to 'anyone with the
  link'") + retry button. Partial downloads cleaned up.
- **Unsupported/corrupt video:** `ffprobe` validation at import rejects with a
  clear message; nothing enters the library that can't play.
- **Browser-incompatible codec (e.g., HEVC):** detected at import; importer
  offers one-time convert-to-H.264 (ffmpeg) so every library video is playable
  in-browser.
- **Clip bounds:** clamped to `[0, durationSec]` server-side.
- **Export failure:** error toast with ffmpeg message; partial output files
  removed.

## Testing

- **Backend (pytest):** store CRUD + clamp logic; clipper ffmpeg args +
  thumbnail generation; importer Drive URL parsing (file vs folder); API tests
  via FastAPI TestClient with a tiny sample video fixture committed to the repo.
- **Frontend (Vitest + React Testing Library):** ClipsPanel filters
  (All/Goals/Shots), clip-mode boundary behavior (pause at clipEnd), event
  sorting, Clip/Full toggle behavior.
- **Manual smoke test (KPI check):** import the real Drive folder, tag events,
  export a clip.

## Out of scope for v1

- AI/vision detection of shots/goals (the whole point of the data model, but later)
- Google OAuth / private Drive files
- Team, player, notes metadata on events
- Highlight-reel stitching (multi-event export)
- Hosting/multi-user/auth — single user, localhost only
- Comments, sharing, anything social
