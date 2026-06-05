"""Shared pytest fixtures.

Storage is redirected to a temporary directory and seeding is disabled BEFORE
the app is imported, so tests never touch real data or the demo videos. Small
fixture videos are generated on the fly with ffmpeg (nothing binary is
committed).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

# Configure environment before any app module is imported.
_TMP_STORAGE = tempfile.mkdtemp(prefix="telora_test_storage_")
os.environ["STORAGE_DIR"] = _TMP_STORAGE
os.environ["ENABLE_SEED"] = "false"
os.environ["ENABLE_ML_DETECTORS"] = "false"

FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")


def _make_video(path: Path, seconds: float, *, motion: str = "smooth", with_audio: bool = False) -> Path:
    """Generate a small synthetic MP4 via ffmpeg.

    ``motion`` controls how busy the frame is so motion analysis has signal.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if motion == "static":
        vsrc = f"color=c=green:s=320x240:d={seconds}:r=15"
    else:
        vsrc = f"testsrc=size=320x240:rate=15:duration={seconds}"

    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", vsrc]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-pix_fmt", "yuv420p", "-t", str(seconds)]
    if with_audio:
        cmd += ["-shortest"]
    cmd += [str(path)]
    subprocess.run(cmd, capture_output=True, check=True)
    return path


@pytest.fixture(scope="session")
def tmp_media_root() -> Path:
    root = Path(tempfile.mkdtemp(prefix="telora_fixture_videos_"))
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="session")
def sample_5s(tmp_media_root: Path) -> Path:
    if FFMPEG is None:
        pytest.skip("ffmpeg not installed")
    return _make_video(tmp_media_root / "sample_5s.mp4", 5)


@pytest.fixture(scope="session")
def sample_motion(tmp_media_root: Path) -> Path:
    if FFMPEG is None:
        pytest.skip("ffmpeg not installed")
    return _make_video(tmp_media_root / "sample_motion.mp4", 6, motion="busy", with_audio=True)


@pytest.fixture(scope="session")
def sample_static(tmp_media_root: Path) -> Path:
    if FFMPEG is None:
        pytest.skip("ffmpeg not installed")
    return _make_video(tmp_media_root / "sample_static.mp4", 4, motion="static")


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
