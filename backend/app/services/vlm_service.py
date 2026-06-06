"""Video-language-model judge for semantic shot/goal detection.

Per docs/newTips.md, the most reliable detector for wide Veo footage is a
frontier video model that reasons about the clip semantically (player kicking
motion, goalkeeper reaction, play reset, celebration) rather than trying to see
the tiny, often-invisible ball.

This module wraps Gemini video understanding behind a small interface and falls
back to a no-op judge when no API key / SDK is available, so the pipeline never
hard-crashes without it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


PROMPT = """You are a precise soccer video analyst reviewing wide Veo-style footage.

Your job is to decide whether THIS short window contains a genuine SHOT or GOAL.
Be STRICT. Most windows of a soccer match contain NO shot — they are passing,
dribbling, midfield play, throw-ins, goal kicks, crosses, or clearances. Those
are NOT shots. Default to "none".

A SHOT is a deliberate strike of the ball BY AN ATTACKER TOWARD THE OPPONENT'S
GOAL, where you can see strong corroborating evidence such as:
- the ball clearly travelling toward the goal mouth, AND
- a goalkeeper reaction (dive, save, parry) OR the ball hitting the net / post /
  going just wide or over the bar near the goal frame.
Count blocked shots and saved shots, but only when the goal and keeper are
actually in frame and reacting.

A GOAL is a shot where the ball clearly ENTERS the net (often followed by play
stopping and players celebrating). Label that "goal", not "shot".

NOT a shot (return "none" for these):
- a pass, cross, or long ball, even if struck hard
- midfield play or build-up with no goal in frame
- a clearance or goal kick away from goal
- general attacking pressure where no actual strike on goal occurs
- camera panning / zooming with no clear strike-and-keeper-reaction

Do NOT invent a shot just because there is attacking play, motion, or crowd
noise. If the goal is not even visible in the window, it is almost certainly
"none".

The window starts at 0 seconds. If (and only if) you find a real shot or goal,
report its timestamp in seconds RELATIVE to the start of THIS window.

Calibrate confidence honestly:
- 0.85-1.0 : unmistakable shot/goal (clear strike toward goal + keeper/net reaction)
- 0.6-0.85 : likely a shot but some doubt
- below 0.5 : weak/ambiguous — prefer "none" instead
Reserve high confidence for clear cases. When unsure, return "none".

Return JSON only:
{
  "event_type": "goal" | "shot" | "none",
  "timestamp_seconds": number | null,
  "confidence": number between 0 and 1,
  "evidence": ["specific visual evidence 1", "specific visual evidence 2"],
  "uncertainty": "what makes you unsure, if anything"
}
"""


VERIFY_PROMPT = """You are a STRICT soccer referee-analyst reviewing one moment from a wide
Veo-style match video. Your only job is to decide if a real SHOT or GOAL occurs,
and to reject everything else. Most candidates you see will NOT be real shots.

A real SHOT requires a clear, resolved attempt ON the goal — you must see the
OUTCOME, not just the ball moving forward:
- the goalkeeper saves / parries / catches it, OR
- the ball hits the net (GOAL), OR
- the ball hits the post/crossbar, OR
- the ball clearly goes WIDE of, or OVER, the actual goal frame (the posts must
  be visible and the ball misses them).

These are NOT shots — return "none" for them:
- a pass, cross, cut-back, or long ball forward (even if hit hard toward the box)
- a clearance, goal kick, or throw-in
- general attacking pressure / possession in the final third with no resolved
  attempt on goal
- a player dribbling toward goal but not striking it
- the goal frame is NOT visible in the clip (then you cannot confirm a shot)

A GOAL is a shot where the ball clearly ENTERS the net (often + players
celebrating / play stopping / kickoff restart). Penalties count as goals if scored.

Be conservative. If you cannot clearly see the goal frame AND a resolved attempt
on it, answer "none". Do not infer a shot from crowd noise, camera movement, or
attacking momentum alone.

Return JSON only:
{
  "event_type": "goal" | "shot" | "none",
  "timestamp_seconds": number | null,   // relative to the START of THIS clip
  "confidence": number 0..1,
  "goal_frame_visible": true | false,
  "outcome": "save" | "net" | "post" | "wide" | "over" | "blocked" | "none",
  "evidence": ["specific visual evidence", "..."],
  "reason_if_none": "why this is not a shot, if none"
}
"""


AFTERMATH_PROMPT = """You are analyzing a soccer video clip to decide whether a real SHOT or GOAL
occurred, by judging its CONSEQUENCE — what happens in the SECONDS AFTER the
attacking action — NOT by trying to see the (often invisible) ball itself.

