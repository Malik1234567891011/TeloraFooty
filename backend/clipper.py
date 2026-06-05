import subprocess
from pathlib import Path


def _run(args: list[str]) -> str:
    res = subprocess.run(args, capture_output=True, text=True)
    if res.returncode != 0:
        tail = res.stderr.strip().splitlines()[-1] if res.stderr.strip() else "ffmpeg failed"
        raise RuntimeError(tail)
    return res.stdout


def probe_duration(video: Path) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "csv=p=0", str(video)])
    return float(out.strip())


def video_codec(video: Path) -> str:
    out = _run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(video)])
    return out.strip()


def extract_thumb(video: Path, timestamp: float, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-ss", str(timestamp), "-i", str(video),
          "-frames:v", "1", "-vf", "scale=320:-2", "-y", str(out)])


def export_clip(video: Path, start: float, end: float, out: Path) -> None:
    """Stream-copy cut: fast, no re-encode."""
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run(["ffmpeg", "-ss", str(start), "-i", str(video),
              "-t", str(end - start), "-c", "copy", "-y", str(out)])
    except RuntimeError:
        out.unlink(missing_ok=True)
        raise


def ensure_h264(video: Path) -> None:
    """Re-encode in place if the codec isn't browser-playable (spec: HEVC handling)."""
    if video_codec(video) == "h264":
        return
    tmp = video.with_suffix(".h264.mp4")
    _run(["ffmpeg", "-i", str(video), "-c:v", "libx264", "-preset", "fast",
          "-c:a", "aac", "-movflags", "+faststart", "-y", str(tmp)])
    tmp.replace(video)
