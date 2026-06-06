import json
import os
import uuid
from datetime import date
from pathlib import Path

CLIP_BEFORE = 30.0
CLIP_AFTER = 10.0


def games_root() -> Path:
    base = os.environ.get("TELORA_DATA_DIR")
    root = Path(base) if base else Path(__file__).resolve().parent.parent / "data"
    p = root / "games"
    p.mkdir(parents=True, exist_ok=True)
    return p


def game_dir(game_id: str) -> Path:
    return games_root() / game_id


def save_game(game: dict) -> None:
    d = game_dir(game["id"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "game.json").write_text(json.dumps(game, indent=2))


def load_game(game_id: str) -> dict | None:
    f = game_dir(game_id) / "game.json"
    return json.loads(f.read_text()) if f.exists() else None


def list_games() -> list[dict]:
    games = [json.loads(f.read_text()) for f in games_root().glob("*/game.json")]
    return sorted(games, key=lambda g: g.get("date", ""), reverse=True)


def new_game(title: str, source: dict) -> dict:
    game = {
        "id": f"game_{uuid.uuid4().hex[:8]}",
        "title": title,
        "date": date.today().isoformat(),
        "durationSec": 0.0,
        "source": source,
        "status": "downloading",
        "error": None,
    }
    save_game(game)
    return game


def load_events(game_id: str) -> list[dict]:
    f = game_dir(game_id) / "events.json"
    if not f.exists():
        return []
    events = json.loads(f.read_text())["events"]
    for e in events:
        e.setdefault("verified", False)  # events written before the rating feature
    return events


def save_events(game_id: str, events: list[dict]) -> None:
    events = sorted(events, key=lambda e: e["timestamp"])
    (game_dir(game_id) / "events.json").write_text(
        json.dumps({"events": events}, indent=2)
    )


def clamp_clip(timestamp: float, duration: float) -> tuple[float, float]:
    return max(0.0, timestamp - CLIP_BEFORE), min(duration, timestamp + CLIP_AFTER)


def create_event(game_id: str, etype: str, timestamp: float, source: str = "manual") -> dict:
    game = load_game(game_id)
    start, end = clamp_clip(timestamp, game["durationSec"])
    event = {
        "id": f"evt_{uuid.uuid4().hex[:8]}",
        "type": etype,
        "timestamp": timestamp,
        "source": source,
        "verified": False,
        "clipStart": start,
        "clipEnd": end,
    }
    events = load_events(game_id)
    events.append(event)
    save_events(game_id, events)
    return event


def update_event(game_id: str, event_id: str, changes: dict) -> dict | None:
    game = load_game(game_id)
    events = load_events(game_id)
    for e in events:
        if e["id"] == event_id:
            e.update({k: changes[k] for k in ("type", "timestamp", "verified") if k in changes})
            e["clipStart"], e["clipEnd"] = clamp_clip(e["timestamp"], game["durationSec"])
            save_events(game_id, events)
            return e
    return None


def delete_event(game_id: str, event_id: str) -> bool:
    events = load_events(game_id)
    kept = [e for e in events if e["id"] != event_id]
    if len(kept) == len(events):
        return False
    save_events(game_id, kept)
    return True
