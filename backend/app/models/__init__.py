"""Domain models for TeloraFooty.

These are plain Pydantic models persisted as JSON for the MVP. They are kept
free of framework concerns so a real database (SQLModel/SQLAlchemy) can be
introduced later without changing the service interfaces.
"""

from app.models.clip import Clip
from app.models.event import Event
from app.models.game import Game
from app.models.job import Job
from app.models.video import Video

__all__ = ["Game", "Video", "Event", "Clip", "Job"]
