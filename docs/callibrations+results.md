# Calibration + Results Log

Running log of every detector adjustment and the measured result, so changes can
be compared and reverted. **Do not hardcode answers** — calibrate generic logic.

## Verified ground truth (from user)

| Clip | Truth | Notes |
|------|-------|-------|
| `g17cunetestingfilmmidland.mp4` (44s) | exactly **one shot @ ~26s** | no goal |
| `mountmartytestingfilm.mp4` (68s) | exactly **one shot @ ~36s** | no goal |

Neither clip contains a goal. Each clip has exactly ONE real shot. So a correct
run should fire on essentially one moment per clip and return `none` everywhere
else. Over-firing = false positives; missing the shot = false negative.

### Dordt short-clip set (8 clips, ~40s each — added iter 8)

Eight ~40-second clips cut from `DordtFirstHalfSept212024.mp4`, **each containing
exactly one event** (filename encodes the match-time + type). 6 shots, 2 goals.
These are the *short-clip demo target*: one event, tight context.

| Clip | Truth type |
|------|-----------|
| `..._goal_2312.mp4` | goal |
| `..._goal_3653.mp4` | goal |
| `..._shot_2512.mp4` | shot |
| `..._shot_2701.mp4` | shot |
| `..._shot_3050.mp4` | shot |
| `..._shot_4509.mp4` | shot |
| `..._shot_4544.mp4` | shot |
| `..._shot_4550.mp4` | shot |

### Dordt full-match (48 min — first ~23 min ground-truthed, used iter 6–7)

`scripts/groundtruth_dordt.txt`: 10 real shots in the first 23 min (one burst of
4 back-to-back at 22:17–22:26), plus a back-pass at 18:07 that is *fine to catch
or miss*. **Recall is paramount** (must catch every shot); a few extra detections
are tolerable.

## How to measure

```bash
cd backend && source .venv/bin/activate
python scripts/calibrate.py            # both clips
python scripts/calibrate.py mountmarty # one clip
```

The harness scores: final decision (type + timestamp within ±5s) and the number
of windows that fired shot/goal vs. how many *should* have (precision).

---

## Iteration 0 — Baseline (recall-maximizing prompt)

**State:** original prompt with explicit "prefer shot over none" bias; windows
judged sequentially; `vlm_max_windows=8`.

**Video 1 (`g17cune…`):** final = `goal @ 26.95` (conf 0.95).
- Windows: 2 `none`, then shot/shot/**goal**/shot/shot/shot across the rest.
- vs truth (shot@26): timestamp right, but **type wrong** (goal, not shot) and
  ~6 windows fired when only ~2 should have.

**Video 2 (`mountmarty…`):** final = `shot @ 3.4` (conf 1.0).
- Windows: **10 of 12 fired `shot`**, 2 `none`. Headline landed at 3.4s.
- vs truth (shot@36): **completely wrong** — fired everywhere, picked the wrong
  moment.

**Diagnosis:** the prompt tells the model to treat any attacking play as a shot
and only say `none` if "clearly" no attempt. On busy wide footage almost every
8s window looks like "an obvious shot-like moment", so it fires constantly. The
fusion then picks the highest-confidence window, which is essentially random
among many 0.9–1.0 shots. Root cause = prompt bias + naive fusion.

**Planned fixes (small steps):**
1. Rewrite prompt for precision: require a *clear* strike toward goal with a
   goalkeeper/defender reaction or ball-to-net; default to `none`; calibrate
   confidence honestly. (iter 1)
2. Smarter fusion if needed: require agreement / suppress lone weak fires. (later)

---

## Iteration 1 — Precision prompt + parallel windows

**Change:** rewrote `vlm_service.PROMPT` to be strict (default `none`; require a
clear strike toward goal + keeper/net reaction; explicit NOT-a-shot list;
honest confidence bands). Also parallelized window judging (3 workers) for speed.
Still `vlm_max_windows=8` (from `.env`) this run.

**Video 1 (`g17cune…`):** final = `shot @ 19.1` (conf 0.9). decision FAIL (ts off).
- Windows fired: `[12-20]@18.5 (FALSE)`, `[18-26]@21.1`, `[24-32]@27.5`,
  `[30-38]@35.2`; rest `none`. 4 fired / 1 false.
- Type now correct (shot, not goal). Far fewer fires. But fuser picked the
  earliest 0.9 window (18.5) → timestamp wrong.

**Video 2 (`mountmarty…`):** final = `shot @ 27.1` (conf 0.9). decision FAIL.
- Only **2 of 8** windows fired (down from 10!): `[24-32]@26.5 (FALSE)` and
  `[54-62]@57.4 (FALSE)`. The REAL shot @36 did not fire.
- Root cause: `max_windows=8` downsampling dropped the `[30-38]` window (the one
  covering 36s) and left coverage GAPS (`[24-32]→[36-44]`). The shot fell in the
  gap / at a window edge and was missed.

**Verdict:** prompt fix is a big win on precision. Remaining issues: (a) coverage
gaps from window downsampling, (b) weak timestamp selection when several windows
tie at conf 0.9.

