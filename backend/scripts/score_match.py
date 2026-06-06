"""Score a full-match scan against user-provided ground truth.

Ground-truth file: one event per line, "MM:SS type", '#' comments allowed:
    # Dordt first half
    21:45 shot
    23:12 goal
    36:27 shot

Usage:
    python scripts/score_match.py <ground_truth.txt> <events.json> [tolerance_s]

Reports precision / recall, plus the exact false positives (detected, no truth
nearby) and false negatives (truth, nothing detected nearby), and type errors.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT_TOL = 8.0


def parse_ts(token: str) -> float:
    token = token.strip().replace("-", ":")
    if ":" in token:
        m, s = token.split(":")
        return int(m) * 60 + float(s)
    return float(token)


def load_truth(path: str) -> list[tuple[float, str]]:
    truth = []
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        ts = parse_ts(parts[0])
        typ = parts[1].lower() if len(parts) > 1 else "shot"
        typ = "goal" if typ.startswith("goal") else "shot"
        truth.append((ts, typ))
    return sorted(truth)


def fmt(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    return f"{m:02d}:{s:02d}"


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: python scripts/score_match.py <ground_truth.txt> <events.json> [tol_s]")
        raise SystemExit(2)

    truth = load_truth(sys.argv[1])
    events = json.loads(Path(sys.argv[2]).read_text())["events"]
    tol = float(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_TOL
    # Optional 4th arg: only score events/truth up to this many seconds.
    cap = float(sys.argv[4]) if len(sys.argv) > 4 else None
    if cap is not None:
        truth = [t for t in truth if t[0] <= cap]
        events = [e for e in events if float(e["timestamp_seconds"]) <= cap]

    det = sorted([(float(e["timestamp_seconds"]), e["event_type"], e) for e in events])

    matched_truth = set()
    matched_det = set()
    type_errors = []

    for di, (dts, dtyp, e) in enumerate(det):
        best = None
        for ti, (tts, ttyp) in enumerate(truth):
            if ti in matched_truth:
                continue
            if abs(dts - tts) <= tol:
                if best is None or abs(dts - tts) < abs(dts - truth[best][0]):
                    best = ti
        if best is not None:
            matched_truth.add(best)
            matched_det.add(di)
            if truth[best][1] != dtyp:
                type_errors.append((fmt(dts), f"detected {dtyp}, truth {truth[best][1]}"))

    tp = len(matched_det)
    fp = [det[i] for i in range(len(det)) if i not in matched_det]
    fn = [truth[i] for i in range(len(truth)) if i not in matched_truth]

    precision = tp / max(len(det), 1)
    recall = tp / max(len(truth), 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)

    print("=" * 70)
    print(f"GROUND TRUTH : {len(truth)} events   DETECTED : {len(det)} events   (tol ±{tol:.0f}s)")
    print(f"TRUE POS     : {tp}")
    print(f"FALSE POS    : {len(fp)}  (detected, nothing real nearby)")
    print(f"FALSE NEG    : {len(fn)}  (real, missed)")
    print(f"TYPE ERRORS  : {len(type_errors)}  (matched but shot/goal wrong)")
    print("-" * 70)
    print(f"PRECISION    : {precision:.0%}   RECALL : {recall:.0%}   F1 : {f1:.0%}")
    print("=" * 70)
    if fp:
        print("\nFALSE POSITIVES (consider tightening):")
        for dts, dtyp, e in fp:
            print(f"  {fmt(dts)}  {dtyp:4} conf={e['confidence']:.2f} x{e['cluster_size']} "
                  f"outcome={e.get('outcome','?')}")
    if fn:
        print("\nFALSE NEGATIVES (missed real events):")
        for tts, ttyp in fn:
            print(f"  {fmt(tts)}  {ttyp}")
    if type_errors:
        print("\nTYPE ERRORS:")
        for t, msg in type_errors:
            print(f"  {t}  {msg}")


if __name__ == "__main__":
    main()
