# How TeloraFooty Detects Shots & Goals — In-Depth Explanation

This document explains **exactly** how the system works today, **why** every piece
exists, and the **story** of how we got here. It's meant to be read top-to-bottom:
each section builds on the last. The core (Sections 1–10) is the **short-clip
detector** that is built and calibrated; **Section 12** then tells the honest
story of what happened when we tried to scale it to a full 48-minute match.

---

## 0. The one-sentence summary

> We slice a soccer clip into short overlapping windows, ask a Google **Gemini
> video model** "is there a shot/goal in this window?" for each one, and then
> **trust the consensus** — a real shot lights up a *cluster* of neighbouring
> windows, while the model's mistakes are scattered one-offs we throw away.

Everything below is the detail behind that sentence.

---

## 1. The problem we're actually solving

**Input:** a video from a wide "Veo-style" fixed camera that films the whole pitch.
**Output:** the moment(s) a **shot** or **goal** happens, plus a short highlight
clip around each moment.

Why this is hard:

- **The ball is tiny.** On a wide shot the ball is often a handful of pixels,
  motion-blurred, or completely hidden behind a player. Classic "track the ball"
  computer vision is unreliable here.
- **"A shot" is a semantic event, not a pixel pattern.** It's defined by *intent
  and context*: an attacker strikes the ball toward goal, a keeper reacts, the net
  ripples, players celebrate. You need to *understand the scene*, not just measure
  pixels moving.
- **Most of the video is nothing.** 95%+ of a match is passing and midfield play.
  A detector that cries "shot!" too easily is useless.

So the core tension is **recall vs precision**:
- Miss a real shot = bad (false negative).
- Shout "shot" at every throw-in = also bad (false positive).

Getting that balance right is basically the whole story (Section 7).

---

## 2. The journey: why we ended up with a video model

We did **not** start here. The evolution matters because it explains why the
final design looks the way it does.

### Attempt 1 — Motion heuristics (failed)
First version measured **camera/pixel motion** and looked for spikes, with the
theory "a shot = a sudden burst of motion toward a goal." It fired on a **long
pass at ~8s** in the first test clip. Why it failed: a hard pass, a camera pan,
and crowd noise all produce the same motion/audio spike as a shot. Motion has no
idea *where the goal is* or *what the players intend*.

### Attempt 2 — Player-distribution heuristics (failed)
Next we added **YOLO player detection** and tried to infer attacks from players
"compressing" toward one end. It fired on **sideline spectators** being mistaken
for players, and still couldn't tell "attacking pressure" from "an actual shot."

### The lesson
Both attempts tried to *reconstruct understanding from cheap signals*. But a
shot is fundamentally a **semantic** event. So we flipped the architecture: let a
**video-language model (VLM)** — which actually "watches" and reasons about the
clip — be the primary judge, and demote motion/players/audio to **supporting
signals** (timestamp refinement + fallback). That's the design we have now.

> This pivot is documented in `docs/newTips.md` (the recommendation) and the
> calibration log in `docs/callibrations+results.md` (the measured results).

---

## 3. The big picture (data flow)

For a clip, `analyze_demo_clip()` in
`backend/app/services/detection_service.py` runs this pipeline:

```
                          video file (e.g. 44s clip)
                                   │
        ┌──────────────────────────┼───────────────────────────┐
        │                          │                            │
  (cheap local CV — supporting signals)              (the real brain)
        │                          │                            │
   1. Frame extract          5. Audio analyze         6. Build OVERLAPPING WINDOWS
   2. Motion analyze              (loudness spikes)        (8s wide, every 6s)
   3. Ball detect (opt)                                        │
   4. Player detect → Attack analyze                           ▼
        │                                            7. For EACH window, in parallel:
        │                                               cut subclip → upload to Gemini
        │                                               → "shot / goal / none?" + JSON
        │                                                        │
        └──────────────┐                                         ▼
                        ▼                              8. FUSE: cluster the windows
              local "candidates"  ───────────────────▶    that fired, pick the densest
              (motion/audio/player                          cluster = THE event
               suspicious moments)                                │
                                                                  ▼
                                                    9. Refine timestamp using nearby
                                                       motion/player peaks
                                                                  │
                                                                  ▼
                                                   10. Cut highlight clip (8s before,
                                                       4s after) with ffmpeg
                                                                  │
                                                                  ▼
                                            result: {event_type, timestamp, confidence,
                                                     explanation, clip_url, debug{...}}
```

The numbered stages below map 1:1 to the numbered comments in
`detection_service.py`.

