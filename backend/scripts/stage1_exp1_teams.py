"""STAGE-1 LAB · Experiment 1 — attacking-team box pressure (NO Gemini).

FROZEN PROTOCOL (do not renegotiate):
  test set   = ../clips (8 Dordt ~40s clips)
  GT         = exactly 30.0s in every clip
  valid      = >=1 candidate within +-4.0s of 30.0s
  budget     = <=3 candidates per clip
  success    = 8/8
  Stage 1    = local CV only, no Gemini.

HYPOTHESIS (Exp 1): the true shot is when the ATTACKING team (separated from the
defending team by jersey colour) packs bodies into the opponent's box. Measuring
only that — not all-player centre-of-mass — should rank the ~30s strike top-3.

EXACT CHANGE vs baseline: drop pan/motion/recenter. Signal = fraction of the
attacking team's field players inside the goal-box band, where the defending team
on each side is the team that occupies that side's box-band most across the clip.

Usage:
    python scripts/stage1_exp1_teams.py ../clips [--box 0.25] [--rebound]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cv.frame_extractor import extract_frames  # noqa: E402

GT = 30.0
TOL = 4.0
MAX_CANDS = 3
SAMPLE_FPS = 4.0
FIELD_MIN_CY, FIELD_MAX_CY, FIELD_MIN_H = 0.33, 0.90, 0.03


def _arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def fmt(sec) -> str:
    if sec is None or (isinstance(sec, float) and np.isnan(sec)):
        return "--"
    m, s = divmod(int(round(sec)), 60)
    return f"{m:01d}:{s:02d}"


def extract_boxes_with_color(video: str):
    """YOLO person boxes + a torso colour sample per box. Cached to /tmp."""
    cache = Path("/tmp") / f"boxes_{Path(video).stem}.json"
    if cache.exists():
        return json.loads(cache.read_text())

    import cv2

    from app.cv.player_detector import get_player_detector

    det = get_player_detector()
    ex = extract_frames(video, sample_fps=SAMPLE_FPS, target_width=640)
    res = det.detect(ex.frames, ex.timestamps)
    if not res.available:
        return None

    frames_out = []
    for frame, fr in zip(ex.frames, res.frames):
        H, W = frame.shape[:2]
        boxes = []
        for p in fr.players:
            # torso point: slightly above box centre; sample a small patch.
            h_px = max(2, int(p.h * H))
            cx_px, cy_px = int(p.cx * W), int(p.cy * H - 0.15 * h_px)
            half_w = max(1, int(0.12 * h_px))
            half_h = max(1, int(0.18 * h_px))
            y0, y1 = max(0, cy_px - half_h), min(H, cy_px + half_h)
            x0, x1 = max(0, cx_px - half_w), min(W, cx_px + half_w)
            patch = frame[y0:y1, x0:x1]
            if patch.size == 0:
                continue
            b, g, r = [float(patch[:, :, c].mean()) for c in range(3)]
            boxes.append({"cx": p.cx, "cy": p.cy, "h": p.h, "rgb": [r, g, b]})
        frames_out.append({"t": round(fr.timestamp_seconds, 3), "boxes": boxes})

    cache.write_text(json.dumps(frames_out))
    return frames_out


def kmeans2(X: np.ndarray, iters: int = 25):
    """Tiny 2-means (avoid sklearn dependency surprises)."""
    rng = np.random.default_rng(0)
    c = X[rng.choice(len(X), 2, replace=False)]
    for _ in range(iters):
        d = np.linalg.norm(X[:, None, :] - c[None, :, :], axis=2)
        lab = d.argmin(1)
        for k in (0, 1):
            if (lab == k).any():
                c[k] = X[lab == k].mean(0)
    return lab, c


def assign_teams(frames):
    """Cluster all torso colours into 2 teams; return per-box team labels."""
    colors, index = [], []
    for fi, fr in enumerate(frames):
        for bi, b in enumerate(fr["boxes"]):
            rgb = np.asarray(b["rgb"], dtype=np.float32)
            norm = rgb / (rgb.sum() + 1e-6)  # chromaticity = lighting-robust
            feat = np.concatenate([norm, [rgb.mean() / 255.0]])  # + brightness
            colors.append(feat)
            index.append((fi, bi))
    if len(colors) < 4:
        return None
    lab, _ = kmeans2(np.asarray(colors, dtype=np.float32))
    teams = {}
    for (fi, bi), l in zip(index, lab):
        teams[(fi, bi)] = int(l)
    return teams


def field_players(frames, teams):
    """Per-frame list of (team, cx) for on-field players only."""
    out = []
    for fi, fr in enumerate(frames):
        plist = []
        for bi, b in enumerate(fr["boxes"]):
            if FIELD_MIN_CY <= b["cy"] <= FIELD_MAX_CY and b["h"] >= FIELD_MIN_H:
                plist.append((teams[(fi, bi)], b["cx"]))
        out.append((fr["t"], plist))
    return out


def attacking_pressure(frames, teams, box: float):
    """Signal(t) = fraction of ATTACKING team's players in the opponent box band.

    Defending team on a side = the team most often in that side's box band over
    the whole clip; the attacking team is the other one.
    """
    fp = field_players(frames, teams)
    # Who defends each side? tally box-band occupancy per team per side.
    left_tally, right_tally = {0: 0, 1: 0}, {0: 0, 1: 0}
    for _t, plist in fp:
        for team, cx in plist:
            if cx < box:
                left_tally[team] += 1
            elif cx > 1 - box:
                right_tally[team] += 1
    def_left = max(left_tally, key=left_tally.get)
    def_right = max(right_tally, key=right_tally.get)

    ts, pressure = [], []
    for t, plist in fp:
        if len(plist) < 4:
            ts.append(t); pressure.append(0.0); continue
        atk_left = sum(1 for team, cx in plist if cx < box and team != def_left)
        atk_right = sum(1 for team, cx in plist if cx > 1 - box and team != def_right)
        n = len(plist)
        ts.append(t)
        pressure.append(max(atk_left, atk_right) / n)
    return np.asarray(ts, np.float32), np.asarray(pressure, np.float32)


def smooth(a, w=3):
    return np.convolve(a, np.ones(w) / w, mode="same") if len(a) >= w else a


def peaks_top(ts, sig, n, min_sep=6.0):
    k = len(sig)
    pk = [i for i in range(1, k - 1) if sig[i] >= sig[i - 1] and sig[i] >= sig[i + 1] and sig[i] > 0]
    if not pk:
        pk = [int(np.argmax(sig))]
    pk.sort(key=lambda i: float(sig[i]), reverse=True)
    chosen = []
    for i in pk:
        if all(abs(ts[i] - ts[j]) >= min_sep for j in chosen):
            chosen.append(i)
        if len(chosen) >= n:
            break
    chosen.sort(key=lambda i: ts[i])
    return [(float(ts[i]), float(sig[i])) for i in chosen]


def main():
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    folder = Path(pos[0] if pos else "../clips")
    box = float(_arg("--box", 0.25))
    use_rebound = "--rebound" in sys.argv

    rows = []
    for clip in sorted(folder.glob("*.mp4")):
        frames = extract_boxes_with_color(str(clip))
        if not frames:
            rows.append({"clip": clip.name, "error": "no player detections"})
            continue
        teams = assign_teams(frames)
        if teams is None:
            rows.append({"clip": clip.name, "error": "team clustering failed"})
            continue
        ts, pressure = attacking_pressure(frames, teams, box)
        score = smooth(pressure)
        if use_rebound and len(score) > 4:
            absp = score.copy()
            reb = np.zeros_like(absp)
            for i in range(len(absp)):
                fut = absp[i + 1 : i + 8]
                if fut.size:
                    reb[i] = max(0.0, absp[i] - float(fut.min()))
            score = score + 0.5 * reb
        cands = peaks_top(ts, score, MAX_CANDS)
        dists = [abs(c[0] - GT) for c in cands]
        closest = min(dists) if dists else float("inf")
        rows.append({
            "clip": clip.name,
            "candidates": [round(c[0], 1) for c in cands],
            "scores": [round(c[1], 3) for c in cands],
            "count": len(cands),
            "closest": round(closest, 1),
            "pass": closest <= TOL,
        })

    print("\n" + "=" * 92)
    print(f"STAGE-1 EXP 1: attacking-team box pressure   GT=30.0s  tol=±4s  budget≤3  box={box}  rebound={use_rebound}")
    print("=" * 92)
    print(f"{'clip':42} {'candidates(s)':18} {'cnt':>3} {'closest':>8} {'res':>5}")
    print("-" * 92)
    npass = n = 0
    for r in rows:
        if "error" in r:
            print(f"{r['clip']:42} ERROR: {r['error']}")
            continue
        n += 1; npass += 1 if r["pass"] else 0
        cs = ",".join(fmt(c) for c in r["candidates"])
        print(f"{r['clip']:42} {cs:18} {r['count']:>3} {r['closest']:>7.1f}s {'PASS' if r['pass'] else 'FAIL':>5}")
    print("-" * 92)
    print(f"RECALL @ ≤3: {npass}/{n}   ->  {'PASS (8/8)' if npass == n == 8 else 'FAILED'}")
    print("=" * 92)
    Path("/tmp/stage1_exp1.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
