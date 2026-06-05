12. Backend Task Breakdown
Phase 1 — Repo and backend setup
Task 1.1 — Create backend structure

Create:

backend/
backend/app/
backend/storage/
backend/tests/
backend/requirements.txt
Task 1.2 — Install backend dependencies

Initial dependencies:

fastapi
uvicorn
python-multipart
pydantic
opencv-python
numpy
ffmpeg-python
python-dotenv
pytest
httpx

Optional ML dependencies:

ultralytics
torch
torchvision
supervision
scikit-learn
Task 1.3 — Add health endpoint

Create:

GET /api/health

Acceptance criteria:

Server starts.
Health endpoint returns status ok.
Frontend can call it.
Phase 2 — Upload and storage
Task 2.1 — Video upload endpoint

Create:

POST /api/videos/upload

Acceptance criteria:

Accepts MP4.
Rejects non-video files.
Stores file with safe generated filename.
Returns video metadata.
Task 2.2 — Video metadata extraction

Use FFmpeg or OpenCV to extract:

duration
fps
width
height

Acceptance criteria:

Metadata is returned after upload.
Invalid/corrupt video returns a clear error.
Task 2.3 — Static media serving

Expose local media URLs:

/media/uploads/...
/media/clips/...

Acceptance criteria:

Frontend can play uploaded videos.
Frontend can play generated clips.
Phase 3 — Manual annotation support
Task 3.1 — Annotation JSON format

Create annotation JSON files for the 3 Veo games.

Acceptance criteria:

Each annotation file maps to a video.
Events include type, timestamp, team, period, notes.
Task 3.2 — Annotation loader

Create annotation_service.py.

Acceptance criteria:

Loads events from JSON.
Validates required fields.
Converts timestamps to seconds if needed.
Task 3.3 — Event API

Create:

GET /api/games/{game_id}/events

Acceptance criteria:

Returns all shots/goals for a game.
Events are sorted by timestamp.
Frontend receives event type and timestamp.
Phase 4 — Clip generation
Task 4.1 — FFmpeg clip service

Create clip_service.py.

Function:

generate_clip(video_path, start_seconds, end_seconds, output_path)

Acceptance criteria:

Generates playable MP4.
Does not crash if start time is near 0.
Does not crash if end time exceeds video duration.
Stores clip in storage/clips.
Task 4.2 — Generate clips from manual annotations

Create a processing function:

process_game_from_annotations(game_id)

Acceptance criteria:

Reads annotations.
Generates one clip per event.
Saves clip metadata.
Events include clip URL.
Phase 5 — Demo clip detector
Task 5.1 — Frame extractor

Create frame_extractor.py.

Acceptance criteria:

Extracts frames at configurable sample FPS.
Returns timestamps for each frame.
Handles 30-second clips quickly.
Task 5.2 — Motion analyzer

Create motion_analyzer.py.

Acceptance criteria:

Computes motion score over time.
Identifies motion peaks.
Returns likely event timestamps.
Task 5.3 — Ball detector interface

Create ball_detector.py.

Important: Make this modular.

Even if the first implementation is weak, the interface should remain stable.

Expected interface:

class BallDetector:
    def detect(self, frames) -> list[BallDetection]:
        ...

Acceptance criteria:

Can return empty detections without breaking pipeline.
Later model can be swapped in.
Task 5.4 — Player detector interface

Create player_detector.py.

Acceptance criteria:

Detects player-like objects if model is available.
Can be skipped if no model is installed.
Does not break demo pipeline.
Task 5.5 — Event classifier

Create event_classifier.py.

Input:

motion peaks
ball track data
player detections
goal area estimate
optional audio features

Output:

{
  "event_type": "shot" | "goal" | "none",
  "timestamp_seconds": 13.8,
  "confidence": 0.82,
  "explanation": "..."
}

Acceptance criteria:

Returns a result for every valid video.
Never crashes just because a detector failed.
Falls back to motion-only analysis if needed.
Task 5.6 — Demo clip endpoint

Create:

POST /api/analysis/demo-clip

Acceptance criteria:

Uploads 30-second clip.
Processes it.
Returns event type, timestamp, confidence.
Generates clip if event is found.
Returns none if no strong event is detected.
Phase 6 — Job/status system
Task 6.1 — Job model

Create job records for:

full game processing
demo clip processing
Task 6.2 — Job status endpoint

Create:

GET /api/jobs/{job_id}

Acceptance criteria:

Returns queued, processing, completed, or failed.
Includes progress and message.
Frontend can poll it.
Phase 7 — Debugging and demo polish
Task 7.1 — Debug JSON

For demo clips, return debug info:

frames analyzed
motion peaks
ball detections count
chosen timestamp
confidence breakdown
Task 7.2 — Debug overlay video/image

Optional but impressive:

Create image/frame with bounding boxes.
Create debug timeline.
Return debug artifact URL.
Task 7.3 — Seed demo data

Create preloaded demo games:

game_001
game_002
game_003

Acceptance criteria:

Frontend can show three games immediately.
Each game has events and clips.
Demo works even before uploading new full games.
13. Important Engineering Principles
Principle 1 — Do not fake the 30-second detector

Full games can use manual annotations.

The 30-second uploaded clip should actually be processed.

Principle 2 — Keep AI modules swappable

Do not hardcode everything inside the API route.

Bad:

@app.post("/demo")
def demo():
    # 300 lines of video logic here

Good:

result = detection_service.analyze_demo_clip(video_path)
Principle 3 — Always return structured output

Frontend should never guess.

Always return:

{
  "status": "...",
  "result": {},
  "debug": {}
}
Principle 4 — Fail gracefully

If ball detection fails, use motion analysis.

If player detection fails, use ball/motion.

If all CV fails, return none with explanation.

Principle 5 — Optimize for demo truth

The demo should be honest:

Full games are processed overnight.
Short clips can be analyzed instantly.
The backend is built to improve as the model improves.