Hello sir — the reason it’s false-negativeing is probably simple: you’re trying to detect a “shot” from low-level visual cues too directly. In soccer, especially Veo-style wide footage, the ball is tiny, blurry, sometimes invisible, and the exact “leaves foot toward net” moment can be almost impossible from a naive YOLO/OpenCV pipeline. Roboflow’s sports CV repo explicitly calls ball tracking “extremely difficult” because of the ball’s small size and rapid movement, especially in high-resolution videos.

The best 2026 approach is not one detector. It’s a high-recall candidate generator + stronger video reasoning/classification layer + timestamp refinement.

The important research conclusion

Soccer shot/goal detection is part of the broader task called Ball Action Spotting: identify the timing and type of ball actions across soccer video. SoccerNet defines it as detecting both the timing and class of ball-related actions, with every action marked by a single timestamp; their ball-action dataset includes dense actions like passes, crosses, shots, blocks, free kicks, and goals.

This is still active research. SoccerNet 2026 has a Player-Centric Ball Action Spotting challenge whose goal is identifying what action happened, when it happened, and who performed it across full soccer matches. FOOTPASS, a 2026 benchmark, describes this as a multi-modal, multi-agent full-match soccer understanding problem.

So: do not expect a simple “ball speed toward goal = shot” rule to work reliably.

The best practical architecture for us

For TeloraFooty, I’d build this:

Uploaded 30s clip
        ↓
Preprocess video
        ↓
Generate many possible event windows, high recall
        ↓
Run 2–3 judges on each candidate window
        ↓
Fuse the scores
        ↓
Return shot / goal / none + timestamp + confidence
        ↓
Generate clip

The key is high recall first. Right now you’re probably trying to be accurate too early, which causes false negatives.

For the mock demo, false positives are less dangerous than false negatives. If the coach uploads a 30-second clip that obviously has a shot and your system says “none,” the demo dies. If it says “shot” with medium confidence on a shot-like clip, that’s fine.

Best option: video-language model + CV refinement

This is the strongest hackathon/product option right now.

Use a frontier video model to understand the 30-second clip semantically, then use your backend to refine timestamp and generate the clip.

Google’s Gemini video understanding docs explicitly support uploading videos and generating text outputs from video inputs. Google’s Gemini 2.5 video-understanding post says Gemini 2.5 Pro can identify specific moments in videos using audio-visual cues, and it performed segment identification in a 10-minute keynote video using both visual and audio information.

That matters because shot detection is semantic. The model can reason:

Did the ball get kicked toward goal?
Did players react like it was a shot?
Did the goalkeeper dive?
Did the ball go out near the net?
Did players celebrate?
Did play reset?

A raw object detector does not understand those things.

Recommended live-demo pipeline
Step 1: Upload 30s clip

Backend receives MP4.

Step 2: Extract metadata

Use FFmpeg/OpenCV:

duration
fps
resolution
audio present?
Step 3: Create candidate windows

Instead of asking “is there a shot in the whole 30s?”, split it into overlapping windows:

0–6s
3–9s
6–12s
9–15s
12–18s
15–21s
18–24s
21–27s
24–30s

For each window, ask the video model:

Does this window contain a shot or goal by our definition?
If yes, estimate the timestamp.

This avoids the model missing one quick action in a long clip.

Step 4: Prompt the VLM with strict definitions

Use a prompt like this:

You are analyzing a soccer clip from a wide Veo-style camera.

Definitions:
A shot means the ball leaves an attacking player's foot and travels toward the opponent's goal. Count blocked shots, saves, shots off the post/crossbar, and shots that go wide over the goal line.
A goal means the ball enters the net. If it is a goal, label it goal, not shot.

Task:
Analyze this video window and return JSON only.

Return:
{
  "event_type": "shot" | "goal" | "none",
  "timestamp_seconds": number | null,
  "confidence": number between 0 and 1,
  "visual_evidence": string[],
  "uncertainty": string
}

Important:
Do not require the ball to be perfectly visible. Use player body movement, goalkeeper reaction, ball trajectory, crowd/audio, celebration, and play reset as supporting evidence.
Prefer false positives over false negatives for obvious shot-like moments.

