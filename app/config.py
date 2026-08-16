"""Runtime configuration. Everything is overridable via environment variables
so the same code runs on the Windows desktop and in CI without edits."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DARTS_DATA_DIR", BASE_DIR / "data"))
LOG_DIR = Path(os.environ.get("DARTS_LOG_DIR", DATA_DIR / "debug"))
CALIBRATION_PATH = DATA_DIR / "calibration.json"

# Ollama (secondary verification only — never on the hot path).
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2-vision")
OLLAMA_TIMEOUT_S = float(os.environ.get("OLLAMA_TIMEOUT_S", "60"))

# Origins allowed to talk to this server. The GitHub Pages origin is added at
# import time; set DARTS_ALLOWED_ORIGINS to a comma-separated list to override.
_DEFAULT_ORIGINS = [
    "https://inasjackw321.github.io",
    "http://localhost:8000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("DARTS_ALLOWED_ORIGINS", ",".join(_DEFAULT_ORIGINS)).split(",")
    if o.strip()
]

# Detection tuning. These are the knobs worth touching first if the pipeline
# is over- or under-triggering on a particular board/lighting setup.
DIFF_THRESHOLD = int(os.environ.get("DARTS_DIFF_THRESHOLD", "28"))
MIN_CONTOUR_AREA_PX = int(os.environ.get("DARTS_MIN_CONTOUR_AREA", "120"))
MAX_CONTOUR_AREA_PX = int(os.environ.get("DARTS_MAX_CONTOUR_AREA", "40000"))
MIN_ELONGATION = float(os.environ.get("DARTS_MIN_ELONGATION", "1.8"))
# Two tips closer than this (in board mm) are treated as the same dart.
DUPLICATE_RADIUS_MM = float(os.environ.get("DARTS_DUPLICATE_RADIUS_MM", "12"))
# A score this close to a wire (mm) is flagged as low confidence.
BOUNDARY_WARN_MM = float(os.environ.get("DARTS_BOUNDARY_WARN_MM", "3"))
# Fraction of pixels that must change before we assume the camera moved rather
# than that darts landed. For scale: three darts change well under 1% of the
# frame, while a bumped camera changes 30%+, so there is a lot of room here.
CAMERA_MOVED_FRACTION = float(os.environ.get("DARTS_CAMERA_MOVED_FRACTION", "0.25"))

# --- Server-side capture --------------------------------------------------
# Where the desktop reads video from. A bare number is a local device index
# ("0" = first USB/virtual webcam); anything else is a URL or file path, e.g.
# an iPhone running IP Camera Lite: http://192.168.1.30:8080/video
VIDEO_SOURCE = os.environ.get("DARTS_VIDEO_SOURCE", "").strip()
CAPTURE_AUTOSTART = os.environ.get("DARTS_CAPTURE_AUTOSTART", "1") not in ("0", "false", "False")
# Fraction of the frame that must change to be worth scoring. One dart is
# roughly 0.2-0.5%; sensor noise sits near zero.
CAPTURE_MOTION_FRACTION = float(os.environ.get("DARTS_CAPTURE_MOTION_FRACTION", "0.0015"))
# Wait this long after motion before grabbing the frame to score, so the dart
# has stopped wobbling and the throwing arm has left the shot.
CAPTURE_SETTLE_S = float(os.environ.get("DARTS_CAPTURE_SETTLE_S", "0.45"))
# After a dart is scored, ignore motion for this long.
CAPTURE_COOLDOWN_S = float(os.environ.get("DARTS_CAPTURE_COOLDOWN_S", "1.5"))
# Polling pause when nothing is happening, to keep the loop off a busy spin.
CAPTURE_IDLE_SLEEP_S = float(os.environ.get("DARTS_CAPTURE_IDLE_SLEEP_S", "0.05"))

DEBUG_LOGGING = os.environ.get("DARTS_DEBUG_LOG", "1") not in ("0", "false", "False")
MAX_DEBUG_FRAMES = int(os.environ.get("DARTS_MAX_DEBUG_FRAMES", "300"))


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DEBUG_LOGGING:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
