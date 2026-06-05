"""Handle saving uploaded videos to local storage.

Generates safe filenames, validates type/size, extracts metadata, and records
a Video in the store. Never trusts the original filename.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.config import settings
from app.core.errors import InvalidVideoError
from app.core.ids import new_id, safe_video_filename
from app.core.logging import get_logger
from app.models import Video
from app.services.store import store
from app.services.video_metadata_service import get_video_metadata

logger = get_logger(__name__)

ALLOWED_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "application/octet-stream",  # some clients send this for mp4
}
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}


@dataclass
class StoredUpload:
    video: Video
    public_url: str


def _validate_upload(file: UploadFile) -> None:
    if file is None or not file.filename:
        raise InvalidVideoError("No file was uploaded.", code="NO_FILE")

    ext = Path(file.filename).suffix.lower()
    content_type = (file.content_type or "").lower()
    if ext not in ALLOWED_EXTENSIONS and content_type not in ALLOWED_CONTENT_TYPES:
        raise InvalidVideoError(
            f"Unsupported file type '{file.filename}'. Expected an MP4 video.",
            code="INVALID_FILE_TYPE",
        )


def save_upload(file: UploadFile, video_type: str = "demo_clip", prefix: str = "upload") -> StoredUpload:
    """Persist an UploadFile to storage and return a Video record.

    ``video_type`` is one of ``full_game`` | ``demo_clip``.
    """
    _validate_upload(file)
    if video_type not in {"full_game", "demo_clip"}:
        raise InvalidVideoError(
            "video_type must be 'full_game' or 'demo_clip'.", code="INVALID_VIDEO_TYPE"
        )

    settings.ensure_dirs()
    stored_filename = safe_video_filename(prefix=prefix)
    dest = settings.uploads_dir / stored_filename

    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    written = 0
    file.file.seek(0)
    with dest.open("wb") as out:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                out.close()
                dest.unlink(missing_ok=True)
                raise InvalidVideoError(
                    f"File exceeds maximum upload size of {settings.max_upload_size_mb} MB.",
                    code="FILE_TOO_LARGE",
                )
            out.write(chunk)

    if written == 0:
        dest.unlink(missing_ok=True)
        raise InvalidVideoError("Uploaded file is empty.", code="EMPTY_FILE")

    # Validate it is a real, readable video by extracting metadata.
    try:
        meta = get_video_metadata(dest)
    except InvalidVideoError:
        dest.unlink(missing_ok=True)
        raise

    video = Video(
        id=new_id("vid"),
        original_filename=Path(file.filename).name,
        stored_filename=stored_filename,
        stored_path=str(dest),
        video_type=video_type,
        duration_seconds=meta.duration_seconds,
        fps=meta.fps,
        width=meta.width,
        height=meta.height,
    )
    store.save_video(video)
    logger.info(
        "Video uploaded: %s (%s, %.1fs, %dx%d)",
        video.id,
        video.video_type,
        video.duration_seconds,
        video.width,
        video.height,
    )
    return StoredUpload(video=video, public_url=public_url_for_upload(stored_filename))


def save_path_as_upload(src_path: str | Path, video_type: str = "full_game", prefix: str = "upload") -> StoredUpload:
    """Copy an existing local file into uploads (used for seeding)."""
    src = Path(src_path)
    if not src.exists():
        raise InvalidVideoError(f"Source file not found: {src}", code="VIDEO_NOT_FOUND")

    settings.ensure_dirs()
    stored_filename = safe_video_filename(prefix=prefix)
    dest = settings.uploads_dir / stored_filename
    shutil.copy2(src, dest)

    meta = get_video_metadata(dest)
    video = Video(
        id=new_id("vid"),
        original_filename=src.name,
        stored_filename=stored_filename,
        stored_path=str(dest),
        video_type=video_type,
        duration_seconds=meta.duration_seconds,
        fps=meta.fps,
        width=meta.width,
        height=meta.height,
    )
    store.save_video(video)
    return StoredUpload(video=video, public_url=public_url_for_upload(stored_filename))


def public_url_for_upload(stored_filename: str) -> str:
    return f"/media/uploads/{stored_filename}"