---

## 4. Stage-by-stage deep dive

### Stage 1 — Frame extraction
`app/cv/frame_extractor.py`. We decode the video into frames, **subsampled** to
~6 fps and **downscaled** to 640px wide. Why: we don't need every frame at full
resolution to measure motion — subsampling makes the local CV fast and cheap. The
*Gemini* judge later gets the actual video (not these frames), so quality there is
preserved separately.

### Stage 2 — Motion analysis
`app/cv/motion_analyzer.py`. Computes a per-frame "how much changed" curve
(frame-to-frame pixel differences), smooths it, and finds **peaks**. These peaks
are *candidate moments* — "something happened here" — but on their own they can't
tell a pass from a shot (that was Attempt 1's downfall). Today they're used only
to (a) seed candidates and (b) **sharpen the final timestamp**.

### Stage 3 — Ball detection (optional)
`app/cv/ball_detector.py`. An interface with a real (YOLO) and a null
implementation. On wide footage the ball is mostly invisible, so this is
best-effort and the pipeline never depends on it. If it throws, we log and
continue (see "fault tolerance," Section 8).

### Stage 4 — Player detection → attack analysis
`app/cv/player_detector.py` (YOLO `yolov8n.pt`) + `app/cv/attack_analyzer.py`.
We detect players on a lower-FPS subset of frames and look at their spatial
distribution over time (are they surging toward one end?). This produces an
"attack" signal with a timestamp. Again: **supporting evidence only**, used for
candidates and timestamp refinement, never the sole decider.

### Stage 5 — Audio analysis
`app/cv/audio_analyzer.py`. Uses ffmpeg to find **loudness spikes** (a shout, a
kick, crowd noise). A spike near the event is weak corroboration; a spike alone
means nothing (the 8s false positive was partly an audio artifact). So audio only
contributes a small candidate score.

### Stage 6 — Windows + candidates (the "high-recall" layer)
`app/cv/candidate_generator.py`. Two outputs:

**(a) Overlapping windows** — `create_windows()`. We tile the clip into
**8-second windows that start every 6 seconds**:
```
[0–8] [6–14] [12–20] [18–26] [24–32] [30–38] [36–44] ...
```
- **Why overlap (8 wide, 6 stride → 2s overlap)?** So no action falls *between*
  windows, and so a single event is *seen by more than one window* — which is the
  whole basis of the consensus trick in Stage 8.
- **Why not one giant window over the whole clip?** A model asked "is there a shot
  somewhere in these 44 seconds?" gives mushy, hard-to-localize answers. Short
  windows force a precise yes/no + timestamp, and let us run them in parallel.
- **No-gap guarantee:** if a clip is long enough to exceed `vlm_max_windows`,
  `create_windows` *widens the stride* so windows still tile the whole clip with
  no holes — rather than dropping windows and leaving blind spots. (We learned
  this the hard way: iter 1/2 in the calibration log, a dropped window hid the
  real shot.)

**(b) Local candidates** — `generate_candidates()`. The top motion peaks, the
attack timestamp, and a strong audio spike become `Candidate(timestamp, score,
source)` entries. These are the "where to look" hints used for refinement and as
a last-resort fallback.

### Stage 7 — The Gemini video judge (the brain)
`app/services/vlm_service.py`, class `GeminiVlmJudge`. For **each window**:

1. **Cut a subclip** with ffmpeg (`_cut_window`): re-encode just that 8s slice,
   downscaled to 640px, no audio — small and fast to upload.
2. **Upload** the subclip to the Gemini Files API and wait until it's `ACTIVE`.
3. **Ask** `generate_content(model, [video, PROMPT])` with a **strict prompt**
   (see below) and `temperature=0`, requesting **JSON only**.
4. **Parse** the JSON into a `VlmJudgment`:
   ```
   { event_type: "goal"|"shot"|"none",
     timestamp_seconds: <relative to window start, converted to absolute>,
     confidence: 0..1,
     evidence: [ "...", "..." ],
     uncertainty: "..." }
   ```
5. **Clean up** the uploaded file and temp clip.

**The prompt is doing real work.** The first version told the model to "prefer
shot over none." On busy footage that made it call *almost every window* a shot
(10 of 12!). The current prompt is deliberately **strict**: default to `none`,
require a *clear strike toward goal* plus a *keeper/net/defender reaction*, with an
explicit "these are NOT shots" list (passes, crosses, clearances, midfield play,
camera pans), and honest confidence bands. That single change is what killed most
of the over-firing.

**Parallelism:** windows are independent, so Stage 7 runs them through a
`ThreadPoolExecutor` (`vlm_concurrency`, default 3) — ~3× faster per run.

**Crucial property — the model is NOT deterministic.** Even at `temperature=0`,
Gemini's video judgments vary run-to-run (it'll call a shot in slightly different
windows each time, occasionally hallucinate a "goal"). We *cannot* fix this by
tuning the prompt. Instead, the fusion layer is built to be **robust to this
noise** — that's Stage 8.

