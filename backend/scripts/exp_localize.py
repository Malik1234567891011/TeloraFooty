"""EXPERIMENT (read-only): local-CV candidate localization — NO Gemini.

Question this answers (and ONLY this):
    "Can local CV produce a SMALL set of candidate timestamps that includes the
     true shot/goal at ~30s?"

It does NOT decide shot-vs-not. It only proposes a few moments to look at. The
Gemini verifier comes later, separately. This script does not touch the main
detection pipeline.

Signals (all local, no model except optional YOLO for player location):
  - camera PAN  : integrated horizontal optical flow (phaseCorrelate) -> a proxy
                  for where on the pitch play is (|pan| high = deep in a third).
  - RECENTER    : how far the pan swings back toward centre after a moment
                  (the goal-kick / keeper-distribution / kick-off aftermath).
  - MOTION burst: normalized frame-difference magnitude (existing motion_analyzer).
  - PLAYERS     : team centre-of-mass penetration past midfield (existing
                  attack_analyzer signal), optional (YOLO); --no-players to skip.

For each clip we report the primary candidate set AND each individual signal's
own peak, so we can see which signal actually carries the prediction.

Usage:
    python scripts/exp_localize.py ../clips [--gt 30] [--tol 4] [--max 3] [--no-players]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cv.frame_extractor import extract_frames  # noqa: E402
from app.cv.motion_analyzer import analyze_motion  # noqa: E402


def _arg(flag: str, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def fmt(sec) -> str:
    if sec is None:
        return "--"
    m, s = divmod(int(round(sec)), 60)
    return f"{m:01d}:{s:02d}"


def _norm01(a: np.ndarray) -> np.ndarray:
    a = np.asarray(a, dtype=np.float32)
    if a.size == 0:
        return a
    lo, hi = float(a.min()), float(a.max())
    return (a - lo) / (hi - lo) if hi > lo else np.zeros_like(a)


def camera_pan(frames: list[np.ndarray]) -> np.ndarray:
    """Integrated horizontal optical-flow position (relative), one value/frame."""
    import cv2

    if len(frames) < 2:
        return np.zeros(len(frames), dtype=np.float32)

    def prep(f):
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
        # smaller = faster + steadier global estimate
        g = cv2.resize(g, (320, 180), interpolation=cv2.INTER_AREA)
        return g

    win = cv2.createHanningWindow((320, 180), cv2.CV_32F)
    prev = prep(frames[0])
    dxs = [0.0]
    for f in frames[1:]:
        cur = prep(f)
        (shift, _resp) = cv2.phaseCorrelate(prev, cur, win)
        dxs.append(float(shift[0]))
        prev = cur
    pos = np.cumsum(np.asarray(dxs, dtype=np.float32))
    pos = pos - np.median(pos)
    scale = np.percentile(np.abs(pos), 95) or 1.0
    return np.clip(pos / scale, -1.5, 1.5)


def recenter_after(pan: np.ndarray, ts: np.ndarray, lookahead_s: float = 7.0) -> np.ndarray:
    """How far |pan| drops (returns toward centre) within lookahead after each t."""
    n = len(pan)
    absp = np.abs(pan)
    out = np.zeros(n, dtype=np.float32)
    if n == 0:
        return out
    dt = float(np.median(np.diff(ts))) if n > 1 else 0.16
    k = max(1, int(round(lookahead_s / max(dt, 1e-3))))
    for i in range(n):
        future = absp[i + 1 : i + 1 + k]
        if future.size:
            out[i] = max(0.0, absp[i] - float(future.min()))
    return out


def player_penetration(video: str, target_w: int = 640) -> tuple[np.ndarray, np.ndarray] | None:
    """Per-frame max(team penetration past midfield) as a 0..1 attack proxy.

    Cached to /tmp so re-running the experiment doesn't re-pay for YOLO.
    """
    from app.cv.attack_analyzer import FIELD_MAX_CY, FIELD_MIN_CY, FIELD_MIN_H
    from app.cv.player_detector import get_player_detector

    cache = Path("/tmp") / f"pen_{Path(video).stem}.npz"
    if cache.exists():
        d = np.load(cache)
        return d["ts"], d["pen"]

    det = get_player_detector()
    ex = extract_frames(video, sample_fps=4.0, target_width=target_w)
    res = det.detect(ex.frames, ex.timestamps)
    if not res.available or not res.frames:
        return None
    ts, pen = [], []
    for fr in res.frames:
        players = [p for p in fr.players if FIELD_MIN_CY <= p.cy <= FIELD_MAX_CY and p.h >= FIELD_MIN_H]
        if len(players) < 4:
            continue
        mx = sum(p.cx for p in players) / len(players)
        ts.append(fr.timestamp_seconds)
        pen.append(max(0.5 - mx, mx - 0.5))  # distance of CoM past centre, either side
    if len(ts) < 3:
        return None
    ts_a, pen_a = np.asarray(ts, np.float32), _norm01(np.asarray(pen, np.float32))
    np.savez(cache, ts=ts_a, pen=pen_a)
    return ts_a, pen_a


def find_candidates(ts: np.ndarray, score: np.ndarray, max_n: int, min_sep_s: float = 6.0):
    """Local-maxima peaks of score, greedy non-max-suppression by time, top N."""
    n = len(score)
    peaks = [i for i in range(1, n - 1) if score[i] >= score[i - 1] and score[i] >= score[i + 1]]
    if not peaks:
        peaks = [int(np.argmax(score))]
    peaks.sort(key=lambda i: float(score[i]), reverse=True)
    chosen: list[int] = []
    for i in peaks:
        if all(abs(ts[i] - ts[j]) >= min_sep_s for j in chosen):
            chosen.append(i)
        if len(chosen) >= max_n:
            break
    chosen.sort(key=lambda i: ts[i])
    return [(float(ts[i]), float(score[i])) for i in chosen]


def argpeak(ts: np.ndarray, sig: np.ndarray) -> float:
    return float(ts[int(np.argmax(sig))]) if len(sig) else float("nan")


def main() -> None:
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    folder = Path(pos[0] if pos else "../clips")
    gt = float(_arg("--gt", 30.0))
    tol = float(_arg("--tol", 4.0))
    max_n = int(_arg("--max", 3))
    use_players = "--no-players" not in sys.argv

    clips = sorted(folder.glob("*.mp4"))
    if not clips:
        print(f"No clips in {folder}")
        raise SystemExit(1)

    rows = []
    for clip in clips:
        ex = extract_frames(str(clip), sample_fps=8.0, target_width=640)
        if len(ex) < 4:
            rows.append({"clip": clip.name, "error": "frame extract failed"})
            continue
        ts = np.asarray(ex.timestamps, dtype=np.float32)
        motion = analyze_motion(ex)
        m = _norm01(np.asarray(motion.motion_curve, dtype=np.float32))
        pan = camera_pan(ex.frames)
        loc = np.abs(pan)
        rec = _norm01(recenter_after(pan, ts))

        comps = {"motion": argpeak(ts, m), "pan|loc|": argpeak(ts, loc), "recenter": argpeak(ts, rec)}

        players_sig = None
        if use_players:
            pp = player_penetration(str(clip))
            if pp is not None:
                pts, pval = pp
                players_sig = np.interp(ts, pts, pval, left=0.0, right=0.0).astype(np.float32)
                comps["players"] = argpeak(ts, players_sig)

        # Primary combined score: a real shot is a motion burst while play is deep
        # in a third, ideally followed by a recenter swing; players reinforce it.
        score = m * (0.4 + 0.6 * loc) + 0.30 * rec
        if players_sig is not None:
            score = score + 0.40 * players_sig * (0.4 + 0.6 * loc)
        # light smoothing
        if len(score) >= 3:
            score = np.convolve(score, np.ones(3) / 3, mode="same")

        cands = find_candidates(ts, score, max_n)
        dists = [abs(c[0] - gt) for c in cands]
        closest = min(dists) if dists else float("inf")

        def hit(cand_list):
            return any(abs(c[0] - gt) <= tol for c in cand_list)

        # Is the event even reachable with a bigger budget? (signal present vs absent)
        recall_at = {b: hit(find_candidates(ts, score, b)) for b in (3, 5, 8)}
        # Per-signal candidate sets (top-3 each) to see the best single signal.
        per_signal = {
            "motion": hit(find_candidates(ts, m, 3)),
            "loc": hit(find_candidates(ts, loc, 3)),
            "recenter": hit(find_candidates(ts, rec, 3)),
        }
        if players_sig is not None:
            per_signal["players"] = hit(find_candidates(ts, players_sig, 3))

        rows.append({
            "clip": clip.name,
            "candidates": [round(c[0], 1) for c in cands],
            "cand_scores": [round(c[1], 3) for c in cands],
            "count": len(cands),
            "closest": round(closest, 1),
            "pass": closest <= tol,
            "recall_at": recall_at,
            "per_signal_hit": per_signal,
            "components": {k: round(v, 1) for k, v in comps.items()},
            "dur": ex.duration_seconds,
        })

    # ---- report ----
    print("\n" + "=" * 100)
    print(f"LOCAL CANDIDATE LOCALIZATION (no Gemini)   GT={gt:.0f}s  tol=±{tol:.0f}s  max_cands={max_n}  players={use_players}")
    print("=" * 100)
    print(f"{'clip':42} {'cands (s)':22} {'cnt':>3} {'closest':>7} {'res':>5}")
    print("-" * 100)
    npass = 0
    for r in rows:
        if "error" in r:
            print(f"{r['clip']:42} ERROR: {r['error']}")
            continue
        npass += 1 if r["pass"] else 0
        cand_str = ",".join(fmt(c) for c in r["candidates"])
        print(f"{r['clip']:42} {cand_str:22} {r['count']:>3} {r['closest']:>6.1f}s {'PASS' if r['pass'] else 'FAIL':>5}")
    n = sum(1 for r in rows if "error" not in r)
    avg_cnt = np.mean([r["count"] for r in rows if "error" not in r]) if n else 0
    print("-" * 100)
    print(f"RECALL (candidate within ±{tol:.0f}s of {gt:.0f}s): {npass}/{n}    avg candidates/clip: {avg_cnt:.1f}")
    print("=" * 100)
    # recall at larger budgets: is the moment reachable if we allow more candidates?
    for b in (3, 5, 8):
        hits = sum(1 for r in rows if "error" not in r and r["recall_at"][b])
        print(f"  recall@top-{b} (combined score): {hits}/{n}")
    print("\nPer-signal recall@top-3 (does this ONE signal alone hit ~30s?):")
    for key in ("motion", "loc", "recenter", "players"):
        hits = sum(1 for r in rows if "error" not in r and r["per_signal_hit"].get(key))
        denom = sum(1 for r in rows if "error" not in r and key in r["per_signal_hit"])
        if denom:
            print(f"  {key:9}: {hits}/{denom}")

    print("\nPer-signal peak location (which single signal best predicts ~30s?):")
    print(f"{'clip':42} " + " ".join(f"{k:>9}" for k in ["motion", "pan|loc|", "recenter", "players"]))
    for r in rows:
        if "error" in r:
            continue
        c = r["components"]
        print(f"{r['clip']:42} " + " ".join(f"{fmt(c.get(k)):>9}" for k in ["motion", "pan|loc|", "recenter", "players"]))

    Path("/tmp/exp_localize.json").write_text(json.dumps(rows, indent=2))
    print("\nWrote /tmp/exp_localize.json")


if __name__ == "__main__":
    main()
