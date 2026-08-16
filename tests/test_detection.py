import math

import numpy as np
import pytest

from app import board, detection
from tests import synthetic


@pytest.fixture(scope="module")
def rig():
    return synthetic.clear_board(), synthetic.calibration()


def test_no_darts_means_no_detections(rig):
    reference, calibration = rig
    # A second capture of the same scene: only noise differs.
    frame = synthetic.clear_board(seed=11)
    tips, mask = detection.detect_tips(reference, frame, calibration)
    assert tips == []
    assert detection.changed_fraction(mask) < 0.02


@pytest.mark.parametrize(
    "segment,ring",
    [(20, board.RING_TREBLE), (20, board.RING_OUTER_SINGLE), (19, board.RING_DOUBLE), (6, board.RING_INNER_SINGLE)],
)
def test_single_dart_is_found_and_scored(rig, segment, ring):
    reference, calibration = rig
    x_mm, y_mm = board.point_for_score(segment, ring)
    frame = synthetic.add_dart(reference, x_mm, y_mm)

    tips, _ = detection.detect_tips(reference, frame, calibration)
    assert len(tips) == 1

    tip = tips[0]
    error = math.hypot(tip.x_mm - x_mm, tip.y_mm - y_mm)
    assert error < 6, f"tip landed {error:.1f}mm from where the dart was drawn"

    score = board.score_point(tip.x_mm, tip.y_mm)
    assert score.segment == segment
    assert score.ring == ring


def test_tip_is_the_inner_end_of_the_dart(rig):
    """The detected point must be the tip, not the flight.

    Get this backwards and every dart scores roughly one ring too far out.
    """
    reference, calibration = rig
    x_mm, y_mm = board.point_for_score(20, board.RING_TREBLE)
    frame = synthetic.add_dart(reference, x_mm, y_mm, length_px=90)
    tips, _ = detection.detect_tips(reference, frame, calibration)
    assert len(tips) == 1
    tip_radius = math.hypot(tips[0].x_mm, tips[0].y_mm)
    assert tip_radius < math.hypot(x_mm, y_mm) + 6


def test_three_darts_are_all_found(rig):
    reference, calibration = rig
    targets = [
        board.point_for_score(20, board.RING_TREBLE),
        board.point_for_score(5, board.RING_OUTER_SINGLE),
        board.point_for_score(12, board.RING_DOUBLE),
    ]
    frame = reference
    for x_mm, y_mm in targets:
        frame = synthetic.add_dart(frame, x_mm, y_mm)

    tips, _ = detection.detect_tips(reference, frame, calibration)
    assert len(tips) == 3
    for x_mm, y_mm in targets:
        assert any(math.hypot(t.x_mm - x_mm, t.y_mm - y_mm) < 8 for t in tips)


def test_round_blobs_are_rejected(rig):
    """A shadow or a hand is round-ish; only elongated blobs pass the filter."""
    import cv2

    reference, calibration = rig
    frame = reference.copy()
    centre = synthetic.board_to_pixel(*board.point_for_score(14, board.RING_OUTER_SINGLE))
    cv2.circle(frame, (int(centre[0]), int(centre[1])), 22, (120, 120, 120), -1)
    tips, _ = detection.detect_tips(reference, frame, calibration)
    assert tips == []


def test_camera_move_produces_a_large_changed_fraction(rig):
    reference, _ = rig
    shifted = np.roll(reference, 60, axis=1)
    mask = detection.diff_mask(detection.to_gray(reference), detection.to_gray(shifted))
    assert detection.changed_fraction(mask) > 0.05


def test_decode_frame_accepts_data_urls_and_rejects_junk(rig):
    reference, _ = rig
    decoded = detection.decode_frame(synthetic.encode(reference))
    assert decoded.shape == reference.shape

    with pytest.raises(detection.FrameDecodeError):
        detection.decode_frame("")
    with pytest.raises(detection.FrameDecodeError):
        detection.decode_frame("data:image/jpeg;base64,bm90YW5pbWFnZQ==")
