"""Run a full-match shot/goal scan on a long video.

Usage:
    python scripts/scan_match.py /path/to/video.mp4 [concurrency]

Outputs highlight clips named 'MM-SS <type>.mp4' into
    backend/storage/clips/<video_stem>/
plus an events.json summary. Progress + a checkpoint are written as it runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.full_match_service import analyze_full_match  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python scripts/scan_match.py <video> [concurrency]")
        raise SystemExit(2)

    video = sys.argv[1]
    concurrency = int(sys.argv[2]) if len(sys.argv) > 2 else None
    checkpoint = Path(video).with_suffix("").name + ".checkpoint.json"

    res = analyze_full_match(video, concurrency=concurrency, checkpoint_path=f"/tmp/{checkpoint}")

    print("=" * 70)
    print(f"VIDEO     : {res.video}  ({res.duration_seconds:.0f}s)")
    print(f"WINDOWS   : {res.windows_judged}/{res.windows_total} judged, {res.windows_failed} failed")
    print(f"EVENTS    : {len(res.events)}")
    print(f"CLIPS DIR : {res.output_dir}")
    print("-" * 70)
    for e in res.events:
        print(f"  {e.timestamp_label:>6}  {e.event_type:4}  conf={e.confidence:.2f}  "
              f"x{e.cluster_size}  -> {e.clip_filename}")
        print(f"          {e.explanation[:110]}")
    print("=" * 70)


if __name__ == "__main__":
    main()
