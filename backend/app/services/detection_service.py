"""Orchestrates the 30-second demo clip analysis (Mode B).

Wires together the CV modules. Each stage is wrapped so a single failure falls
back gracefully (bestpractices.md #5). Always returns a structured result with
``result`` + ``debug`` sections.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.ids import new_id
from app.core.logging import get_logger
from app.cv import attack_analyzer, audio_analyzer, candidate_generator, frame_extractor, motion_analyzer
from app.cv.ball_detector import get_ball_detector
from app.cv.event_classifier import ClassifierInputs, classify_event
from app.cv.player_detector import get_player_detector
from app.services.clip_service import clip_window_for_event, generate_clip
from app.services.vlm_service import VlmJudgment, get_vlm_judge
from app.services.wholeclip_detector import get_wholeclip_detector

logger = get_logger(__name__)


@dataclass
class DemoAnalysis:
    analysis_id: str
    event_type: str
    timestamp_seconds: float | None
    confidence: float
    team: str | None
    clip_url: str | None
    explanation: str
    debug: dict[str, Any] = field(default_factory=dict)


def analyze_demo_clip(
    video_path: str | Path,
    *,
    team_name: str | None = None,
    attacking_direction: str = "unknown",
) -> DemoAnalysis:
    analysis_id = new_id("analysis")
    video_path = Path(video_path)

    # 0) Primary path: whole-clip two-stage detector (EXPERIMENT 2-WC, the only
    #    approach that hit 8/8 on the verified short-clip suite — see
    #    docs/callibrations+results.md). Falls through to the legacy
    #    window-voting + local-CV pipeline when unavailable (no API key/ffmpeg).
    if settings.enable_wholeclip_detector:
        detector = get_wholeclip_detector()
        if detector.available:
            try:
                wc = detector.analyze(video_path)
                if wc.error is None:
                    return _demo_analysis_from_wholeclip(wc, analysis_id, video_path, team_name)
                logger.warning("Whole-clip detector errored (%s); falling back.", wc.error)
            except Exception as exc:
                logger.warning("Whole-clip detector failed (%s); falling back.", exc)

    # 1) Frame extraction
    extracted = frame_extractor.extract_frames(
        str(video_path),
        sample_fps=settings.demo_sample_fps,
        target_width=settings.demo_analysis_width,
    )

    if len(extracted) < 2:
        logger.warning("Demo analysis: too few frames extracted for %s", video_path.name)
        return DemoAnalysis(
            analysis_id=analysis_id,
            event_type="none",
            timestamp_seconds=None,
            confidence=0.0,
            team=_normalize_team(team_name),
            clip_url=None,
            explanation="Could not extract enough frames to analyze the clip.",
            debug={
                "frames_analyzed": len(extracted),
                "fps_sampled": extracted.fps_sampled,
                "duration_seconds": extracted.duration_seconds,
            },
        )

    # 2) Motion analysis
    motion = motion_analyzer.analyze_motion(extracted)

    # 3) Ball detection (optional, graceful)
    ball_tracks = []
    try:
        ball_tracks = get_ball_detector().detect(extracted.frames, extracted.timestamps)
    except Exception as exc:
        logger.warning("Ball detection failed (%s); continuing without it.", exc)

    # 4) Player detection over a subsampled set of frames (YOLO is the slow
    #    part, so we run it at a lower FPS). Optional + graceful.
    players_detected = 0
    attack = attack_analyzer.AttackResult("none", None, 0.0, None, "Player analysis not run.")
    try:
        p_frames, p_ts = _subsample(extracted, settings.player_analysis_fps)
        player_result = get_player_detector().detect(p_frames, p_ts)
        players_detected = player_result.players_detected
        if player_result.available:
            attack = attack_analyzer.analyze_attack(player_result)
    except Exception as exc:
        logger.warning("Player/attack analysis failed (%s); continuing without it.", exc)

    # 5) Audio analysis (optional, graceful)
    audio = audio_analyzer.AudioResult()
    try:
        audio = audio_analyzer.analyze_audio(str(video_path))
    except Exception as exc:
        logger.warning("Audio analysis failed (%s); continuing without it.", exc)

    # 6) Local candidate generation (high recall) — suspicious moments + windows.
    candidates = candidate_generator.generate_candidates(motion, attack, audio)
    windows = candidate_generator.create_windows(
        extracted.duration_seconds or len(extracted) / max(extracted.fps_sampled, 1),
        settings.vlm_window_size,
        settings.vlm_stride,
        settings.vlm_max_windows,
    )

    # 7) Video-language-model judge over each window (primary semantic signal).
    #    Windows are independent, so we judge them concurrently for speed.
    judge = get_vlm_judge()
    vlm_results: list[VlmJudgment] = []
    if judge.available and windows:
        workers = max(1, min(settings.vlm_concurrency, len(windows)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(judge.judge_window, str(video_path), ws, we): (ws, we)
                for (ws, we) in windows
            }
            for fut in as_completed(futures):
                vlm_results.append(fut.result())
        vlm_results.sort(key=lambda r: r.window_start)

    # 8) Fuse + decide.
    motion_classification = classify_event(
        ClassifierInputs(
            motion=motion,
            ball_tracks=ball_tracks,
            players_detected=players_detected,
            attacking_direction=attacking_direction,
            audio_spike_score=audio.spike_score,
            audio_spike_timestamp=audio.spike_timestamp,
            duration_seconds=extracted.duration_seconds,
        )
    )

    decision = _fuse(vlm_results, candidates, attack, motion_classification, judge.available)
    event_type = decision["event_type"]
    confidence = decision["confidence"]
    explanation = decision["explanation"]
    timestamp_seconds = decision["timestamp_seconds"]

    # 9) Local timestamp refinement around the chosen moment.
    if timestamp_seconds is not None:
        timestamp_seconds = _refine_timestamp(timestamp_seconds, motion, attack)

    # 10) Generate highlight clip if an event was found.
    clip_url = None
    if event_type in {"shot", "goal"} and timestamp_seconds is not None:
        clip_url = _generate_demo_clip(
            video_path, analysis_id, event_type, timestamp_seconds, extracted.duration_seconds
        )

    debug = {
        "method": decision["method"],
        "primary_signal": decision["primary"],
        "frames_analyzed": len(extracted),
        "fps_sampled": extracted.fps_sampled,
        "duration_seconds": extracted.duration_seconds,
        "vlm_available": judge.available,
        "vlm_results": [
            {
                "window": [r.window_start, r.window_end],
                "event_type": r.event_type,
                "timestamp_seconds": r.timestamp_seconds,
                "confidence": r.confidence,
                "evidence": r.evidence,
                "error": r.error,
            }
            for r in vlm_results
        ],
        "windows": windows,
        "local_candidates": [
            {"timestamp_seconds": c.timestamp_seconds, "score": c.score, "source": c.source}
            for c in candidates
        ],
        "ball_track_points": len(ball_tracks),
        "players_detected": players_detected,
        "attack": {
            "event_type": attack.event_type,
            "timestamp_seconds": attack.timestamp_seconds,
            "side": attack.side,
            "confidence": attack.confidence,
            **attack.debug,
        },
        "motion_peaks": [
            {"timestamp_seconds": p.timestamp_seconds, "score": p.score} for p in motion.peaks[:5]
        ],
        "audio_has_audio": audio.has_audio,
        "audio_spike_timestamp": audio.spike_timestamp,
        "audio_spike_score": audio.spike_score,
        "evidence": decision.get("evidence", []),
        "cluster_size": decision.get("cluster_size"),
        "cluster_windows": decision.get("cluster_windows"),
        "ml_detectors_enabled": settings.enable_ml_detectors,
    }

    return DemoAnalysis(
        analysis_id=analysis_id,
        event_type=event_type,
        timestamp_seconds=timestamp_seconds,
        confidence=confidence,
        team=_normalize_team(team_name),
        clip_url=clip_url,
        explanation=explanation,
        debug=debug,
    )


def _demo_analysis_from_wholeclip(
    wc, analysis_id: str, video_path: Path, team_name: str | None
) -> DemoAnalysis:
    """Package a WholeClipResult as the standard DemoAnalysis (incl. clip cut)."""
    clip_url = None
    duration = None
    if wc.event_type in {"shot", "goal"} and wc.timestamp_seconds is not None:
        try:
            from app.services.video_metadata_service import get_video_metadata

            duration = get_video_metadata(video_path).duration_seconds
        except Exception:
            duration = None
        clip_url = _generate_demo_clip(
            video_path, analysis_id, wc.event_type, wc.timestamp_seconds, duration or 0.0
        )
    return DemoAnalysis(
        analysis_id=analysis_id,
        event_type=wc.event_type,
        timestamp_seconds=wc.timestamp_seconds,
        confidence=wc.confidence,
        team=_normalize_team(team_name),
        clip_url=clip_url,
        explanation=wc.explanation,
        debug={**wc.debug, "vlm_available": True},
    )


def _fuse(vlm_results, candidates, attack, motion_classification, vlm_available: bool) -> dict:
    """Consensus-clustering fusion (docs/callibrations+results.md iter 4).

    Gemini video judgments are noisy per-window (not deterministic even at t=0),
    BUT a real shot reliably lights up a dense cluster of 2-3 ADJACENT overlapping
    windows (buildup -> strike -> aftermath). False positives are isolated
    singletons that move around between runs. So instead of trusting the single
    highest-confidence window, we find the densest cluster of agreeing windows.
    """
    fired = [
        r for r in vlm_results
        if r.event_type in {"shot", "goal"}
        and r.timestamp_seconds is not None
        and r.confidence >= settings.shot_threshold
    ]

    if fired:
        clusters = _cluster_fires(fired)
        # Densest cluster wins; tie-break by total confidence.
        best_cluster = max(clusters, key=lambda c: (len(c), sum(r.confidence for r in c)))

        if len(best_cluster) >= settings.vlm_min_cluster:
            return _cluster_decision(best_cluster)

        # Only isolated fires exist. Allow a single VERY confident window through,
        # otherwise treat lone fires as noise and return none.
        lone = max(best_cluster, key=lambda r: r.confidence)
        if lone.confidence >= settings.vlm_lone_fire_conf:
            evt = "goal" if lone.event_type == "goal" and lone.confidence >= settings.goal_threshold else "shot"
            return _vlm_decision(evt, lone, "video_language_model")
        # fall through to local signals / none

    # No confident VLM cluster. Fall back to the strongest local evidence as a
    # "possible shot" rather than silently returning none.
    best_local = max(candidates, key=lambda c: c.score) if candidates else None
    if best_local is not None and best_local.score >= 0.55:
        method = "video_language_model+local" if vlm_available else "local_candidate"
        return {
            "event_type": "shot",
            "timestamp_seconds": best_local.timestamp_seconds,
            "confidence": round(min(0.6, 0.45 + best_local.score * 0.2), 4),
            "explanation": (
                "Local play dynamics (player movement toward goal / motion) suggest a possible shot."
            ),
            "evidence": [f"{best_local.source} signal at {best_local.timestamp_seconds:.1f}s"],
            "method": method,
            "primary": best_local.source,
        }

    if attack.available and attack.event_type == "shot":
        return {
            "event_type": "shot",
            "timestamp_seconds": attack.timestamp_seconds,
            "confidence": attack.confidence,
            "explanation": attack.explanation,
            "evidence": ["player compression toward goal"],
            "method": "local_players",
            "primary": "players",
        }

    return {
        "event_type": "none",
        "timestamp_seconds": None,
        "confidence": 0.0,
        "explanation": "No shot or goal attempt detected.",
        "evidence": [],
        "method": "video_language_model" if vlm_available else "local",
        "primary": "vlm" if vlm_available else "local",
    }


def _cluster_fires(fired: list[VlmJudgment]) -> list[list[VlmJudgment]]:
    """Group firing windows whose time spans overlap or touch into clusters.

    Two windows belong to the same event if their [start, end] spans overlap (or
    are within a small slack), since a single shot's context is reported across
    adjacent overlapping windows.
    """
    ordered = sorted(fired, key=lambda r: r.window_start)
    clusters: list[list[VlmJudgment]] = []
    for r in ordered:
        # Bridge a single dropped (noisy "none") window in the middle of an event
        # by allowing up to ~one stride of gap between consecutive fires.
        if clusters and r.window_start <= clusters[-1][-1].window_end + settings.vlm_cluster_gap:
            clusters[-1].append(r)
        else:
            clusters.append([r])
    return clusters


def _cluster_decision(cluster: list[VlmJudgment]) -> dict:
    """Build a decision from a consensus cluster of firing windows."""
    n_goal = sum(1 for r in cluster if r.event_type == "goal")
    n_shot = sum(1 for r in cluster if r.event_type == "shot")
    # Goal only wins if it is the clear majority of the cluster (a lone "goal"
    # among "shot"s is treated as the model over-calling a shot).
    event_type = "goal" if n_goal > n_shot else "shot"

    total_w = sum(r.confidence for r in cluster) or 1.0
    ts = sum(r.confidence * r.timestamp_seconds for r in cluster) / total_w
    avg_conf = total_w / len(cluster)
    # Consensus across N windows is stronger evidence than any single one.
    consensus_bonus = min(0.1, 0.03 * (len(cluster) - 1))
    confidence = round(min(0.99, avg_conf + consensus_bonus), 4)

    evidence: list[str] = []
    for r in cluster:
        evidence.extend(r.evidence or [])
    explanation = "; ".join(evidence[:4]) if evidence else f"Video model identified a {event_type}."

    return {
        "event_type": event_type,
        "timestamp_seconds": round(ts, 3),
        "confidence": confidence,
        "explanation": explanation,
        "evidence": evidence[:6],
        "method": "video_language_model",
        "primary": "vlm",
        "cluster_size": len(cluster),
        "cluster_windows": [[r.window_start, r.window_end] for r in cluster],
    }


def _vlm_decision(event_type: str, r: VlmJudgment, method: str) -> dict:
    return {
        "event_type": event_type,
        "timestamp_seconds": r.timestamp_seconds,
        "confidence": round(float(r.confidence), 4),
        "explanation": "; ".join(r.evidence) if r.evidence else f"Video model identified a {event_type}.",
        "evidence": r.evidence,
        "method": method,
        "primary": "vlm",
    }


def _refine_timestamp(vlm_ts: float, motion, attack) -> float:
    """Blend the VLM timestamp with nearby local peaks (docs/newTips.md Step 6)."""
    parts = [(0.60, vlm_ts)]

    near_motion = _nearest(
        [p.timestamp_seconds for p in getattr(motion, "peaks", [])], vlm_ts, max_dist=3.0
    )
    if near_motion is not None:
        parts.append((0.25, near_motion))

    if getattr(attack, "available", False) and attack.timestamp_seconds is not None:
        if abs(attack.timestamp_seconds - vlm_ts) <= 4.0:
            parts.append((0.15, attack.timestamp_seconds))

    total_w = sum(w for w, _ in parts)
    return round(sum(w * t for w, t in parts) / total_w, 3)


def _nearest(values: list[float], target: float, max_dist: float) -> float | None:
    near = [v for v in values if abs(v - target) <= max_dist]
    if not near:
        return None
    return min(near, key=lambda v: abs(v - target))


def _subsample(extracted, target_fps: float):
    """Take every k-th extracted frame to approximate ``target_fps``."""
    if not extracted.frames:
        return [], []
    step = max(1, int(round(extracted.fps_sampled / max(target_fps, 0.1))))
    frames = extracted.frames[::step]
    ts = extracted.timestamps[::step]
    return frames, ts


def _generate_demo_clip(
    video_path: Path,
    analysis_id: str,
    event_type: str,
    timestamp_seconds: float,
    duration_seconds: float,
) -> str | None:
    window = clip_window_for_event(event_type, timestamp_seconds, duration_seconds)
    clip_filename = f"demo_{analysis_id}.mp4"
    clip_path = settings.clips_dir / clip_filename
    try:
        generate_clip(
            video_path,
            window.start_seconds,
            window.end_seconds,
            clip_path,
            video_duration=duration_seconds,
        )
        return f"/media/clips/{clip_filename}"
    except Exception as exc:
        logger.warning("Demo clip generation failed (%s); returning result without clip.", exc)
        return None


def _normalize_team(team_name: str | None) -> str:
    if not team_name:
        return "our_team"
    return team_name
