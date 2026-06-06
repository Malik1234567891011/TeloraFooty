"""Recover analyses orphaned by a server restart.

A FastAPI background task dies with the process. Any game left mid-run is stuck
in 'processing'/'downloading' with no live worker. On startup we flip those to
'interrupted' (the frontend offers a Retry) and fail their dangling jobs.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.services.store import store

logger = get_logger(__name__)

_INTERRUPTED_MSG = "Analysis was interrupted (server restart). Retry to resume."


def recover_orphaned_jobs() -> int:
    """Flip running games to 'interrupted'. Returns how many were recovered."""
    recovered = 0
    for game in list(store.list_games()):
        if game.status in {"downloading", "processing"}:
            game.status = "interrupted"
            game.error = _INTERRUPTED_MSG
            store.save_game(game)
            for job in list(store.jobs.values()):
                if job.game_id == game.id and job.status in {"queued", "processing"}:
                    job.status = "failed"
                    job.message = _INTERRUPTED_MSG
                    store.save_job(job)
            recovered += 1
    if recovered:
        logger.info("Recovered %d interrupted game(s) on startup.", recovered)
    return recovered
