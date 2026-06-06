from __future__ import annotations

import pytest

from app.models import Game, Job
from app.services import recovery_service
from app.services.store import store


@pytest.fixture(autouse=True)
def _clean():
    yield
    for gid in list(store.games):
        store.delete_game(gid)
    store.jobs.clear()


def test_recovery_flips_running_games_to_interrupted():
    store.save_game(Game(id="g_run", title="A", status="processing"))
    store.save_game(Game(id="g_dl", title="B", status="downloading"))
    store.save_game(Game(id="g_done", title="C", status="completed"))
    store.save_job(Job(id="j_run", job_type="full_game", game_id="g_run", status="processing"))

    n = recovery_service.recover_orphaned_jobs()

    assert n == 2
    assert store.get_game("g_run").status == "interrupted"
    assert store.get_game("g_run").error and "interrupted" in store.get_game("g_run").error.lower()
    assert store.get_game("g_dl").status == "interrupted"
    assert store.get_game("g_done").status == "completed"  # untouched
    assert store.get_job("j_run").status == "failed"
