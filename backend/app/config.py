"""Application configuration.

Loaded from environment variables (and an optional .env file). All paths are
resolved to absolute paths so the app behaves the same regardless of the
working directory it is launched from.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ directory (two levels up from this file: app/config.py -> app -> backend)
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime settings for the TeloraFooty backend."""

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "TeloraFooty backend"

    # Storage
    storage_dir: str = "./storage"
    max_upload_size_mb: int = 2000

    # Detection / ML
    enable_ml_detectors: bool = True
    ball_model_path: str = ""
    player_model_path: str = "yolov8n.pt"

    # Demo clip sampling
    demo_sample_fps: float = 6.0
    demo_analysis_width: int = 640

    # Highlight clip window around a detected shot/goal: seconds of build-up
    # before the moment and aftermath after it.
    clip_pre_seconds: float = 8.0
    clip_post_seconds: float = 4.0
    clip_post_seconds_goal: float = 6.0

    # Auto-analysis dispatch: videos at or below this duration go through the
    # whole-clip detector; longer ones through the full-match funnel.
    short_clip_max_seconds: float = 180.0

    # SMTP clip emailing (ported from the MVP backend). For Gmail use an app
    # password from https://myaccount.google.com/apppasswords.
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_from: str = ""

    # Player-based attack detection (YOLO)
    player_analysis_fps: float = 2.5
    player_detect_imgsz: int = 1280
    player_detect_conf: float = 0.25

    # Video-language-model judge (Gemini) — the primary semantic detector.
    enable_vlm: bool = True
    gemini_api_key: str = ""
    vlm_model: str = "gemini-2.5-flash"
    # Stronger model used in the precision-verification stage of the full-match
    # funnel (Tier-1 billing; cost acceptable for far fewer, higher-stakes calls).
    vlm_verify_model: str = "gemini-2.5-pro"
    # Context window (seconds) sent to the verifier around each candidate moment.
    verify_window_pre: float = 14.0
    verify_window_post: float = 12.0
    # A candidate survives verification only at/above this confidence.
    verify_threshold: float = 0.6

    # Aftermath/play-restart verification (approach B): ask about the CONSEQUENCE
    # of a candidate (keeper possession, goal kick, corner, goal+kickoff) rather
    # than trying to see the ball. Window leans heavily on the seconds AFTER.
    vlm_aftermath_model: str = "gemini-2.5-flash"
    aftermath_pre: float = 6.0
    aftermath_post: float = 18.0
    aftermath_threshold: float = 0.6
    vlm_window_size: float = 8.0
    vlm_stride: float = 6.0
    vlm_max_windows: int = 12
    # How many windows to judge concurrently (Gemini calls run in threads).
    vlm_concurrency: int = 3

    # Whole-clip two-stage detector (EXPERIMENT 2-WC — the primary short-clip
    # path; see docs/callibrations+results.md and services/wholeclip_detector.py).
    enable_wholeclip_detector: bool = True
    wc_votes: int = 5                # stage-1 localization votes per clip
    wc_max_candidates: int = 3       # stage-1 candidate budget (frozen protocol)
    wc_verify_votes: int = 3         # stage-2 votes per candidate window
    wc_verify_fps: float = 5.0       # stage-2 frame sampling (denser than 1fps default)
    wc_zoom_pre: float = 7.0         # stage-2 window: seconds before candidate
    wc_zoom_post: float = 12.0       # stage-2 window: seconds after candidate
    wc_min_conf: float = 0.5         # verified attempts below this are noise
    wc_seq_gap: float = 8.0          # attempts within this gap = one sequence

    # Decision thresholds. Calibrated against verified ground truth
    # (see docs/callibrations+results.md). Each clip has exactly one real shot,
    # so precision matters as much as recall.
    shot_threshold: float = 0.50
    goal_threshold: float = 0.65

    # Consensus clustering (iter 4): a real shot lights up >= this many adjacent
    # overlapping windows; isolated single fires are treated as noise unless they
    # are extremely confident.
    vlm_min_cluster: int = 2
    vlm_lone_fire_conf: float = 0.97
    # Max gap (s) between consecutive fires still considered the same event, so a
    # single noisy "none" window in the middle doesn't split a real cluster.
    vlm_cluster_gap: float = 7.0

    debug_mode: bool = True

    # Seed demo games on startup (disabled in tests for isolation/speed).
    enable_seed: bool = True

    @property
    def storage_path(self) -> Path:
        """Absolute path to the storage directory."""
        p = Path(self.storage_dir)
        if not p.is_absolute():
            p = (BACKEND_DIR / p).resolve()
        return p

    @property
    def uploads_dir(self) -> Path:
        return self.storage_path / "uploads"

    @property
    def clips_dir(self) -> Path:
        return self.storage_path / "clips"

    @property
    def processed_dir(self) -> Path:
        return self.storage_path / "processed"

    @property
    def thumbnails_dir(self) -> Path:
        return self.storage_path / "thumbnails"

    @property
    def annotations_dir(self) -> Path:
        return self.storage_path / "annotations"

    @property
    def data_dir(self) -> Path:
        return BACKEND_DIR / "app" / "data"

    @property
    def resolved_player_model_path(self) -> str:
        """Absolute path to the player model, resolved against backend/ if relative."""
        if not self.player_model_path:
            return ""
        p = Path(self.player_model_path)
        if not p.is_absolute():
            candidate = (BACKEND_DIR / p).resolve()
            if candidate.exists():
                return str(candidate)
        return self.player_model_path

    def ensure_dirs(self) -> None:
        """Create all storage folders if they do not yet exist."""
        for d in (
            self.uploads_dir,
            self.clips_dir,
            self.processed_dir,
            self.thumbnails_dir,
            self.annotations_dir,
            self.data_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


settings = get_settings()
