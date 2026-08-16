"""Server-side video capture.

Reads frames directly from a camera the desktop can see — a phone running a
webcam app on the LAN, a phone bridged as a virtual webcam over USB, or an
ordinary USB camera — and scores them without a browser in the loop.

This is the simpler half of the system to operate: because no browser needs the
camera, nothing here requires HTTPS, a certificate, or a phone with its screen
awake. The web UI becomes a pure scoreboard.

Motion gating lives here rather than in JavaScript, so it works at full frame
resolution instead of on a thumbnail, and the frames never make a base64 round
trip over HTTP.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional, Union

import cv2
import numpy as np

from . import config

# Frames are compared at this size to decide "did anything change" — small
# enough to be free, large enough that a single dart still registers.
MOTION_THUMB = (128, 96)
PIXEL_DELTA = 22


def parse_source(source: str) -> Union[int, str]:
    """A bare number is a local device index; anything else is a URL/path."""
    text = str(source).strip()
    return int(text) if text.isdigit() else text


def motion_fraction(previous: Optional[np.ndarray], current: np.ndarray) -> tuple[float, np.ndarray]:
    """Fraction of the downscaled frame that changed, plus the new thumbnail."""
    thumb = cv2.cvtColor(cv2.resize(current, MOTION_THUMB), cv2.COLOR_BGR2GRAY).astype(np.int16)
    if previous is None:
        return 0.0, thumb
    changed = int(np.count_nonzero(np.abs(thumb - previous) > PIXEL_DELTA))
    return changed / float(thumb.size), thumb


class CaptureWorker:
    """Background thread that watches a video source and scores what it sees."""

    def __init__(
        self,
        source: Union[int, str],
        on_frame: Callable[..., dict],
        client_id: str = "server-capture",
    ) -> None:
        self.source = source
        self.on_frame = on_frame
        self.client_id = client_id

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

        self.connected = False
        self.error: str = ""
        self.frames_read = 0
        self.frames_scored = 0
        self.last_frame_at = 0.0
        self.last_motion = 0.0
        self.started_at = 0.0

    # --- lifecycle --------------------------------------------------------
    def start(self) -> None:
        if self.is_running():
            return
        self._stop.clear()
        self.error = ""
        self.started_at = time.time()
        self._thread = threading.Thread(target=self._run, name="darts-capture", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        self.connected = False

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict:
        with self._lock:
            return {
                "running": self.is_running(),
                "connected": self.connected,
                "source": str(self.source),
                "error": self.error,
                "frames_read": self.frames_read,
                "frames_scored": self.frames_scored,
                "last_frame_age_s": round(time.time() - self.last_frame_at, 1) if self.last_frame_at else None,
                "last_motion_pct": round(self.last_motion * 100, 2),
            }

    # --- the loop ---------------------------------------------------------
    def _open(self) -> Optional[cv2.VideoCapture]:
        capture = cv2.VideoCapture(self.source)
        if not capture.isOpened():
            capture.release()
            return None
        # Keep the buffer short so we score what is on the board *now* rather
        # than working through a backlog of stale frames.
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return capture

    def _run(self) -> None:
        backoff = 1.0
        capture: Optional[cv2.VideoCapture] = None
        previous_thumb: Optional[np.ndarray] = None
        cooldown_until = 0.0
        reference_taken = False

        try:
            while not self._stop.is_set():
                if capture is None:
                    capture = self._open()
                    if capture is None:
                        with self._lock:
                            self.connected = False
                            self.error = f"cannot open video source {self.source!r}"
                        # A phone stream comes and goes; keep trying rather than
                        # dying the moment the app is backgrounded.
                        if self._stop.wait(backoff):
                            break
                        backoff = min(backoff * 2, 15.0)
                        continue
                    with self._lock:
                        self.connected = True
                        self.error = ""
                    backoff = 1.0
                    previous_thumb = None
                    reference_taken = False

                ok, frame = capture.read()
                if not ok or frame is None:
                    capture.release()
                    capture = None
                    with self._lock:
                        self.connected = False
                        self.error = "video source stopped sending frames"
                    continue

                now = time.time()
                with self._lock:
                    self.frames_read += 1
                    self.last_frame_at = now

                fraction, previous_thumb = motion_fraction(previous_thumb, frame)
                with self._lock:
                    self.last_motion = fraction

                if not reference_taken:
                    # First frame of a session is the clear board to diff against.
                    self._score(frame, set_reference=True)
                    reference_taken = True
                    continue

                if now < cooldown_until or fraction < config.CAPTURE_MOTION_FRACTION:
                    if self._stop.wait(config.CAPTURE_IDLE_SLEEP_S):
                        break
                    continue

                # Something moved. Let the dart settle, then score a fresh frame
                # rather than the blurred one containing the throw itself.
                if self._stop.wait(config.CAPTURE_SETTLE_S):
                    break
                ok, settled = capture.read()
                if ok and settled is not None:
                    frame = settled
                    _, previous_thumb = motion_fraction(None, frame)

                result = self._score(frame)
                cooldown_until = time.time() + (
                    config.CAPTURE_COOLDOWN_S if result.get("new_darts") else config.CAPTURE_SETTLE_S
                )
        finally:
            if capture is not None:
                capture.release()
            with self._lock:
                self.connected = False

    def _score(self, frame: np.ndarray, set_reference: bool = False) -> dict:
        try:
            result = self.on_frame(frame, set_reference=set_reference, client_id=self.client_id)
        except Exception as exc:  # never let one bad frame kill the loop
            with self._lock:
                self.error = f"scoring failed: {exc}"
            return {}
        with self._lock:
            self.frames_scored += 1
        return result or {}
