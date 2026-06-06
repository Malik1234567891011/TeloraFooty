"""Two-stage whole-clip shot/goal detector (the EXPERIMENT 2-WC architecture).

Production port of the lab pipeline that first hit 8/8 on the Dordt short-clip
suite (scripts/stage1_exp2_wholeclip.py + scripts/exp_pipeline_v2.py — see
docs/callibrations+results.md, EXPERIMENT 2-WC):

Stage 1 — localization: K independent Gemini votes over the WHOLE original
clip (native resolution, WITH audio — both matter), each asked to comparatively
localize up to 3 strike moments across the full timeline. Timestamps are
MM:SS-authoritative (Gemini intermittently emits seconds shifted two decimal
places when forced to a bare JSON number). Votes cluster by timestamp; the
top-<=3 clusters become candidates.

Stage 2 — verification: each candidate window is re-cut at native resolution
with audio and verified at denser frame sampling (exact strike time, outcome,
and whether play RESETS afterwards or CONTINUES live).

Selection — deterministic, generic soccer logic: verified attempts group into
sequences (gap <= seq_gap is one goalmouth passage); the headline is the LAST
attempt of the best sequence after which play resets (a flurry is decided by
the attempt that ends it). Goal-vs-shot is decided by stage-1 UNANIMITY alone:
all K whole-clip votes must call the moment a goal. Both real goals in the
verified suite are unanimous in every run; true shots never are — while every
richer signal (stage-2 "net" outcomes, video aftermath checks, image panels)
proved parallax-fallible: a ball resting just outside the side netting reads
as inside it from this camera, in both video AND stills.

Determinism comes from consensus: K-vote clustering, majority outcomes, median
timestamps, and a fixed-tiebreak selection — not from hoping a single video
call is stable (it is not, even at temperature=0).
"""

from __future__ import annotations

import re
import shutil
import statistics
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.logging import get_logger
from app.services.vlm_service import _api_key, _parse_json, _with_retry

logger = get_logger(__name__)


LOCALIZE_PROMPT = """You are analyzing one short clip of wide-angle (Veo-style) soccer footage.
Your job is TEMPORAL LOCALIZATION: find the moment(s) where a genuine SHOT on
goal or a GOAL occurs, and report WHEN the strike happens.

Definitions:
- "shot": a deliberate strike by an attacker toward the opponent's goal that is
  RESOLVED at the goal: the keeper saves/catches/parries it, it hits the post or
  crossbar, it clearly goes just wide or over the goal frame, or it is blocked
  near the line.
- "goal": the ball fully crosses the line into the net. A real goal is ALWAYS
  followed by play STOPPING: the scoring team celebrates, the ball is retrieved
  from inside the goal, and the game restarts with a kickoff from the centre
  circle. If, in the seconds after the moment, the goalkeeper simply distributes
  the ball (throw/roll/kick from hands), or a goal kick or corner is taken, or
  open play continues, then NO goal was scored — label that moment "shot".

How to localize reliably on wide footage (the ball itself is often hard to see):
- Use the WHOLE timeline for context and compare moments against each other. A
  real shot is followed within a few seconds by a clear game-state change:
  keeper possession, goal kick, corner, play pausing, or celebration + kickoff.
  Ordinary passes, crosses and clearances do NOT produce such a reset.
- Use the AUDIO track: the thump of a hard strike and the crowd/bench reaction
  immediately after it are strong cues.
- The strike is a single kick or header by one attacker. It can happen ANYWHERE
  within range of the goal — inside the box, at the edge of it, or a LONG-RANGE
  strike from 25-40 yards out. For long-range strikes watch the ball's flight
  toward the goal and the keeper's reaction, not just the goal area.

Report up to 3 candidate moments, ranked most-likely first (1 is usually enough
when the clip clearly contains one attempt). Timestamp the STRIKE itself — not
the buildup before it, not the aftermath after it.
If the clip contains no shot or goal at all, return an empty candidates list.

Return JSON only:
{
  "candidates": [
    {
      "rank": 1,
      "event_type": "shot" | "goal",
      "strike_time": "M:SS.s",
      "strike_timestamp_seconds": number,
      "outcome": "save" | "net" | "post" | "wide" | "over" | "blocked" | "corner" | "unclear",
      "aftermath": "what visibly happens in the ~5s after the strike",
      "evidence": ["specific visual or audio evidence", "..."],
      "confidence": number 0..1
    }
  ]
}

"strike_time" is the strike moment as minutes:seconds from the start of THIS
clip, e.g. "0:29.5" for 29.5 seconds in. "strike_timestamp_seconds" is the SAME
moment as a plain number of seconds (29.5 in that example). Fill both.
"""

