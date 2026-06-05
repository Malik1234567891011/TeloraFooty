"""Player detection (YOLO) with a safe no-op fallback.

Exposes a stable interface (docs/Plan.md Module 4). The YOLO model is loaded
once and reused. Beyond a simple count, it returns per-frame player positions so
the attack analyzer can reason about *where* players are over time (the key
signal for distinguishing an attack-on-goal from midfield play).

If Ultralytics/torch or the model file is unavailable, ``get_player_detector``
returns a ``NullPlayerDetector`` and the pipeline falls back to motion-only
analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PlayerBox:
    cx: float  # normalized 0..1 center x
    cy: float  # normalized 0..1 center y
    h: float   # normalized box height (a rough distance proxy)
    conf: float


@dataclass
class FramePlayers:
    timestamp_seconds: float
    players: list[PlayerBox] = field(default_factory=list)


@dataclass
class PlayerDetectionResult:
    players_detected: int = 0
    frames: list[FramePlayers] = field(default_factory=list)
    available: bool = False


class PlayerDetector(Protocol):
    def detect(self, frames: list[np.ndarray], timestamps: list[float]) -> PlayerDetectionResult:
        ...


class NullPlayerDetector:
    available = False

    def detect(self, frames: list[np.ndarray], timestamps: list[float]) -> PlayerDetectionResult:
        return PlayerDetectionResult(available=False)


class YoloPlayerDetector:
    """Ultralytics YOLO person detector. Loaded once; never crashes the app."""

    _model = None  # class-level cache shared across instances

    def __init__(self, model_path: str):
        self.available = False
        if YoloPlayerDetector._model is not None:
            self.available = True
            return
        try:
            from ultralytics import YOLO

            YoloPlayerDetector._model = YOLO(model_path)
            self.available = True
            logger.info("YoloPlayerDetector loaded from %s", model_path)
        except Exception as exc:  # pragma: no cover - optional path
            logger.warning("YoloPlayerDetector unavailable (%s); using fallback.", exc)

    def detect(self, frames: list[np.ndarray], timestamps: list[float]) -> PlayerDetectionResult:
        model = YoloPlayerDetector._model
        if not self.available or model is None or not frames:
            return PlayerDetectionResult(available=False)

        imgsz = settings.player_detect_imgsz
        conf = settings.player_detect_conf
        out_frames: list[FramePlayers] = []
        total = 0
        try:
            for frame, ts in zip(frames, timestamps):
                h, w = frame.shape[:2]
                result = model.predict(frame, verbose=False, conf=conf, imgsz=imgsz)[0]
                players: list[PlayerBox] = []
                for box in result.boxes:
                    if int(box.cls[0]) != 0:  # 0 = person (COCO)
                        continue
                    x1, y1, x2, y2 = [float(v) for v in box.xyxy[0]]
                    players.append(
                        PlayerBox(
                            cx=round((x1 + x2) / 2 / w, 4),
                            cy=round((y1 + y2) / 2 / h, 4),
                            h=round((y2 - y1) / h, 4),
                            conf=round(float(box.conf[0]) if box.conf is not None else 0.0, 4),
                        )
                    )
                out_frames.append(FramePlayers(timestamp_seconds=round(ts, 3), players=players))
                total += len(players)
        except Exception as exc:  # pragma: no cover - optional path
            logger.warning("Player detection failed mid-run (%s); returning partial.", exc)

        return PlayerDetectionResult(
            players_detected=total,
            frames=out_frames,
            available=bool(out_frames),
        )


def get_player_detector() -> PlayerDetector:
    if settings.enable_ml_detectors:
        model_path = settings.resolved_player_model_path or "yolov8n.pt"
        detector = YoloPlayerDetector(model_path)
        if detector.available:
            return detector
    return NullPlayerDetector()