---

## Iteration 2 — No-gap window coverage

**Change:** `candidate_generator.create_windows` no longer drops windows when
over the cap; instead it widens the stride so windows still tile the clip
contiguously (overlapping, no holes). Raised `VLM_MAX_WINDOWS` 8 → 16 so
demo-length clips (44–68s) keep every contiguous window.

**Result:**
- **V1 (`g17cune…`):** final `shot @ 20.9` (conf 0.9). Only **1 window fired**
  (`[18-26]@21`), 0 false. Cleanest V1 yet, but headline ts 20.9 vs truth 26
  (5.1s off → just outside ±5 tol). Coverage now contiguous (no gaps).
- **V2 (`mountmarty…`):** final `goal @ 17.8` (conf 0.95) — WRONG type+time. 12
  windows, 4 fired, 3 false incl. a spurious `goal@17.8` that won. Real 36s shot
  still not firing cleanly (`[24-32]@30.5` only).

**Critical finding — NON-DETERMINISM:** comparing iter1 vs iter2 on the SAME
clips/prompt, the model returns different windows/types/timestamps each run
(V1 fired 4 windows in iter1, 1 in iter2; V2 produced a `goal` in iter2 that
wasn't there in iter1). Default sampling temperature is making results unstable,
so calibration is chasing noise. Must make judgments deterministic before
tuning anything else.

---

## Iteration 3 — Deterministic judging (temperature=0)

**Change:** pass `GenerateContentConfig(temperature=0, top_p=1, response_mime_type
=application/json)` to Gemini.

**Result:**
- **V1:** `shot @ 42.9` (FAIL). 3 fired: `[18-26]@22`, `[24-32]@28.5` (the real
  pair), + isolated `[36-44]@43` FALSE which won on conf 0.95.
- **V2:** `goal @ 5.3` (FAIL). 7 fired incl. phantom `[0-8]goal@5`. Real cluster
  `[24-32]@29.5 + [30-38]@34 + [36-44]@41.5` all fired but lost to the lone goal.

**Critical finding:** temperature=0 did NOT make video judging deterministic —
results still differ run-to-run (Gemini video isn't deterministic even at t=0).
So determinism is a dead end; the fusion must be ROBUST to per-window noise.

**Cross-run pattern (the key signal):** in every run the TRUE shot shows up as a
**dense cluster of 2–3 ADJACENT overlapping windows** (buildup→strike→aftermath):
- V1 truth ~26 → cluster `[18-26]+[24-32]` fires consistently.
- V2 truth ~36 → cluster `[24-32]+[30-38]+[36-44]` fires consistently.

FALSE fires are ISOLATED singletons that move around each run (`[0-8]goal@5`,
`[36-44]`, `[12-20]`…). Therefore: pick the **densest cluster of adjacent firing
windows**, require ≥2 agreement, ignore lone fires. Keep temperature=0 (cheap,
slightly less variance) but rely on clustering for correctness.

---

## Iteration 4 — Consensus clustering fusion

**Change:** rewrote `detection_service._fuse`. Group firing windows whose time
spans overlap/touch into clusters; choose the cluster with the most windows
(tie-break by summed confidence). Require cluster size ≥ 2 to declare an event
(suppresses isolated phantom fires). Event type = confidence-weighted vote within
the cluster (goal only if it dominates); timestamp = confidence-weighted mean of
the cluster's window timestamps.

**Result:**
- **V1:** `shot @ 22.8` (conf 0.99) — **PASS** (truth 26, within ±5). Cluster
  `[6-14][12-20][18-26][24-32][30-38]` (incl. 2 early false fires that merged in
  but didn't break the decision).
- **V2:** `shot @ 5.3` (conf 0.6) — **FAIL**, fell back to local signal. The true
  windows `[24-32]@29.5` and `[36-44]@41.5` both fired, but the middle `[30-38]`
  returned `none`, so the 2 fires didn't cluster (32→36 = 2s gap, > 0.5 slack).
  No cluster ≥ 2 → fell to weak local fallback. The persistent `[0-8]goal@5`
  phantom (seen most runs) stayed isolated (good).

**Verdict:** clustering works (V1 pass, phantom suppressed) but is too brittle to
a single dropped middle window. Need to bridge one-window gaps.

---

## Iteration 5 — Bridge single-window dropouts in clustering

**Change:** `_cluster_fires` now merges fires within `vlm_cluster_gap` (= ~one
stride, 7s) of the running cluster, so a real event survives one noisy `none`
window in the middle. Isolated phantoms (e.g. `[0-8]` alone) stay separate.

**Result — BOTH CLIPS PASS DECISION:**
- **V1:** `shot @ 21.8` (conf 0.98) — **PASS** (truth 26). Cluster
  `[12-20][18-26][24-32]`. `[24-32]` called it "goal@26" but cluster majority is
  shot (2 vs 1) → correctly resolved to `shot`. 1 leftover false window.
- **V2:** `shot @ 33.7` (conf 0.96) — **PASS** (truth 36). True 3-window cluster
  `[24-32][30-38][36-44]` beat the 2-window false cluster `[54-62][60-68]`. The
  `[0-8]` phantom didn't appear this run.

**Verdict:** consensus clustering + gap-bridging gets the headline right on both
clips. Remaining noise = smaller false clusters that lose to the denser true
cluster, so they don't change the decision. Harness "OVERALL" still flags them
as false fires (zero-false-fire bar), but the user-facing result is correct.

**Next:** stability re-runs (model is non-deterministic) to confirm both stay
correct across runs; consider raising min-cluster or down-weighting end-of-clip
fires only if a false cluster ever wins.

### Stability confirmation (3 consecutive runs, iter 5 config)

| Run | V1 (truth shot@26) | V2 (truth shot@36) |
|-----|--------------------|--------------------|
| 1   | shot @ 21.8 ✅      | shot @ 33.7 ✅      |
| 2   | shot @ 28.3 ✅      | shot @ 34.2 ✅      |
| 3   | shot @ 22.6 ✅      | shot @ 35.5 ✅      |

**Both clips pass on every run.** Decision type = `shot` (no phantom goals win),
timestamp within ±5s of truth, no false cluster ever beats the true one. This is
the current calibrated baseline. Config that produced it:
`vlm_window_size=8, vlm_stride=6, vlm_max_windows=16, temperature=0,
shot_threshold=0.50, vlm_min_cluster=2, vlm_lone_fire_conf=0.97,
vlm_cluster_gap=7.0`, strict precision prompt, consensus-clustering fusion.

### Summary of the journey
- iter 0 (baseline): both wrong; ~10 shots/clip, phantom goal.
- iter 1 (strict prompt): big precision gain; over-firing mostly gone.
- iter 2 (no-gap windows): fixed coverage holes from downsampling.
- iter 3 (temperature=0): found video judging is NOT deterministic.
- iter 4 (consensus clustering): V1 pass; V2 brittle to a dropped middle window.
- iter 5 (gap bridging): **both clips pass, stable across 3 runs.**

---

# Full-match phase (48-min Dordt video)

Iters 0–5 nailed the *short single-event clip*. The next experiments tried to
scale that to a whole 48-minute half. Short version: **it does not scale yet, and
we learned exactly why.**

## Iteration 6 — Full-match scan + two-stage funnel (flash recall → pro verify)

**Setup:** tile the entire video with overlapping windows (`full_match_service`),
judge every window with `gemini-2.5-flash` (the recall pass), cluster fires into
candidate events, then re-check each candidate with the stronger
`gemini-2.5-pro` on a longer, higher-res clip using a strict **outcome-based**
verify prompt ("did the ball go in / was it saved / wide?"). Scored against the
first 23 min of ground truth with `scripts/score_match.py`.

**Result — recall pass:** **100% window-level recall** — every one of the 10 real
shots was covered by ≥1 firing window. Good news: we are *not missing* shots.

**Result — precision was terrible:** flash called "shot" in **~34% of all
windows** (79 of 230 in 0–23 min). It cannot tell *attacking play* from an actual
*shot* on wide footage, so it fires almost continuously during any attack. The
sprawling fire pattern also defeats clustering (5-minute attacking spells merge
into one giant "event").

**Result — the pro verifier BACKFIRED:** asked to confirm the outcome,
`gemini-2.5-pro` **confidently confabulated** — it labelled **23 of 35 candidates
as "goal — ball in net" at conf 1.00**, in a half with *zero* goals. A stronger
model didn't see better; it *invented* outcomes it couldn't actually perceive.

**Finding (critical):** on wide, downscaled Veo footage the VLM **cannot see the
ball outcome**. Neither flash nor pro can reliably tell shot-vs-pass or
goal-vs-save. Prompt/model upgrades don't fix a perception problem.

## Iteration 7 — Approach B: judge by CONSEQUENCE, not the ball ("aftermath")

**Hypothesis:** stop asking the (blind) model to *see the ball*; ask it about the
**visible game-state after** the moment instead — a real shot is followed by
keeper possession / goal kick / corner / (for a goal) celebration + kickoff. If
play just flows on, it wasn't a shot. Game-state is much bigger on screen than
the ball.

**Implementation:** `vlm_service.verify_aftermath()` + `AFTERMATH_PROMPT` (new),
window weighted toward the seconds *after* the candidate (`aftermath_pre=6`,
`aftermath_post=18`, scale 854px). Tested **cheaply** by reusing the saved recall
checkpoint (`scripts/exp_aftermath.py`): 80 fired windows in 0–23 min → merged
into **62 candidate moments** → aftermath-verified each with flash.

**Result:** **precision 23%, recall 80%** (tol ±10s). Kept 35 of 62. The model
**confabulated the consequence too** — it returned `keeper_possession` or
`corner` at conf **1.00** for *nearly every* candidate, with boilerplate evidence
("a player in white shoots towards the goal"). The 2 "missed" shots were just the
22:17–22:26 burst collapsing under the merge tolerance, not a true miss.

**Finding:** asking the same blind model a *different question* doesn't help — it
rationalizes a plausible-sounding consequence for any attacking moment. **Approach
B does not work on this footage.**

**Decision:** the remaining real lever is **Approach A** — crop the goal-mouth at
native 1080p (the source *is* 1080p; we currently downscale the whole frame to
640–854px, so the goal is only ~100px) and feed *that* high-res crop so the model
can actually see ball-vs-net / keeper. Parked for now because the immediate demo
need is the short-clip path (iter 8), and A is real effort (goal-mouth must be
localized on a panning camera).

## Iteration 8 — Short-clip validation on the 8 Dordt single-event clips

**Why:** the demo's real target is short clips with one event. Ran the unchanged
iter-5 detector (`analyze_demo_clip`) over all 8 clips via
`scripts/run_clips.py`.

**Result — 8/8 found + timestamped** (local time within each ~40s clip):

| Clip | Detected | Timestamp | Conf |
|------|----------|-----------|------|
| `goal_2312` | shot* | 0:30 (30.4s) | 0.99 |
| `goal_3653` | shot* | 0:22 (21.9s) | 0.99 |
| `shot_2512` | shot | 0:21 (21.1s) | 0.93 |
| `shot_2701` | shot | 0:12 (11.6s) | 0.60 ⚠ |
| `shot_3050` | shot | 0:27 (26.6s) | 0.99 |
| `shot_4509` | shot | 0:23 (23.4s) | 0.96 |
| `shot_4544` | shot | 0:23 (22.5s) | 0.99 |
| `shot_4550` | shot | 0:22 (21.7s) | 0.99 |

**Caveats:**
- `*` The **two goals were timestamped correctly but labelled `shot`**, not
  `goal`. The model's *own evidence* saw it ("Ball clearly travels into the net;
  Players celebrate immediately"), but `_cluster_decision`'s majority-vote type
  rule downgrades a lone "goal" call surrounded by "shot" windows. **Label bug,
  not a detection miss** — fix: let a clear net/celebration call win the type.
- `shot_2701` (conf 0.60) is the only one where the **VLM did not fire**; the
  timestamp came from the local-motion fallback ("play dynamics suggest a possible
  shot"), so 0:12 is the least trustworthy of the eight.

**Takeaway:** the contrast is the whole story. **Tight clips with one event →
reliable (8/8).** A full 48-min match → recall is fine but precision/outcome fails
because the VLM can't perceive the ball on wide footage (iters 6–7). The product
sweet spot today is the short-clip analyzer.

### Summary of the full-match phase
- iter 6 (full scan + pro funnel): 100% recall but ~34% windows fire; pro
  *confabulates* 23 fake goals. VLM can't see ball outcome on wide footage.
- iter 7 (aftermath/consequence): precision 23% — model confabulates the
  consequence too. Approach B rejected.
- iter 8 (8 short clips): **8/8** detected + timestamped. Short-clip path works;
  goal-vs-shot labelling is the one fixable wart.

> **CORRECTION to iter 8 (added after user review).** The "8/8" was an
> **illusion**. Ground truth: the real event is at **~30s in every clip**. The
> detector's timestamps were 30.4, 21.9, 21.1, 11.6, 26.6, 23.4, 22.5, 21.7 —
> i.e. **1/8** within ±5s, landing **~8s early almost every time**. Per-window
> dumps (`scripts/debug_clip.py`) showed *why*: the VLM fires "shot toward goal"
> on **6–7 of 7 windows per clip**, each confabulating a different attempt, so the
> consensus timestamp is just the **clip midpoint**, not the strike. Both goals
> were also mislabelled "shot." Conclusion: **VLM window-voting is not a real
> detector on wide footage** — it confirms "attacking play exists," it does not
> localize the shot. This triggered the Stage-1 redesign (below).

---

# Redesign phase — separate localization from classification

New strategy (user-directed): stop using VLM window-voting as the detector. Use
cheap local CV to propose a *small* set of candidate moments (localization), then
use Gemini only as a verifier on those few candidates (classification). Validate
each stage independently against the 8 verified ~30s clips.

# STAGE-1 LOCALIZATION LAB — frozen protocol

This is a strict lab. **The protocol below is FROZEN and does not get
renegotiated between experiments.** No result is "softened." `recall@8` and
"maybe the event is later" are explicitly *out of scope* — they are different
experiments and do not count toward pass/fail.

### Frozen ground truth & protocol
- **Test set:** the 8 Dordt short clips (~40s each), `../clips/`.
- **Event timestamp:** **exactly 30.0s** in every clip. This is fixed, not
  uncertain. We do NOT optimize against "30–35s."
- **Valid localization:** at least one candidate within **±4.0s** of 30.0s.
- **Candidate budget:** **≤3 candidates per clip.**
- **Success bar:** **8/8** clips pass at ≤3 candidates. Anything less = FAILED.
- **No Gemini** in Stage 1. Local CV only. Gemini is a later verifier only.

### Per-experiment log template
hypothesis · exact change · per-clip {candidates, closest dist, count} · pass/fail
· conclusion.

> Long-term framing (noted, not yet built): the correct architecture for this is
> **action spotting / ball-action spotting** — a temporal event-spotting model
> with peak-picking + hard-negative rejection — with Gemini only as a verifier
> on proposed candidates. Handcrafted local signals (below) are being tested
> first because they're cheap; if they fail, we move to the model/dataset approach
> (Experiment 3).

---

## BASELINE — combined handcrafted local signal (`scripts/exp_localize.py`)

**Hypothesis:** a combination of camera-pan location, recenter swing, motion
burst, and all-player centre-of-mass penetration will rank the true ~30s event
inside the top-3 local peaks.

**Exact change:** score(t) = motion·(0.4+0.6·|pan|) + 0.30·recenter +
0.40·players·(0.4+0.6·|pan|); local-maxima peaks; 6s non-max-suppression; top 3.
Signals: `cv2.phaseCorrelate` integrated horizontal flow (pan), |pan| drop ahead
(recenter), `motion_analyzer` frame-diff (motion), `attack_analyzer` team CoM
penetration via YOLO (players).

**Per-clip result (GT=30.0s, ±4s, ≤3 cands):**

| Clip | Candidates (s) | Closest | Count | Result |
|------|----------------|---------|-------|--------|
| goal_2312 | 0, 28, 36 | 2.5 | 3 | PASS |
| goal_3653 | 14, 21, 28 | 2.4 | 3 | PASS |
| shot_2512 | 1, 9, 28 | 1.6 | 3 | PASS |
| shot_2701 | 4, 14, 24 | 6.5 | 3 | FAIL |
| shot_3050 | 5, 16, 36 | 5.5 | 3 | FAIL |
| shot_4509 | 0, 10, 24 | 6.5 | 3 | FAIL |
| shot_4544 | 12, 18, 38 | 7.9 | 3 | FAIL |
| shot_4550 | 0, 11, 32 | 1.6 | 3 | PASS |

**RECALL @ ≤3: 4/8 → FAILED** (bar is 8/8).

Best single signal (recall@top-3, diagnostic only): players 5/8, |pan| 4/8,
recenter 4/8, motion 2/8.

**Conclusion:** the combined handcrafted signal does not localize the shot — the
strike at 30s is not the most salient local event. **Baseline FAILED.** Proceed to
Experiment 1.

---

## EXPERIMENT 1 — attacking-team box pressure (`scripts/stage1_exp1_teams.py`)

**Hypothesis:** the true shot is when the ATTACKING team (separated from the
defending team by jersey colour) packs bodies into the opponent's box. Measuring
only that — instead of all-player centre-of-mass — should rank the ~30s strike
into the top-3.

**Exact change vs baseline:** removed pan/motion/recenter entirely. (1) YOLO
person boxes + a torso colour sample per box (cached). (2) cluster all torso
colours into 2 teams via 2-means on chromaticity+brightness. (3) per side, the
*defending* team = the one most often in that side's box band over the clip; the
*attacking* team = the other. (4) signal(t) = fraction of attacking-team field
players inside the goal-box band (outer `box` of width). Peaks, 6s NMS, top 3.

**Per-clip result (box=0.25, GT=30.0s, ±4s, ≤3 cands):**

| Clip | Candidates (s) | Closest | Count | Result |
|------|----------------|---------|-------|--------|
| goal_2312 | 2, 20, 33 | 3.3 | 3 | PASS |
| goal_3653 | 19, 32, 40 | 2.0 | 3 | PASS |
| shot_2512 | 8, 21, 40 | 9.2 | 3 | FAIL |
| shot_2701 | 2, 11, 32 | 2.0 | 3 | PASS |
| shot_3050 | 11, 19, 36 | 6.3 | 3 | FAIL |
| shot_4509 | 2, 24, 31 | 0.7 | 3 | PASS |
| shot_4544 | 11, 21, 32 | 1.5 | 3 | PASS |
| shot_4550 | 15, 22, 38 | 7.9 | 3 | FAIL |

**RECALL @ ≤3: 5/8 → FAILED** (bar is 8/8).

**Parameter sweep (same hypothesis, characterizing its ceiling):**
box=0.18 → 3/8, box=0.20 → 3/8, box=0.25 → 5/8, box=0.30 → 5/8; adding a
clearance-rebound term changed nothing. **Ceiling = 5/8.**

**Conclusion:** team-separated box pressure is *marginally* better than baseline
(5/8 vs 4/8) but nowhere near the bar, and it plateaus. On 640px-downscaled
footage the players are tiny, so jersey-colour clustering is itself shaky.
Handcrafted local signals top out around 5/8 — they **cannot reliably propose the
shot moment**. **Experiment 1 FAILED.**

**Logical note on Experiment 2:** Exp 2 (high-res goal-mouth crops as a *verifier*
input) targets candidate **precision**, not **localization recall**. It cannot
recover a missed event — if the ≤3 candidate set doesn't contain the strike (our
current failure mode, 3/8 missed), no verifier helps. So Exp 2 does not address
the failing bottleneck. The evidence now points at **Experiment 3** (a real
temporal action-spotting model — the soccer-analytics-standard approach), which is
the architecture noted at the top of this lab. Decision deferred to user.

---

## EXPERIMENT 2-WC — whole-clip Gemini localization + K-vote consensus
(`scripts/stage1_exp2_wholeclip.py`)

**Protocol deviation (user-approved):** Gemini IS allowed in this experiment.
The "no Gemini in Stage 1" rule existed because per-window VLM **voting** failed
as a localizer (iter-8 correction). This tests a structurally different use:
ONE call over the WHOLE original clip — **1080p, WITH audio** (the old path cut
8s windows, downscaled to 640px, stripped audio) — asking the model to
comparatively localize the decisive strike across the full timeline, K
independent votes, timestamps clustered across votes (4s slack), top-≤3
clusters by (rank-weighted confidence × cross-vote-agreement) as candidates.

**Hypothesis:** per-window firing was the artifact of asking a classification
question without global context. Given the whole timeline in one request, the
model can compare moments and anchor on the aftermath (keeper possession / goal
kick / corner / celebration), so the true strike ranks in the top-3 candidates.

**Run 1 (votes=3, fps=default 1): 8/8 PASS** — first approach to hit the bar.
Closest distances: 0.5, 4.0, 1.0, 1.0, 2.5, 0.4, 1.9, 1.1.

**Runs 2-3 (same config): 7/8, 6/8 FAILED** — two systematic failure modes:
1. `goal_3653` consistently lands ~25.5-26.0 (4.0-4.5s early). Frame inspection
   shows a set piece: at 26.5s the box is still in free-kick formation; the ball
   arrives ~29.5s. The model timestamps the START of the sequence it attends to
   (delivery), not the strike/net moment.
2. A recurring phantom candidate at ~0.2-0.3s (run 3: 7 of 8 clips; run-3
   `goal_2312` returned ONLY `goal@0.288` — a total miss).

**Root cause of the phantom (decisive find):** numeric formatting collapse, not
perception. Cross-referencing votes: `goal_2312` flips between `29.5` and
`0.288` (= 28.8/100); `goal_3653` between `25.5` and `0.255` (= 25.5/100
exactly). Gemini intermittently emits the seconds value shifted two decimal
places when forced to a JSON number. Run-3 `goal_2312`'s "miss" was actually
three unanimous votes for ~28.8s wearing the wrong units.

**Fix:** prompt now requires the strike time BOTH as `"strike_time": "M:SS.s"`
string and as a number; the parser treats MM:SS as authoritative
(`candidate_ts()`), numeric field is fallback only.

**Remaining issue for the product (top-1):** candidate recall ≥ top-3 is not the
user bar — the single headline answer must land at ~30s. In flurry clips
(`shot_2512`, `shot_4550` — verified by frame inspection to contain real
multi-attempt goalmouth sieges) the most-voted candidate is an EARLIER attempt
of the same sequence. Addressed by Stage-2 zoom verification + sequence
resolution (`scripts/exp_pipeline_v2.py`): each candidate window re-verified on
a 16s native-1080p subclip WITH audio at fps=5 (exact strike time, outcome, and
whether play RESETS after the attempt), then deterministic selection: attempts
group into sequences (gap ≤ 8s); headline = last attempt of the best sequence
after which play resets — generic soccer logic (a flurry is decided by the
attempt that ends it), no clip-specific tuning.

### Pipeline V2 results (stage 1 + stage 2 + selection, scored on TOP-1)

**First full run: TOP-1 8/8 PASS** — every headline within ±2.9s of 30.0
(distances 0.2, 2.4, 0.4, 0.4, 2.5, 0.6, 1.5, 2.9). `shot_4544`'s two real
keeper events (≈16s and ≈31.5s) were separated correctly by the sequence rule
(16s verified "continues" w=2.0; 31.5s verified "resets" w=3.0 → wins).

**Goal-vs-shot was the last wart.** `goal_3653` is a SCRAMBLE goal (frame
inspection: free kick ~28s → keeper punch-out → goal-mouth scramble → ball
forced in ~30s → celebration at 31.2s). The stage-2 zoom reports only
"parry, continues" — it loses the ball in the scramble. Meanwhile the
whole-clip pass votes "goal(net)" 5/5 on every run. Inverse problem on
`shot_2701`: whole-clip votes "net" 40–80% per run, but frame inspection proves
NO goal — the ball rests just outside the side netting and a GOAL KICK restarts
play (33–39s). **The wide camera's "net" call is a parallax illusion** (a ball
beside the net reads as inside it).

**Four arbiter designs tested and rejected** (each validated/refuted on saved
run data or cheap targeted A/Bs before full runs):
1. Stage-1 consensus promotion (≥0.7, ≥3 votes): wrongly promotes 2701 (its
   goal-vote fraction reached 0.8 in some runs).
2. Celebration/aftermath video check: confirms 3653 ✓ but false-confirms 2701 ✗
   (aftermath stills of the two clips are nearly indistinguishable at this
   distance; the model confabulates celebration).
3. Ball-fate tracking ("track the ball after the keeper touch"): rejects 2701 ✓
   (3/3) but misses 3653's scramble goal ✗ (follows the FIRST resolution, the
   punch-out, and stops).
4. Combined forensic check (final-resolution + net-retrieval + celebration +
   keeper-distribution cues): 3653 ✓ 6/6 but 2701 ✗ 5/6 "in_net, celebration"
   — the parallax illusion survives every goal-mouth video question.
Also tested: a sharpened goal definition in the stage-1 prompt ("a real goal is
ALWAYS followed by play stopping; keeper distribution ⇒ not a goal"). Kept (it
sharpened timestamps to 28.5–29.5 and held both real goals at 5/5) but it did
NOT fix 2701 (still 2/5–4/5 goal votes between rounds).

**Interim rule — witness trust:** trust stage-2 unless its sequence ended
"continues" (unresolved), then defer to stage-1 consensus. Replayed 8/8 on one
run's data — but the first 3-run stability gauntlet broke it (7/8, 7/8, 7/8):
every run a DIFFERENT field lied (stage-2 "catch, resets" on the 3653 scramble
goal; stage-2 "net" on 4544's non-goal — the parallax reaches the zoom level
too; stage-1 4/5 "goal" on 4544 under a since-reverted prompt line).

### Stability gauntlet findings (3 runs, pre-final fixes)

1. **`shot_4550` failed the TIMESTAMP bar in all 3 runs the same way**
   (headline 25.0–25.8, 4.2–5.0s early): greedy stage-1 clustering CHAINS the
   real 25s save and the real 31s strike into ONE candidate (each link ≤ 4s
   slack), so only one mis-centred zoom window is cut and the true strike never
   gets verified. **Fix: split clusters spanning > slack at their largest
   internal gap** (same-moment vote scatter is ≤~3s; a wider cluster is two
   moments wearing one hat). Also stage-2 votes 2 → 3.
2. **Prompt lesson:** the "goals can come from scrambles, judge by what
   follows" line (added to help 3653) flipped 4544's stage-1 to 4-5/5 "goal" —
   it was validated on 3 clips, not the full suite. REVERTED. Prompt changes
   must be validated suite-wide.
3. **Image-panel arbiter (stills at native res), A/B-tested two variants:**
   v1: perfect rejections (2701, 4544: 12/12) but only 1/3 on the 3653 scramble
   goal — votes fixate on a static ball behind the goal ("spare ball" decoy).
   v2 (+spare-ball guard): fixed 3653 (6/6) but **vetoed the CLEAN goal 2312
   0/3 in one round** (a ball sitting in the net is also "motionless across
   frames") and eroded 4544's rejection. Panels add an OBSERVED risk against
   true goals; rejected from the decision, kept in code for the record.

**FINAL type rule — stage-1 unanimity, nothing else:** `goal` iff ALL K
whole-clip votes call the moment a goal (members 100% "goal", ≥K distinct
votes, within 6s of the headline). Evidence: both real goals are 5/5 in every
observed run (7+ runs); no true shot ever reached 5/5 with the final prompt
(worst observed: 4/5 once each for 2701/4544 under earlier prompts). Replaying
the rule over all 3 gauntlet runs: **24/24 types correct.** Every richer
signal — stage-2 "net", three video arbiters, two image panels — was rejected
on measured evidence as parallax-fallible in at least one direction.

### Final round — the long-range blind spot + the goal-label verdict

**`shot_4550` root cause (the last timestamp failure):** frame inspection shows
the labeled strike at 30s is a LONG-RANGE shot from ~35-40 yards — the shooter
is at the far edge of the frame, ball flying in over the bar area at ~31s. Our
own prompts said the strike is "a single kick by one attacker **near or inside
the penalty box**" — the pipeline was *instructed* not to find this shot, so
both stages collapsed onto the (real) earlier box attempt at ~24s, every run.
**Fix:** both prompts now state attempts can come from anywhere in range,
including 25-40 yards, with the cue to watch ball flight + keeper reaction.
Single-clip validation: stage-1 votes for ~31.0 went 0/5 → 3-4/5; timestamp
passes (1.3s). Lab lesson learned twice now: iterate on the FAILING CLIP ALONE
(2-min runs) before paying for full-suite gauntlets.

**Goal-vs-shot: measured to the end, then scope-cut.** Two further approaches
tested and refuted after the panel:
- **Cropped goal-mouth stills (the parked "Approach A"): definitively refuted.**
  With a 2x zoom crop the model reports "ball clearly inside the net, conf 1.0"
  for ALL FOUR type-critical clips — 24/24 votes — including both non-goals.
  The camera's elevation/angle makes a ball lying beside/behind the net
  visually identical to one inside it; zooming amplifies acuity, not geometry.
  This retroactively explains every spurious "net" vote across the project.
- **Restart classification from stills:** classifies the aftermath as
  "goal_kick" for everything — including both true goals — so it would veto
  real goals. Refuted.

That makes EIGHT measured signals (s1 consensus, s1 unanimity, video
celebration, video ball-fate, forensic combined, image panels v1/v2, goal-mouth
crops, restart classification), none reliable on the two pathological clips
(`goal_3653` scramble goal, `shot_2701` parallax near-miss). **Conclusion: on
this footage the goal-vs-shot distinction for these cases is not reliably
extractable by the current VLM** — the discriminating information barely exists
from this camera angle within 10s of aftermath.

**Scope decision (user-driven):** the product bar is the TIMESTAMP ("all 8
flagged at ~30s every run"). Goal-vs-shot labels ship best-effort via stage-1
unanimity (correct in 22/24 replayed gauntlet cases; both label-error modes
documented). Future fix paths: a temporal action-spotting model (Experiment 3)
or camera-side improvement (second angle / higher mount).

**Bar relaxation (user, overnight):** "doesn't need to be perfect, 80-90% is
good too." Operational reading: kill SYSTEMATIC failures (same clip failing
every run); tolerate occasional MARGINAL misses (borderline timestamps on
rotating clips). Over-detection preferred to under-detection throughout.

### Overnight gauntlets + robustness hardening (v6/v7)

Three more rounds of cause-elimination, all from full-log evidence:
1. `shot_3050` — second long-range-strike clip (strike from ~25 yards at 30.0s,
   earlier goalmouth action stealing attention). Fixed by the long-range prompt
   plus a wider verify window; later runs also exposed that my "follow-up
   chase" (added for 3050) RE-VERIFIED already-covered seconds on `shot_4544`,
   stacking duplicate hallucinated readings of its dead-ball goal-kick
   choreography and dragging the median late (34.6). Chase now gated to NEW
   GROUND only (`cover_end`); on 40s clips it self-disables. 4544: 4/4 solo
   passes after the gate (33.2 ×3, 33.4).
2. Transient infrastructure was producing whole-clip "none" results: one run
   died on `SSL: TLSV1_ALERT_DECODE_ERROR` (the easiest clip, goal_2312, which
   passes every healthy run). Hardening: retry list now covers network/TLS
   flakes and 5xx, and stage-1 votes / stage-2 windows degrade PER-CALL instead
   of killing the clip.
3. Lab-process lessons, learned the expensive way: iterate on the failing clip
   ALONE (2-min runs) before full gauntlets; never grep-filter validation logs
   (it hid the SSL error and cost a diagnosis round); one change at a time
   (bundling window-widening + chase masked which one fixed 3050).

**Gauntlet v6 (pre-hardening code): 7/8, 7/8, 8/8.**
- run 1: `3050` at 25.9 — 0.1s over tolerance (marginal).
- run 2: `2312` "none" — the TLS flake (infra, not detection); detection-wise
  this run was effectively 8/8.
- run 3: **8/8 PASS, all 8 types correct** — first fully clean run.

**Gauntlet v7 (hardened, official): 8/8, 8/8, 8/8 — all types correct in all
three runs.** Combined with v6 run 3 that is FOUR consecutive perfect runs,
satisfying the ORIGINAL strict protocol (3× consecutive 8/8 at ±4s), beyond
the relaxed 80-90% bar. Distance profile across the three official runs:
max 3.8s (goal_3653 once), 19 of 24 clip-runs within 2.1s, several at 0.0-0.2s.
Both goals labelled "goal" with "net" outcomes in every run; no parallax
mislabels.

| Clip | v7 r1 | v7 r2 | v7 r3 |
|------|-------|-------|-------|
| goal_2312 | goal 29.8 (0.2) | goal 28.3 (1.7) | goal 28.3 (1.7) |
| goal_3653 | goal 27.9 (2.1) | goal 27.5 (2.5) | goal 26.2 (3.8) |
| shot_2512 | 30.1 (0.1) | 30.0 (0.0) | 30.0 (0.0) |
| shot_2701 | 29.3 (0.7) | 29.3 (0.7) | 29.9 (0.1) |
| shot_3050 | 27.9 (2.1) | 28.5 (1.5) | 28.3 (1.7) |
| shot_4509 | 31.0 (1.0) | 31.0 (1.0) | 31.0 (1.0) |
| shot_4544 | 33.2 (3.2) | 33.2 (3.2) | 32.7 (2.7) |
| shot_4550 | 28.5 (1.5) | 28.5 (1.5) | 28.5 (1.5) |

### End-to-end proof (production path)

`python scripts/run_clips.py ../clips` → `analyze_demo_clip` →
`wholeclip_detector` (the real backend code path, not the lab script):
**8/8 detected at ~30s, both goals labelled `goal`, all shots `shot`:**
29.8, 27.5, 30.4, 29.9, 27.7, 31.0, 33.0, 28.5 — every clip within ±4s.

---

**Production port:** `app/services/wholeclip_detector.py` (same prompts +
logic, knobs in `config.py` as `wc_*`), wired as the primary path in
`detection_service.analyze_demo_clip` with the legacy window-voting pipeline as
fallback when no API key/ffmpeg. Tests hardened to stay hermetic
(`tests/conftest.py` forces `ENABLE_VLM=false`, `ENABLE_WHOLECLIP_DETECTOR=false`,
empty `GEMINI_API_KEY`) so a developer's real `.env` key can never make the
suite call the live API.

---