VERIFY_PROMPT = """You are verifying a SHORT window of wide-angle soccer footage at high detail.
A coarse pass suggested a possible shot or goal attempt somewhere near the
middle of this window. Decide what genuinely happens.

An ATTEMPT is a deliberate strike toward the opponent's goal (kick or header).
Attempts can come from ANYWHERE in range — inside the box, the edge of the box,
or LONG-RANGE strikes from 25-40 yards (for those, watch the ball's flight
toward the goal and the keeper's reaction; the shooter may be far from the
goal, even near the edge of the frame).
NOT attempts: passes, crosses into the box, clearances, the keeper catching a
cross, goal kicks, and free-kick/corner DELIVERIES (the delivery itself is not
an attempt; a direct strike at goal IS).

For EVERY genuine attempt inside this window, report:
1. "strike_time": the exact moment the attacker's foot/head CONTACTS the ball,
   as "M:SS.s" measured from the start of THIS window (e.g. "0:07.4"). Also
   fill "strike_timestamp_seconds" with the same moment as plain seconds (7.4).
2. "outcome": "save" | "catch" | "parry" | "net" | "post" | "wide" | "over" |
   "blocked" | "unclear"  ("net" means the ball crosses the line into the goal)
3. "play_after": what happens in the seconds AFTER this attempt —
   - "resets": the keeper holds the ball, a goal kick is awarded, a corner is
     awarded, or a goal is scored (celebration / kickoff restart follows)
   - "continues": a parry/rebound stays live, the scramble goes on, or the ball
     is cleared but open play simply flows on
4. "reset_kind": "keeper_holds" | "goal_kick" | "corner" | "kickoff_celebration" | null
5. "confidence" 0..1, and short "evidence" — cite BOTH visual and audio cues
   (strike thump, crowd reaction) where available.

Watch the goal mouth carefully; the footage is high resolution. If there is no
genuine attempt in this window, return {"attempts": []}.

Return JSON only:
{
  "attempts": [
    {
      "strike_time": "M:SS.s",
      "strike_timestamp_seconds": number,
      "event_type": "shot" | "goal",
      "outcome": "...",
      "play_after": "resets" | "continues",
      "reset_kind": "..." | null,
      "confidence": number,
      "evidence": ["...", "..."]
    }
  ]
}
"""

RANK_WEIGHT = {1: 1.0, 2: 0.6, 3: 0.4}


def _parse_mmss(value) -> float | None:
    """Parse 'M:SS(.s)' -> seconds. Returns None if not parseable."""
    if not isinstance(value, str):
        return None
    m = re.match(r"^\s*(\d+):([0-5]?\d(?:\.\d+)?)\s*$", value)
    if not m:
        return None
    return int(m.group(1)) * 60 + float(m.group(2))


def _candidate_ts(c: dict) -> float | None:
    """Authoritative timestamp for one model candidate (MM:SS string wins)."""
    mmss = _parse_mmss(c.get("strike_time"))
    if mmss is not None:
        return mmss
    num = c.get("strike_timestamp_seconds")
    return float(num) if isinstance(num, (int, float)) else None


