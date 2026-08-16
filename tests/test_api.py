"""End-to-end API tests: calibrate, capture a reference, throw darts, score.

This is the whole round trip the phone performs, minus the camera and Ollama.
"""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import board, config, detection, main
from tests import synthetic


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "debug")
    monkeypatch.setattr(config, "CALIBRATION_PATH", tmp_path / "calibration.json")
    monkeypatch.setattr(config, "DEBUG_LOGGING", False)
    # Ollama is not running in CI; /status must not hang or fail because of it.
    monkeypatch.setattr(main.ollama_client, "is_available", lambda *a, **k: False)
    main.state.__init__()
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def calibrated(client):
    reference = synthetic.clear_board()
    image_points = [
        list(synthetic.board_to_pixel(p["x_mm"], p["y_mm"])) for p in board.DEFAULT_REFERENCE_POINTS
    ]
    response = client.post("/calibrate", json={
        "image_points": image_points,
        "frame_width": synthetic.WIDTH,
        "frame_height": synthetic.HEIGHT,
        "image": synthetic.encode(reference),
    })
    assert response.status_code == 200, response.text
    return client, reference


def test_status_is_reachable_before_anything_is_set_up(client):
    body = client.get("/status").json()
    assert body["ok"] is True
    assert body["calibrated"] is False
    assert body["game"]["current_player"] == "Player 1"


def test_calibration_persists_and_reports_its_fit(calibrated):
    client, _ = calibrated
    body = client.get("/calibration").json()
    assert body["calibrated"] is True
    assert body["rms_error_mm"] < 0.01
    assert len(body["board_outline_px"]) == 120


def test_calibration_rejects_the_wrong_number_of_points(client):
    response = client.post("/calibrate", json={"image_points": [[1, 1], [2, 2], [3, 3]]})
    assert response.status_code == 400


def test_scoring_without_calibration_is_refused(client):
    frame = synthetic.encode(synthetic.clear_board())
    # First frame is swallowed as the reference; the second one tries to score.
    client.post("/frame", json={"image": frame})
    response = client.post("/frame", json={"image": frame})
    assert response.status_code == 409
    assert "calibrat" in response.json()["detail"]


def test_full_turn_scores_three_darts(calibrated):
    client, reference = calibrated
    throws = [
        (20, board.RING_TREBLE, "T20", 60),
        (19, board.RING_OUTER_SINGLE, "19", 19),
        (18, board.RING_DOUBLE, "D18", 36),
    ]
    frame = reference
    expected_total = 0
    for segment, ring, label, points in throws:
        x_mm, y_mm = board.point_for_score(segment, ring)
        frame = synthetic.add_dart(frame, x_mm, y_mm)
        body = client.post("/frame", json={"image": synthetic.encode(frame)}).json()
        assert body["status"] == "ok"
        # Only the newly-arrived dart is reported; the ones already in the
        # board are recognised as duplicates rather than counted again.
        assert [d["label"] for d in body["new_darts"]] == [label]
        expected_total += points
        assert body["game"]["turn_total"] == expected_total

    game = client.get("/game").json()
    assert [d["label"] for d in game["current_turn"]] == ["T20", "19", "D18"]
    assert game["turn_complete"] is True
    assert game["players"][0]["score"] == 115


def test_an_unchanged_frame_scores_nothing(calibrated):
    client, reference = calibrated
    body = client.post("/frame", json={"image": synthetic.encode(reference)}).json()
    assert body["new_darts"] == []
    assert body["game"]["turn_total"] == 0


def test_camera_movement_is_flagged_instead_of_scored(calibrated):
    client, reference = calibrated
    shifted = np.roll(reference, 200, axis=1)
    body = client.post("/frame", json={"image": synthetic.encode(shifted)}).json()
    assert body["status"] == "scene_changed"
    assert body["new_darts"] == []
    assert body["needs_recalibration"] is True
    assert client.get("/status").json()["needs_recalibration"] is True


def test_next_turn_banks_the_turn_and_drops_the_reference(calibrated):
    client, reference = calibrated
    x_mm, y_mm = board.point_for_score(20, board.RING_TREBLE)
    frame = synthetic.add_dart(reference, x_mm, y_mm)
    client.post("/frame", json={"image": synthetic.encode(frame)})

    body = client.post("/turn/next", json={}).json()
    assert body["game"]["current_turn"] == []
    assert body["game"]["turn_number"] == 2
    assert body["game"]["players"][0]["turns"][0][0]["label"] == "T20"
    # No reference means the next frame becomes one — darts get pulled out
    # between turns, so the old reference is stale.
    assert client.get("/status").json()["has_reference_frame"] is False


def test_manual_dart_undo_and_edit(calibrated):
    client, _ = calibrated
    added = client.post("/dart", json={"segment": 20, "ring": "treble"}).json()
    assert added["dart"]["label"] == "T20"
    assert added["dart"]["source"] == "manual"

    dart_id = added["dart"]["id"]
    edited = client.patch("/dart", json={"dart_id": dart_id, "segment": 5, "ring": "double"}).json()
    assert edited["dart"]["label"] == "D5"
    assert edited["game"]["turn_total"] == 10

    undone = client.post("/dart/undo").json()
    assert undone["removed"]["label"] == "D5"
    assert undone["game"]["current_turn"] == []

    assert client.post("/dart/undo").status_code == 409


def test_editing_an_unknown_dart_is_a_404(calibrated):
    client, _ = calibrated
    response = client.patch("/dart", json={"dart_id": "missing", "segment": 20, "ring": "treble"})
    assert response.status_code == 404


