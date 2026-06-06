"""Experiment (approach B): verify candidates by their CONSEQUENCE, not the ball.

Reuses the saved recall checkpoint (no re-paying for the recall pass), turns the
fired windows into fine-grained candidate moments, then asks the VLM whether play
visibly RESETS after each (keeper possession / goal kick / corner / kickoff). Keeps
only candidates whose aftermath confirms a shot, and scores against ground truth.

Usage:
    python scripts/exp_aftermath.py <video> <checkpoint.json> <ground_truth.txt> \
        [--cap 1380] [--merge 5] [--tol 10] [--workers 6] [--out /tmp/aftermath.json]
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services.vlm_service import get_vlm_judge  # noqa: E402


def _arg(flag: str, default):
    if flag in sys.argv:
        return sys.argv[sys.argv.index(flag) + 1]
    return default


def fmt(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    return f"{m:02d}:{s:02d}"


def parse_ts(token: str) -> float:
    token = token.strip().replace("-", ":")
    if ":" in token:
        m, s = token.split(":")
        return int(m) * 60 + float(s)
    return float(token)


def load_truth(path: str, cap: float) -> list[tuple[float, str]]:
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        ts = parse_ts(parts[0])
        typ = "goal" if len(parts) > 1 and parts[1].lower().startswith("goal") else "shot"
        if ts <= cap:
            out.append((ts, typ))
    return sorted(out)


def build_candidates(checkpoint: str, cap: float, merge_gap: float) -> list[dict]:
    """Fired windows -> distinct candidate moments (merge reported ts within gap)."""
    raw = json.loads(Path(checkpoint).read_text())
    fired = [
        w for w in raw
        if w.get("event_type") in ("shot", "goal")
        and isinstance(w.get("timestamp_seconds"), (int, float))
        and (w.get("confidence") or 0.0) >= settings.shot_threshold
        and w["timestamp_seconds"] <= cap
    ]
    fired.sort(key=lambda w: w["timestamp_seconds"])
    groups: list[list[dict]] = []
    for w in fired:
        if groups and w["timestamp_seconds"] - groups[-1][-1]["timestamp_seconds"] <= merge_gap:
            groups[-1].append(w)
        else:
            groups.append([w])
    cands = []
    for g in groups:
        tot = sum(w["confidence"] for w in g) or 1.0
        ts = sum(w["confidence"] * w["timestamp_seconds"] for w in g) / tot
        cands.append({
            "timestamp_seconds": round(ts, 2),
            "recall_size": len(g),
            "recall_conf": round(max(w["confidence"] for w in g), 2),
        })
    return cands


def main() -> None:
    if len(sys.argv) < 4:
        print(__doc__)
        raise SystemExit(2)

    video, checkpoint, gt = sys.argv[1], sys.argv[2], sys.argv[3]
    cap = float(_arg("--cap", 1380))
    merge_gap = float(_arg("--merge", 5))
    tol = float(_arg("--tol", 10))
    workers = int(_arg("--workers", 6))
    out = _arg("--out", "/tmp/aftermath_events.json")

    judge = get_vlm_judge()
    if not judge.available:
        raise RuntimeError("VLM judge unavailable (no GEMINI_API_KEY?).")

    duration_cap = cap + 60  # allow aftermath window to run past the cap
    cands = build_candidates(checkpoint, cap, merge_gap)
    print(f"Built {len(cands)} candidate moments (cap {fmt(cap)}, merge {merge_gap}s).")

    def _verify(c: dict) -> dict:
        ts = c["timestamp_seconds"]
        start = max(0.0, ts - settings.aftermath_pre)
        end = ts + settings.aftermath_post
        v = judge.verify_aftermath(str(video), start, end)
        kept = v.event_type in ("shot", "goal") and v.confidence >= settings.aftermath_threshold
        out_ts = v.timestamp_seconds if v.timestamp_seconds is not None else ts
        rec = {
            "cand_ts": ts, "kept": kept,
            "event_type": v.event_type, "confidence": round(v.confidence, 2),
            "timestamp_seconds": round(out_ts, 2),
            "consequence": v.outcome, "evidence": v.evidence[:3],
            "recall_size": c["recall_size"], "error": v.error,
        }
        tag = "KEEP " if kept else "drop "
        print(f"  {tag}{fmt(ts)} -> {v.event_type:4} conf={v.confidence:.2f} "
              f"consequence={v.outcome or '?':22} {('| ' + v.evidence[0][:60]) if v.evidence else ''}")
        return rec

    with ThreadPoolExecutor(max_workers=workers) as pool:
        records = list(pool.map(_verify, cands))

    kept = [r for r in records if r["kept"]]
    # collapse kept that fall within tol of each other (overlapping aftermath windows)
    kept.sort(key=lambda r: r["timestamp_seconds"])
    merged: list[dict] = []
    for r in kept:
        if merged and r["timestamp_seconds"] - merged[-1]["timestamp_seconds"] <= tol:
            if r["confidence"] > merged[-1]["confidence"]:
                merged[-1] = r
        else:
            merged.append(r)

    truth = load_truth(gt, cap)
    det = sorted([(r["timestamp_seconds"], r["event_type"], r) for r in merged])
    matched_t, matched_d = set(), set()
    for di, (dts, dtyp, r) in enumerate(det):
        best = None
        for ti, (tts, _) in enumerate(truth):
            if ti in matched_t:
                continue
            if abs(dts - tts) <= tol and (best is None or abs(dts - tts) < abs(dts - truth[best][0])):
                best = ti
        if best is not None:
            matched_t.add(best)
            matched_d.add(di)

    tp = len(matched_d)
    fp = [det[i] for i in range(len(det)) if i not in matched_d]
    fn = [truth[i] for i in range(len(truth)) if i not in matched_t]
    precision = tp / max(len(det), 1)
    recall = tp / max(len(truth), 1)

    print("=" * 70)
    print(f"CANDIDATES : {len(cands)}  ->  KEPT {len(merged)} (after aftermath verify + merge)")
    print(f"TRUTH      : {len(truth)}   TP {tp}   FP {len(fp)}   FN {len(fn)}   (tol ±{tol:.0f}s)")
    print(f"PRECISION  : {precision:.0%}   RECALL : {recall:.0%}")
    print("=" * 70)
    if fn:
        print("MISSED (false negatives):")
        for tts, ttyp in fn:
            print(f"  {fmt(tts)} {ttyp}")
    if fp:
        print("EXTRA (false positives):")
        for dts, dtyp, r in fp:
            print(f"  {fmt(dts)} {dtyp} conf={r['confidence']:.2f} consequence={r['consequence']}")

    Path(out).write_text(json.dumps(
        {"events": [{**r, "cluster_size": r["recall_size"], "outcome": r["consequence"],
                     "explanation": "; ".join(r["evidence"])} for r in merged],
         "all_records": records}, indent=2))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
