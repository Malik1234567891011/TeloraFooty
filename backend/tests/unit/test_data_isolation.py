"""Guard: tests must never touch the real JSON store under backend/app/data.

Regression for the data-loss incident where the store ignored STORAGE_DIR and
test teardown wiped production games/events.
"""

from __future__ import annotations

from app.config import BACKEND_DIR, settings
from app.services.store import store


def test_store_is_isolated_from_real_data_dir():
    real = BACKEND_DIR / "app" / "data"
    assert settings.data_dir != real, "TELORA_DATA_DIR override not applied in tests"
    assert store._dir != real, "store singleton points at real data dir"
    assert store._dir == settings.data_dir
