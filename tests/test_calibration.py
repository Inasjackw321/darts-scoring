import numpy as np
import pytest

from app import board
from app.calibration import CalibrationError, compute_calibration, load, save


# A synthetic camera: the board seen slightly off-axis, so the transform under
# test is a genuine perspective warp rather than a plain scale.
IMAGE_POINTS = [[320, 90], [560, 250], [330, 420], [95, 245]]
BOARD_POINTS = [[p["x_mm"], p["y_mm"]] for p in board.DEFAULT_REFERENCE_POINTS]


def test_four_points_map_exactly():
    calibration = compute_calibration(IMAGE_POINTS, BOARD_POINTS)
    mapped = calibration.to_board(IMAGE_POINTS)
    np.testing.assert_allclose(mapped, np.array(BOARD_POINTS), atol=1e-6)
    assert calibration.rms_error_mm < 1e-6


def test_round_trip_image_to_board_to_image():
    calibration = compute_calibration(IMAGE_POINTS, BOARD_POINTS)
    probe = [[300.0, 210.0], [400.0, 260.0]]
    back = calibration.to_image(calibration.to_board(probe))
    np.testing.assert_allclose(back, np.array(probe), atol=1e-6)


def test_extra_points_are_least_squares_fitted():
    """A fifth, deliberately noisy, click should not break the fit."""
    points = IMAGE_POINTS + [[327, 253]]
    targets = BOARD_POINTS + [[0.0, 0.0]]
    calibration = compute_calibration(points, targets)
    assert calibration.rms_error_mm < 25


def test_collinear_points_are_rejected():
    collinear = [[0, 0], [10, 10], [20, 20], [30, 30]]
    with pytest.raises(CalibrationError):
        compute_calibration(collinear, BOARD_POINTS)


def test_too_few_points_rejected():
    with pytest.raises(CalibrationError):
        compute_calibration(IMAGE_POINTS[:3], BOARD_POINTS[:3])


def test_mismatched_lengths_rejected():
    with pytest.raises(CalibrationError):
        compute_calibration(IMAGE_POINTS, BOARD_POINTS[:3])


def test_save_and_load_round_trip(tmp_path):
    calibration = compute_calibration(IMAGE_POINTS, BOARD_POINTS, frame_width=640, frame_height=480)
    path = tmp_path / "calibration.json"
    save(calibration, path)
    restored = load(path)
    assert restored is not None
    np.testing.assert_allclose(restored.matrix, calibration.matrix)
    assert restored.frame_width == 640


def test_load_missing_or_corrupt_file_returns_none(tmp_path):
    assert load(tmp_path / "nope.json") is None
    corrupt = tmp_path / "bad.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert load(corrupt) is None


def test_board_centre_maps_into_the_middle_of_the_clicked_quad():
    calibration = compute_calibration(IMAGE_POINTS, BOARD_POINTS)
    centre_px = calibration.to_image([[0.0, 0.0]])[0]
    xs = [p[0] for p in IMAGE_POINTS]
    ys = [p[1] for p in IMAGE_POINTS]
    assert min(xs) < centre_px[0] < max(xs)
    assert min(ys) < centre_px[1] < max(ys)
