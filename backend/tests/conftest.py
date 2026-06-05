import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # import backend modules

FIXTURE = Path(__file__).parent / "fixtures" / "sample.mp4"


@pytest.fixture(scope="session")
def sample_video() -> Path:
    """10-second H.264 test video, generated once per machine."""
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    if not FIXTURE.exists():
        subprocess.run(
            ["ffmpeg", "-f", "lavfi", "-i", "testsrc=duration=10:size=320x240:rate=24",
             "-pix_fmt", "yuv420p", "-y", str(FIXTURE)],
            check=True, capture_output=True,
        )
    return FIXTURE


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Point the app's data root at a temp dir."""
    monkeypatch.setenv("TELORA_DATA_DIR", str(tmp_path))
    return tmp_path
