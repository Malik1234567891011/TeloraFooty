"""Optional audio loudness analysis using ffmpeg.

Detects loudness spikes (crowd/whistle/cheer) that often accompany goals. Uses
ffmpeg's ``astats`` over short windows. Returns ``None`` gracefully if audio is
absent or ffmpeg fails, so the pipeline never depends on it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class AudioResult:
    has_audio: bool = False
    spike_timestamp: float | None = None
    spike_score: float = 0.0  # 0..1 relative loudness of the spike


def analyze_audio(video_path: str, window_seconds: float = 1.0) -> AudioResult:
    if shutil.which("ffmpeg") is None:
        return AudioResult(has_audio=False)

    # Measure per-window RMS level via the astats filter, printed to stderr.
    cmd = [
        "ffmpeg",
        "-i",
        str(video_path),
        "-af",
        f"astats=metadata=1:reset={int(max(1, window_seconds))},ametadata=print:key=lavfi.astats.Overall.RMS_level",
        "-f",
        "null",
        "-",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (subprocess.SubprocessError, OSError) as exc:
        logger.info("Audio analysis skipped (%s).", exc)
        return AudioResult(has_audio=False)

    stderr = out.stderr or ""
    if "does not contain any stream" in stderr or "Audio: " not in stderr and "RMS_level" not in stderr:
        # Heuristic check; continue parsing anyway.
        pass

    times: list[float] = []
    levels: list[float] = []
    cur_time = 0.0
    for line in stderr.splitlines():
        tmatch = re.search(r"pts_time:([0-9.]+)", line)
        if tmatch:
            cur_time = float(tmatch.group(1))
        lmatch = re.search(r"RMS_level=(-?[0-9.]+|-inf)", line)
        if lmatch:
            raw = lmatch.group(1)
            level = -120.0 if raw == "-inf" else float(raw)
            times.append(cur_time)
            levels.append(level)

    if not levels:
        return AudioResult(has_audio=False)

    lo = min(levels)
    hi = max(levels)
    if hi <= lo:
        return AudioResult(has_audio=True, spike_timestamp=times[0], spike_score=0.0)

    idx = max(range(len(levels)), key=lambda i: levels[i])
    score = (levels[idx] - lo) / (hi - lo)
    return AudioResult(has_audio=True, spike_timestamp=round(times[idx], 3), spike_score=round(float(score), 4))
