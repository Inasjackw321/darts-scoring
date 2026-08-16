"""OpenCV dart-tip detection.

This is the primary scoring path and it is deliberately deterministic: diff the
incoming frame against a reference frame of the clear board, clean up the mask,
keep contours that look like a dart (elongated, sensibly sized), then pick the
tip as the end of each contour's principal axis that points inwards toward the
board centre — darts land pointing at the board, so the inner extreme of the
blob is the tip.

No VLM is involved here. Ollama only ever sees a frame through `/verify`.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Optional, Sequence

import cv2
import numpy as np

from . import config
from .calibration import Calibration


class FrameDecodeError(ValueError):
    """Raised when an uploaded frame is not decodable image data."""


@dataclass
class TipCandidate:
    """A detected dart tip, in image pixels and (optionally) board mm."""

    x_px: float
    y_px: float
    area_px: float
    elongation: float
    x_mm: Optional[float] = None
    y_mm: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "x_px": round(self.x_px, 1),
            "y_px": round(self.y_px, 1),
            "area_px": round(self.area_px, 1),
            "elongation": round(self.elongation, 2),
            "x_mm": None if self.x_mm is None else round(self.x_mm, 2),
            "y_mm": None if self.y_mm is None else round(self.y_mm, 2),
        }


def decode_frame(data: str | bytes) -> np.ndarray:
    """Decode a base64 data URL / base64 string / raw JPEG bytes into BGR."""
    if isinstance(data, str):
        payload = data.split(",", 1)[1] if data.startswith("data:") else data
        try:
            raw = base64.b64decode(payload, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise FrameDecodeError("frame is not valid base64") from exc
    else:
        raw = data

    if not raw:
        raise FrameDecodeError("frame payload was empty")

    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise FrameDecodeError("frame could not be decoded as an image")
    return image


def to_gray(image: np.ndarray) -> np.ndarray:
    """Grayscale + blur. Blurring first keeps sensor noise out of the diff."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    return cv2.GaussianBlur(gray, (5, 5), 0)


def diff_mask(reference_gray: np.ndarray, frame_gray: np.ndarray) -> np.ndarray:
    """Binary mask of what changed between the clear board and this frame."""
    if reference_gray.shape != frame_gray.shape:
        frame_gray = cv2.resize(frame_gray, (reference_gray.shape[1], reference_gray.shape[0]))
    delta = cv2.absdiff(reference_gray, frame_gray)
    _, mask = cv2.threshold(delta, config.DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    return mask


def changed_fraction(mask: np.ndarray) -> float:
    """Fraction of the frame that differs from the reference.

    A very large value means the whole scene changed — usually the camera was
    bumped or someone walked in front of it, not that eight darts landed at once.
    """
    if mask.size == 0:
        return 0.0
    return float(np.count_nonzero(mask)) / float(mask.size)


def _principal_axis(contour: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Return (centre, unit direction, elongation) for a contour via PCA."""
    pts = contour.reshape(-1, 2).astype(np.float64)
    centre = pts.mean(axis=0)
    centred = pts - centre
    # SVD is the numerically stable way to get the principal axis of a blob.
    _, singular, vt = np.linalg.svd(centred, full_matrices=False)
    direction = vt[0]
    minor = singular[1] if len(singular) > 1 else 0.0
    elongation = float(singular[0] / minor) if minor > 1e-6 else float("inf")
    return centre, direction, elongation


def _tip_from_contour(contour: np.ndarray, board_centre_px: np.ndarray) -> tuple[np.ndarray, float]:
    """Pick the contour extreme that points toward the board centre."""
    pts = contour.reshape(-1, 2).astype(np.float64)
    centre, direction, elongation = _principal_axis(contour)
    projections = (pts - centre) @ direction
    ends = (pts[int(np.argmin(projections))], pts[int(np.argmax(projections))])
    # The tip is whichever end sits closer to the centre of the board: a dart
    # in the board points inward, with its flight trailing outward.
    distances = [np.linalg.norm(end - board_centre_px) for end in ends]
    return ends[int(np.argmin(distances))], elongation


def detect_tips(
    reference: np.ndarray,
    frame: np.ndarray,
    calibration: Optional[Calibration] = None,
    max_tips: int = 6,
) -> tuple[list[TipCandidate], np.ndarray]:
    """Find dart tips in `frame` relative to the clear-board `reference`.

    Returns the candidates plus the diff mask (the mask is handed to the debug
    logger so misreads can be inspected after the fact).
    """
    reference_gray = to_gray(reference)
    frame_gray = to_gray(frame)
    mask = diff_mask(reference_gray, frame_gray)

    height, width = mask.shape[:2]
    if calibration is not None:
        board_centre_px = calibration.to_image([[0.0, 0.0]])[0]
    else:
        board_centre_px = np.array([width / 2.0, height / 2.0])

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[TipCandidate] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < config.MIN_CONTOUR_AREA_PX or area > config.MAX_CONTOUR_AREA_PX:
            continue
        if len(contour) < 5:
            continue
        tip, elongation = _tip_from_contour(contour, np.asarray(board_centre_px, dtype=np.float64))
        # Hands, shadows and lighting shifts produce round-ish blobs; a dart in
        # the board is a long thin streak, so elongation is the cheapest filter.
        if elongation < config.MIN_ELONGATION:
            continue
        candidates.append(
            TipCandidate(x_px=float(tip[0]), y_px=float(tip[1]), area_px=area, elongation=elongation)
        )

    # Biggest blobs first — those are the most confident detections.
    candidates.sort(key=lambda c: c.area_px, reverse=True)
    candidates = candidates[:max_tips]

    if calibration is not None and candidates:
        board_pts = calibration.to_board([[c.x_px, c.y_px] for c in candidates])
        for candidate, (x_mm, y_mm) in zip(candidates, board_pts):
            candidate.x_mm = float(x_mm)
            candidate.y_mm = float(y_mm)

    return candidates, mask


def encode_jpeg(image: np.ndarray, quality: int = 85) -> bytes:
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("failed to encode image as JPEG")
    return buffer.tobytes()


def encode_jpeg_base64(image: np.ndarray, quality: int = 85) -> str:
    return base64.b64encode(encode_jpeg(image, quality)).decode("ascii")


def annotate(
    frame: np.ndarray,
    tips: Sequence[TipCandidate],
    outline_px: Optional[Sequence[Sequence[float]]] = None,
) -> np.ndarray:
    """Draw detections (and optionally the calibrated board outline) on a copy."""
    canvas = frame.copy()
    if outline_px:
        pts = np.asarray(outline_px, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(canvas, [pts], isClosed=True, color=(0, 200, 255), thickness=2)
    for tip in tips:
        centre = (int(round(tip.x_px)), int(round(tip.y_px)))
        cv2.circle(canvas, centre, 8, (0, 0, 255), 2)
        cv2.drawMarker(canvas, centre, (0, 0, 255), cv2.MARKER_CROSS, 14, 1)
    return canvas
