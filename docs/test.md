
---

# `test.md`

```md
# TeloraFooty Backend Testing Plan

## 1. Testing Goals

The backend must be tested for:

1. API correctness.
2. Video upload reliability.
3. Video metadata extraction.
4. Manual annotation loading.
5. Clip generation.
6. Demo clip analysis.
7. Error handling.
8. Integration with the Next.js frontend.

The goal is not to prove the AI detector is perfect.

The goal is to prove:

- The backend does not crash.
- The API returns consistent JSON.
- Uploaded videos are saved correctly.
- Clips are generated correctly.
- Manual full-game annotations produce correct shot/goal clips.
- The 30-second demo pipeline returns a valid result.
- Edge cases are handled safely.

---

## 2. Testing Tools

Use:

```txt
pytest
httpx
FastAPI TestClient
OpenCV
FFmpeg
temporary test folders
small fixture videos

Install test dependencies:

pip install pytest httpx

Optional:

pip install pytest-cov

Run tests:

cd backend
pytest

Run with coverage:

pytest --cov=app
3. Test Folder Structure
backend/tests/
  unit/
    test_clip_service.py
    test_annotation_service.py
    test_video_metadata.py
    test_motion_analyzer.py
    test_event_classifier.py

  integration/
    test_health_api.py
    test_video_upload_api.py
    test_demo_clip_api.py
    test_game_events_api.py
    test_clip_api.py

  fixtures/
    sample_5s.mp4
    sample_30s_shot.mp4
    sample_30s_goal.mp4
    sample_30s_no_event.mp4
    annotations/
      sample_game.json

Do not use full 90-minute games in automated tests.

Use tiny fixture videos.

4. API Tests
Test health endpoint

Endpoint:

GET /api/health

Expected:

{
  "status": "ok"
}

Test cases:

Returns 200.
Response contains status.
Status equals ok.
Test video upload endpoint

Endpoint:

POST /api/videos/upload

Test cases:

Upload valid MP4.
Upload invalid file type.
Upload missing file.
Upload empty file.
Upload file with weird filename.
Upload demo clip.
Upload full game.

Expected for valid file:

Status code 200 or 201.
Response includes video_id.
Response includes filename.
Response includes duration_seconds.
File exists in storage.

Expected for invalid file:

Status code 400.
Clear error message.
Test game events endpoint

Endpoint:

GET /api/games/{game_id}/events

Test cases:

Existing game with events.
Existing game with no events.
Nonexistent game.
Events are sorted by timestamp.
Goal is not double-tagged as shot.

Expected:

Returns event list.
Every event has type, timestamp, confidence, source.
Test demo clip endpoint

Endpoint:

POST /api/analysis/demo-clip

Test cases:

30-second clip with obvious shot.
30-second clip with obvious goal.
30-second clip with no shot or goal.
Clip shorter than expected.
Clip longer than expected.
Corrupt video file.
Detector fails internally.

Expected:

Endpoint returns structured JSON.
It never crashes from missing detections.
It returns shot, goal, or none.
If event is found, it includes timestamp and clip URL.
If no event is found, clip URL can be null.
Confidence is between 0 and 1.
5. Unit Tests
5.1 Clip service tests

Function:

generate_clip(video_path, start_seconds, end_seconds, output_path)

Test cases:

Normal clip

Input:

start = 2
end = 6

Expected:

Output file exists.
Output file is playable.
Duration is approximately 4 seconds.
Start below zero

Input:

start = -5
end = 5

Expected:

Start is clamped to 0.
Output file exists.
No crash.
End beyond duration

Input:

start = 3
end = 999

Expected:

End is clamped to video duration.
Output file exists.
No crash.
Invalid range

Input:

start = 8
end = 3

Expected:

Raises validation error.
Does not generate broken clip.
5.2 Annotation service tests

Function:

load_annotations(game_id)

Test cases:

Valid annotation file.
Missing annotation file.
Invalid JSON.
Missing event type.
Missing timestamp.
Timestamp as mm:ss.
Timestamp as seconds.
Events unsorted.

