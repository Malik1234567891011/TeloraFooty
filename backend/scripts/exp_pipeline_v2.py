"""PIPELINE V2 — whole-clip localization (Stage 1) + high-res zoom verification
and sequence-resolution selection (Stage 2). Scored on TOP-1 (the single
headline timestamp), which is the user-facing bar: the final answer must land
within +/-4s of the true strike on all 8 clips, run after run.

Stage 1 (stage1_exp2_wholeclip): K votes over the WHOLE original clip
(1080p + audio), MM:SS-authoritative timestamps, cross-vote clustering ->
<=3 candidate moments per clip.

Stage 2 (this script):
  For each candidate, cut a tight subclip [ts-7, ts+9] at native 1080p WITH
  audio, and have Gemini verify it at fps=5 frame sampling: exact strike time,
  outcome, and whether play RESETS afterwards (keeper holds / goal kick /
  corner / celebration+kickoff) or CONTINUES live (parry, rebound, scramble).

Selection (deterministic code, generic soccer logic — no tuned magic):
  - verified attempts cluster across candidates/votes (3s slack)
  - attempts group into SEQUENCES (gap <= 8s = one goalmouth passage of play)
  - best sequence by total verified confidence
  - headline = the LAST attempt of the sequence after which play resets
    (a flurry is decided by the attempt that ends it), else the last attempt
  - goal iff the headline's verified outcome is the net

Usage:
    python scripts/exp_pipeline_v2.py /Users/omarlahmimi/Documents/clips \
        [--votes 5] [--verify-votes 2] [--gt 30] [--tol 4] [--workers 3]
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import settings  # noqa: E402
from stage1_exp2_wholeclip import (  # noqa: E402
    _cluster_votes,
    _contents_for,
    _one_vote,
    _parse_json,
    _parse_mmss,
    _upload,
    _with_retry,
    candidate_ts,
)

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

# NOTE: four goal-vs-shot arbiters were built and A/B-tested here, then
# REMOVED from the decision: video aftermath/celebration, video ball-fate,
# combined forensic, and the image panel below. Each confabulates in at least
# one direction on the parallax clips (shot_2701 / shot_4544: a just-wide ball
# beside the net reads as "in the net" from the wide camera), and panel v2
# even vetoed a TRUE goal once (goal_2312). The final decision uses stage-1
# unanimity only — see analyze_clip_v2. The panel is kept for the record.
# Full evidence trail: docs/callibrations+results.md.

PANEL_PROMPT = """These six photos are consecutive moments (about 2 seconds apart, in order)
from the seconds AFTER a shot attempt in an amateur soccer match, filmed from a
high wide angle. Decide whether the attempt was A GOAL, using the game state.

IMPORTANT: amateur fields often have a SPARE practice ball lying on the grass
behind or beside the goal. A ball that sits MOTIONLESS in the same spot across
ALL six photos is such a spare ball — ignore it completely; it tells you
nothing about the attempt.

GOAL evidence:
- two or more attacking players celebrating: both arms raised high, hugging,
  high-fiving, or jogging away together while play has stopped. Celebrations
  are BRIEF — they may appear clearly in only one or two of the photos; scan
  every photo for raised arms.
- a player lifting/retrieving the ball from INSIDE the goal net
- both teams drifting toward the halfway line for a kickoff restart

NOT-goal evidence:
- the goalkeeper holding the ball and preparing to distribute it
- a goal kick being set up (ball placed near the 6-yard box, players pushing
  out toward midfield, keeper walking to collect a dead ball)
- a corner being set up, or open play continuing
- a single player briefly raising one arm (appeal/frustration) is NOT a celebration

