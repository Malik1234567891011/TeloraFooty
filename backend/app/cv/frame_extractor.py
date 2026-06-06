"""Frame extraction for demo-clip analysis.

Samples frames at a configurable FPS and downscales them for fast analysis,
while keeping the original video untouched for final clipping (docs/Plan.md
Module 1 + Performance rules).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ExtractedFrames:
    frames: list[np.ndarray] = field(default_factory=list)
    timestamps: list[float] = field(default_factory=list)
    fps_sampled: float = 0.0
    duration_seconds: float = 0.0
    source_fps: float = 0.0
    width: int = 0
    height: int = 0

    def __len__(self) -> int:
        return len(self.frames)


def extract_frames(
    video_path: str,
    sample_fps: float = 6.0,
    target_width: int = 640,
) -> ExtractedFrames:
    """Extract downscaled frames sampled at ~``sample_fps``.

    Returns an empty ``ExtractedFrames`` (never raises) if the video cannot be
    opened, so the pipeline can fall back gracefully.
    """
    try:
        import cv2
    except ImportError:
        logger.warning("OpenCV not available; cannot extract frames.")
        return ExtractedFrames()

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.warning("Could not open video for frame extraction: %s", video_path)
        return ExtractedFrames()

    try:
        source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if source_fps <= 0:
            source_fps = 30.0
        duration = frame_count / source_fps if frame_count else 0.0

        step = max(1, int(round(source_fps / max(sample_fps, 0.1))))

        scale = target_width / src_w if src_w > target_width else 1.0
        out_w = int(src_w * scale) if scale < 1.0 else src_w
        out_h = int(src_h * scale) if scale < 1.0 else src_h

        frames: list[np.ndarray] = []
        timestamps: list[float] = []
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                if scale < 1.0:
                    frame = cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA)
                frames.append(frame)
                timestamps.append(idx / source_fps)
            idx += 1

        actual_sample_fps = (len(frames) / duration) if duration > 0 and frames else sample_fps
        logger.info(
            "Extracted %d frames at ~%.1f fps from %.1fs clip.",
            len(frames),
            actual_sample_fps,
            duration,
        )
        return ExtractedFrames(
            frames=frames,
            timestamps=timestamps,
            fps_sampled=round(actual_sample_fps, 2),
            duration_seconds=round(duration, 3),
            source_fps=source_fps,
            width=out_w or src_w,
            height=out_h or src_h,
        )
    finally:
        cap.release()
