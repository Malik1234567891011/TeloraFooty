"""STAGE-1 EXPERIMENT 2-WC — whole-clip Gemini localization with K-vote consensus.

Frozen protocol (docs/callibrations+results.md): 8 Dordt clips, event at exactly
30.0s, valid = candidate within +/-4.0s, budget <=3 candidates/clip, bar = 8/8.

DEVIATION (user-approved): Gemini IS allowed here. The original "no Gemini in
Stage 1" rule existed because per-window VLM voting failed as a localizer
(iter-8 correction). This experiment tests a structurally different question:
ONE call over the WHOLE original clip (1080p, WITH audio — never tried before;
the old path cut 8s windows, downscaled to 640px and stripped audio), asking the
model to comparatively localize the single decisive strike across the full
timeline. Non-determinism is handled by K independent votes + timestamp
clustering, not by hoping a single call is stable.

Usage:
    python scripts/stage1_exp2_wholeclip.py /Users/omarlahmimi/Documents/clips \
        [--votes 3] [--max 3] [--gt 30] [--tol 4] [--fps N] [--model m] [--workers 3]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402

PROMPT = """You are analyzing one short clip of wide-angle (Veo-style) soccer footage.
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


def _parse_mmss(value) -> float | None:
    """Parse 'M:SS(.s)' -> seconds. Returns None if not parseable."""
    if not isinstance(value, str):
        return None
    m = re.match(r"^\s*(\d+):([0-5]?\d(?:\.\d+)?)\s*$", value)
    if not m:
        return None
    return int(m.group(1)) * 60 + float(m.group(2))


def candidate_ts(c: dict) -> float | None:
    """Authoritative timestamp for one model candidate.

    Gemini intermittently emits the seconds number shifted two decimal places
    (29.5 -> 0.288-style collapse), so the MM:SS string is authoritative; the
    numeric field is only a fallback when the string is missing/unparseable.
    """
    mmss = _parse_mmss(c.get("strike_time"))
    num = c.get("strike_timestamp_seconds")
    num = float(num) if isinstance(num, (int, float)) else None
    if mmss is not None:
        return mmss
    return num

RANK_WEIGHT = {1: 1.0, 2: 0.6, 3: 0.4}


@dataclass
class VoteCandidate:
    ts: float
    event_type: str
    outcome: str
    confidence: float
    rank: int
    vote: int
    evidence: list[str] = field(default_factory=list)


def _is_rate_limit(exc: Exception) -> bool:
    """Retryable: rate limits, transient server errors, AND network/TLS flakes
    (overnight runs hit e.g. 'SSL: TLSV1_ALERT_DECODE_ERROR' mid-gauntlet)."""
    msg = str(exc).lower()
    return any(t in msg for t in (
        "429", "resource_exhausted", "quota", "rate limit", "too many requests",
        "500", "502", "503", "internal", "unavailable", "deadline", "timed out", "timeout",
        "ssl", "tls", "connection", "socket", "eof occurred", "broken pipe",
        "remotedisconnected", "reset by peer",
    ))


def _with_retry(fn, *, attempts: int = 6, base_delay: float = 5.0):
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:
            if not _is_rate_limit(exc):
                raise
            last = exc
            delay = min(90.0, base_delay * (2**i))
            print(f"    rate limited; backing off {delay:.0f}s", flush=True)
            time.sleep(delay)
    raise last  # type: ignore[misc]


def _parse_json(text: str) -> dict:
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


def _upload(client, path: Path):
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


def _contents_for(uploaded, fps: float | None, prompt: str = PROMPT):
    """Build request contents; optionally ask for denser frame sampling."""
    if fps is None:
        return [uploaded, prompt]
    from google.genai import types

    part = types.Part(
        file_data=types.FileData(file_uri=uploaded.uri, mime_type=uploaded.mime_type),
        video_metadata=types.VideoMetadata(fps=fps),
    )
    return [types.Content(role="user", parts=[part, types.Part(text=prompt)])]


def _one_vote(client, model: str, uploaded, fps: float | None, vote_idx: int) -> list[VoteCandidate]:
    from google.genai import types

    config = types.GenerateContentConfig(
        temperature=0.0,
        top_p=1.0,
        response_mime_type="application/json",
    )
    response = _with_retry(
        lambda: client.models.generate_content(
            model=model, contents=_contents_for(uploaded, fps), config=config
        )
    )
    data = _parse_json(response.text or "")
    out: list[VoteCandidate] = []
    for c in (data.get("candidates") or [])[:3]:
        ts = candidate_ts(c)
        if ts is None:
            continue
        out.append(
            VoteCandidate(
                ts=ts,
                event_type=str(c.get("event_type", "shot")).lower(),
                outcome=str(c.get("outcome", "unclear")),
                confidence=float(c.get("confidence", 0.0) or 0.0),
                rank=int(c.get("rank", len(out) + 1) or (len(out) + 1)),
                vote=vote_idx,
                evidence=list(c.get("evidence", []) or []),
            )
        )
    return out


def _split_wide(cluster: list, max_span: float, ts_of) -> list[list]:
    """Recursively split chain-merged clusters at their largest internal gap.

    Greedy clustering chains votes 25.0→26.5→28.5→30.5 into one "moment" even
    though they describe TWO real attempts (each link ≤ slack). Same-moment
    vote scatter is ≤~3s, so a cluster spanning more than max_span is two
    moments wearing one hat (shot_4550, final-gauntlet run 1).
    """
    if ts_of(cluster[-1]) - ts_of(cluster[0]) <= max_span:
        return [cluster]
    gaps = [(ts_of(cluster[i + 1]) - ts_of(cluster[i]), i) for i in range(len(cluster) - 1)]
    _, i = max(gaps)
    return _split_wide(cluster[: i + 1], max_span, ts_of) + _split_wide(cluster[i + 1:], max_span, ts_of)