That one line is huge:

Do not require the ball to be perfectly visible.

Because the ball will often be invisible.

Step 5: Fuse overlapping answers

If multiple windows say shot/goal, merge them.

Logic:

If any window says goal with confidence >= 0.65:
    final = goal
Else if any window says shot with confidence >= 0.55:
    final = shot
Else:
    final = none

For the demo, I’d start thresholds lower:

shot_threshold = 0.50
goal_threshold = 0.65

False negatives are the enemy.

Step 6: Refine timestamp locally

Once the VLM says “shot around 14s,” use OpenCV only around that area:

candidate range = timestamp ± 2 seconds

Then look for:

biggest motion spike,
ball-like object acceleration,
camera pan spike,
player cluster reaction,
audio spike if available.

Final timestamp:

weighted average of VLM timestamp + motion peak + ball speed peak

Example:

final_timestamp = 
0.60 * vlm_timestamp
+ 0.25 * motion_peak_timestamp
+ 0.15 * ball_speed_peak_timestamp

If ball detection is missing, skip that term.

Why this is better than your current detector

Your current pipeline is probably doing something like:

Find ball → estimate direction → check if toward goal → classify shot

That fails because:

No ball detection = no shot
Bad goal-zone estimate = no shot
Low confidence = no shot
Occlusion = no shot
Wide camera = no shot
Blocked shot = no shot

The better version is:

Find all suspicious soccer-action moments → ask stronger model/classifier → only then refine

That turns false negatives into candidate windows instead of dead ends.

Option 1 — Fastest strong version: Gemini video judge

Use Gemini video understanding for the 30-second clip and your backend for clipping.

Flow
1. Upload video to backend.
2. Backend sends video to Gemini.
3. Gemini returns event_type, timestamp, confidence, evidence.
4. Backend uses FFmpeg to cut timestamp ± seconds.
5. Frontend displays result.
Pros
Best chance of working quickly.
Understands semantic soccer context.
Can use visual + audio cues.
No cloud GPU setup.
Very impressive if it works live.
Cons
API latency can vary.
Timestamp may not be frame-perfect.
Costs money per call.
You depend on an external API.
You need internet during the demo.
My take

This is the best live demo option.

For your scenario, I would absolutely build this first.

Option 2 — Cloud GPU CV pipeline: YOLO/RT-DETR + tracking + heuristics

This is the “real CV product” route.

Use a cloud GPU to run:

player detector
ball detector
goalpost/net detector
tracker
motion analyzer
event classifier

YOLO + ByteTrack/OpenCV is a common practical stack for football analytics; one 2025 project describes using YOLOv8, ByteTrack, and OpenCV to detect and track players, referees, and ball, then compute possession from proximity/speed/position.

Flow
1. Detect players.
2. Detect ball.
3. Detect goal/net/goal area if visible.
4. Track ball over time.
5. Track players over time.
6. Estimate attacking direction.
7. Detect candidate shot moments.
8. Classify shot/goal using heuristics.
Pros
More controllable.
Can run locally/cloud without VLM dependency.
You can show debug overlays.
Looks technically impressive.
Good foundation for long-term product.
Cons
Ball detection is the bottleneck.
Goal detection is even harder.
Needs training/fine-tuning to work well on your Veo footage.
Generic models may miss the ball constantly.
More engineering work.
My take

Good as a secondary layer, not the only detector.

Use it for:

timestamp refinement
debug visualization
confidence support

Do not rely on it alone for shot detection.

Option 3 — Grounded SAM 2 / SAM 2 tracking layer

SAM 2 is strong for video segmentation/tracking. Meta describes SAM 2 as a unified image/video segmentation model that can track selected objects across video, even if the object temporarily disappears, using video memory. Grounded SAM 2 combines Grounding DINO / DINO-X / Florence-2 with SAM 2 for open-set detection, segmentation, and tracking in videos.

How we could use it

Not as “shot detector.”

Use it for:

