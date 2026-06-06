"""Dump the per-window VLM verdicts + final fusion for one clip.

Usage:
    python scripts/debug_clip.py ../clips/DordtFirstHalfSept212024_goal_2312.mp4
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.detection_service import analyze_demo_clip  # noqa: E402


def main() -> None:
    clip = sys.argv[1]
    res = analyze_demo_clip(clip, attacking_direction="unknown")
    d = res.debug or {}
    vlm = d.get("vlm_results") or []
    print("\n" + "=" * 78)
    print(f"CLIP: {Path(clip).name}")
    print(f"FINAL: {res.event_type} @ {res.timestamp_seconds} (conf {res.confidence})")
    print("-" * 78)
    print("per-window VLM verdicts:")
    for w in sorted(vlm, key=lambda x: (x.get("window") or [0])[0]):
        win = w.get("window", [0, 0])
        et = w.get("event_type")
        mark = "  <== FIRED" if et in {"shot", "goal"} else ""
        print(f"  [{win[0]:>5},{win[1]:>5}] {str(et):5} ts={w.get('timestamp_seconds')} "
              f"conf={w.get('confidence')}{mark}")
        ev = w.get("evidence") or []
        if ev:
            print(f"          evidence: {ev[0][:80]}")
    print("=" * 78)


if __name__ == "__main__":
    main()
