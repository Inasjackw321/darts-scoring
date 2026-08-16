"""Synthetic board and dart images, so the vision pipeline can be tested
without a camera, a real board, or a person to throw darts at it."""

from __future__ import annotations

import math

import cv2
import numpy as np

from app import board
from app.calibration import compute_calibration

WIDTH, HEIGHT = 640, 480
CENTRE = (WIDTH // 2, HEIGHT // 2)
PIXELS_PER_MM = 1.2  # camera scale for the synthetic rig


def board_to_pixel(x_mm: float, y_mm: float) -> tuple[float, float]:
    """Synthetic camera projection: scale, flip y (image y grows downward)."""
    return CENTRE[0] + x_mm * PIXELS_PER_MM, CENTRE[1] - y_mm * PIXELS_PER_MM


def calibration():
    """The calibration a user would end up with after clicking the four
    reference points on a frame from this synthetic camera."""
    image_points = [
        list(board_to_pixel(p["x_mm"], p["y_mm"])) for p in board.DEFAULT_REFERENCE_POINTS
    ]
    board_points = [[p["x_mm"], p["y_mm"]] for p in board.DEFAULT_REFERENCE_POINTS]
    return compute_calibration(image_points, board_points, WIDTH, HEIGHT)


def clear_board(seed: int = 7) -> np.ndarray:
    """A dart-free board frame, with a little sensor noise for realism."""
    rng = np.random.default_rng(seed)
    image = np.full((HEIGHT, WIDTH, 3), 30, np.uint8)
    radius = int(board.R_DOUBLE_OUTER * PIXELS_PER_MM)
    cv2.circle(image, CENTRE, radius, (35, 35, 35), -1)
    for index, number in enumerate(board.SEGMENT_ORDER):
        centre_deg = 90 - index * board.SEGMENT_ARC_DEG
        colour = (240, 235, 210) if index % 2 else (18, 18, 18)
        cv2.ellipse(
            image, CENTRE, (radius, radius), 0,
            -(centre_deg + 9), -(centre_deg - 9), colour, -1,
        )
        void = number
    cv2.circle(image, CENTRE, int(board.R_OUTER_BULL * PIXELS_PER_MM), (40, 120, 60), -1)
    noise = rng.normal(0, 2.0, image.shape)
    return np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def add_dart(image: np.ndarray, x_mm: float, y_mm: float, length_px: int = 70) -> np.ndarray:
    """Draw a dart whose tip sits at the given board-space point.

    The shaft trails outward from the centre, matching a real dart's geometry —
    which is exactly the cue `detection` uses to decide which end is the tip.
    """
    frame = image.copy()
    tip = board_to_pixel(x_mm, y_mm)
    angle = math.atan2(y_mm, x_mm) if (x_mm or y_mm) else math.pi / 2
    tail = (
        tip[0] + length_px * math.cos(angle),
        tip[1] - length_px * math.sin(angle),
    )
    cv2.line(frame, (int(tip[0]), int(tip[1])), (int(tail[0]), int(tail[1])), (200, 60, 200), 5)
    cv2.circle(frame, (int(tip[0]), int(tip[1])), 3, (220, 80, 220), -1)
    return frame


def encode(image: np.ndarray) -> str:
    """Base64 data URL, as the phone would send it."""
    import base64

    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(buffer.tobytes()).decode("ascii")