Expected:

Valid annotations load.
Invalid annotations return clear error.
Events are normalized to seconds.
Events are sorted.
5.3 Video metadata tests

Function:

get_video_metadata(video_path)

Test cases:

Valid MP4.
Missing file.
Corrupt file.
Very short clip.
Video with unusual FPS.

Expected:

Returns duration, fps, width, height.
Handles error cases cleanly.
5.4 Motion analyzer tests

Function:

analyze_motion(frames)

Test cases:

Static clip.
Clip with sudden motion spike.
Clip with camera pan.
Empty frames list.
One frame only.

Expected:

Static clip has low motion score.
Spike clip has high motion peak.
Empty frames do not crash.
Returns timestamps.
5.5 Event classifier tests

Function:

classify_event(features)

Test cases:

Strong shot evidence.
Strong goal evidence.
Weak evidence.
Contradictory evidence.
Missing ball detections.
Missing player detections.
Motion-only fallback.

Expected:

Strong shot returns shot.
Strong goal returns goal.
Weak evidence returns none.
Missing optional features do not crash.
Confidence is between 0 and 1.
Explanation is included.
6. Integration Tests
Full game manual processing integration test

Use small fixture video and annotation JSON.

Flow:

1. Upload fixture video.
2. Load annotation JSON.
3. Process game.
4. Generate clips.
5. Request events.
6. Request clips.

Expected:

Events are created.
Clips are created.
Clip URLs are returned.
Files exist on disk.
Demo clip integration test

Flow:

1. Upload demo clip.
2. Run analysis.
3. Receive event result.
4. Generate highlight clip if event found.

Expected:

API returns valid result.
No internal exception.
Clip exists if event is detected.
7. Manual Demo Testing Checklist

Before presenting to the coach/client:

Backend startup
 Run backend server.
 Visit /api/health.
 Confirm status is ok.
Preloaded games
 Game 1 appears.
 Game 2 appears.
 Game 3 appears.
 Each game has shot/goal events.
 Each event has a playable clip.
Clip playback
 Full game video plays.
 Shot clips play.
 Goal clips play.
 Clip timestamps make sense.
30-second upload
 Upload obvious shot clip.
 Backend returns shot.
 Timestamp is reasonable.
 Generated clip plays.
Goal clip
 Upload obvious goal clip.
 Backend returns goal if confidence is strong.
 If not, backend should at least return shot.
No-event clip
 Upload random possession clip.
 Backend returns none or low-confidence shot.
 No crash.
Error case
 Upload non-video file.
 Backend rejects it cleanly.
8. Test Data Requirements

Create or collect:

One 5-second generic MP4.
One 30-second clip with obvious shot.
One 30-second clip with obvious goal.
One 30-second clip with no shot/goal.
One tiny manually annotated fake game video.
Annotation JSON with 2–3 events.

Do not rely only on the real Veo games for testing.

9. Detection Quality Testing

For the 30-second detector, manually evaluate:

precision = detected true shots / all detected shots
recall = detected true shots / all actual shots

For the demo, track:

Did it detect obvious shots?
Did it avoid false positives on normal possession?
Was timestamp within 2 seconds of actual event?
Did generated clip contain the event?

Minimum demo-quality standard:

Obvious shot clips: should detect
Obvious goal clips: should detect as goal or shot
No-event clips: should usually return none
Timestamp: should be within ~2 seconds
Clip: should include event clearly
10. Regression Testing Rules

Whenever changing detection logic:

Run all unit tests.
Run demo clip tests.
Test at least one real 30-second clip manually.
Confirm API response shape did not break.
Confirm generated clip still plays.

Do not improve one case while silently breaking the API.

11. Cursor Testing Instructions

Cursor should:

Add tests when adding services.
Keep tests small and focused.
Use fixture videos, not full games.
Mock heavy model calls when possible.
Test fallback behavior when detectors fail.
Never require a GPU for normal automated tests.
Keep AI/model quality tests separate from backend correctness tests.