"""Safe ID and filename helpers.

Never trust user-provided filenames (see docs/bestpractices.md #8). All stored
files use generated, collision-resistant names.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def _short() -> str:
    return uuid.uuid4().hex[:8]


def new_id(prefix: str) -> str:
    """Generate an id like ``vid_7f3a9c12``."""
    return f"{prefix}_{_short()}"


def safe_video_filename(prefix: str = "upload") -> str:
    """Generate a safe stored filename like ``upload_20260605_7f3a9c12.mp4``."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{prefix}_{stamp}_{_short()}.mp4"
