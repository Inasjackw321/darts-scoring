"""Camera-pixel to board-space calibration via a homography.

The user clicks a handful of known board landmarks in a captured frame; each
click gives us an (image_x, image_y) -> (board_x_mm, board_y_mm) correspondence.
Four points determine a homography exactly; more than four are least-squares
fitted with RANSAC, which is worth doing because clicks on a phone are sloppy.

The matrix is persisted to disk so calibration survives a server restart — it
only needs redoing when the camera physically moves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

import cv2
import numpy as np

from . import config
from .board import BOARD_RADIUS_MM


class CalibrationError(ValueError):
    """Raised when the supplied points cannot produce a usable homography."""


@dataclass
class Calibration:
    """A stored image->board homography plus the points that produced it."""

    matrix: np.ndarray  # 3x3, maps image pixels to board millimetres
    image_points: list[list[float]] = field(default_factory=list)
    board_points: list[list[float]] = field(default_factory=list)
    frame_width: int = 0
    frame_height: int = 0
    rms_error_mm: float = 0.0
    created_at: str = ""

    @property
    def inverse(self) -> np.ndarray:
        """Board millimetres back to image pixels (used for overlays)."""
        return np.linalg.inv(self.matrix)

    def to_board(self, points: Sequence[Sequence[float]]) -> np.ndarray:
        """Transform Nx2 image-pixel points into board millimetres."""
        return _apply(self.matrix, points)

    def to_image(self, points: Sequence[Sequence[float]]) -> np.ndarray:
        """Transform Nx2 board-millimetre points back into image pixels."""
        return _apply(self.inverse, points)

    def to_dict(self) -> dict:
        return {
            "matrix": self.matrix.tolist(),
            "image_points": self.image_points,
            "board_points": self.board_points,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "rms_error_mm": self.rms_error_mm,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Calibration":
        return cls(
            matrix=np.array(raw["matrix"], dtype=np.float64),
            image_points=raw.get("image_points", []),
            board_points=raw.get("board_points", []),
            frame_width=raw.get("frame_width", 0),
            frame_height=raw.get("frame_height", 0),
            rms_error_mm=raw.get("rms_error_mm", 0.0),
            created_at=raw.get("created_at", ""),
        )


def _apply(matrix: np.ndarray, points: Sequence[Sequence[float]]) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 1, 2)
    if pts.size == 0:
        return np.zeros((0, 2), dtype=np.float64)
    return cv2.perspectiveTransform(pts, matrix).reshape(-1, 2)


def compute_calibration(
    image_points: Iterable[Sequence[float]],
    board_points: Iterable[Sequence[float]],
    frame_width: int = 0,
    frame_height: int = 0,
    created_at: str = "",
) -> Calibration:
    """Fit the image->board homography from clicked correspondences."""
    src = np.asarray(list(image_points), dtype=np.float64)
    dst = np.asarray(list(board_points), dtype=np.float64)

    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 2:
        raise CalibrationError("image_points and board_points must both be lists of [x, y] pairs of equal length")
    if len(src) < 4:
        raise CalibrationError(f"need at least 4 reference points, got {len(src)}")

    if len(src) == 4:
        matrix = cv2.getPerspectiveTransform(src.astype(np.float32), dst.astype(np.float32))
        matrix = matrix.astype(np.float64)
    else:
        matrix, _ = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
        if matrix is None:
            raise CalibrationError("could not fit a homography — are the points collinear or mis-ordered?")

    if not np.all(np.isfinite(matrix)) or abs(np.linalg.det(matrix)) < 1e-12:
        raise CalibrationError("degenerate homography — the reference points are probably collinear")

    # Round-trip the clicked points to report how good the fit actually is.
    projected = _apply(matrix, src)
    rms = float(np.sqrt(np.mean(np.sum((projected - dst) ** 2, axis=1))))

    return Calibration(
        matrix=matrix,
        image_points=src.tolist(),
        board_points=dst.tolist(),
        frame_width=int(frame_width),
        frame_height=int(frame_height),
        rms_error_mm=round(rms, 3),
        created_at=created_at,
    )


def save(calibration: Calibration, path: Optional[Path] = None) -> Path:
    path = path or config.CALIBRATION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(calibration.to_dict(), indent=2), encoding="utf-8")
    return path


def load(path: Optional[Path] = None) -> Optional[Calibration]:
    path = path or config.CALIBRATION_PATH
    if not path.exists():
        return None
    try:
        return Calibration.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def clear(path: Optional[Path] = None) -> None:
    path = path or config.CALIBRATION_PATH
    path.unlink(missing_ok=True)


def board_outline_image_points(calibration: Calibration, steps: int = 120) -> list[list[float]]:
    """Pixel coordinates of the outer double wire, for the UI sanity overlay.

    If this circle lands on the real board's outer wire in the phone preview,
    the calibration is good; if it is skewed or offset, it needs redoing.
    """
    angles = np.linspace(0, 2 * np.pi, steps, endpoint=False)
    ring = np.stack(
        [BOARD_RADIUS_MM * np.cos(angles), BOARD_RADIUS_MM * np.sin(angles)], axis=1
    )
    return calibration.to_image(ring).round(2).tolist()