track goal frame / net
track goalkeeper
track player clusters
maybe track ball if manually/automatically initialized
Pros
Frontier-feeling.
Strong object tracking.
Useful for debug overlays.
Can track objects through short windows.
Cloud GPU friendly.
Cons
Prompting “soccer ball” may still fail because the ball is tiny.
SAM 2 needs a prompt/box/click/mask or grounding step.
It tracks objects, but does not know “this was a shot.”
More complicated than VLM API.
My take

Cool, but not the main shot detector.

Use SAM 2 if you want an impressive debug mode:

“Here is the player/goal/ball tracking overlay.”

But for the actual classification, still use VLM + event fusion.

Option 4 — Train/fine-tune a real Ball Action Spotting model

This is the most “research-correct” version.

Use SoccerNet Ball Action Spotting / Team Ball Action Spotting style models.

SoccerNet’s action spotting repo includes full untrimmed broadcast videos, annotations, ResNet features, and ball-action labels for 12 classes. The 2025 Team Ball Action Spotting task involved annotating 90-minute videos with labels including Pass, Drive, Header, High Pass, Out, Cross, Throw In, Shot, Ball-Player Block, Successful Tackle, Free Kick, and Goal, plus predicting the team.

Transformer approaches are strong here. ASTRA is a Transformer-based soccer action-spotting model that handles precise localization, label noise, long-tail data, and uses audio to help detect non-visible actions; it reports tight Average-mAP of 66.82 and SoccerNet 2023 challenge Average-mAP of 70.21.

Pros
Most academically correct.
Best long-term path.
Trained for exactly “what happened and when.”
Can detect actions without tracking every ball frame.
Cons
Usually trained/evaluated on broadcast footage, not necessarily Veo.
Needs dataset setup.
Needs GPU.
Fine-tuning on your footage requires annotations.
Not fastest for the demo.
My take

This is your long-term serious product direction, not the live fix tonight.

If we do it, use it as:

Cloud GPU worker:
- train/fine-tune on SoccerNet BAS
- add your manually tagged Veo shots/goals
- export inference endpoint
My recommended final architecture

Use a 3-layer detector:

Layer 1: High-recall candidate generator

This is local and fast.

It should output many possible timestamps.

Sources:

motion spike
camera pan spike
audio spike
ball speed spike if ball visible
players near goal area
ball/player cluster near box
play stopping
celebration-like movement

Important: candidate generator should be generous.

For a 30-second clip, it’s okay to generate 3–8 candidate timestamps.

Layer 2: Video-language model judge

For each candidate window, send:

candidate_timestamp ± 5 seconds

Ask:

Is this a shot, goal, or neither?

The VLM gives semantic judgment.

Layer 3: Local timestamp refinement

Use OpenCV/FFmpeg to refine event timestamp and cut the clip.

Final output:

{
  "event_type": "shot",
  "timestamp_seconds": 14.2,
  "confidence": 0.78,
  "clip_url": "/media/clips/demo_abc123.mp4",
  "evidence": [
    "attacking player kicks ball toward goal",
    "defender/goalkeeper reacts",
    "ball travels into goal area"
  ],
  "method": "candidate_generation + video_language_model + motion_refinement"
}
Exact detection logic I’d implement now
1. Stop using strict none

Your classifier should not return none unless the clip is clearly normal possession.

Instead of:

shot_score >= 0.75 → shot
else none

Use:

shot_score >= 0.50 → shot
goal_score >= 0.65 → goal
else if any shot-like evidence → possible_shot
else none

For frontend, you can still display:

Shot detected

if possible_shot is above your demo threshold.

2. Add candidate windows

Even before Gemini/model call, generate candidate windows:

windows = [
    (0, 6),
    (3, 9),
    (6, 12),
    (9, 15),
    (12, 18),
    (15, 21),
    (18, 24),
    (21, 27),
    (24, 30),
]

Analyze all of them.

3. Use a “shot-likelihood” score, not a hard rule

Suggested score:

shot_score =
  0.25 * semantic_vlm_shot_score
+ 0.15 * motion_spike_score
+ 0.15 * ball_or_tiny_object_speed_score
+ 0.15 * goal_area_pressure_score
+ 0.10 * goalkeeper_or_defender_reaction_score
+ 0.10 * camera_pan_score
+ 0.10 * play_stops_or_ball_out_score

