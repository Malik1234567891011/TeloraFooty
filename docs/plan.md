# TeloraFooty — Backend Engineering Plan

## 1. Project Overview

TeloraFooty is a soccer video analysis platform for coaches.

The demo scenario:

- A coach gives us 3 full Veo soccer match videos.
- The system identifies every shot and goal.
- The coach can view the original video and all generated shot/goal clips.
- During onboarding, the coach may upload a short 30-second test clip.
- The system should process the 30-second clip live and return whether it contains a shot or goal, the timestamp of the event, and a generated highlight clip.

The backend is responsible for:

1. Accepting video uploads.
2. Storing videos locally.
3. Processing full match videos asynchronously.
4. Processing short demo clips quickly.
5. Generating clips from detected/manual timestamps.
6. Returning clean API responses for the Next.js frontend.
7. Maintaining metadata for games, events, clips, and processing status.
8. Being structured so the detection system can improve over time.

The frontend will be built separately using Next.js + TypeScript.

---

## 2. Product Reality

The system has two modes:

### Mode A — Full Game Processing

Full game videos are 90-minute Veo MP4s.

For the demo, these videos can be manually annotated because:

- Full automatic soccer action detection is still a difficult research problem.
- The client/demo does not need to watch the full processing happen.
- The onboarding story is that full games are processed overnight.
- We can precompute the clips and metadata before the demo.

The backend should still expose the full-game workflow as if it is real:

1. Upload game.
2. Create processing job.
3. Mark job as `processing`.
4. Load or generate event timestamps.
5. Generate shot/goal clips.
6. Mark job as `completed`.
7. Serve clips and metadata to frontend.

This keeps the product demo realistic without requiring a perfect full-game AI model immediately.

### Mode B — 30-Second Live Demo Processing

The 30-second clip must be processed for real.

The coach may upload a short clip and ask:

> “If I upload this clip right now, can your system detect the shot or goal?”

For this, the backend must:

1. Save the uploaded clip.
2. Extract frames.
3. Analyze motion, players, ball movement, goal/net behavior, and optional audio.
4. Decide whether the clip contains:
   - `shot`
   - `goal`
   - `none`
5. Estimate the event timestamp.
6. Generate a short highlight clip around the event.
7. Return the result to the frontend.

---

## 3. Definitions

### Shot

A shot is counted when the ball leaves an attacking player's foot and travels toward the opponent's net.

A shot includes:

- Ball goes into the net.
- Ball hits the post or crossbar.
- Ball is saved by the goalkeeper.
- Ball goes out over the goal line.
- Ball is blocked by a defender.
- Ball is clearly directed toward goal.

A goal should not be double-tagged as both `shot` and `goal`.

If a goal occurs, the event type should be `goal`.

### Goal

A goal is counted when the ball fully enters the net.

For the MVP, goal detection can use multiple cues:

- Ball enters goal/net area.
- Players celebrate.
- Defending team stops playing.
- Camera pans/zooms toward celebration.
- Play resets afterward.
- Audio/crowd spike if available.
- Ball no longer returns into active play.
- Attacking players run to corner/teammates.

### Team

The system should support team assignment.

For MVP:

- The user can manually select which team is "our team" before processing.
- The backend can store this as metadata.
- Automatic team classification is optional but should be designed for later.

Possible future automatic team assignment:

- Detect players.
- Cluster jersey colors.
- Assign team labels.
- Estimate which team was attacking based on direction and possession.
- Use manual correction if needed.

### Player Identification

Out of scope for MVP.

The backend should not attempt to identify the specific player who shot unless added later.

---

## 4. Recommended Backend Stack

Use Python.

This is not because it is easier. It is because the best video intelligence stack is Python-first.

### Core backend

- Python 3.11+
- FastAPI
- Uvicorn
- Pydantic
- SQLModel or SQLAlchemy
- SQLite for MVP
- Later: PostgreSQL if deployed

### Video processing

- FFmpeg
- OpenCV
- MoviePy only if needed, but prefer FFmpeg for speed

### Computer vision / ML

Initial realistic stack:

- OpenCV for frame extraction and motion analysis
- Ultralytics YOLO for player/ball/goal-related object detection if available
- ByteTrack/BOT-SORT style tracking through Ultralytics tracking mode
- Optional RT-DETR-style detector if we want a transformer-based detector experiment
- Optional custom fine-tuned ball detector later

### Annotation / manual tagging

- JSON annotation file for MVP
- Optional CVAT later for serious annotation workflow

### Job processing

MVP:

- FastAPI background tasks for lightweight jobs
- Local folder-based job status

Better version:

- Redis + RQ or Celery
- Separate worker process
- Job polling endpoint

Given the project ambition, structure the code so a queue can be added later.

### Storage

MVP local storage:

```txt
backend/storage/uploads/
backend/storage/clips/
backend/storage/processed/
backend/storage/thumbnails/
backend/storage/annotations/
High-Level Architecture
TeloraFooty/
  backend/
    app/
      main.py
      config.py

      api/
        routes/
          health.py
          videos.py
          games.py
          clips.py
          analysis.py
          jobs.py

      core/
        settings.py
        errors.py
        logging.py

      models/
        game.py
        video.py
        event.py
        clip.py
        job.py

      schemas/
        game_schema.py
        video_schema.py
        event_schema.py
        clip_schema.py
        job_schema.py

      services/
        video_storage_service.py
        annotation_service.py
        clip_service.py
        processing_service.py
        detection_service.py
        team_service.py

      cv/
        frame_extractor.py
        motion_analyzer.py
        ball_detector.py
        player_detector.py
        tracker.py
        event_classifier.py
        goal_classifier.py
        debug_visualizer.py

      workers/
        process_full_game.py
        process_demo_clip.py

      data/
        games.json
        events.json
        clips.json

      tests/
        unit/
        integration/
        fixtures/

    storage/
      uploads/
      clips/
      processed/
      thumbnails/
      annotations/

    requirements.txt
    README.md

  frontend/
    # Omar's Next.js app

  docs/
    Plan.md
    git.md
    test.md
    bestpractices.md
    6. Backend API Design

The backend should expose clean REST endpoints.

Health
GET /api/health

Response:

{
  "status": "ok",
  "service": "TeloraFooty backend"
}
Upload video
POST /api/videos/upload

Form data:

file: MP4 video
video_type: "full_game" | "demo_clip"
team_name: optional string
opponent_name: optional string

Response:

{
  "video_id": "vid_123",
  "filename": "game1.mp4",
  "video_type": "full_game",
  "status": "uploaded",
  "duration_seconds": 5400
}
Start full game processing
POST /api/games/{game_id}/process

Response:

{
  "job_id": "job_123",
  "game_id": "game_123",
  "status": "processing",
  "message": "Full game processing started. Results will be available later."
}

For MVP, this can load manual annotations and generate clips.

Get game details
GET /api/games/{game_id}

Response:

{
  "game_id": "game_123",
  "title": "TeloraFooty Demo Game 1",
  "video_url": "/media/uploads/game1.mp4",
  "status": "completed",
  "team_name": "Our Team",
  "opponent_name": "Opponent",
  "duration_seconds": 5400,
  "event_count": 14
}
Get events for game
GET /api/games/{game_id}/events

Response:

{
  "game_id": "game_123",
  "events": [
    {
      "event_id": "evt_001",
      "type": "shot",
      "team": "our_team",
      "timestamp_seconds": 418.2,
      "period": 1,
      "confidence": 1.0,
      "source": "manual",
      "clip_id": "clip_001"
    },
    {
      "event_id": "evt_002",
      "type": "goal",
      "team": "our_team",
      "timestamp_seconds": 1044.7,
      "period": 1,
      "confidence": 1.0,
      "source": "manual",
      "clip_id": "clip_002"
    }
  ]
}
Get clips for game
GET /api/games/{game_id}/clips

Response:

{
  "game_id": "game_123",
  "clips": [
    {
      "clip_id": "clip_001",
      "event_type": "shot",
      "timestamp_seconds": 418.2,
      "start_seconds": 412.2,
      "end_seconds": 424.2,
      "clip_url": "/media/clips/clip_001.mp4"
    }
  ]
}
Process 30-second demo clip
POST /api/analysis/demo-clip

Form data:

file: MP4 video
team_name: optional string
attacking_direction: optional "left_to_right" | "right_to_left" | "unknown"

Response:

{
  "analysis_id": "analysis_123",
  "status": "completed",
  "result": {
    "event_type": "shot",
    "timestamp_seconds": 13.8,
    "confidence": 0.82,
    "team": "our_team",
    "clip_url": "/media/clips/demo_analysis_123.mp4",
    "explanation": "Fast ball movement toward goal area followed by goalkeeper/defender reaction and camera motion."
  },
  "debug": {
    "frames_analyzed": 180,
    "fps_sampled": 6,
    "ball_track_points": 9,
    "motion_spike_timestamp": 13.6,
    "audio_spike_timestamp": null
  }
}
Get job status
GET /api/jobs/{job_id}

Response:

{
  "job_id": "job_123",
  "status": "completed",
  "progress": 100,
  "message": "Processing completed.",
  "created_at": "2026-06-05T20:00:00Z",
  "completed_at": "2026-06-05T20:04:00Z"
}
7. Detection Strategy for 30-Second Clip

The live detector should be a scoring system.

Do not rely on one model.

Use evidence from multiple modules.

Module 1 — Frame extraction

Extract frames from the uploaded clip.

For 30-second clips:

Sample around 5–10 FPS.
Downscale frames for speed.
Keep original video for final clipping.

Output:

{
  "frames": ["frame_0001.jpg", "frame_0002.jpg"],
  "fps_sampled": 6,
  "duration_seconds": 30
}
Module 2 — Motion analysis

Detect major motion spikes.

Useful signals:

Camera suddenly pans toward goal.
Ball/player movement accelerates.
Players suddenly change direction.
Large optical flow near attacking area.

Implementation ideas:

OpenCV optical flow.
Frame difference.
Motion magnitude per frame.
Smooth the motion curve.
Identify peaks.

Output:

{
  "motion_peaks": [
    {
      "timestamp_seconds": 13.6,
      "score": 0.79
    }
  ]
}
Module 3 — Ball detection

Use an object detector if available.

Possible detectors:

YOLO11 / YOLO26 style detector
RT-DETR-style detector
Fine-tuned ball detector later

Important:

Generic COCO models may not detect soccer balls reliably.
The ball is small and fast.
Missing ball detections are expected.
Interpolate missing positions if the ball disappears briefly.

Output:

{
  "ball_tracks": [
    {
      "timestamp_seconds": 12.9,
      "x": 0.62,
      "y": 0.41,
      "confidence": 0.72
    }
  ],
  "ball_speed_peaks": [
    {
      "timestamp_seconds": 13.8,
      "speed_score": 0.84
    }
  ]
}
Module 4 — Player detection and team color clustering

Detect players.

Use this for:

Understanding team positions.
Identifying attacking direction.
Detecting defensive block / goalkeeper reaction.
Optional team assignment.

MVP version:

Detect players.
Cluster jersey colors into two teams.
Allow manual override from frontend.

Output:

{
  "players_detected": 16,
  "team_clusters": [
    {
      "team_label": "team_a",
      "dominant_color": "#1E3A8A"
    },
    {
      "team_label": "team_b",
      "dominant_color": "#FFFFFF"
    }
  ]
}
Module 5 — Goal area estimation

For Veo footage, the camera angle is usually wide.

The backend can estimate possible goal areas by:

Detecting white goal posts/net if visible.
Using manual attacking direction.
Assuming goal area is near left/right edge depending on direction.
Allowing frontend/manual setup later.

MVP:

Use attacking direction if provided.
If unknown, use heuristics.

Example:

If attacking_direction = left_to_right:
  likely goal area = right 25% of frame

If attacking_direction = right_to_left:
  likely goal area = left 25% of frame
Module 6 — Shot classifier

The shot classifier combines evidence.

Potential scoring features:

shot_score =
  0.30 * ball_speed_toward_goal
+ 0.20 * ball_near_goal_area
+ 0.15 * player_kicking_motion_proxy
+ 0.15 * defensive_reaction
+ 0.10 * camera_motion_peak
+ 0.10 * ball_disappears_near_goal_or_block

A shot is detected when:

shot_score >= 0.65

The event timestamp should be the strongest peak near the suspected kick/ball acceleration.

Output:

{
  "event_type": "shot",
  "timestamp_seconds": 13.8,
  "confidence": 0.82
}
Module 7 — Goal classifier

Goal classification should run after a shot is suspected.

Potential goal signals:

goal_score =
  0.25 * ball_reaches_goal_area
+ 0.20 * players_celebrate_or_run_away_from_goal
+ 0.15 * play_stops_or_resets
+ 0.15 * camera_tracks_celebration
+ 0.10 * audio_spike
+ 0.10 * goalkeeper_stops_chasing
+ 0.05 * ball_not_seen_returning_to_play

A goal is detected when:

goal_score >= 0.70

If goal score passes threshold, return goal instead of shot.

Important:

Goal detection will be less reliable than shot detection.
For the demo, it is acceptable to say goal only when confidence is strong.
If unsure, classify as shot.
8. Clipping Strategy

Use FFmpeg.

Every event gets a clip.

Default clip window:

start = max(0, event_timestamp - 6 seconds)
end = min(video_duration, event_timestamp + 8 seconds)

For goals:

start = max(0, event_timestamp - 8 seconds)
end = min(video_duration, event_timestamp + 12 seconds)

This captures buildup, shot, and reaction.

Clip naming:

{game_id}_{event_type}_{timestamp_seconds}.mp4

Example:

game_001_goal_1044_7.mp4
9. Full Game Manual Annotation Format

Manual annotations should live in:

backend/storage/annotations/game_001.json

Example:

{
  "game_id": "game_001",
  "title": "Demo Game 1",
  "team_name": "Our Team",
  "opponent_name": "Opponent",
  "video_filename": "game1.mp4",
  "events": [
    {
      "type": "shot",
      "team": "our_team",
      "timestamp_seconds": 418.2,
      "period": 1,
      "notes": "Blocked shot from edge of box"
    },
    {
      "type": "goal",
      "team": "our_team",
      "timestamp_seconds": 1044.7,
      "period": 1,
      "notes": "Goal after cross"
    }
  ]
}

Rules:

Use seconds, not mm:ss, internally.
Frontend can format seconds into mm:ss.
Do not double-tag goals as shots.
Every event should produce one clip.
Every clip should link back to the event.
10. Processing Pipeline
Full game pipeline
1. Receive full game upload.
2. Save MP4 to storage/uploads.
3. Create game record.
4. Create processing job.
5. Load matching manual annotation JSON.
6. For each event:
   a. Calculate clip start/end.
   b. Generate clip with FFmpeg.
   c. Store clip metadata.
7. Save all event metadata.
8. Mark job completed.
Demo clip pipeline
1. Receive 30-second uploaded clip.
2. Save MP4 to storage/uploads/demo.
3. Extract video metadata.
4. Sample frames.
5. Run motion analysis.
6. Run ball detector if available.
7. Run player detector if available.
8. Estimate likely goal area.
9. Calculate shot score.
10. If shot score is high, calculate goal score.
11. Choose final event type:
    - goal if goal score passes threshold
    - shot if shot score passes threshold
    - none otherwise
12. Generate highlight clip if event found.
13. Return result JSON to frontend.
11. Data Models
Game
class Game:
    id: str
    title: str
    video_id: str
    team_name: str
    opponent_name: str | None
    status: str
    duration_seconds: float
    created_at: datetime
Video
class Video:
    id: str
    original_filename: str
    stored_path: str
    video_type: str
    duration_seconds: float
    fps: float
    width: int
    height: int
    uploaded_at: datetime
Event
class Event:
    id: str
    game_id: str | None
    video_id: str
    event_type: str
    team: str | None
    timestamp_seconds: float
    period: int | None
    confidence: float
    source: str # manual | model | hybrid
    notes: str | None
Clip
class Clip:
    id: str
    event_id: str
    video_id: str
    start_seconds: float
    end_seconds: float
    stored_path: str
    public_url: str
    created_at: datetime
Job
class Job:
    id: str
    job_type: str
    status: str
    progress: int
    message: str
    created_at: datetime
    completed_at: datetime | None