from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.errors import NotFoundError, ValidationError
from app.services.annotation_service import (
    load_annotations_from_file,
    normalize_timestamp,
    parse_annotations,
)


def test_normalize_seconds():
    assert normalize_timestamp(418.2) == 418.2


def test_normalize_mm_ss():
    assert normalize_timestamp("6:58") == 418.0


def test_normalize_hh_mm_ss():
    assert normalize_timestamp("1:02:03") == 3723.0


def test_normalize_negative_raises():
    with pytest.raises(ValidationError):
        normalize_timestamp(-1)


def test_parse_sorts_events():
    raw = {
        "game_id": "g1",
        "events": [
            {"type": "goal", "timestamp_seconds": 50},
            {"type": "shot", "timestamp_seconds": 10},
        ],
    }
    parsed = parse_annotations(raw)
    assert [e.timestamp_seconds for e in parsed.events] == [10, 50]


def test_parse_missing_type_raises():
    with pytest.raises(ValidationError):
        parse_annotations({"game_id": "g1", "events": [{"timestamp_seconds": 10}]})


def test_parse_missing_timestamp_raises():
    with pytest.raises(ValidationError):
        parse_annotations({"game_id": "g1", "events": [{"type": "shot"}]})


def test_parse_missing_game_id_raises():
    with pytest.raises(ValidationError):
        parse_annotations({"events": []})


def test_load_from_file_invalid_json(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json")
    with pytest.raises(ValidationError):
        load_annotations_from_file(p)


def test_load_from_file_missing(tmp_path: Path):
    with pytest.raises(NotFoundError):
        load_annotations_from_file(tmp_path / "nope.json")


def test_load_valid_file(tmp_path: Path):
    p = tmp_path / "g.json"
    p.write_text(json.dumps({"game_id": "g1", "events": [{"type": "shot", "timestamp": "0:10"}]}))
    parsed = load_annotations_from_file(p)
    assert parsed.events[0].timestamp_seconds == 10.0
