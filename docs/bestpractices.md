
---

# `bestpractices.md`

```md
# TeloraFooty Backend Best Practices

## 1. Main Rule

The backend should be modular, testable, and hard to break.

Do not write all logic inside API routes.

Routes should:

- Receive requests.
- Validate inputs.
- Call services.
- Return responses.

Services should contain business logic.

CV modules should contain computer vision logic.

---

## 2. Route Best Practices

Bad:

```python
@app.post("/api/analysis/demo-clip")
def analyze_clip(file: UploadFile):
    # save file
    # extract frames
    # run detection
    # generate clips
    # return response
    # 300 lines of logic

Good:

@router.post("/demo-clip")
def analyze_demo_clip(file: UploadFile):
    video = video_storage_service.save_upload(file)
    result = detection_service.analyze_demo_clip(video.path)
    return result

Routes should stay thin.

3. Service Layer Rules

Use services for:

Upload storage
Metadata extraction
Annotation loading
Clip generation
Game processing
Demo clip analysis
Job status updates

Example:

video_storage_service.py
clip_service.py
annotation_service.py
processing_service.py
detection_service.py

Each service should have one clear responsibility.

4. Computer Vision Module Rules

CV code should live in:

backend/app/cv/

Possible modules:

frame_extractor.py
motion_analyzer.py
ball_detector.py
player_detector.py
tracker.py
event_classifier.py
goal_classifier.py

Do not mix CV code with API routes.

Do not hardcode one model everywhere.

Create stable interfaces so models can be swapped.

Example:

class BallDetector:
    def detect(self, frames):
        raise NotImplementedError

Then implementations can change later.

5. Make the AI Pipeline Fault-Tolerant

The detector should never crash because one module fails.

If ball detector fails:

Continue with motion analysis.

If player detector fails:

Continue with ball/motion.

If everything fails:

{
  "event_type": "none",
  "confidence": 0.0,
  "explanation": "Analysis failed or no event detected."
}

The frontend should always receive a valid response.

6. Do Not Pretend Confidence Is Truth

Confidence is an estimate.

Use confidence carefully.

Example:

{
  "event_type": "shot",
  "confidence": 0.72,
  "explanation": "Motion and ball trajectory suggest a shot."
}

Avoid saying:

{
  "event_type": "shot",
  "confidence": 1.0
}

unless it is manually annotated.

Manual annotations can use:

{
  "confidence": 1.0,
  "source": "manual"
}

Model/hybrid detections should usually be less than 1.0.

7. Use Clear Event Sources

Every event should include a source:

manual
model
hybrid

Meaning:

manual: human-tagged event from full-game annotation.
model: detected only by model.
hybrid: detected using model + heuristics.

This keeps the product honest and debuggable.

8. File Naming Rules

Never trust original filenames.

Bad:

../../../weird file.mp4

Good:

vid_20260605_abc123.mp4

Use generated safe filenames.

Recommended format:

{prefix}_{uuid}.mp4

Examples:

upload_vid_7f3a9c.mp4
clip_evt_19a2bc.mp4
demo_analysis_882a0e.mp4
9. Storage Rules

Use organized folders:

backend/storage/uploads/
backend/storage/clips/
backend/storage/processed/
backend/storage/thumbnails/
backend/storage/annotations/

Never scatter generated files across the project.

Do not commit large videos.

Do commit small annotation JSON files.

10. API Response Rules

All API responses should be predictable.

Good response:

{
  "status": "completed",
  "data": {},
  "error": null
}

Error response:

{
  "status": "failed",
  "data": null,
  "error": {
    "message": "Invalid video file.",
    "code": "INVALID_VIDEO"
  }
}

Avoid random inconsistent responses.

11. Error Handling

Handle:

Missing file
Invalid file type
Corrupt video
FFmpeg failure
OpenCV failure
Detector/model failure
Missing annotation file
Invalid timestamp
Clip start/end out of range

Every error should have a clear message.

Do not expose huge stack traces to the frontend.

Log internal details separately.

12. Logging Rules

Log important events:

Video uploaded
Processing started
Processing completed
Processing failed
Clip generated
Demo analysis completed
Detector failed and fallback was used

Logs should help debug the demo quickly.

Use structured log messages when possible.

13. Performance Rules

For 30-second demo clips:

Do not process every frame at full resolution unless needed.
Sample frames at 5–10 FPS.
Downscale frames for analysis.
Use original video only for final clipping.
Cache extracted metadata.
Avoid loading huge videos entirely into memory.

For full games:

Process asynchronously.
Generate clips from timestamps.
Avoid blocking the main API server.
14. Model Rules

Do not make the whole backend depend on one model.

Model loading should be isolated.

Good:

detector = BallDetector(model_path=settings.BALL_MODEL_PATH)

Bad:

model = YOLO("model.pt")

inside every request.

Load models once if possible.

Use fallback mode if model files are missing.

15. Configuration Rules

Use environment variables for:

STORAGE_DIR
MAX_UPLOAD_SIZE_MB
ENABLE_ML_DETECTORS
BALL_MODEL_PATH
PLAYER_MODEL_PATH
DEBUG_MODE

Use .env locally.

Never commit .env.

Provide .env.example.

Example:

STORAGE_DIR=./storage
MAX_UPLOAD_SIZE_MB=2000
ENABLE_ML_DETECTORS=true
DEBUG_MODE=true
16. Validation Rules

Validate all user inputs.

Video type must be:

full_game
demo_clip

Event type must be:

shot
goal
none

Team should be:

our_team
opponent
unknown

Timestamps must be:

timestamp_seconds >= 0

Clip ranges must satisfy:

start_seconds < end_seconds
17. Annotation Rules

Manual annotations must be clean.

Use this format:

{
  "type": "shot",
  "team": "our_team",
  "timestamp_seconds": 418.2,
  "period": 1,
  "notes": "Blocked shot from edge of box"
}

Do not mix random timestamp formats unless the loader explicitly supports conversion.

If using mm:ss, convert it before saving or inside the annotation service.

18. Frontend Compatibility Rules

The backend must support the Next.js frontend.

Frontend needs:

Video URL
Clip URL
Event type
Timestamp
Confidence
Status
Processing progress

Do not change API response shapes without telling Omar.

Use example JSON in docs.

19. Security Basics

Even for a demo:

Validate file type.
Limit upload size.
Generate safe filenames.
Do not execute user-provided filenames.
Do not serve arbitrary file paths.
Do not allow path traversal.
Do not commit secrets.
Do not expose local machine paths in API responses.

Bad:

{
  "clip_path": "/Users/malik/Desktop/TeloraFooty/backend/storage/clips/clip.mp4"
}

Good:

{
  "clip_url": "/media/clips/clip.mp4"
}
20. Demo Reliability Rules

Before the demo:

Preload the 3 full games.
Pre-generate all manual clips.
Test every clip.
Test the 30-second upload endpoint.
Have one backup 30-second shot clip.
Have one backup 30-second goal clip.
Have one no-event clip.
Restart backend before demo.
Keep terminal open for logs.

The demo should not depend on full-game AI working live.

The full-game story is overnight processing.

The 30-second story is instant detection.