If no ball detection:

redistribute ball score into semantic_vlm + motion + reaction

Do not set score to zero because ball is missing.

4. Goal should be detected differently from shot

Do not try to prove the ball crossed the line from Veo footage.

For MVP:

goal_score =
  0.30 * VLM_goal_score
+ 0.20 * celebration_score
+ 0.15 * play_reset_score
+ 0.15 * ball_enters_or_disappears_near_goal_score
+ 0.10 * audio_spike_score
+ 0.10 * goalkeeper_stops_or_reacts_score

Goal detection is more about aftermath than the ball itself.

Your own intuition was right: if players run to the corner, play resets, defenders stop, etc., that is strong goal evidence.

How to fix false negatives immediately

Do these in order.

Fix 1: Make the detector return candidates, not final truth

Current bad behavior:

No confident shot found → none

Better:

Suspicious moments:
- 8.2s, motion spike
- 13.7s, camera pan + players near goal
- 22.4s, ball-like speed

Then classify those.

Fix 2: Lower thresholds

For the 30-second live demo:

shot_threshold = 0.50
goal_threshold = 0.65
none_threshold = only if all signals weak
Fix 3: Add overlapping windows

A model can miss a shot in one 30s pass. It is less likely to miss it if asked about 6-second windows.

Fix 4: Use “possible shot” internally

Internal labels:

goal
shot
possible_shot
none

Frontend labels:

goal → Goal detected
shot → Shot detected
possible_shot → Shot detected, medium confidence
none → No shot detected
Fix 5: Never require ball visibility

This should become a core rule:

Missing ball detection must not prevent shot detection.

The ball is often missing in exactly the moments that matter.

Cloud GPU plan

If you want the ambitious GPU route, I’d use it like this:

Cloud GPU worker responsibilities
1. Run YOLO/RT-DETR object detection.
2. Run ball detector at high resolution.
3. Run player tracking.
4. Optional: run Grounded SAM 2/SAM 2 tracking.
5. Produce debug overlay video.
6. Return structured detections to main backend.
Main backend responsibilities
1. Upload video.
2. Store video.
3. Submit job to GPU worker.
4. Poll job status.
5. Receive JSON results.
6. Generate clips.
7. Serve frontend API.
Good cloud choices

For hackathon-style GPU:

Modal
RunPod
Replicate
Lambda Labs
AWS/GCP/Azure GPU VM

I’d personally use Modal or RunPod for this kind of project because you can spin up a GPU worker without turning your whole backend into cloud infrastructure.

GPU model stack

Ambitious stack:

Detector:
YOLO / RT-DETR fine-tuned for ball, players, goalkeeper, goalpost

Tracker:
ByteTrack / BoT-SORT for players
custom interpolation for ball

Segmenter:
SAM 2 / Grounded SAM 2 for goal/player/ball debug tracking

Classifier:
VLM or temporal model to classify candidate windows

Clipper:
FFmpeg
The actual best path for you

Given your exact situation, I would do this:

Tonight / immediate fix

Add Gemini video judge.

Pipeline:

30s upload
→ split into overlapping windows
→ ask Gemini shot/goal/none per window
→ merge results
→ clip around timestamp

This will likely improve false negatives the fastest.

Then add local CV support

Add:

motion peaks
audio spikes
ball-like movement if visible
camera pan detection

Use these to support/refine Gemini’s answer.

Then add cloud GPU debug mode

Add optional GPU processing:

/analysis/demo-clip?mode=advanced

Advanced mode returns:

event result
debug overlay
ball/player tracks
confidence breakdown
Later serious product

Train or fine-tune a SoccerNet-style ball action spotting model using:

SoccerNet BAS
SoccerTrack v2 if usable
your manually tagged Veo games

SoccerTrack v2 is especially relevant because it uses panoramic full-pitch recordings and includes ball action spotting labels like shots, not just broadcast clips.

Concrete implementation design
Endpoint
POST /api/analysis/demo-clip

Parameters:

file
team=our_team
attacking_direction=left_to_right | right_to_left | unknown
mode=fast | advanced
Internal flow
def analyze_demo_clip(video_path):
    metadata = get_video_metadata(video_path)

    candidate_windows = create_overlapping_windows(
        duration=metadata.duration,
        window_size=6,
        stride=3
    )

    local_features = analyze_local_features(video_path, candidate_windows)

    vlm_results = []
    for window in candidate_windows:
        subclip_path = cut_temp_window(video_path, window)
        result = ask_video_model(subclip_path)
        vlm_results.append(result)

    fused = fuse_vlm_and_local_results(vlm_results, local_features)

    if fused.event_type in ["shot", "goal"]:
        clip = generate_highlight_clip(
            video_path,
            timestamp=fused.timestamp_seconds,
            event_type=fused.event_type
        )
    else:
        clip = None

    return {
        "event_type": fused.event_type,
        "timestamp_seconds": fused.timestamp_seconds,
        "confidence": fused.confidence,
        "clip_url": clip.url if clip else None,
        "evidence": fused.evidence,
        "debug": fused.debug
    }
Fusion logic

Use this logic:

def fuse_results(vlm_results, local_features):
    goal_candidates = []
    shot_candidates = []

    for result in vlm_results:
        if result.event_type == "goal":
            goal_candidates.append(result)
        elif result.event_type == "shot":
            shot_candidates.append(result)

    if goal_candidates:
        best_goal = max(goal_candidates, key=lambda x: x.confidence)
        if best_goal.confidence >= 0.65:
            return best_goal

    if shot_candidates:
        best_shot = max(shot_candidates, key=lambda x: x.confidence)
        if best_shot.confidence >= 0.50:
            refined_timestamp = refine_timestamp(
                best_shot.timestamp_seconds,
                local_features
            )
            best_shot.timestamp_seconds = refined_timestamp
            return best_shot

    suspicious = local_features.best_suspicious_moment
    if suspicious and suspicious.score >= 0.60:
        return {
            "event_type": "shot",
            "timestamp_seconds": suspicious.timestamp,
            "confidence": 0.52,
            "evidence": ["Local motion and play dynamics suggest a possible shot."]
        }

    return {
        "event_type": "none",
        "timestamp_seconds": None,
        "confidence": 0.0
    }
The prompt I would use

Use this exact style:

You are a soccer video analyst.

Analyze this short soccer video window.

Definitions:
- A shot happens when the ball leaves an attacking player's foot and travels toward the opponent's goal.
- Count blocked shots, goalkeeper saves, shots off the post/crossbar, and shots that go wide over the goal line.
- A goal happens when the ball enters the net.
- If it is a goal, label it "goal", not "shot".

Important:
The ball may be tiny, blurry, or temporarily invisible. Do not require perfect ball visibility.
Use context: player kicking motion, goalkeeper reaction, defenders blocking, ball trajectory, camera movement, players celebrating, play stopping, and play resetting.

Return JSON only:
{
  "event_type": "goal" | "shot" | "none",
  "timestamp_seconds": number | null,
  "confidence": number,
  "evidence": ["short evidence 1", "short evidence 2"],
  "uncertainty": "short explanation"
}

Bias:
For an obvious shot-like moment, prefer "shot" over "none".
Only return "none" if there is clearly no shot or goal attempt.
My ranking of options
1. Best for your demo

Gemini video understanding + local timestamp refinement

This is the best chance of reducing false negatives immediately.

2. Best technical-looking version

Gemini + YOLO/RT-DETR + OpenCV + debug overlay

This gives you both reliability and impressive engineering.

3. Best “frontier cloud GPU” version

Grounded SAM 2 / SAM 2 + detector + tracker + VLM classifier

Very cool, but too complex to rely on as the first fix.

4. Best long-term startup version

Train/fine-tune SoccerNet-style temporal action spotting model

This is the correct long-term research path, especially if you gather your own Veo annotations.

Final recommendation

Do not keep trying to fix false negatives by tweaking one OpenCV/YOLO heuristic.

Change the architecture.

Build this:

High-recall candidate generator
+ overlapping video windows
+ frontier video-language model judge
+ local CV timestamp refinement
+ FFmpeg clipping

That is the best blend of works now, looks ambitious, and can become real later.