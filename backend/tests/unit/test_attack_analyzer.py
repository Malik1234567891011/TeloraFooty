from __future__ import annotations

from app.cv.attack_analyzer import analyze_attack
from app.cv.player_detector import FramePlayers, PlayerBox, PlayerDetectionResult


def _players(xs: list[float]) -> list[PlayerBox]:
    # cy/h chosen to pass the on-field filter.
    return [PlayerBox(cx=x, cy=0.6, h=0.08, conf=0.6) for x in xs]


def _result(frames: list[FramePlayers]) -> PlayerDetectionResult:
    return PlayerDetectionResult(
        players_detected=sum(len(f.players) for f in frames),
        frames=frames,
        available=True,
    )


def test_unavailable_returns_none():
    res = analyze_attack(PlayerDetectionResult(available=False))
    assert res.event_type == "none"
    assert res.available is False


def test_midfield_play_returns_none():
    # Players always spread around midfield -> no attack.
    frames = []
    for i in range(20):
        xs = [0.35, 0.45, 0.5, 0.55, 0.65, 0.4, 0.6, 0.5]
        frames.append(FramePlayers(timestamp_seconds=i * 0.5, players=_players(xs)))
    res = analyze_attack(_result(frames))
    assert res.event_type == "none"


def test_attack_on_left_goal_detected_with_recovery():
    frames = []
    for i in range(40):
        t = i * 0.5
        if 10 <= t <= 13:  # compress toward the left goal mouth around t=10-13
            xs = [0.05, 0.08, 0.12, 0.15, 0.18, 0.1, 0.2, 0.25]
        elif t > 13:  # clearance / goal kick: players stream back out to midfield
            xs = [0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.5, 0.6]
        else:  # earlier midfield play
            xs = [0.4, 0.45, 0.5, 0.55, 0.6, 0.5, 0.45, 0.5]
        frames.append(FramePlayers(timestamp_seconds=t, players=_players(xs)))
    res = analyze_attack(_result(frames))
    assert res.event_type == "shot"
    assert res.side == "left"
    assert 10.0 <= res.timestamp_seconds <= 13.5
    assert 0.0 < res.confidence <= 0.9
    assert res.debug["recovery"] > 0.15


def test_attack_on_right_goal_detected():
    frames = []
    for i in range(30):
        t = i * 0.5
        if 6 <= t <= 9:
            xs = [0.95, 0.92, 0.88, 0.85, 0.82, 0.9, 0.8, 0.78]
        else:
            xs = [0.45, 0.5, 0.55, 0.5, 0.6, 0.4, 0.5, 0.52]
        frames.append(FramePlayers(timestamp_seconds=t, players=_players(xs)))
    res = analyze_attack(_result(frames))
    assert res.event_type == "shot"
    assert res.side == "right"
    assert 6.0 <= res.timestamp_seconds <= 9.5