@dataclass
class WholeClipResult:
    event_type: str  # goal | shot | none
    timestamp_seconds: float | None
    confidence: float
    outcome: str = ""
    explanation: str = ""
    debug: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class WholeClipDetector:
    """Gemini-backed two-stage detector for short single-event clips."""

    _client = None

    def __init__(self):
        self.available = False
        key = _api_key()
        if not key:
            logger.info("Whole-clip detector disabled: no API key set.")
            return
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            logger.warning("Whole-clip detector disabled: ffmpeg/ffprobe missing.")
            return
        try:
            from google import genai

            if WholeClipDetector._client is None:
                WholeClipDetector._client = genai.Client(api_key=key)
            self.available = True
            logger.info("Whole-clip detector ready (model=%s).", settings.vlm_model)
        except Exception as exc:  # pragma: no cover - optional path
            logger.warning("Whole-clip detector unavailable (%s).", exc)

    # ---------- shared plumbing ----------

    def _upload(self, path: Path):
        client = WholeClipDetector._client
        uploaded = _with_retry(lambda: client.files.upload(file=str(path)))
        for _ in range(60):
            state = getattr(getattr(uploaded, "state", None), "name", None) or getattr(uploaded, "state", None)
            if str(state) == "ACTIVE":
                return uploaded
            if str(state) == "FAILED":
                raise RuntimeError(f"upload FAILED for {path.name}")
            time.sleep(1)
            uploaded = client.files.get(name=uploaded.name)
        raise RuntimeError(f"upload never became ACTIVE for {path.name}")

    def _delete_quiet(self, uploaded) -> None:
        try:
            WholeClipDetector._client.files.delete(name=uploaded.name)
        except Exception:
            pass

    def _generate(self, uploaded, prompt: str, model: str, fps: float | None) -> dict:
        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=0.0, top_p=1.0, response_mime_type="application/json",
        )
        if fps is None:
            contents = [uploaded, prompt]
        else:
            part = types.Part(
                file_data=types.FileData(file_uri=uploaded.uri, mime_type=uploaded.mime_type),
                video_metadata=types.VideoMetadata(fps=fps),
            )
            contents = [types.Content(role="user", parts=[part, types.Part(text=prompt)])]
        response = _with_retry(
            lambda: WholeClipDetector._client.models.generate_content(
                model=model, contents=contents, config=config
            )
        )
        return _parse_json(response.text or "")

    @staticmethod
    def _duration(path: Path) -> float:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        try:
            return float(out.stdout.strip())
        except ValueError:
            return 0.0

    @staticmethod
    def _cut(path: Path, start: float, end: float) -> Path:
        """Cut [start, end] at native resolution, keeping the audio track."""
        tmp = Path(tempfile.mkdtemp(prefix="wc_zoom_")) / f"zoom_{start:.1f}_{end:.1f}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(path),
             "-t", f"{end - start:.3f}", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "23", "-c:a", "aac", "-b:a", "96k", str(tmp)],
            capture_output=True, timeout=120,
        )
        return tmp

    # ---------- stage 1: whole-clip localization ----------

    def _localize_vote(self, uploaded, vote: int) -> list[dict]:
        data = self._generate(uploaded, LOCALIZE_PROMPT, settings.vlm_model, None)
        out = []
        for i, c in enumerate((data.get("candidates") or [])[:3]):
            ts = _candidate_ts(c)
            if ts is None:
                continue
            out.append({
                "ts": ts,
                "type": str(c.get("event_type", "shot")).lower(),
                "outcome": str(c.get("outcome", "unclear")).lower(),
                "conf": float(c.get("confidence", 0.0) or 0.0),
                "rank": int(c.get("rank", i + 1) or (i + 1)),
                "vote": vote,
                "evidence": list(c.get("evidence", []) or []),
            })
        return out

    @staticmethod
    def _split_wide(cluster: list[dict], max_span: float) -> list[list[dict]]:
        """Recursively split chain-merged clusters at their largest internal gap.

        Same-moment vote scatter is ≤~3s; a cluster spanning more than max_span
        is two real moments chained by greedy clustering (shot_4550 failure).
        """
        if cluster[-1]["ts"] - cluster[0]["ts"] <= max_span:
            return [cluster]
        gaps = [(cluster[i + 1]["ts"] - cluster[i]["ts"], i) for i in range(len(cluster) - 1)]
        _, i = max(gaps)
        return (WholeClipDetector._split_wide(cluster[: i + 1], max_span)
                + WholeClipDetector._split_wide(cluster[i + 1:], max_span))

    @staticmethod
    def _cluster_localization(cands: list[dict], slack: float = 4.0) -> list[dict]:
        clusters: list[list[dict]] = []
        for c in sorted(cands, key=lambda c: c["ts"]):
            if clusters and c["ts"] - clusters[-1][-1]["ts"] <= slack:
                clusters[-1].append(c)
            else:
                clusters.append([c])
        clusters = [part for cl in clusters for part in WholeClipDetector._split_wide(cl, slack)]
        scored = []
        for cl in clusters:
            votes = {c["vote"] for c in cl}
            score = sum(RANK_WEIGHT.get(c["rank"], 0.3) * max(c["conf"], 0.05) for c in cl)
            score *= 1.0 + 0.5 * (len(votes) - 1)
            n_goal = sum(1 for c in cl if c["type"] == "goal")
            scored.append({
                "timestamp": round(statistics.median(c["ts"] for c in cl), 2),
                "event_type": "goal" if n_goal > len(cl) / 2 else "shot",
                "score": round(score, 3),
                "votes": len(votes),
                "members": cl,
            })
        scored.sort(key=lambda s: -s["score"])
        return scored

    # ---------- stage 2: zoom verification ----------

    def _verify_window(self, path: Path, win_start: float, win_end: float) -> list[dict]:
        sub = self._cut(path, win_start, win_end)
        attempts: list[dict] = []
        try:
            if not sub.exists() or sub.stat().st_size == 0:
                return attempts
            uploaded = self._upload(sub)
            try:
                for v in range(settings.wc_verify_votes):
                    data = self._generate(uploaded, VERIFY_PROMPT, settings.vlm_model, settings.wc_verify_fps)
                    for a in (data.get("attempts") or [])[:4]:
                        rel = _candidate_ts(a)
                        if rel is None or rel < 0 or rel > (win_end - win_start) + 1.0:
                            continue
                        attempts.append({
                            "ts": round(win_start + rel, 2),
                            "event_type": str(a.get("event_type", "shot")).lower(),
                            "outcome": str(a.get("outcome", "unclear")).lower(),
                            "play_after": str(a.get("play_after", "")).lower(),
                            "reset_kind": a.get("reset_kind"),
                            "confidence": float(a.get("confidence", 0.0) or 0.0),
                            "evidence": list(a.get("evidence", []) or []),
                            "vote": v,
                        })
            finally:
                self._delete_quiet(uploaded)
        finally:
            shutil.rmtree(sub.parent, ignore_errors=True)
        return attempts

    @staticmethod
    def _majority(values: list[str], default: str = "") -> str:
        """Most common value; deterministic tiebreak (count desc, lexicographic)."""
        vals = [v for v in values if v]
        if not vals:
            return default
        return sorted(set(vals), key=lambda v: (-vals.count(v), v))[0]

    @staticmethod
    def _play_after_majority(values: list[str]) -> str:
        """Majority for play_after; ties resolve to "resets" (keeps the stage-1
        goal override narrow — wide-view "net" votes can be parallax illusions)."""
        cont = values.count("continues")
        res = values.count("resets")
        if cont > res:
            return "continues"
        if res > 0 or cont > 0:
            return "resets"
        return ""

    @classmethod
    def _cluster_attempts(cls, attempts: list[dict], slack: float = 3.0) -> list[dict]:
        groups: list[list[dict]] = []
        for a in sorted(attempts, key=lambda a: a["ts"]):
            if groups and a["ts"] - groups[-1][-1]["ts"] <= slack:
                groups[-1].append(a)
            else:
                groups.append([a])
        out = []
        for g in groups:
            out.append({
                "ts": round(statistics.median(a["ts"] for a in g), 2),
                "event_type": cls._majority([a["event_type"] for a in g], "shot"),
                "outcome": cls._majority([a["outcome"] for a in g], "unclear"),
                "play_after": cls._play_after_majority([a["play_after"] for a in g]),
                "confidence": round(statistics.mean(a["confidence"] for a in g), 3),
                "weight": round(sum(a["confidence"] for a in g), 3),
                "n": len(g),
                "evidence": [e for a in g for e in a["evidence"]][:6],
            })
        return out

    # ---------- selection ----------

    @staticmethod
    def _stage1_unanimous_goal(stage1_clusters: list[dict], headline_ts: float) -> bool:
        """ALL stage-1 votes called the moment nearest the headline a goal.

        Unanimity is the only goal signal that never failed on the verified
        suite: both real goals are 5/5 in every run; true shots top out at 4/5
        (and that only under a since-reverted prompt line). Every richer
        signal — stage-2 "net", video aftermath checks, image panels — proved
        parallax-fallible in one direction or another.
        """
        near = [cl for cl in stage1_clusters if abs(cl["timestamp"] - headline_ts) <= 6.0]
        if not near:
            return False
        cl = min(near, key=lambda c: abs(c["timestamp"] - headline_ts))
        members = cl.get("members", [])
        if not members:
            return False
        goal_members = [m for m in members if m.get("type") == "goal"]
        if len(goal_members) != len(members):
            return False
        return len({m.get("vote") for m in goal_members}) >= settings.wc_votes

    @staticmethod
    def _select(attempt_clusters: list[dict]) -> tuple[dict, list[dict], list[dict]] | None:
        """Pick the headline attempt; returns (headline, its sequence, all
        sequence headlines). Secondary sequences are surfaced too — the product
        prefers over-detection to missing a real attempt (false negatives are
        the enemy)."""
        kept = [c for c in attempt_clusters if c["confidence"] >= settings.wc_min_conf]
        if not kept:
            return None
        sequences: list[list[dict]] = []
        for c in kept:
            if sequences and c["ts"] - sequences[-1][-1]["ts"] <= settings.wc_seq_gap:
                sequences[-1].append(c)
            else:
                sequences.append([c])
        best_seq = max(sequences, key=lambda s: sum(c["weight"] for c in s))

        def seq_headline(seq: list[dict]) -> dict:
            resetting = [c for c in seq if c["play_after"] == "resets"]
            return resetting[-1] if resetting else seq[-1]

        headline = seq_headline(best_seq)
        all_events = [seq_headline(s) for s in sequences]
        return headline, best_seq, all_events

    # ---------- public API ----------

    def analyze(self, video_path: str | Path) -> WholeClipResult:
        """Run the full two-stage detection on one short clip."""
        if not self.available:
            return WholeClipResult("none", None, 0.0, error="wholeclip_unavailable")

        path = Path(video_path)
        duration = self._duration(path)

        # Stage 1 — K concurrent localization votes over the whole clip.
        uploaded = self._upload(path)
        try:
            def safe_vote(v: int) -> list[dict]:
                try:
                    return self._localize_vote(uploaded, v)
                except Exception as exc:
                    logger.warning("Localization vote %d failed (%s); continuing.", v, exc)
                    return []

            with ThreadPoolExecutor(max_workers=max(1, settings.vlm_concurrency)) as pool:
                per_vote = list(pool.map(safe_vote, range(settings.wc_votes)))
        finally:
            self._delete_quiet(uploaded)

        clusters = self._cluster_localization([c for vc in per_vote for c in vc])
        candidates = clusters[: settings.wc_max_candidates]

        if not candidates:
            return WholeClipResult(
                "none", None, 0.0,
                explanation="No shot or goal attempt detected.",
                debug={"stage1_clusters": clusters, "method": "wholeclip_two_stage"},
            )

        # Stage 2 — zoom-verify candidate windows concurrently.
        def verify(cl: dict) -> list[dict]:
            ws = max(0.0, cl["timestamp"] - settings.wc_zoom_pre)
            we = min(duration, cl["timestamp"] + settings.wc_zoom_post)
            try:
                return self._verify_window(path, ws, we)
            except Exception as exc:
                logger.warning("Verify window %.0f-%.0f failed (%s); continuing.", ws, we, exc)
                return []

        with ThreadPoolExecutor(max_workers=max(1, settings.vlm_concurrency)) as pool:
            attempt_lists = list(pool.map(verify, candidates))
        attempts = [a for lst in attempt_lists for a in lst]
        attempt_clusters = self._cluster_attempts(attempts)
        cover_end = max((min(duration, cl["timestamp"] + settings.wc_zoom_post)
                         for cl in candidates), default=0.0)

        # Follow-up: a sequence whose LAST attempt "continues" admits the
        # passage is not over — the decisive attempt may lie past the verified
        # window's edge (its aftermath cut off). Chase the continuation; prefer
        # extra looking to missing (recall over precision).
        for _ in range(2):
            if not attempt_clusters or attempt_clusters[-1]["play_after"] != "continues":
                break
            last_ts = attempt_clusters[-1]["ts"]
            fw_start, fw_end = max(0.0, last_ts - 1.0), min(duration, last_ts + 13.0)
            # Only chase NEW ground — re-verifying covered seconds stacks
            # duplicate readings of the same aftermath (shot_4544 regression).
            if fw_end < cover_end + 2.0:
                break
            if fw_end - fw_start < 4.0:
                break
            extra = self._verify_window(path, fw_start, fw_end)
            cover_end = max(cover_end, fw_end)
            new = [a for a in extra if a["ts"] > last_ts + 1.0]
            if not new:
                break
            attempts.extend(new)
            attempt_clusters = self._cluster_attempts(attempts)

        selected = self._select(attempt_clusters)
        if selected is None:
            # Candidates existed but none verified: fall back to the best
            # stage-1 cluster at reduced confidence rather than silently none.
            best = candidates[0]
            return WholeClipResult(
                best["event_type"], best["timestamp"], 0.5,
                explanation="Coarse localization only; verification found no clear attempt.",
                debug={"stage1_clusters": clusters, "attempt_clusters": attempt_clusters,
                       "method": "wholeclip_stage1_only"},
            )
        headline, best_seq, all_events = selected

        # Goal-vs-shot: stage-1 unanimity, nothing else (see
        # _stage1_unanimous_goal and docs/callibrations+results.md — every
        # richer signal, including stage-2's own "net" outcome, proved
        # parallax-fallible on this footage).
        s1_unanimous = self._stage1_unanimous_goal(clusters, headline["ts"])
        event_type = "goal" if s1_unanimous else "shot"

        explanation = "; ".join(headline.get("evidence", [])[:3]) or (
            f"Video analysis identified a {event_type}."
        )
        return WholeClipResult(
            event_type=event_type,
            timestamp_seconds=headline["ts"],
            confidence=min(0.99, headline["confidence"]),
            outcome=headline["outcome"],
            explanation=explanation,
            debug={
                "method": "wholeclip_two_stage",
                "stage1_clusters": [
                    {k: cl[k] for k in ("timestamp", "event_type", "score", "votes")}
                    for cl in clusters
                ],
                "attempt_clusters": attempt_clusters,
                "type_decision": {"stage1_unanimous_goal": s1_unanimous},
                # All verified attempt sequences (recall over precision: the
                # product surfaces every real attempt, not just the headline).
                "all_events": [
                    {"timestamp": e["ts"], "outcome": e["outcome"],
                     "confidence": e["confidence"], "play_after": e["play_after"]}
                    for e in all_events
                ],
            },
        )


def get_wholeclip_detector() -> WholeClipDetector:
    return WholeClipDetector()