Answer strictly from what is visible in these photos.
Return JSON only:
{"goal": true | false, "confidence": number 0..1, "what_you_see": "one sentence"}
"""


def _image_panel_goal_votes(client, model: str, clip: Path, ts: float, duration: float,
                            votes: int = 3) -> int:
    """Native-res aftermath stills panel; returns the number of 'goal' votes."""
    from google.genai import types

    tmp = Path(tempfile.mkdtemp(prefix="panel_"))
    try:
        parts = []
        for i in range(6):
            t = min(ts + 1 + 2 * i, duration - 0.6)
            f = tmp / f"f{i}.jpg"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(clip),
                            "-frames:v", "1", "-q:v", "2", str(f)], capture_output=True, timeout=60)
            if f.exists() and f.stat().st_size > 0:
                parts.append(types.Part.from_bytes(data=f.read_bytes(), mime_type="image/jpeg"))
        if not parts:
            return 0
        parts.append(types.Part(text=PANEL_PROMPT))
        config = types.GenerateContentConfig(
            temperature=0.0, top_p=1.0, response_mime_type="application/json",
        )
        yes = 0
        for _ in range(votes):
            r = _with_retry(lambda: client.models.generate_content(
                model=model, contents=[types.Content(role="user", parts=parts)], config=config))
            d = _parse_json(r.text or "")
            if bool(d.get("goal")) and float(d.get("confidence", 0) or 0) >= 0.5:
                yes += 1
        return yes
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _s1_goal_stats(stage1_clusters: list[dict], headline_ts: float,
                   max_dist: float = 6.0) -> tuple[float, int, int]:
    """(goal_fraction, distinct_goal_votes, member_count) of the s1 cluster
    nearest the headline. (0.0, 0, 0) when none is near."""
    near = [cl for cl in stage1_clusters or [] if abs(cl["timestamp"] - headline_ts) <= max_dist]
    if not near:
        return 0.0, 0, 0
    cl = min(near, key=lambda c: abs(c["timestamp"] - headline_ts))
    members = cl.get("members", [])
    if not members:
        return 0.0, 0, 0
    goal_members = [m for m in members if m.get("type") == "goal"]
    votes = len({m.get("vote") for m in goal_members})
    return len(goal_members) / len(members), votes, len(members)


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    return float(out.stdout.strip() or 0.0)


def _cut_zoom(path: Path, start: float, end: float) -> Path:
    """Cut [start, end] at native resolution, keeping the audio track."""
    tmp = Path(tempfile.mkdtemp(prefix="zoom_")) / f"zoom_{start:.1f}_{end:.1f}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(path),
         "-t", f"{end - start:.3f}", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "23", "-c:a", "aac", "-b:a", "96k", str(tmp)],
        capture_output=True, timeout=120,
    )
    return tmp


def _verify_window(client, model: str, clip: Path, win_start: float, win_end: float,
                   votes: int, fps: float) -> list[dict]:
    """Zoom-verify one window; return verified attempts with ABSOLUTE timestamps."""
    sub = _cut_zoom(clip, win_start, win_end)
    attempts: list[dict] = []
    try:
        if not sub.exists() or sub.stat().st_size == 0:
            return attempts
        uploaded = _upload(client, sub)
        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                temperature=0.0, top_p=1.0, response_mime_type="application/json",
            )
            for v in range(votes):
                response = _with_retry(
                    lambda: client.models.generate_content(
                        model=model,
                        contents=_contents_for(uploaded, fps, VERIFY_PROMPT),
                        config=config,
                    )
                )
                data = _parse_json(response.text or "")
                for a in (data.get("attempts") or [])[:4]:
                    rel = candidate_ts(a)
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
                        "window": [win_start, win_end],
                    })
        finally:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass
    finally:
        shutil.rmtree(sub.parent, ignore_errors=True)
    return attempts


def _majority(values: list[str], default: str = "") -> str:
    """Most common value; deterministic tiebreak (count desc, then lexicographic).

    Identical votes must always produce identical output, so never rely on set
    iteration order.
    """
    vals = [v for v in values if v]
    if not vals:
        return default
    return sorted(set(vals), key=lambda v: (-vals.count(v), v))[0]


def _play_after_majority(values: list[str]) -> str:
    """Majority for play_after with ties resolving to "resets".

    A tie means the close-up witness is split on whether the sequence resolved;
    treating it as resolved keeps the stage-1 goal override NARROW (stage-1
    "net" votes can be a parallax illusion, so they are only consulted when
    stage-2 clearly lost the ending).
    """
    cont = values.count("continues")
    res = values.count("resets")
    if cont > res:
        return "continues"
    if res > 0 or cont > 0:
        return "resets"
    return ""


def cluster_attempts(attempts: list[dict], slack: float = 3.0) -> list[dict]:
    """Merge verified attempts that refer to the same strike (3s slack)."""
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
            "event_type": _majority([a["event_type"] for a in g], "shot"),
            "outcome": _majority([a["outcome"] for a in g], "unclear"),
            "play_after": _play_after_majority([a["play_after"] for a in g]),
            "reset_kind": _majority([str(a["reset_kind"]) for a in g if a["reset_kind"]], ""),
            "confidence": round(statistics.mean(a["confidence"] for a in g), 3),
            "weight": round(sum(a["confidence"] for a in g), 3),
            "n": len(g),
            "members": g,
        })
    return out


def _stage1_says_goal(stage1_clusters: list[dict], headline_ts: float,
                      max_dist: float = 6.0, min_frac: float = 0.7, min_votes: int = 3) -> bool:
    """Strong whole-clip consensus that the moment near the headline is a GOAL.

    Goal-vs-shot is a GLOBAL property (celebration, kickoff-from-centre restart)
    that the whole-clip pass sees and a tight zoom window can miss (goal_3653:
    zoom said "parry"; whole-clip voted net 5/5). Promote to goal only on strong
    consensus so occasional confabulated "net" votes (shot_2701: 2/5) don't flip
    true shots.
    """
    near = [cl for cl in stage1_clusters or [] if abs(cl["timestamp"] - headline_ts) <= max_dist]
    if not near:
        return False
    cl = min(near, key=lambda c: abs(c["timestamp"] - headline_ts))
    members = cl.get("members", [])
    if not members:
        return False
    goal_members = [m for m in members if m.get("type") == "goal"]
    frac = len(goal_members) / len(members)
    distinct_votes = len({m.get("vote") for m in goal_members})
    return frac >= min_frac and distinct_votes >= min_votes


def select_headline(attempt_clusters: list[dict], min_conf: float, seq_gap: float,
                    stage1_clusters: list[dict] | None = None) -> dict | None:
    """Pick the single user-facing event. See module docstring for the logic."""
    kept = [c for c in attempt_clusters if c["confidence"] >= min_conf]
    if not kept:
        return None

    # Group attempt clusters into sequences (one goalmouth passage of play).
    sequences: list[list[dict]] = []
    for c in kept:  # kept is ts-ordered (cluster_attempts sorts)
        if sequences and c["ts"] - sequences[-1][-1]["ts"] <= seq_gap:
            sequences[-1].append(c)
        else:
            sequences.append([c])

    best_seq = max(sequences, key=lambda s: sum(c["weight"] for c in s))

    resetting = [c for c in best_seq if c["play_after"] == "resets"]
    headline = resetting[-1] if resetting else best_seq[-1]

    # Raw stage-2 view of the type; the FINAL goal-vs-shot decision is made in
    # analyze_clip_v2 (stage-1 unanimity nominates, the image panel confirms or
    # vetoes) because every single-stage video signal proved parallax-fallible.
    event_type = "goal" if (headline["outcome"] == "net" or headline["event_type"] == "goal") else "shot"
    return {
        "event_type": event_type,
        "timestamp": headline["ts"],
        "confidence": headline["confidence"],
        "outcome": headline["outcome"],
        "play_after": headline["play_after"],
        "reset_kind": headline["reset_kind"],
        "sequence": [{k: c[k] for k in ("ts", "outcome", "play_after", "confidence", "n")} for c in best_seq],
        "n_sequences": len(sequences),
    }


def analyze_clip_v2(client, args, path: Path) -> dict:
    short = path.name.replace("DordtFirstHalfSept212024_", "").replace(".mp4", "")
    duration = _duration(path)

    # ---- Stage 1: whole-clip localization votes
    uploaded = _upload(client, path)
    try:
        per_vote = []
        for v in range(args.votes):
            try:
                cands = _one_vote(client, args.model, uploaded, None, v)
            except Exception as exc:
                # A dead vote degrades consensus slightly; it must never zero
                # the whole clip (run-2 v6: one TLS flake -> "none" for the
                # easiest clip in the suite).
                print(f"    [{short}] s1 vote {v} FAILED ({exc}); continuing", flush=True)
                cands = []
            per_vote.append(cands)
            print(f"    [{short}] s1 vote {v}: "
                  + (", ".join(f"{c.event_type}@{c.ts:.1f}({c.outcome})" for c in cands) or "none"),
                  flush=True)
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass
    clusters = _cluster_votes([c for vc in per_vote for c in vc], slack=4.0)[: args.max]

    # ---- Stage 2: zoom-verify each candidate window
    all_attempts: list[dict] = []
    cover_end = 0.0  # rightmost time any verified window has covered
    for cl in clusters:
        ws = max(0.0, cl["timestamp"] - args.zoom_pre)
        we = min(duration, cl["timestamp"] + args.zoom_post)
        cover_end = max(cover_end, we)
        try:
            attempts = _verify_window(client, args.verify_model, path, ws, we,
                                      args.verify_votes, args.verify_fps)
        except Exception as exc:
            print(f"    [{short}] s2 [{ws:.0f}-{we:.0f}] FAILED ({exc}); continuing", flush=True)
            attempts = []
        for a in attempts:
            print(f"    [{short}] s2 [{ws:.0f}-{we:.0f}] v{a['vote']}: {a['event_type']}@{a['ts']} "
                  f"({a['outcome']}, after={a['play_after']}, {a['confidence']:.2f})", flush=True)
        if not attempts:
            print(f"    [{short}] s2 [{ws:.0f}-{we:.0f}]: no attempt verified", flush=True)
        all_attempts.extend(attempts)

    attempt_clusters = cluster_attempts(all_attempts)

    # Follow-up pass: a sequence whose LAST attempt "continues" is an admission
    # that the passage of play is not over — the decisive attempt may lie just
    # beyond the verified window (shot_3050: candidates at 23.5/27.5 put the
    # window edge at 32.5, cutting off the 30.0 strike's aftermath). Chase the
    # continuation with one extra window after the last attempt. Also serves
    # the recall-over-precision directive: prefer extra looking to missing.
    for _ in range(2):  # at most two follow-ups; each must find something new
        if not attempt_clusters or attempt_clusters[-1]["play_after"] != "continues":
            break
        last_ts = attempt_clusters[-1]["ts"]
        fw_start, fw_end = max(0.0, last_ts - 1.0), min(duration, last_ts + 13.0)
        # Only chase NEW ground. Re-verifying already-covered seconds just
        # stacks duplicate/hallucinated readings of the same aftermath
        # (shot_4544: dead-ball goal-kick choreography re-read as "attempts"
        # on every pass, dragging the cluster median late).
        if fw_end < cover_end + 2.0:
            break
        if fw_end - fw_start < 4.0:  # nothing left to look at
            break
        extra = _verify_window(client, args.verify_model, path, fw_start, fw_end,
                               args.verify_votes, args.verify_fps)
        cover_end = max(cover_end, fw_end)
        new = [a for a in extra if a["ts"] > last_ts + 1.0]
        for a in new:
            print(f"    [{short}] s2-followup [{fw_start:.0f}-{fw_end:.0f}] v{a['vote']}: "
                  f"{a['event_type']}@{a['ts']} ({a['outcome']}, after={a['play_after']})", flush=True)
        if not new:
            break
        all_attempts.extend(new)
        attempt_clusters = cluster_attempts(all_attempts)

    headline = select_headline(attempt_clusters, args.min_conf, args.seq_gap, clusters)

    # ---- Final goal-vs-shot decision: stage-1 UNANIMITY, nothing else.
    # Evidence (docs/callibrations+results.md): both real goals are 5/5
    # whole-clip goal votes in EVERY observed run; no true shot ever reached
    # 5/5 with the final prompt (worst: 4544 at 4/5 under a since-reverted
    # prompt line; 2701 at 4/5 once, typically 1-3/5). Every richer signal
    # tried — s2 "net" outcome, video aftermath checks, image panels — was
    # parallax-fallible in at least one direction, including occasionally
    # AGAINST true goals, so adding them increases error, not robustness.
    type_debug = None
    if headline is not None:
        frac, gvotes, members = _s1_goal_stats(clusters, headline["timestamp"])
        s1_unanimous = members > 0 and frac == 1.0 and gvotes >= args.votes
        final_type = "goal" if s1_unanimous else "shot"
        if frac > 0:
            print(f"    [{short}] type: s1_frac={frac:.2f} gvotes={gvotes} "
                  f"unanimous={s1_unanimous} -> {final_type}", flush=True)
        type_debug = {"s1_goal_frac": frac, "s1_goal_votes": gvotes,
                      "s1_unanimous": s1_unanimous}
        headline["event_type"] = final_type

    return {
        "stage1_clusters": clusters,
        "attempt_clusters": attempt_clusters,
        "headline": headline,
        "type_decision": type_debug,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default="../clips")
    ap.add_argument("--votes", type=int, default=5, help="stage-1 whole-clip votes")
    ap.add_argument("--max", type=int, default=3, help="stage-1 candidate budget")
    ap.add_argument("--verify-votes", type=int, default=3)
    ap.add_argument("--verify-fps", type=float, default=5.0)
    ap.add_argument("--zoom-pre", type=float, default=7.0)
    ap.add_argument("--zoom-post", type=float, default=12.0)
    ap.add_argument("--min-conf", type=float, default=0.5)
    ap.add_argument("--seq-gap", type=float, default=8.0)
    ap.add_argument("--gt", type=float, default=30.0)
    ap.add_argument("--tol", type=float, default=4.0)
    ap.add_argument("--model", default=settings.vlm_model)
    ap.add_argument("--verify-model", default=settings.vlm_model)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    from google import genai

    if not settings.gemini_api_key:
        print("No GEMINI_API_KEY configured (backend/.env)."); raise SystemExit(1)
    client = genai.Client(api_key=settings.gemini_api_key)

    clips = sorted(Path(args.folder).glob("*.mp4"))
    if not clips:
        print(f"No .mp4 clips in {args.folder}"); raise SystemExit(1)

    print(f"s1: model={args.model} votes={args.votes} budget<={args.max} | "
          f"s2: model={args.verify_model} votes={args.verify_votes} fps={args.verify_fps} "
          f"zoom=[-{args.zoom_pre},+{args.zoom_post}] | gt={args.gt}±{args.tol}\n")

    results: dict[str, dict] = {}

    def run(clip: Path) -> None:
        print(f"--- {clip.name}", flush=True)
        try:
            results[clip.name] = analyze_clip_v2(client, args, clip)
        except Exception as exc:
            results[clip.name] = {"error": str(exc), "headline": None}
            print(f"    ERROR on {clip.name}: {exc}", flush=True)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        list(pool.map(run, clips))

    print("\n" + "=" * 100)
    print(f"{'CLIP':28} {'TRUTH':14} {'TOP-1':22} {'DIST':>6}  RESULT")
    print("-" * 100)
    passes = 0
    type_ok_all = True
    for clip in clips:
        short = clip.name.replace("DordtFirstHalfSept212024_", "").replace(".mp4", "")
        truth_type = "goal" if short.startswith("goal") else "shot"
        h = results[clip.name].get("headline")
        if h is None:
            print(f"{short:28} {truth_type}@{args.gt:<8} {'none':22} {'inf':>6}  FAIL")
            type_ok_all = False
            continue
        dist = abs(h["timestamp"] - args.gt)
        ok = dist <= args.tol
        passes += ok
        t_ok = h["event_type"] == truth_type
        type_ok_all = type_ok_all and t_ok
        desc = f"{h['event_type']}@{h['timestamp']:.1f} ({h['outcome']})"
        print(f"{short:28} {truth_type}@{args.gt:<8} {desc:22} {dist:6.1f}  "
              f"{'PASS' if ok else 'FAIL'}{'' if t_ok else '  type✗'}")
    print("=" * 100)
    verdict = "PASS (8/8)" if passes == len(clips) else "FAILED"
    print(f"TOP-1 RECALL (within ±{args.tol}s of {args.gt}s): {passes}/{len(clips)}  ->  {verdict}"
          f"   | types {'all correct' if type_ok_all else 'HAVE ERRORS'}")

    out = Path("/tmp/exp_pipeline_v2.json")
    out.write_text(json.dumps({"config": vars(args), "results": results}, indent=2, default=str))
    print(f"details -> {out}")


if __name__ == "__main__":
    main()