def test_manual_dart_needs_a_segment_or_coordinates(calibrated):
    client, _ = calibrated
    assert client.post("/dart", json={}).status_code == 400


def test_reset_clears_the_game_and_switches_mode(calibrated):
    client, _ = calibrated
    client.post("/dart", json={"segment": 20, "ring": "treble"})
    body = client.post("/reset", json={"mode": "x01", "players": ["Jack", "Sam"], "start_score": 501}).json()
    assert body["game"]["players"][0]["score"] == 501
    assert body["game"]["current_player"] == "Jack"
    assert body["game"]["current_turn"] == []
    assert client.get("/status").json()["has_reference_frame"] is False


def test_reset_rejects_an_unknown_mode(calibrated):
    client, _ = calibrated
    assert client.post("/reset", json={"mode": "cricket"}).status_code == 400


def test_bad_frame_payload_is_a_400(calibrated):
    client, _ = calibrated
    assert client.post("/frame", json={"image": "data:image/jpeg;base64,bm90YW5pbWFnZQ=="}).status_code == 400


def test_verify_reports_disagreement_without_changing_the_score(calibrated, monkeypatch):
    client, reference = calibrated
    x_mm, y_mm = board.point_for_score(20, board.RING_TREBLE)
    frame = synthetic.add_dart(reference, x_mm, y_mm)
    client.post("/frame", json={"image": synthetic.encode(frame)})

    from app.ollama_client import VerifyResult

    monkeypatch.setattr(
        main.ollama_client,
        "verify_frame",
        lambda *a, **k: VerifyResult(available=True, dart_count=2, model="fake-vlm", latency_ms=12),
    )
    body = client.post("/verify", json={"image": synthetic.encode(frame)}).json()
    assert body["expected_darts"] == 1
    assert body["agrees"] is False
    assert any("2 dart" in w for w in body["warnings"])
    # Advisory only: the OpenCV result stands.
    assert client.get("/game").json()["turn_total"] == 60


def test_verify_handles_ollama_being_down(calibrated, monkeypatch):
    client, reference = calibrated
    from app.ollama_client import VerifyResult

    monkeypatch.setattr(
        main.ollama_client,
        "verify_frame",
        lambda *a, **k: VerifyResult(available=False, model="fake-vlm", error="connection refused"),
    )
    body = client.post("/verify", json={"image": synthetic.encode(reference)}).json()
    assert body["verify"]["available"] is False
    assert body["warnings"] == []


def test_board_geometry_endpoint_matches_the_scoring_module(calibrated):
    client, _ = calibrated
    body = client.get("/board").json()
    assert body["segment_order"] == board.SEGMENT_ORDER
    assert body["radii_mm"]["double_outer"] == board.R_DOUBLE_OUTER


def test_preview_is_404_until_a_camera_sends_a_frame(client):
    assert client.get("/preview.jpg").status_code == 404


def test_preview_returns_the_latest_annotated_frame(calibrated):
    client, reference = calibrated
    x_mm, y_mm = board.point_for_score(20, board.RING_TREBLE)
    frame = synthetic.add_dart(reference, x_mm, y_mm)
    client.post("/frame", json={"image": synthetic.encode(frame), "client_id": "phone-1"})

    response = client.get("/preview.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert "no-store" in response.headers["cache-control"]

    # It must be a real, decodable image — this is what other screens display.
    decoded = detection.decode_frame(response.content)
    assert decoded.shape[1] <= main.PREVIEW_MAX_WIDTH


def test_the_first_device_to_send_a_frame_becomes_the_camera(calibrated):
    client, reference = calibrated
    client.post("/frame", json={"image": synthetic.encode(reference), "client_id": "phone-1"})
    camera = client.get("/status").json()["camera"]
    assert camera["active"] is True
    assert camera["client_id"] == "phone-1"


def test_a_second_device_does_not_steal_an_active_camera(calibrated):
    client, reference = calibrated
    client.post("/frame", json={"image": synthetic.encode(reference), "client_id": "phone-1"})
    client.post("/frame", json={"image": synthetic.encode(reference), "client_id": "desktop-2"})
    # The desktop's frame is still scored, but the camera role stays with the
    # phone, so the desktop keeps showing the preview instead of competing.
    assert client.get("/status").json()["camera"]["client_id"] == "phone-1"


def test_the_camera_role_is_released_once_the_device_goes_quiet(calibrated, monkeypatch):
    client, reference = calibrated
    client.post("/frame", json={"image": synthetic.encode(reference), "client_id": "phone-1"})

    # Pretend the phone stopped sending frames a while ago.
    with main.state.lock:
        main.state.camera_seen_at -= main.CAMERA_ACTIVE_TIMEOUT_S + 5
    assert client.get("/status").json()["camera"]["active"] is False

    client.post("/frame", json={"image": synthetic.encode(reference), "client_id": "tablet-3"})
    assert client.get("/status").json()["camera"]["client_id"] == "tablet-3"


def test_frames_without_a_client_id_still_score(calibrated):
    """Older clients, curl, and the API docs must keep working."""
    client, reference = calibrated
    x_mm, y_mm = board.point_for_score(20, board.RING_TREBLE)
    frame = synthetic.add_dart(reference, x_mm, y_mm)
    body = client.post("/frame", json={"image": synthetic.encode(frame)}).json()
    assert [d["label"] for d in body["new_darts"]] == ["T20"]
