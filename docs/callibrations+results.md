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