The clip contains a candidate attacking moment near the start, followed by its
aftermath. Watch the aftermath closely.

A real SHOT is almost always followed within a few seconds by a clear restart /
stoppage caused by the attempt on goal:
- the GOALKEEPER gains possession (catches, holds, picks up, or rolls/kicks it
  out from hand), OR
- a GOAL KICK (ball placed in the 6-yard box, keeper/defender kicks it long), OR
- a CORNER KICK (play moves to the corner flag), OR
- a GOAL: players celebrate and the game restarts with a KICK-OFF from the centre
  circle.

If instead OPEN PLAY simply CONTINUES — the ball stays among outfield players in
midfield/wings, possession flows on, no keeper possession, no set-piece restart,
no celebration — then it was NOT a shot (it was a pass, cross, or attacking
pressure that didn't result in a real attempt on goal).

Decide from the consequence:
- "goal": celebration + kick-off from the centre circle, OR ball clearly in net.
- "shot": followed by keeper possession / goal kick / corner (an attempt that the
  keeper or goal frame resolved), but NOT a goal.
- "none": open play continues with no such restart.

Return JSON only:
{
  "event_type": "goal" | "shot" | "none",
  "timestamp_seconds": number | null,   // when the attempt occurs, relative to THIS clip start
  "confidence": number 0..1,
  "consequence": "keeper_possession" | "goal_kick" | "corner" | "kickoff_goal" | "open_play_continues" | "unclear",
  "evidence": ["what you saw in the aftermath", "..."]
}
"""


@dataclass
class VlmJudgment:
    event_type: str  # goal | shot | none
    timestamp_seconds: float | None
    confidence: float
    evidence: list[str] = field(default_factory=list)
    uncertainty: str = ""
    window_start: float = 0.0
    window_end: float = 0.0
    error: str | None = None
    # Populated by the strict verification stage.
    outcome: str = ""
    goal_frame_visible: bool | None = None


class VlmJudge(Protocol):
    available: bool

    def judge_window(self, video_path: str, start: float, end: float) -> VlmJudgment:
        ...

    def verify_candidate(self, video_path: str, start: float, end: float) -> VlmJudgment:
        ...

    def verify_aftermath(self, video_path: str, start: float, end: float) -> VlmJudgment:
        ...


class NullVlmJudge:
    available = False

    def judge_window(self, video_path: str, start: float, end: float) -> VlmJudgment:
        return VlmJudgment("none", None, 0.0, window_start=start, window_end=end, error="vlm_unavailable")

    def verify_candidate(self, video_path: str, start: float, end: float) -> VlmJudgment:
        return VlmJudgment("none", None, 0.0, window_start=start, window_end=end, error="vlm_unavailable")

    def verify_aftermath(self, video_path: str, start: float, end: float) -> VlmJudgment:
        return VlmJudgment("none", None, 0.0, window_start=start, window_end=end, error="vlm_unavailable")


def _api_key() -> str:
    return settings.gemini_api_key or os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")


def _is_rate_limit(exc: Exception) -> bool:
    """Retryable: rate limits, transient server errors, AND network/TLS flakes."""
    msg = str(exc).lower()
    return any(t in msg for t in (
        "429", "resource_exhausted", "quota", "rate limit", "too many requests",
        "500", "502", "503", "internal", "unavailable", "deadline", "timed out", "timeout",
        "ssl", "tls", "connection", "socket", "eof occurred", "broken pipe",
        "remotedisconnected", "reset by peer",
    ))


def _with_retry(fn, *, attempts: int = 6, base_delay: float = 5.0):
    """Call ``fn`` with exponential backoff on rate-limit / quota errors.

    Long full-match scans fire hundreds of requests through one API key, so we
    expect to be throttled. Backoff lets the scan self-pace instead of dropping
    windows. Non-rate-limit errors propagate immediately.
    """
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # pragma: no cover - network path
            if not _is_rate_limit(exc):
                raise
            last = exc
            delay = min(90.0, base_delay * (2 ** i))
            logger.warning("Rate limited (attempt %d/%d); backing off %.0fs.", i + 1, attempts, delay)
            time.sleep(delay)
    if last is not None:
        raise last
    raise RuntimeError("retry failed without exception")


def _generation_config():
    """Deterministic decoding so calibration runs are repeatable.

    The default sampling temperature made the judge non-deterministic (different
    shots/goals per run — see docs/callibrations+results.md iter 2). temperature=0
    pins the output so tuning measures real changes, not sampling noise.
    """
    try:
        from google.genai import types

        return types.GenerateContentConfig(
            temperature=0.0,
            top_p=1.0,
            response_mime_type="application/json",
        )
    except Exception:  # pragma: no cover - SDK shape fallback
        return None


class GeminiVlmJudge:
    """Gemini-backed judge. Cuts a temp subclip per window and asks for JSON."""

    _client = None

    def __init__(self):
        self.available = False
        key = _api_key()
        if not key:
            logger.info("Gemini judge disabled: no API key set.")
            return
        if shutil.which("ffmpeg") is None:
            logger.warning("Gemini judge disabled: ffmpeg missing.")
            return
        try:
            from google import genai

            if GeminiVlmJudge._client is None:
                GeminiVlmJudge._client = genai.Client(api_key=key)
            self.available = True
            logger.info("Gemini judge ready (model=%s).", settings.vlm_model)
        except Exception as exc:  # pragma: no cover - optional path
            logger.warning("Gemini judge unavailable (%s).", exc)

    def _cut_window(self, video_path: str, start: float, end: float, *, scale: int = 640) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="vlm_win_")) / f"win_{start:.1f}_{end:.1f}.mp4"
        duration = max(0.5, end - start)
        cmd = [
            "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(video_path),
            "-t", f"{duration:.3f}", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "28", "-an", "-vf", f"scale={scale}:-2", str(tmp),
        ]
        subprocess.run(cmd, capture_output=True, timeout=120)
        return tmp

    def verify_candidate(self, video_path: str, start: float, end: float) -> VlmJudgment:
        """Strict, high-precision re-check of a candidate moment.

        Uses the stronger ``vlm_verify_model`` on a longer (higher-context) clip
        with an outcome-based prompt, to reject the "attacking play looks like a
        shot" false positives that the cheap recall pass produces.
        """
        if not self.available or GeminiVlmJudge._client is None:
            return VlmJudgment("none", None, 0.0, window_start=start, window_end=end, error="vlm_unavailable")

        client = GeminiVlmJudge._client
        sub = None
        uploaded = None
        try:
            sub = self._cut_window(video_path, start, end, scale=854)
            if not sub.exists() or sub.stat().st_size == 0:
                return VlmJudgment("none", None, 0.0, window_start=start, window_end=end, error="cut_failed")

            uploaded = _with_retry(lambda: client.files.upload(file=str(sub)))
            for _ in range(30):
                state = getattr(getattr(uploaded, "state", None), "name", None) or getattr(uploaded, "state", None)
                if str(state) == "ACTIVE":
                    break
                time.sleep(1)
                uploaded = client.files.get(name=uploaded.name)

            response = _with_retry(
                lambda: client.models.generate_content(
                    model=settings.vlm_verify_model,
                    contents=[uploaded, VERIFY_PROMPT],
                    config=_generation_config(),
                )
            )
            data = _parse_json(response.text or "")
            ts = data.get("timestamp_seconds")
            abs_ts = (start + float(ts)) if isinstance(ts, (int, float)) else None
            return VlmJudgment(
                event_type=str(data.get("event_type", "none")).lower(),
                timestamp_seconds=abs_ts,
                confidence=float(data.get("confidence", 0.0) or 0.0),
                evidence=list(data.get("evidence", []) or []),
                uncertainty=str(data.get("reason_if_none", "")),
                window_start=start,
                window_end=end,
                outcome=str(data.get("outcome", "") or ""),
                goal_frame_visible=data.get("goal_frame_visible"),
            )
        except Exception as exc:  # pragma: no cover - network path
            logger.warning("Gemini verify failed for %.1f-%.1f (%s).", start, end, exc)
            return VlmJudgment("none", None, 0.0, window_start=start, window_end=end, error=str(exc))
        finally:
            try:
                if uploaded is not None:
                    GeminiVlmJudge._client.files.delete(name=uploaded.name)
            except Exception:
                pass
            if sub is not None:
                shutil.rmtree(sub.parent, ignore_errors=True)

    def verify_aftermath(self, video_path: str, start: float, end: float) -> VlmJudgment:
        """Approach B: judge a candidate by its CONSEQUENCE, not the ball.

        Sends a clip weighted toward the seconds AFTER the candidate and asks the
        model whether play visibly resets (keeper possession / goal kick / corner /
        kickoff after a goal). Game-state is far more visible on wide footage than
        the ball, so this avoids the outcome-confabulation the ball-based verifier hit.
        """
        if not self.available or GeminiVlmJudge._client is None:
            return VlmJudgment("none", None, 0.0, window_start=start, window_end=end, error="vlm_unavailable")

        client = GeminiVlmJudge._client
        sub = None
        uploaded = None
        try:
            sub = self._cut_window(video_path, start, end, scale=854)
            if not sub.exists() or sub.stat().st_size == 0:
                return VlmJudgment("none", None, 0.0, window_start=start, window_end=end, error="cut_failed")

            uploaded = _with_retry(lambda: client.files.upload(file=str(sub)))
            for _ in range(30):
                state = getattr(getattr(uploaded, "state", None), "name", None) or getattr(uploaded, "state", None)
                if str(state) == "ACTIVE":
                    break
                time.sleep(1)
                uploaded = client.files.get(name=uploaded.name)

            response = _with_retry(
                lambda: client.models.generate_content(
                    model=settings.vlm_aftermath_model,
                    contents=[uploaded, AFTERMATH_PROMPT],
                    config=_generation_config(),
                )
            )
            data = _parse_json(response.text or "")
            ts = data.get("timestamp_seconds")
            abs_ts = (start + float(ts)) if isinstance(ts, (int, float)) else None
            return VlmJudgment(
                event_type=str(data.get("event_type", "none")).lower(),
                timestamp_seconds=abs_ts,
                confidence=float(data.get("confidence", 0.0) or 0.0),
                evidence=list(data.get("evidence", []) or []),
                window_start=start,
                window_end=end,
                outcome=str(data.get("consequence", "") or ""),
            )
        except Exception as exc:  # pragma: no cover - network path
            logger.warning("Gemini aftermath failed for %.1f-%.1f (%s).", start, end, exc)
            return VlmJudgment("none", None, 0.0, window_start=start, window_end=end, error=str(exc))
        finally:
            try:
                if uploaded is not None:
                    GeminiVlmJudge._client.files.delete(name=uploaded.name)
            except Exception:
                pass
            if sub is not None:
                shutil.rmtree(sub.parent, ignore_errors=True)

    def judge_window(self, video_path: str, start: float, end: float) -> VlmJudgment:
        if not self.available or GeminiVlmJudge._client is None:
            return VlmJudgment("none", None, 0.0, window_start=start, window_end=end, error="vlm_unavailable")

        client = GeminiVlmJudge._client
        sub = None
        uploaded = None
        try:
            sub = self._cut_window(video_path, start, end)
            if not sub.exists() or sub.stat().st_size == 0:
                return VlmJudgment("none", None, 0.0, window_start=start, window_end=end, error="cut_failed")

            uploaded = _with_retry(lambda: client.files.upload(file=str(sub)))
            # Wait for the file to become ACTIVE before generating.
            for _ in range(30):
                state = getattr(getattr(uploaded, "state", None), "name", None) or getattr(uploaded, "state", None)
                if str(state) == "ACTIVE":
                    break
                time.sleep(1)
                uploaded = client.files.get(name=uploaded.name)

            response = _with_retry(
                lambda: client.models.generate_content(
                    model=settings.vlm_model,
                    contents=[uploaded, PROMPT],
                    config=_generation_config(),
                )
            )
            data = _parse_json(response.text or "")
            ts = data.get("timestamp_seconds")
            abs_ts = (start + float(ts)) if isinstance(ts, (int, float)) else None
            return VlmJudgment(
                event_type=str(data.get("event_type", "none")).lower(),
                timestamp_seconds=abs_ts,
                confidence=float(data.get("confidence", 0.0) or 0.0),
                evidence=list(data.get("evidence", []) or []),
                uncertainty=str(data.get("uncertainty", "")),
                window_start=start,
                window_end=end,
            )
        except Exception as exc:  # pragma: no cover - network path
            logger.warning("Gemini judge failed for window %.1f-%.1f (%s).", start, end, exc)
            return VlmJudgment("none", None, 0.0, window_start=start, window_end=end, error=str(exc))
        finally:
            try:
                if uploaded is not None:
                    GeminiVlmJudge._client.files.delete(name=uploaded.name)
            except Exception:
                pass
            if sub is not None:
                shutil.rmtree(sub.parent, ignore_errors=True)


def _parse_json(text: str) -> dict:
    """Extract the first JSON object from a model response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip().rstrip("`").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def get_vlm_judge() -> VlmJudge:
    if settings.enable_vlm:
        judge = GeminiVlmJudge()
        if judge.available:
            return judge
    return NullVlmJudge()
