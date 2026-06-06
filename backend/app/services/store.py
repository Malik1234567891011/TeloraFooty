"""A tiny JSON-backed data store for the MVP.

This intentionally mimics a repository so it can be swapped for SQLModel later
without changing callers. All collections persist to JSON files under
``app/data/``. Access is guarded by a lock for safety with FastAPI background
tasks.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Iterable

from app.config import settings
from app.core.logging import get_logger
from app.models import Clip, Event, Game, Job, Video

logger = get_logger(__name__)


class JsonStore:
    def __init__(self, data_dir: Path | None = None):
        self._dir = data_dir or settings.data_dir
        self._lock = threading.RLock()
        self._dir.mkdir(parents=True, exist_ok=True)
        self.games: dict[str, Game] = {}
        self.videos: dict[str, Video] = {}
        self.events: dict[str, Event] = {}
        self.clips: dict[str, Clip] = {}
        self.jobs: dict[str, Job] = {}
        self._load()

    # ------------------------------------------------------------------ I/O
    def _path(self, name: str) -> Path:
        return self._dir / f"{name}.json"

    def _load(self) -> None:
        self.games = self._load_collection("games", Game)
        self.videos = self._load_collection("videos", Video)
        self.events = self._load_collection("events", Event)
        self.clips = self._load_collection("clips", Clip)
        self.jobs = self._load_collection("jobs", Job)

    def _load_collection(self, name: str, model) -> dict:
        path = self._path(name)
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text())
            return {item["id"]: model(**item) for item in raw}
        except Exception as exc:  # corrupt file should not crash startup
            logger.warning("Failed to load %s store (%s); starting empty.", name, exc)
            return {}

    def _save_collection(self, name: str, items: Iterable) -> None:
        path = self._path(name)
        data = [item.model_dump(mode="json") for item in items]
        path.write_text(json.dumps(data, indent=2))

    def _persist(self) -> None:
        self._save_collection("games", self.games.values())
        self._save_collection("videos", self.videos.values())
        self._save_collection("events", self.events.values())
        self._save_collection("clips", self.clips.values())
        self._save_collection("jobs", self.jobs.values())

    # --------------------------------------------------------------- upserts
    def save_game(self, game: Game) -> Game:
        with self._lock:
            self.games[game.id] = game
            self._save_collection("games", self.games.values())
        return game

    def save_video(self, video: Video) -> Video:
        with self._lock:
            self.videos[video.id] = video
            self._save_collection("videos", self.videos.values())
        return video

    def save_event(self, event: Event) -> Event:
        with self._lock:
            self.events[event.id] = event
            self._save_collection("events", self.events.values())
        return event

    def save_clip(self, clip: Clip) -> Clip:
        with self._lock:
            self.clips[clip.id] = clip
            self._save_collection("clips", self.clips.values())
        return clip

    def save_job(self, job: Job) -> Job:
        with self._lock:
            self.jobs[job.id] = job
            self._save_collection("jobs", self.jobs.values())
        return job

    # ----------------------------------------------------------------- reads
    def get_game(self, game_id: str) -> Game | None:
        return self.games.get(game_id)

    def get_video(self, video_id: str) -> Video | None:
        return self.videos.get(video_id)

    def get_job(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list_games(self) -> list[Game]:
        return sorted(self.games.values(), key=lambda g: g.created_at)

    def events_for_game(self, game_id: str) -> list[Event]:
        items = [e for e in self.events.values() if e.game_id == game_id]
        return sorted(items, key=lambda e: e.timestamp_seconds)

    def clips_for_game(self, game_id: str) -> list[Clip]:
        items = [c for c in self.clips.values() if c.game_id == game_id]
        return sorted(items, key=lambda c: c.timestamp_seconds)

    def clear_events_for_game(self, game_id: str) -> None:
        with self._lock:
            self.events = {k: v for k, v in self.events.items() if v.game_id != game_id}
            self.clips = {k: v for k, v in self.clips.items() if v.game_id != game_id}
            self._save_collection("events", self.events.values())
            self._save_collection("clips", self.clips.values())

    def delete_event(self, event_id: str) -> bool:
        with self._lock:
            if self.events.pop(event_id, None) is None:
                return False
            self._save_collection("events", self.events.values())
        return True

    def delete_clip(self, clip_id: str) -> None:
        with self._lock:
            if self.clips.pop(clip_id, None) is not None:
                self._save_collection("clips", self.clips.values())

    def delete_game(self, game_id: str) -> bool:
        with self._lock:
            game = self.games.pop(game_id, None)
            if game is None:
                return False
            if game.video_id:
                self.videos.pop(game.video_id, None)
            self.events = {k: v for k, v in self.events.items() if v.game_id != game_id}
            self.clips = {k: v for k, v in self.clips.items() if v.game_id != game_id}
            self.jobs = {k: v for k, v in self.jobs.items() if v.game_id != game_id}
            self._persist()
        return True


# Module-level singleton used across the app.
store = JsonStore()
