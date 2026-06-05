"""Calibration harness for the demo shot/goal detector.

Runs the full detection pipeline against clips with VERIFIED ground truth and
scores the result, so calibration changes can be measured instead of guessed.

Ground truth (provided by the user — do NOT hardcode into the detector):
    g17cunetestingfilmmidland.mp4 : exactly one shot at ~26s, no goal.
    mountmartytestingfilm.mp4     : exactly one shot at ~36s, no goal.

Usage:
    python scripts/calibrate.py            # run all clips
    python scripts/calibrate.py mountmarty # run clips matching a substring

Each clip is scored on:
    - decision_ok : final event_type + timestamp match ground truth (±TOL s)
    - precision   : how many windows fired shot/goal vs. how many should have
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# Make `app` importable when run from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.detection_service import analyze_demo_clip  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
TOL = 5.0  # seconds tolerance for the headline timestamp


@dataclass
class Truth:
    filename: str
    event_type: str          # "shot" | "goal" | "none"
    timestamp: float | None   # seconds, or None
    # A window is "expected to fire" if it overlaps [timestamp-pad, timestamp+pad].
    pad: float = 4.0


GROUND_TRUTH = [
    Truth("g17cunetestingfilmmidland.mp4", "shot", 26.0),
    Truth("mountmartytestingfilm.mp4", "shot", 36.0),
]


def _window_should_fire(truth: Truth, ws: float, we: float) -> bool:
    if truth.timestamp is None:
        return False
    lo, hi = truth.timestamp - truth.pad, truth.timestamp + truth.pad
    return not (we < lo or ws > hi)


def score_clip(truth: Truth) -> dict:
    path = REPO / truth.filename
    if not path.exists():
        return {"filename": truth.filename, "error": "missing file"}

    res = analyze_demo_clip(str(path), attacking_direction="unknown")
    d = res.debug or {}
    vlm = d.get("vlm_results") or []

    # Decision correctness.
    ts_ok = (
        truth.timestamp is not None
        and res.timestamp_seconds is not None
        and abs(res.timestamp_seconds - truth.timestamp) <= TOL
    )
    type_ok = res.event_type == truth.event_type
    decision_ok = type_ok and (ts_ok or truth.event_type == "none")

    # Window-level precision: count fires vs. expected fires.
    fired = [r for r in vlm if r.get("event_type") in {"shot", "goal"}]
    correct_fires = [
        r for r in fired
        if _window_should_fire(truth, r.get("window", [0, 0])[0], r.get("window", [0, 0])[1])
    ]
    false_fires = [r for r in fired if r not in correct_fires]

    return {
        "filename": truth.filename,
        "expected": f"{truth.event_type}@{truth.timestamp}",
        "got": f"{res.event_type}@{res.timestamp_seconds} (conf {res.confidence})",
        "decision_ok": decision_ok,
        "type_ok": type_ok,
        "ts_ok": ts_ok,
        "n_windows": len(vlm),
        "n_fired": len(fired),
        "n_false_fires": len(false_fires),
        "vlm": vlm,
        "explanation": res.explanation,
    }


def main() -> None:
    needle = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    truths = [t for t in GROUND_TRUTH if needle in t.filename.lower()]

    overall_ok = True
    for truth in truths:
        r = score_clip(truth)
        print("=" * 78)
        print(f"CLIP: {r['filename']}")
        if "error" in r:
            print(f"  ERROR: {r['error']}")
            continue
        print(f"  expected : {r['expected']}")
        print(f"  got      : {r['got']}")
        print(f"  decision : {'PASS' if r['decision_ok'] else 'FAIL'}"
              f"  (type_ok={r['type_ok']} ts_ok={r['ts_ok']})")
        print(f"  windows  : {r['n_windows']} total | {r['n_fired']} fired | "
              f"{r['n_false_fires']} FALSE fires")
        print(f"  explain  : {r['explanation'][:160]}")
        print("  --- per-window ---")
        for w in r["vlm"]:
            win = w.get("window", [0, 0])
            mark = ""
            if w.get("event_type") in {"shot", "goal"}:
                mark = " <== FALSE" if w in [
                    x for x in r["vlm"]
                    if x.get("event_type") in {"shot", "goal"}
                    and not _window_should_fire(truth, x.get("window", [0, 0])[0], x.get("window", [0, 0])[1])
                ] else " <== expected"
            print(f"    [{win[0]:>5}, {win[1]:>5}] {str(w.get('event_type')):5} "
                  f"ts={w.get('timestamp_seconds')} conf={w.get('confidence')}{mark}")
        overall_ok = overall_ok and r["decision_ok"] and r["n_false_fires"] == 0

    print("=" * 78)
    print(f"OVERALL: {'ALL PASS (decision + zero false fires)' if overall_ok else 'NOT YET CLEAN'}")


if __name__ == "__main__":
    main()
