"""Server-side capture tests.

The worker is driven with real video — a file for the unit tests, and a live
MJPEG stream over HTTP for the integration test, because an MJPEG URL is
exactly what a phone webcam app serves and what OpenCV has to open.
"""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
import pytest

from app import board, capture, config
from tests import synthetic


def board_sequence():
    """Clear board, then a T20 lands, then a 19."""
    clear = synthetic.clear_board()
    one = synthetic.add_dart(clear, *board.point_for_score(20, board.RING_TREBLE))
    two = synthetic.add_dart(one, *board.point_for_score(19, board.RING_OUTER_SINGLE))
    return clear, one, two


@pytest.fixture
def video_file(tmp_path):
    clear, one, two = board_sequence()
    path = tmp_path / "board.avi"
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"MJPG"), 15, (synthetic.WIDTH, synthetic.HEIGHT)
    )
    assert writer.isOpened(), "OpenCV could not open an MJPG writer"
    for frame in [clear] * 20 + [one] * 25 + [two] * 40:
        writer.write(frame)
    writer.release()
    return path


def test_parse_source_tells_device_indexes_from_urls():
    assert capture.parse_source("0") == 0
    assert capture.parse_source(" 1 ") == 1
    assert capture.parse_source("http://192.168.1.30:8080/video") == "http://192.168.1.30:8080/video"
    assert capture.parse_source("/dev/video0") == "/dev/video0"


def test_motion_fraction_is_zero_for_a_still_scene_and_rises_with_a_dart():
    clear, one, _ = board_sequence()
    _, thumb = capture.motion_fraction(None, clear)
    still, thumb = capture.motion_fraction(thumb, clear)
    assert still == 0.0

    moved, _ = capture.motion_fraction(thumb, one)
    # A single dart is small but must clear the configured trigger.
    assert moved > config.CAPTURE_MOTION_FRACTION
    assert moved < 0.05


def test_worker_reads_a_video_source_and_scores_the_darts(video_file):
    scored = []

    def on_frame(frame, set_reference=False, client_id=None):
        scored.append({"set_reference": set_reference, "client_id": client_id, "frame": frame})
        return {"new_darts": [] if set_reference else [{"label": "x"}]}

    worker = capture.CaptureWorker(str(video_file), on_frame)
    worker.start()
    deadline = time.time() + 15
    while time.time() < deadline and len(scored) < 3:
        time.sleep(0.1)
    worker.stop()

    assert not worker.is_running()
    # First call takes the clear-board reference; later ones are real throws.
    assert scored[0]["set_reference"] is True
    assert scored[0]["client_id"] == "server-capture"
    assert len(scored) >= 2, "the worker never scored a frame after the reference"
    assert worker.status()["frames_read"] > 0


def test_worker_reports_a_source_it_cannot_open_and_keeps_retrying():
    worker = capture.CaptureWorker("/nonexistent/path/to/video.avi", lambda *a, **k: {})
    worker.start()
    deadline = time.time() + 6
    while time.time() < deadline and not worker.error:
        time.sleep(0.1)
    status = worker.status()
    worker.stop()

    assert status["connected"] is False
    assert "cannot open" in status["error"]
    # Still running: a phone stream that is briefly away should be waited for.
    assert status["running"] is True


def test_worker_survives_a_scoring_error(video_file):
    calls = []

    def exploding(frame, set_reference=False, client_id=None):
        calls.append(1)
        raise RuntimeError("detection blew up")

    worker = capture.CaptureWorker(str(video_file), exploding)
    worker.start()
    deadline = time.time() + 8
    while time.time() < deadline and len(calls) < 2:
        time.sleep(0.1)
    status = worker.status()
    worker.stop()

    assert len(calls) >= 1
    assert "scoring failed" in status["error"]


def test_stop_is_safe_to_call_when_never_started():
    worker = capture.CaptureWorker("0", lambda *a, **k: {})
    worker.stop()
    assert worker.is_running() is False
    assert worker.status()["running"] is False


# --------------------------------------------------------------------------
# The real configuration: an MJPEG stream over HTTP, as a phone webcam app
# serves it.
# --------------------------------------------------------------------------
class _MjpegServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    frames: list = []


class _MjpegHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep pytest output clean
        pass

    def do_GET(self):
        boundary = "frameboundary"
        self.send_response(200)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary}")
        self.end_headers()
        try:
            for _ in range(3):  # loop the clip a few times
                for frame in self.server.frames:
                    ok, buffer = cv2.imencode(".jpg", frame)
                    if not ok:
                        continue
                    payload = buffer.tobytes()
                    self.wfile.write(f"--{boundary}\r\n".encode())
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(payload)}\r\n\r\n".encode())
                    self.wfile.write(payload)
                    self.wfile.write(b"\r\n")
                    time.sleep(1 / 15)
        except (BrokenPipeError, ConnectionResetError):
            pass


@pytest.fixture
def mjpeg_stream():
    clear, one, two = board_sequence()
    server = _MjpegServer(("127.0.0.1", 0), _MjpegHandler)
    server.frames = [clear] * 20 + [one] * 25 + [two] * 40
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/video"
    server.shutdown()
    server.server_close()


def test_worker_reads_an_mjpeg_stream_like_a_phone_webcam_app(mjpeg_stream):
    """This is the iPhone/Android webcam-app path end to end."""
    scored = []

    def on_frame(frame, set_reference=False, client_id=None):
        scored.append(set_reference)
        return {"new_darts": [] if set_reference else [{"label": "x"}]}

    worker = capture.CaptureWorker(mjpeg_stream, on_frame)
    worker.start()
    deadline = time.time() + 25
    while time.time() < deadline and len(scored) < 2:
        time.sleep(0.2)
    status = worker.status()
    worker.stop()

    assert status["frames_read"] > 0, f"never read a frame from the stream: {status}"
    assert scored and scored[0] is True
    assert len(scored) >= 2, "stream connected but no motion was ever scored"


def test_capture_scores_real_darts_through_the_real_pipeline(mjpeg_stream, tmp_path, monkeypatch):
    """Worker -> detection -> homography -> game state, with nothing stubbed."""
    from app import main

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "CALIBRATION_PATH", tmp_path / "calibration.json")
    monkeypatch.setattr(config, "DEBUG_LOGGING", False)
    main.state.__init__()
    main.state.calibration = synthetic.calibration()

    worker = capture.CaptureWorker(mjpeg_stream, main.score_frame)
    worker.start()
    deadline = time.time() + 25
    while time.time() < deadline and len(main.state.game.current_turn) < 2:
        time.sleep(0.2)
    worker.stop()

    labels = [d.score.label for d in main.state.game.current_turn]
    assert labels == ["T20", "19"], f"expected T20 then 19 from the stream, got {labels}"
    assert main.state.game.players[0].score == 79
    # The scoreboard preview must be populated for the browser views.
    assert main.state.preview_jpeg is not None
    assert main.state.camera_status()["client_id"] == "server-capture"