### Stage 8 — Fusion by consensus clustering (the heart of the system)
`detection_service._fuse()` + `_cluster_fires()` + `_cluster_decision()`.

This is the single most important idea, so here's the reasoning in full.

**Observation from the data:** across many runs, the *real* shot always lit up a
**dense cluster of adjacent overlapping windows** — because a shot's build-up,
strike, and aftermath span ~10–15s and therefore show up in 2–3 neighbouring
8s windows. The model's *mistakes*, on the other hand, were **isolated
singletons** that jumped to a different spot every run.

Example (clip 2, truth = one shot at ~36s):
```
[24–32] shot      ← part of the true cluster
[30–38] shot      ← part of the true cluster
[36–44] shot      ← part of the true cluster   } DENSE = the real event
[0–8]   goal      ← lone phantom (ignored)
[54–62] shot      ← smaller cluster (loses)
```

**So the algorithm is:**

1. **Filter to "fired" windows:** `event_type ∈ {shot, goal}` and
   `confidence ≥ shot_threshold` (0.50).
2. **Cluster adjacent fires** (`_cluster_fires`): walk windows in time order; a
   window joins the current cluster if it starts within `vlm_cluster_gap` (7s) of
   the previous one's end. The 7s gap **bridges a single noisy `none` window** in
   the middle of a real event (without it, one dropped window splits the cluster
   and we miss the shot — that was iter 4's failure).
3. **Pick the densest cluster:** `max(clusters, key=(size, total_confidence))`.
   More windows agreeing = stronger evidence. Ties break on summed confidence.
4. **Require ≥ `vlm_min_cluster` (2) windows.** This is the precision lever: a
   lone window is treated as **noise and discarded**, unless it's *extremely*
   confident (`vlm_lone_fire_conf` = 0.97), which suppresses the random phantoms.
5. **Decide type + timestamp** (`_cluster_decision`):
   - **type** = majority vote in the cluster. A lone "goal" among "shots" is read
     as the model over-labelling a shot → we say `shot`. (Both our truth clips are
     shots-not-goals, and this rule correctly resolved the stray "goal" calls.)
   - **timestamp** = **confidence-weighted average** of the cluster's window
     timestamps (so the most-confident windows pull the moment toward themselves).
   - **confidence** = average window confidence + a small **consensus bonus**
     (`+0.03` per extra window, capped) — rewarding agreement.

6. **Fallbacks** (only if no VLM cluster qualifies): use the strongest **local
   candidate** as a low-confidence "possible shot," then the **attack** signal,
   then finally `none`. This means even with no API key the system degrades
   gracefully instead of crashing.

**Why this is the right design:** it converts an unreliable, noisy per-window
signal into a stable decision by demanding *spatial-temporal agreement*. It's the
reason the detector now passes **both** clips on **every** run (see the stability
table in `docs/callibrations+results.md`).

### Stage 9 — Timestamp refinement
`_refine_timestamp()`. The model's within-window timestamp is rough (it doesn't
perceive time precisely). So we **blend** it: 60% the VLM timestamp, 25% the
nearest motion peak (within 3s), 15% the player-attack peak (within 4s). This
snaps the final moment onto the actual on-field action.

