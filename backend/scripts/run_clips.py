"""Run the demo shot/goal detector over a folder of short clips.

Each clip is assumed to contain exactly one event. Reports the single headline
timestamp (MM:SS and raw seconds) the system picks for each clip.

Usage:
    python scripts/run_clips.py ../clips
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.detection_service import analyze_demo_clip  # noqa: E402


def fmt(sec) -> str:
    if sec is None:
        return "  --  "
    m, s = divmod(int(round(sec)), 60)
    return f"{m:01d}:{s:02d}"


def main() -> None:
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "../clips")
    clips = sorted(folder.glob("*.mp4"))
    if not clips:
        print(f"No .mp4 clips in {folder}")
        raise SystemExit(1)

    rows = []
    for clip in clips:
        print(f"--- analyzing {clip.name} ...", flush=True)
        try:
            res = analyze_demo_clip(str(clip), attacking_direction="unknown")
            rows.append((clip.name, res.event_type, res.timestamp_seconds, res.confidence, res.explanation))
        except Exception as exc:
            rows.append((clip.name, "ERROR", None, 0.0, str(exc)))

    print("\n" + "=" * 90)
    print(f"{'CLIP':45} {'DETECTED':6} {'TIME':>7} {'SECS':>7}  CONF")
    print("-" * 90)
    for name, et, ts, conf, _ in rows:
        print(f"{name:45} {et:6} {fmt(ts):>7} {('%.1f' % ts) if ts is not None else '  --':>7}  {conf:.2f}")
    print("=" * 90)
    for name, et, ts, conf, expl in rows:
        print(f"\n{name}\n  -> {et} @ {fmt(ts)} ({('%.1f' % ts) if ts is not None else '--'}s), conf {conf:.2f}")
        print(f"  {expl[:160]}")


if __name__ == "__main__":
    main()
