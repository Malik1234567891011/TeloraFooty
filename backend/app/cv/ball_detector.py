"""Ball detection interface and a safe default implementation.

The interface is stable so a fine-tuned detector can be swapped in later
(docs/Plan.md Module 3, bestpractices.md #4/#14). The default
``NullBallDetector`` returns no detections so the pipeline degrades gracefully
to motion-only analysis.

If ML detectors are enabled and Ultralytics + a model are available, the
``YoloBallDetector`` can be used. It is imported lazily and never required.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class BallDetection:
    timestamp_seconds: float
    x: float  # normalized 0..1 center x
    y: float  # normalized 0..1 center y
    confidence: float


class BallDetector(Protocol):
    def detect(self, frames: list[np.ndarray], timestamps: list[float]) -> list[BallDetection]:
        ...


class NullBallDetector:
    """Returns no detections. Used when ML detectors are disabled/unavailable."""

    available = False

    def detect(self, frames: list[np.ndarray], timestamps: list[float]) -> list[BallDetection]:
        return []


class YoloBallDetector:
    """Optional Ultralytics-backed detector. Loaded once; never crashes the app."""

    def __init__(self, model_path: str):
        self.available = False
        self._model = None
        try:
            from ultralytics import YOLO

            self._model = YOLO(model_path)
            self.available = True
            logger.info("YoloBallDetector loaded from %s", model_path)
        except Exception as exc:  # pragma: no cover - optional path
            logger.warning("YoloBallDetector unavailable (%s); using fallback.", exc)

    def detect(self, frames: list[np.ndarray], timestamps: list[float]) -> list[BallDetection]:
        if not self.available or self._model is None:
            return []
        detections: list[BallDetection] = []
        try:  # pragma: no cover - optional path
            for frame, ts in zip(frames, timestamps):
                h, w = frame.shape[:2]
                results = self._model.predict(frame, verbose=False)
                for r in results:
                    for box in getattr(r, "boxes", []):
                        cls = int(box.cls[0]) if box.cls is not None else -1
                        name = r.names.get(cls, "") if hasattr(r, "names") else ""
                        if "ball" not in str(name).lower() and cls != 32:  # 32 = sports ball (COCO)
                            continue
                        xyxy = box.xyxy[0].tolist()
                        cx = (xyxy[0] + xyxy[2]) / 2 / w
                        cy = (xyxy[1] + xyxy[3]) / 2 / h
                        conf = float(box.conf[0]) if box.conf is not None else 0.0
                        detections.append(BallDetection(round(ts, 3), round(cx, 4), round(cy, 4), round(conf, 4)))
        except Exception as exc:  # pragma: no cover - optional path
            logger.warning("Ball detection failed mid-run (%s); returning partial.", exc)
        return detections


def get_ball_detector() -> BallDetector:
    """Factory honoring configuration. Defaults to the safe no-op detector."""
    if settings.enable_ml_detectors and settings.ball_model_path:
        detector = YoloBallDetector(settings.ball_model_path)
        if detector.available:
            return detector
    return NullBallDetector()