### Stage 10 — Highlight clip
`app/services/clip_service.py`. `clip_window_for_event()` turns the moment into a
window — **8s before, 4s after** (6s after for goals), clamped to the video's
bounds — and `generate_clip()` re-encodes that slice with ffmpeg into a
web-playable, faststart MP4 in `backend/storage/clips/demo_<id>.mp4`. The result
carries a `clip_url` like `/media/clips/demo_<id>.mp4`.
(Full clip walkthrough lives in this repo's chat history / `clip_service.py`.)

---

## 5. What the system returns

`DemoAnalysis` (and the JSON the API serves) contains:
- `event_type`: `shot` | `goal` | `none`
- `timestamp_seconds`: the refined moment
- `confidence`: 0..1
- `explanation`: human-readable evidence (joined from the VLM's evidence list)
- `clip_url`: the highlight
- `debug`: everything — every window's verdict, the chosen cluster, motion peaks,
  audio spikes, player counts, candidates. This is what makes the system
  **auditable** (you can see *why* it decided what it did).

---

## 6. Why "consensus" beats "highest confidence"

It's tempting to just take the single most-confident window. We tried that — it
fails, because the model will hand you a **0.95-confidence phantom goal** in a
random window. Confidence per-window is not trustworthy. **Agreement across
overlapping windows is.** A made-up event can score high once; it can't reliably
make 2–3 *adjacent* windows all fire at the same spot, run after run. Consensus
turns the model's noise into signal.

---

## 7. The calibration story (the knobs and why they exist)

Every parameter below was set by **measuring against verified ground truth** (two
clips, each with exactly one real shot — clip 1 @ ~26s, clip 2 @ ~36s, no goals),
using the harness `backend/scripts/calibrate.py`. The full blow-by-blow is in
`docs/callibrations+results.md`. Short version:

| Iter | Change | Result |
|------|--------|--------|
| 0 | baseline (recall-biased prompt) | ~10 "shots" per clip + a phantom goal. Useless. |
| 1 | **strict prompt** | over-firing mostly gone (10 → 2 fires) |
| 2 | **no-gap windows** | fixed a coverage hole that hid clip 2's shot |
| 3 | **temperature = 0** | discovered video judging *isn't* deterministic |
| 4 | **consensus clustering** | clip 1 passes; clip 2 brittle to one dropped window |
| 5 | **gap-bridging (7s)** | **both clips pass, stable across 3 runs** |

**No answers are hardcoded.** Nothing keys on "26" or "36"; the logic is generic
(thresholds + clustering). The clips are just the measuring stick.

---

## 8. Design principles baked in

- **Fault tolerance:** every optional stage (ball, players, audio, even the whole
  VLM) is wrapped so a failure logs a warning and the pipeline continues with a
  graceful fallback. One broken module never takes down a request.
- **Confidence + evidence, always:** we never return a bare "shot." We return how
  sure we are and the evidence, and stash the full reasoning in `debug`.
- **Config over code:** all the knobs live in `app/config.py` and can be set via
  `.env`. No magic numbers buried in logic.
- **VLM primary, CV supporting:** the expensive semantic judge decides; the cheap
  local signals refine and back up. Best of both.

---

## 9. Configuration reference

All in `backend/app/config.py` (override via `backend/.env`):

| Setting | Default | What it controls |
|---------|---------|------------------|
| `vlm_model` | `gemini-2.5-flash` | which Gemini model judges windows |
| `vlm_window_size` | `8.0` | window length (seconds) |
| `vlm_stride` | `6.0` | gap between window starts → 2s overlap |
| `vlm_max_windows` | `16` | cap; beyond it, stride widens (no gaps) |
| `vlm_concurrency` | `3` | windows judged in parallel |
| `shot_threshold` | `0.50` | min window confidence to count as "fired" |
| `goal_threshold` | `0.65` | min confidence for a goal verdict |
| `vlm_min_cluster` | `2` | windows that must agree to declare an event |
| `vlm_lone_fire_conf` | `0.97` | confidence needed for a *single* window to count |
| `vlm_cluster_gap` | `7.0` | max seconds between fires in one cluster (bridges dropouts) |
| `clip_pre_seconds` | `8.0` | highlight build-up before the moment |
| `clip_post_seconds` | `4.0` | highlight aftermath (shots) |
| `clip_post_seconds_goal` | `6.0` | highlight aftermath (goals) |

---

## 10. Glossary

- **VLM (video-language model):** an AI model (here, Gemini) that takes video +
  text and reasons about it — "watches" the clip and answers in words/JSON.
- **Window:** a short (8s) slice of the clip we ask the model about.
- **Fire:** a window whose verdict is `shot`/`goal` above the threshold.
- **Cluster:** a run of adjacent firing windows that overlap in time = one event.
- **Consensus:** trusting agreement across windows instead of any single verdict.
- **Recall / precision:** catching real events / not crying wolf.
- **Fallback:** a cheaper backup path used when a better one is unavailable.

---

## 11. Honest limitations (so you know the edges)

- **Non-determinism:** the model can still vary run-to-run; consensus tames it but
  doesn't make it perfectly repeatable.
- **Tuned on two clips:** robust on those, but more test footage = more confidence.
- **Single headline event:** this short-clip analyzer reports *the* event; a full
  match needs a multi-event scan (see Section 12).
- **Cost/time:** each window = one Gemini video call (cut + upload + judge), so a
  44s clip is ~8 calls and ~1–2 minutes.

---

## 12. Scaling to a full match — what we tried and what we learned

The short-clip detector is solid (8/8 on a fresh set of single-event clips, see
below). The obvious next step — point the same machinery at a whole 48-minute
half — is where reality bit. This section is the honest account.

### 12.1 The naive idea and why it isn't enough

"Just tile the whole match with windows and cluster the fires." We built exactly
that (`backend/app/services/full_match_service.py`) and measured it against
human-provided ground truth for the first 23 minutes (10 real shots).

- **Recall was perfect: 100%.** Every real shot was covered by a firing window.
  We do **not** miss shots.
- **Precision was awful.** `gemini-2.5-flash` called "shot" in **~34% of all
  windows**. On wide footage it cannot separate *attacking play* from an *actual
  shot*, so during any spell of pressure it fires almost continuously. Those
  sprawling fires also wreck the clustering that works so well on short clips — a
  5-minute attacking spell merges into one giant blob instead of distinct events.

### 12.2 Throwing a bigger model at it (and getting burned)

We added a **two-stage funnel**: cheap `flash` for recall, then strict
`gemini-2.5-pro` to *verify* each candidate by its **outcome** ("did the ball go
in? saved? wide?"). The stronger model made it **worse**: it **confidently made
things up**, labelling **23 of 35 candidates as "goal — ball in net" at 100%
confidence** in a half that had **zero goals**.

> **The core lesson:** on wide, downscaled Veo footage the ball is a few pixels.
> The model literally **cannot see the outcome** — so when you *ask* it for one,
> it **confabulates** a confident answer. A smarter model doesn't see better; it
> invents more convincingly. This is a *perception* limit, not a prompt bug.

### 12.3 Asking a smarter question — "the aftermath" (approach B)

If it can't see the ball, ask about something it *can* see: the **consequence**. A
real shot is followed by visible game-state — keeper catches/holds it, a goal
kick, a corner, or (for a goal) celebration + kickoff. If play just flows on, it
wasn't a shot. We built this (`verify_aftermath` + `AFTERMATH_PROMPT`) and tested
it cheaply by reusing the saved recall results: 62 candidate moments →
aftermath-check each.

**It didn't work either: ~23% precision.** The model **confabulated the
consequence too** — "keeper possession" or "corner" at 100% confidence on nearly
every candidate, with boilerplate evidence. Asking the same blind model a
*different* question just makes it rationalize a plausible-sounding story for any
attacking moment.

### 12.4 Where that leaves us

- **What works now:** the **short-clip analyzer**. Given a tight clip with one
  event, it reliably finds and timestamps it.
- **The remaining real lever (approach A, not yet built):** give the model
  *eyes*. The source is actually **1080p**; we currently downscale the whole frame
  to 640–854px, leaving the goal ~100px wide. Cropping the **goal-mouth at native
  resolution** and feeding *that* would let the model genuinely see ball-vs-net /
  keeper save. It's real effort (the goal must be located on a panning camera),
  so it's parked behind the short-clip demo.

### 12.5 Proof the short-clip path works (8 single-event clips)

Eight ~40-second clips cut from the Dordt match, **each with exactly one event**
(6 shots, 2 goals). Run via `backend/scripts/run_clips.py`:

| Clip | Detected | Timestamp | Conf |
|------|----------|-----------|------|
| `goal_2312` | shot\* | 0:30 | 0.99 |
| `goal_3653` | shot\* | 0:22 | 0.99 |
| `shot_2512` | shot | 0:21 | 0.93 |
| `shot_2701` | shot | 0:12 | 0.60 |
| `shot_3050` | shot | 0:27 | 0.99 |
| `shot_4509` | shot | 0:23 | 0.96 |
| `shot_4544` | shot | 0:23 | 0.99 |
| `shot_4550` | shot | 0:22 | 0.99 |

**8/8 found and timestamped.** Two honest notes: (\*) the two **goals were
timestamped right but labelled `shot`** — the model's evidence *did* see the net
and celebration, but the cluster's majority-vote type rule (Stage 8) downgrades a
lone "goal" surrounded by "shot" windows; this is a fixable labelling wart, not a
miss. And `shot_2701` (conf 0.60) is the one case the VLM didn't fire and we fell
back to local motion, so its timestamp is the least trustworthy.

> Bottom line: **tight clip with one event → reliable. Whole wide-angle match →
> recall is fine, but precision/outcome fails because the model can't perceive the
> ball.** The honest product sweet spot today is the short-clip analyzer.
