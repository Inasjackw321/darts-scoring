"""Dartboard geometry and scoring maths.

Everything in here works in *board space*: millimetres, origin at the centre
of the bull, +x to the right, +y up. A frame only reaches board space after
the homography from `calibration.py` has been applied, so this module is
pure maths with no dependency on OpenCV or on any camera.

Standard steel-tip board dimensions (BDO/WDF spec) are used throughout.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Optional

# --- Radii in millimetres, measured from the centre of the bull ------------
R_INNER_BULL = 6.35  # "double bull" / 50
R_OUTER_BULL = 15.9  # 25
R_TREBLE_INNER = 99.0
R_TREBLE_OUTER = 107.0
R_DOUBLE_INNER = 162.0
R_DOUBLE_OUTER = 170.0  # anything beyond this is off the scoring area

BOARD_RADIUS_MM = R_DOUBLE_OUTER

# Segment numbers in clockwise order starting at 20 (which sits at the top).
SEGMENT_ORDER = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5]
SEGMENT_ARC_DEG = 360.0 / len(SEGMENT_ORDER)  # 18 degrees per number

# Ring identifiers used in the API payloads.
RING_MISS = "miss"
RING_INNER_BULL = "inner_bull"
RING_OUTER_BULL = "outer_bull"
RING_INNER_SINGLE = "inner_single"  # between outer bull and the treble ring
RING_TREBLE = "treble"
RING_OUTER_SINGLE = "outer_single"  # between the treble and double rings
RING_DOUBLE = "double"


@dataclass
class Score:
    """The result of scoring a single board-space point."""

    segment: int  # 1-20, or 25 for the bull, or 0 for a miss
    ring: str
    multiplier: int
    points: int
    # Board-space position, kept so the UI can draw the dart on its diagram.
    x_mm: float = 0.0
    y_mm: float = 0.0
    radius_mm: float = 0.0
    angle_deg: float = 0.0
    # How close (in mm) the point sits to the nearest ring/segment wire. Small
    # values mean "this could plausibly have been the neighbouring score", which
    # is what triggers the optional Ollama sanity check.
    boundary_margin_mm: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def label(self) -> str:
        """Human-readable label, e.g. 'T20', 'D16', '5', 'BULL', 'MISS'."""
        if self.segment == 0:
            return "MISS"
        if self.segment == 25:
            return "BULL" if self.multiplier == 2 else "25"
        prefix = {1: "", 2: "D", 3: "T"}[self.multiplier]
        return f"{prefix}{self.segment}"


def segment_for_angle(angle_deg: float) -> int:
    """Return the segment number whose wedge contains `angle_deg`.

    Angles are measured the usual mathematical way: 0 deg points at +x (the 6),
    90 deg points at +y (the 20), increasing anticlockwise. The numbers run
    clockwise from 20, so index = (90 - angle) / 18 rounded to nearest.
    """
    index = int(round((90.0 - angle_deg) / SEGMENT_ARC_DEG)) % len(SEGMENT_ORDER)
    return SEGMENT_ORDER[index]


def angle_for_segment(segment: int) -> float:
    """Centre angle (degrees) of a segment. Inverse of `segment_for_angle`."""
    index = SEGMENT_ORDER.index(segment)
    return (90.0 - index * SEGMENT_ARC_DEG) % 360.0


def _angular_margin_mm(angle_deg: float, radius_mm: float) -> float:
    """Distance in mm from the point to the nearest segment wire."""
    # Segment centres sit at multiples of 18 deg from the 20; the wires sit
    # halfway between them, so the nearest wire is always 9 deg away from the
    # offset, folded into a single wedge.
    offset = (90.0 - angle_deg) % SEGMENT_ARC_DEG
    deg_to_wire = abs(offset - SEGMENT_ARC_DEG / 2.0)
    return math.radians(deg_to_wire) * radius_mm


def _radial_margin_mm(radius_mm: float) -> float:
    """Distance in mm from the point to the nearest ring boundary."""
    boundaries = (
        R_INNER_BULL,
        R_OUTER_BULL,
        R_TREBLE_INNER,
        R_TREBLE_OUTER,
        R_DOUBLE_INNER,
        R_DOUBLE_OUTER,
    )
    return min(abs(radius_mm - b) for b in boundaries)


def score_point(x_mm: float, y_mm: float) -> Score:
    """Score a single point given in board-space millimetres."""
    radius = math.hypot(x_mm, y_mm)
    angle = math.degrees(math.atan2(y_mm, x_mm)) % 360.0

    if radius <= R_INNER_BULL:
        segment, ring, multiplier = 25, RING_INNER_BULL, 2
    elif radius <= R_OUTER_BULL:
        segment, ring, multiplier = 25, RING_OUTER_BULL, 1
    elif radius > R_DOUBLE_OUTER:
        segment, ring, multiplier = 0, RING_MISS, 0
    else:
        segment = segment_for_angle(angle)
        if radius < R_TREBLE_INNER:
            ring, multiplier = RING_INNER_SINGLE, 1
        elif radius <= R_TREBLE_OUTER:
            ring, multiplier = RING_TREBLE, 3
        elif radius < R_DOUBLE_INNER:
            ring, multiplier = RING_OUTER_SINGLE, 1
        else:
            ring, multiplier = RING_DOUBLE, 2

    points = segment * multiplier
    if ring == RING_INNER_BULL:
        points = 50
    elif ring == RING_OUTER_BULL:
        points = 25

    # A miss has no meaningful wire nearby other than the outer double wire.
    if ring == RING_MISS:
        margin = abs(radius - R_DOUBLE_OUTER)
    elif segment == 25:
        margin = _radial_margin_mm(radius)
    else:
        margin = min(_radial_margin_mm(radius), _angular_margin_mm(angle, radius))

    return Score(
        segment=segment,
        ring=ring,
        multiplier=multiplier,
        points=points,
        x_mm=round(x_mm, 2),
        y_mm=round(y_mm, 2),
        radius_mm=round(radius, 2),
        angle_deg=round(angle, 2),
        boundary_margin_mm=round(margin, 2),
    )


def point_for_score(segment: int, ring: str) -> tuple[float, float]:
    """Return a representative board-space point for a segment/ring.

    Used by the tests and by the manual-correction path in the UI, so a
    hand-entered score still gets a sensible position on the board diagram.
    """
    if segment == 25:
        radius = 0.0 if ring == RING_INNER_BULL else (R_OUTER_BULL + R_INNER_BULL) / 2
        return 0.0, radius
    radii = {
        RING_INNER_SINGLE: (R_OUTER_BULL + R_TREBLE_INNER) / 2,
        RING_TREBLE: (R_TREBLE_INNER + R_TREBLE_OUTER) / 2,
        RING_OUTER_SINGLE: (R_TREBLE_OUTER + R_DOUBLE_INNER) / 2,
        RING_DOUBLE: (R_DOUBLE_INNER + R_DOUBLE_OUTER) / 2,
    }
    radius = radii.get(ring, (R_TREBLE_OUTER + R_DOUBLE_INNER) / 2)
    angle = math.radians(angle_for_segment(segment))
    return radius * math.cos(angle), radius * math.sin(angle)


# Reference points used by the calibration UI. These are the outermost points
# of the double ring for the numbers that sit at the four cardinal directions:
# 20 at the top, 6 on the right, 3 at the bottom, 11 on the left. They are the
# easiest points on a real board to click accurately, because each one is where
# a segment's centre wire meets the outer double wire.
DEFAULT_REFERENCE_POINTS = [
    {"name": "20 (top, outer double wire)", "x_mm": 0.0, "y_mm": R_DOUBLE_OUTER},
    {"name": "6 (right, outer double wire)", "x_mm": R_DOUBLE_OUTER, "y_mm": 0.0},
    {"name": "3 (bottom, outer double wire)", "x_mm": 0.0, "y_mm": -R_DOUBLE_OUTER},
    {"name": "11 (left, outer double wire)", "x_mm": -R_DOUBLE_OUTER, "y_mm": 0.0},
]