def _cluster_votes(cands: list[VoteCandidate], slack: float) -> list[dict]:
    """Greedy timestamp clustering across votes; score by votes + rank + conf."""
    clusters: list[list[VoteCandidate]] = []
    for c in sorted(cands, key=lambda c: c.ts):
        if clusters and c.ts - clusters[-1][-1].ts <= slack:
            clusters[-1].append(c)
        else:
            clusters.append([c])
    clusters = [part for cl in clusters for part in _split_wide(cl, slack, lambda c: c.ts)]

    scored = []
    for cl in clusters:
        votes = {c.vote for c in cl}
        score = sum(RANK_WEIGHT.get(c.rank, 0.3) * max(c.confidence, 0.05) for c in cl)
        score *= 1.0 + 0.5 * (len(votes) - 1)  # cross-vote agreement bonus
        n_goal = sum(1 for c in cl if c.event_type == "goal")
        scored.append(
            {
                "timestamp": round(statistics.median(c.ts for c in cl), 2),
                "event_type": "goal" if n_goal > len(cl) / 2 else "shot",
                "score": round(score, 3),
                "votes": len(votes),
                "members": [
                    {"vote": c.vote, "ts": c.ts, "rank": c.rank, "type": c.event_type,
                     "outcome": c.outcome, "conf": c.confidence}
                    for c in cl
                ],
                "outcomes": sorted({c.outcome for c in cl}),
            }
        )
    scored.sort(key=lambda s: -s["score"])
    return scored


def analyze_clip(client, model: str, path: Path, votes: int, fps: float | None, max_cands: int) -> dict:
    short = path.name.replace("DordtFirstHalfSept212024_", "").replace(".mp4", "")
    uploaded = _upload(client, path)
    try:
        per_vote: list[list[VoteCandidate]] = []
        for v in range(votes):
            cands = _one_vote(client, model, uploaded, fps, v)
            per_vote.append(cands)
            print(
                f"    [{short}] vote {v}: "
                + (", ".join(f"{c.event_type}@{c.ts:.1f}({c.outcome},{c.confidence:.2f})" for c in cands) or "none"),
                flush=True,
            )
        clusters = _cluster_votes([c for vc in per_vote for c in vc], slack=4.0)
        return {"clusters": clusters[:max_cands], "all_clusters": clusters,
                "raw_votes": [[c.__dict__ for c in vc] for vc in per_vote]}
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default="../clips")
    ap.add_argument("--votes", type=int, default=3)
    ap.add_argument("--max", type=int, default=3, help="candidate budget per clip")
    ap.add_argument("--gt", type=float, default=30.0)
    ap.add_argument("--tol", type=float, default=4.0)
    ap.add_argument("--fps", type=float, default=None, help="video sampling fps override")
    ap.add_argument("--model", default=settings.vlm_model)
    ap.add_argument("--workers", type=int, default=3, help="clips analyzed concurrently")
    args = ap.parse_args()

    from google import genai

    key = settings.gemini_api_key
    if not key:
        print("No GEMINI_API_KEY configured (backend/.env)."); raise SystemExit(1)
    client = genai.Client(api_key=key)

    clips = sorted(Path(args.folder).glob("*.mp4"))
    if not clips:
        print(f"No .mp4 clips in {args.folder}"); raise SystemExit(1)

    print(f"model={args.model} votes={args.votes} fps={args.fps or 'default(1)'} "
          f"gt={args.gt} tol=±{args.tol} budget≤{args.max}\n")

    results: dict[str, dict] = {}

    def run(clip: Path) -> None:
        print(f"--- {clip.name}", flush=True)
        try:
            results[clip.name] = analyze_clip(client, args.model, clip, args.votes, args.fps, args.max)
        except Exception as exc:
            results[clip.name] = {"error": str(exc), "clusters": []}
            print(f"    ERROR: {exc}", flush=True)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        list(pool.map(run, clips))

    print("\n" + "=" * 96)
    print(f"{'CLIP':42} {'CANDIDATES (s)':24} {'CLOSEST':>8} {'COUNT':>6}  RESULT")
    print("-" * 96)
    passes = 0
    for clip in clips:
        r = results[clip.name]
        cl = r.get("clusters", [])
        cand_ts = [c["timestamp"] for c in cl]
        closest = min((abs(t - args.gt) for t in cand_ts), default=float("inf"))
        ok = closest <= args.tol
        passes += ok
        short = clip.name.replace("DordtFirstHalfSept212024_", "")
        print(f"{short:42} {', '.join(f'{t:.1f}' for t in cand_ts):24} "
              f"{closest if closest != float('inf') else -1:8.1f} {len(cand_ts):6d}  {'PASS' if ok else 'FAIL'}")
    print("=" * 96)
    verdict = "PASS (8/8)" if passes == len(clips) else "FAILED"
    print(f"RECALL @ ≤{args.max} (within ±{args.tol}s of {args.gt}s): {passes}/{len(clips)}  ->  {verdict}")

    out = Path("/tmp/stage1_exp2_wholeclip.json")
    out.write_text(json.dumps({"config": vars(args), "results": results}, indent=2, default=str))
    print(f"details -> {out}")


if __name__ == "__main__":
    main()
