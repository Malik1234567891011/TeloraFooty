"""Full-match scan: detect EVERY shot/goal across a long video.

This is the long-video counterpart to ``detection_service.analyze_demo_clip``.
The short-clip analyzer returns a single headline event; a full 45-90 min match
has many, so here we:

1. Tile the ENTIRE video with overlapping windows (no cap collapse) so coverage
   is complete and nothing falls between windows.
2. Judge every window with Gemini, in parallel (rate-limited + retried).
3. Reuse the SAME calibrated consensus-clustering, but emit ONE event per
   qualifying cluster (not just the densest one).
4. Cut a highlight clip per event, named by timestamp + type, e.g.
   ``07-23 shot.mp4`` (zero-padded MM-SS so they sort chronologically).

We deliberately skip the local motion/player/audio refinement used on short
clips: loading ~17k frames of a 48-min video into memory is wasteful, and the
cluster timestamp is plenty precise given we clip a generous window around it.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.config import settings
from app.core.logging import get_logger
from app.cv.candidate_generator import _tile
from app.services.clip_service import clip_window_for_event, generate_clip
from app.services.detection_service import _cluster_decision, _cluster_fires
from app.services.video_metadata_service import get_video_metadata
from app.services.vlm_service import VlmJudgment, get_vlm_judge

logger = get_logger(__name__)


@dataclass
class MatchEvent:
    timestamp_seconds: float
    timestamp_label: str
    event_type: str
    confidence: float
    cluster_size: int
    explanation: str
    outcome: str = ""
    clip_filename: str | None = None
    clip_url: str | None = None


@dataclass
class FullMatchResult:
    video: str
    duration_seconds: float
    windows_total: int
    windows_judged: int
    windows_failed: int
    events: list[MatchEvent] = field(default_factory=list)
    output_dir: str = ""


def _fmt_ts(seconds: float) -> str:
    """Seconds -> zero-padded 'MM-SS' (filesystem-safe, sorts chronologically)."""
    total = int(round(seconds))
    m, s = divmod(total, 60)
    return f"{m:02d}-{s:02d}"


def analyze_full_match(
    video_path: str | Path,
    *,
    concurrency: int | None = None,
    checkpoint_path: str | Path | None = None,
    progress_every: int = 20,
    verify: bool = True,
    on_progress=None,
) -> FullMatchResult:
    video_path = Path(video_path)
    judge = get_vlm_judge()
    if not judge.available:
        raise RuntimeError("VLM judge unavailable (no GEMINI_API_KEY?). Full-match scan needs it.")

    duration = get_video_metadata(video_path).duration_seconds
    windows = _tile(duration, settings.vlm_window_size, settings.vlm_stride)
    workers = concurrency or settings.vlm_concurrency
    logger.info(
        "Full-match scan: %s (%.0fs) -> %d windows, %d workers.",
        video_path.name, duration, len(windows), workers,
    )

    results: list[VlmJudgment] = []
    failed = 0
    done = 0
    started = time.time()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(judge.judge_window, str(video_path), ws, we): (ws, we)
            for (ws, we) in windows
        }
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            if r.error:
                failed += 1
            done += 1
            if on_progress:
                on_progress(15 + int(75 * done / max(len(windows), 1)),
                            f"Scanning {done}/{len(windows)} windows")
            if done % progress_every == 0 or done == len(windows):
                rate = done / max(time.time() - started, 1e-6)
                eta = (len(windows) - done) / max(rate, 1e-6)
                logger.info(
                    "  scanned %d/%d windows (%d failed) | %.2f win/s | ETA %.0fs",
                    done, len(windows), failed, rate, eta,
                )
                if checkpoint_path:
                    _write_checkpoint(checkpoint_path, results)

    results.sort(key=lambda r: r.window_start)
    return _finalize(
        judge, video_path, results, duration,
        windows_total=len(windows), windows_judged=done, windows_failed=failed,
        workers=workers, verify=verify, generate_clips=True, on_progress=on_progress,
    )


def analyze_from_checkpoint(
    video_path: str | Path,
    checkpoint_path: str | Path,
    *,
    verify: bool = True,
    concurrency: int | None = None,
    generate_clips: bool = True,
) -> FullMatchResult:
    """Re-run only the fusion + verification stages from a saved recall checkpoint.

    Lets us iterate on the precision logic WITHOUT re-paying for the ~480-window
    recall pass. The expensive part already happened; this just re-decides.
    """
    video_path = Path(video_path)
    judge = get_vlm_judge()
    duration = get_video_metadata(video_path).duration_seconds
    raw = json.loads(Path(checkpoint_path).read_text())
    results = [
        VlmJudgment(
            event_type=str(w.get("event_type", "none")),
            timestamp_seconds=w.get("timestamp_seconds"),
            confidence=float(w.get("confidence", 0.0) or 0.0),
            window_start=float(w["window"][0]),
            window_end=float(w["window"][1]),
            error=w.get("error"),
        )
        for w in raw
    ]
    results.sort(key=lambda r: r.window_start)
    workers = concurrency or settings.vlm_concurrency
    logger.info("Loaded %d windows from checkpoint %s.", len(results), checkpoint_path)
    return _finalize(
        judge, video_path, results, duration,
        windows_total=len(results), windows_judged=len(results),
        windows_failed=sum(1 for r in results if r.error),
        workers=workers, verify=verify, generate_clips=generate_clips,
    )


def _finalize(
    judge, video_path: Path, results: list[VlmJudgment], duration: float,
    *, windows_total: int, windows_judged: int, windows_failed: int,
    workers: int, verify: bool, generate_clips: bool, on_progress=None,
) -> FullMatchResult:
    """Shared tail: results -> clusters -> verify -> events (+clips)."""
    fired = [
        r for r in results
        if r.event_type in {"shot", "goal"}
        and r.timestamp_seconds is not None
        and r.confidence >= settings.shot_threshold
    ]
    clusters = _cluster_fires(fired)
    qualifying = [c for c in clusters if len(c) >= settings.vlm_min_cluster]
    logger.info("Recall pass: %d candidate clusters (>=%d windows).",
                len(qualifying), settings.vlm_min_cluster)

    candidates = [_cluster_decision(c) for c in qualifying]
    if verify and candidates:
        if on_progress:
            on_progress(92, "Verifying candidates")
        candidates = _verify_candidates(judge, video_path, candidates, duration, workers)

    out_dir = settings.clips_dir / video_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    events: list[MatchEvent] = []
    for d in candidates:
        ts = float(d["timestamp_seconds"])
        et = d["event_type"]
        label = _fmt_ts(ts)
        clip_name = f"{label} {et}.mp4"
        clip_url = None
        if generate_clips:
            try:
                window = clip_window_for_event(et, ts, duration)
                generate_clip(
                    video_path, window.start_seconds, window.end_seconds,
                    out_dir / clip_name, video_duration=duration,
                )
                clip_url = f"/media/clips/{video_path.stem}/{clip_name}"
            except Exception as exc:
                logger.warning("Clip failed for %s (%s).", clip_name, exc)
                clip_name = None
        else:
            clip_name = None

        events.append(MatchEvent(
            timestamp_seconds=round(ts, 2),
            timestamp_label=label.replace("-", ":"),
            event_type=et,
            confidence=d["confidence"],
            cluster_size=d["cluster_size"],
            explanation=d["explanation"],
            outcome=d.get("outcome", ""),
            clip_filename=clip_name,
            clip_url=clip_url,
        ))

    events.sort(key=lambda e: e.timestamp_seconds)
    result = FullMatchResult(
        video=video_path.name,
        duration_seconds=round(duration, 2),
        windows_total=windows_total,
        windows_judged=windows_judged,
        windows_failed=windows_failed,
        events=events,
        output_dir=str(out_dir),
    )
    _write_summary(out_dir / "events.json", result)
    logger.info("Full-match scan done: %d events, clips in %s", len(events), out_dir)
    return result


def _verify_candidates(judge, video_path, candidates: list[dict], duration: float, workers: int) -> list[dict]:
    """Strictly re-verify each candidate with the stronger model; drop the ones
    that don't survive. Returns kept candidates (with verified type/ts/outcome)."""
    def _verify(cand: dict) -> dict | None:
        ts = float(cand["timestamp_seconds"])
        start = max(0.0, ts - settings.verify_window_pre)
        end = min(duration, ts + settings.verify_window_post)
        v = judge.verify_candidate(str(video_path), start, end)
        if v.event_type not in {"shot", "goal"} or v.confidence < settings.verify_threshold:
            logger.info("  REJECT @%s -> %s (conf %.2f) %s",
                        _fmt_ts(ts), v.event_type, v.confidence, v.uncertainty[:80])
            return None
        kept = dict(cand)
        kept["event_type"] = v.event_type  # verifier decides goal vs shot
        if v.timestamp_seconds is not None:
            kept["timestamp_seconds"] = round(v.timestamp_seconds, 3)
        kept["confidence"] = round(v.confidence, 4)
        kept["explanation"] = "; ".join(v.evidence) if v.evidence else cand.get("explanation", "")
        kept["outcome"] = v.outcome
        logger.info("  KEEP   @%s -> %s (conf %.2f, outcome=%s)",
                    _fmt_ts(ts), v.event_type, v.confidence, v.outcome or "?")
        return kept

    kept: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for res in pool.map(_verify, candidates):
            if res is not None:
                kept.append(res)
    logger.info("Verification: kept %d / %d candidates.", len(kept), len(candidates))
    return kept


def _write_checkpoint(path: str | Path, results: list[VlmJudgment]) -> None:
    try:
        data = [
            {
                "window": [r.window_start, r.window_end],
                "event_type": r.event_type,
                "timestamp_seconds": r.timestamp_seconds,
                "confidence": r.confidence,
                "error": r.error,
            }
            for r in results
        ]
        Path(path).write_text(json.dumps(data, indent=2))
    except Exception as exc:  # pragma: no cover
        logger.warning("Checkpoint write failed (%s).", exc)


def _write_summary(path: Path, result: FullMatchResult) -> None:
    try:
        payload = asdict(result)
        path.write_text(json.dumps(payload, indent=2))
    except Exception as exc:  # pragma: no cover
        logger.warning("Summary write failed (%s).", exc)
