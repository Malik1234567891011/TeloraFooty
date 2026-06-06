"""Re-run fusion + strict verification from a saved recall checkpoint.

Avoids re-paying for the ~480-window recall pass while we iterate on precision.

Usage:
    python scripts/verify_from_checkpoint.py <video> <checkpoint.json> [--no-clips]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.full_match_service import analyze_from_checkpoint  # noqa: E402


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: python scripts/verify_from_checkpoint.py <video> <checkpoint.json> [--no-clips]")
        raise SystemExit(2)

    video = sys.argv[1]
    checkpoint = sys.argv[2]
    gen_clips = "--no-clips" not in sys.argv[3:]

    res = analyze_from_checkpoint(video, checkpoint, verify=True, generate_clips=gen_clips)

    print("=" * 70)
    print(f"VIDEO  : {res.video}  ({res.duration_seconds:.0f}s)")
    print(f"EVENTS : {len(res.events)} (after strict verification)")
    print("-" * 70)
    for e in res.events:
        print(f"  {e.timestamp_label:>6}  {e.event_type:4}  conf={e.confidence:.2f}  "
              f"outcome={e.outcome or '?':6}  -> {e.clip_filename}")
        print(f"          {e.explanation[:110]}")
    print("=" * 70)


if __name__ == "__main__":
    main()
