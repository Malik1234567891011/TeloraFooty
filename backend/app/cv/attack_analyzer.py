"""Player-distribution based attack / shot detection.

Insight (validated on real Veo footage): a shot is preceded by players being
compressed toward a goal mouth, and is typically followed by a clearance / goal
kick where players stream back out toward midfield. Midfield build-up, by
contrast, keeps players spread out and never packs the goal mouth.

This analyzer turns per-frame player positions into time series and finds the
single strongest, most *prominent* attacking moment toward either goal. It does
NOT use hardcoded timestamps — everything is derived from where players are.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from app.cv.player_detector import PlayerDetectionResult
from app.core.logging import get_logger

logger = get_logger(__name__)

# A player box is treated as an on-field player only if it sits in the field
# band (excludes crowd/scoreboard up top and camera ops/coaches in the very
# foreground) and is big enough to be near play.
FIELD_MIN_CY = 0.33
FIELD_MAX_CY = 0.90
FIELD_MIN_H = 0.03

# Goal-mouth band width at each edge (used for transparency/debug only — it is
# too contaminated by sideline staff/spectators to drive the decision).
GOAL_BAND = 0.20
FIELD_CENTER = 0.5

# Decision thresholds (model parameters, not per-clip values). The signal is the
# collective shift of players toward a goal (penetration of mean_x past center).
MIN_PENETRATION = 0.06   # how far past center the team's center-of-mass pushes
MIN_PROMINENCE = 0.035   # how far the peak stands above the typical penetration
RECOVERY_FOR_CLEARANCE = 0.12  # mean_x rebound that signals a clearance/goal kick


@dataclass
class AttackResult:
    event_type: str  # "shot" | "none"
    timestamp_seconds: float | None
    confidence: float
    side: str | None  # "left" | "right"
    explanation: str
    available: bool = False
    debug: dict = field(default_factory=dict)


def _smooth(values: list[float], window: int = 3) -> list[float]:
    if len(values) < window or window <= 1:
        return list(values)
    half = window // 2
    out = []
    for i in range(len(values)):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        seg = values[lo:hi]
        out.append(sum(seg) / len(seg))
    return out


def _field_players(frame):
    return [
        p
        for p in frame.players
        if FIELD_MIN_CY <= p.cy <= FIELD_MAX_CY and p.h >= FIELD_MIN_H
    ]


def analyze_attack(detection: PlayerDetectionResult) -> AttackResult:
    if not detection.available or not detection.frames:
        return AttackResult("none", None, 0.0, None, "No player detections available.", available=False)

    timestamps: list[float] = []
    mean_x: list[float] = []
    left_occ: list[float] = []
    right_occ: list[float] = []

    for fr in detection.frames:
        players = _field_players(fr)
        if len(players) < 4:  # too few to judge a formation
            continue
        xs = [p.cx for p in players]
        n = len(xs)
        timestamps.append(fr.timestamp_seconds)
        mean_x.append(sum(xs) / n)
        left_occ.append(sum(1 for x in xs if x < GOAL_BAND) / n)
        right_occ.append(sum(1 for x in xs if x > (1 - GOAL_BAND)) / n)

    if len(timestamps) < 3:
        return AttackResult("none", None, 0.0, None, "Not enough usable frames.", available=True)

    mean_x_s = _smooth(mean_x)
    left_occ_s = _smooth(left_occ)
    right_occ_s = _smooth(right_occ)

    # Penetration = how far the team's center-of-mass pushes past midfield toward
    # each goal. This aggregate is robust to a few stray sideline detections,
    # unlike per-frame goal-mouth occupancy.
    left_pen = [max(0.0, FIELD_CENTER - mx) for mx in mean_x_s]
    right_pen = [max(0.0, mx - FIELD_CENTER) for mx in mean_x_s]

    left_i = max(range(len(left_pen)), key=lambda i: left_pen[i])
    right_i = max(range(len(right_pen)), key=lambda i: right_pen[i])

    # Each side's case is scored by penetration plus the strength of the
    # clearance/goal-kick rebound that follows it.
    left_recovery = _recovery_after_peak(mean_x_s, left_i, "left")
    right_recovery = _recovery_after_peak(mean_x_s, right_i, "right")
    left_score = left_pen[left_i] + 0.3 * left_recovery
    right_score = right_pen[right_i] + 0.3 * right_recovery

    if left_score >= right_score:
        side, peak_i, pen_series, recovery = "left", left_i, left_pen, left_recovery
    else:
        side, peak_i, pen_series, recovery = "right", right_i, right_pen, right_recovery

    peak_pen = pen_series[peak_i]
    baseline = median(pen_series)
    prominence = peak_pen - baseline
    peak_ts = timestamps[peak_i]

    debug = {
        "side": side,
        "peak_penetration": round(peak_pen, 4),
        "baseline": round(baseline, 4),
        "prominence": round(prominence, 4),
        "recovery": round(recovery, 4),
        "min_mean_x": round(min(mean_x_s), 4),
        "max_mean_x": round(max(mean_x_s), 4),
        "frames_used": len(timestamps),
        "series": [
            {"t": round(t, 2), "mean_x": round(mx, 3), "left": round(lo, 3), "right": round(ro, 3)}
            for t, mx, lo, ro in zip(timestamps, mean_x_s, left_occ_s, right_occ_s)
        ],
    }

    # A real shot needs a meaningful, prominent push toward a goal AND either a
    # strong penetration or a clearance rebound afterwards. Midfield play has
    # low penetration and no rebound, so it returns none.
    has_clearance = recovery >= RECOVERY_FOR_CLEARANCE
    if (
        peak_pen < MIN_PENETRATION
        or prominence < MIN_PROMINENCE
        or not (has_clearance or peak_pen >= 2 * MIN_PENETRATION)
    ):
        return AttackResult(
            "none",
            None,
            round(min(0.4, peak_pen * 2), 4),
            side,
            "Players never pushed decisively toward a goal — no clear shot/attack.",
            available=True,
            debug=debug,
        )

    confidence = 0.45 + 2.2 * prominence + 0.9 * recovery
    confidence = round(min(0.9, max(0.0, confidence)), 4)

    explanation = (
        f"Players pushed hardest toward the {side} goal at the strongest point of the clip "
        f"(penetration {peak_pen:.2f} vs typical {baseline:.2f})"
        + (
            ", then streamed back out toward midfield — consistent with a shot followed by a goal kick / keeper possession."
            if has_clearance
            else " — consistent with an attacking shot on goal."
        )
    )

    return AttackResult(
        event_type="shot",
        timestamp_seconds=round(peak_ts, 3),
        confidence=confidence,
        side=side,
        explanation=explanation,
        available=True,
        debug=debug,
    )


def _recovery_after_peak(mean_x_s: list[float], peak_i: int, side: str, lookahead: int = 12) -> float:
    """Measure how strongly play moved away from the attacked goal after the peak."""
    if peak_i >= len(mean_x_s) - 1:
        return 0.0
    after = mean_x_s[peak_i + 1 : peak_i + 1 + lookahead]
    if not after:
        return 0.0
    peak_val = mean_x_s[peak_i]
    if side == "left":
        # play recovers if mean_x increases (moves right, away from left goal)
        return float(max(0.0, max(after) - peak_val))
    return float(max(0.0, peak_val - min(after)))
