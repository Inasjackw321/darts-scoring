"""Local debug logging of frames, masks and detection results.

Misreads are the thing you actually spend time on with a setup like this, and
they are impossible to diagnose from a score that "looked wrong" ten minutes
ago. Every scoring call optionally drops the frame, the diff mask, an annotated
copy and the JSON result into data/debug/, oldest entries pruned automatically.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from . import config


def _prune(directory: Path, keep: int) -> None:
    entries = sorted(directory.glob("frame_*"), key=lambda p: p.name)
    # Each event writes several files, so count events by their JSON records.
    records = [p for p in entries if p.suffix == ".json"]
    for stale in records[: max(0, len(records) - keep)]:
        stem = stale.stem
        for sibling in directory.glob(f"{stem}*"):
            sibling.unlink(missing_ok=True)


def log_detection(
    frame: Optional[np.ndarray],
    mask: Optional[np.ndarray],
    annotated: Optional[np.ndarray],
    record: dict,
) -> Optional[Path]:
    """Write one detection event to the debug directory. Never raises."""
    if not config.DEBUG_LOGGING:
        return None
    try:
        config.ensure_dirs()
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
        stem = f"frame_{stamp}"
        directory = config.LOG_DIR
        if frame is not None:
            cv2.imwrite(str(directory / f"{stem}_raw.jpg"), frame)
        if mask is not None:
            cv2.imwrite(str(directory / f"{stem}_mask.png"), mask)
        if annotated is not None:
            cv2.imwrite(str(directory / f"{stem}_annotated.jpg"), annotated)
        path = directory / f"{stem}.json"
        path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
        _prune(directory, config.MAX_DEBUG_FRAMES)
        return path
    except (OSError, ValueError):
        # Debug logging must never take the scoring path down with it.
        return None


def log_event(name: str, payload: dict) -> Optional[Path]:
    """Log a non-frame event (calibration, verify calls, resets)."""
    if not config.DEBUG_LOGGING:
        return None
    try:
        config.ensure_dirs()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = config.LOG_DIR / f"event_{stamp}_{name}.json"
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path
    except (OSError, ValueError):
        return None
