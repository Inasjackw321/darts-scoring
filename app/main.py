"""FastAPI application — the LAN-facing server that does the scoring.

Hot path (`POST /frame`) is pure OpenCV plus homography maths, so a throw is
scored in milliseconds. The vision model is only ever reached through the
explicitly-called `POST /verify`.
"""

from __future__ import annotations

import socket
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import board, calibration as calib, config, debug_log, detection, ollama_client
from .game import GAME_MODES, MODE_COUNT_UP, GameState

APP_VERSION = "0.1.0"
FRONTEND_DIR = config.BASE_DIR / "docs"

@asynccontextmanager
async def lifespan(_: FastAPI):
    config.ensure_dirs()
    print(f"\n  AI Vision Dart Scorer v{APP_VERSION}")
    print(f"  Phone should connect to:  http://{lan_ip()}:8000")
    print(f"  Calibrated: {state.calibration is not None}\n")
    yield


app = FastAPI(title="AI Vision Dart Scorer", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ServerState:
    """Everything the server remembers between requests."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.game = GameState(mode=MODE_COUNT_UP)
        self.calibration: Optional[calib.Calibration] = calib.load()
        # Grayscale snapshot of the board with no darts in it. All detection is
        # a diff against this, so it is re-captured at the start of every turn.
        self.reference_gray: Optional[np.ndarray] = None
        self.reference_captured_at: float = 0.0
        self.last_frame_at: float = 0.0
        self.frames_processed: int = 0
        self.needs_recalibration: bool = False
        self.last_verify: Optional[dict] = None


state = ServerState()


# --------------------------------------------------------------------------
# Request models
# --------------------------------------------------------------------------
class FrameRequest(BaseModel):
    image: str = Field(..., description="JPEG/PNG frame as base64 or a data URL")
    set_reference: bool = Field(False, description="Store this frame as the clear-board reference instead of scoring it")


class CalibrateRequest(BaseModel):
    image_points: list[list[float]] = Field(..., description="Clicked pixel coordinates, [[x, y], ...]")
    board_points: Optional[list[list[float]]] = Field(
        None, description="Board-space millimetres for each clicked point; defaults to the four cardinal outer-double points"
    )
    frame_width: int = 0
    frame_height: int = 0
    image: Optional[str] = Field(None, description="Optional frame to store as the clear-board reference")


class NextTurnRequest(BaseModel):
    image: Optional[str] = Field(None, description="Frame of the cleared board to use as the new reference")


class VerifyRequest(BaseModel):
    image: str
    model: Optional[str] = None
    expected_darts: Optional[int] = None


class ResetRequest(BaseModel):
    mode: Optional[str] = None
    players: Optional[list[str]] = None
    start_score: int = 501
    image: Optional[str] = Field(None, description="Fresh clear-board frame to use as the new reference")


class ManualDartRequest(BaseModel):
    segment: Optional[int] = None
    ring: Optional[str] = None
    x_mm: Optional[float] = None
    y_mm: Optional[float] = None


class EditDartRequest(ManualDartRequest):
    dart_id: str


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def lan_ip() -> str:
    """Best-effort LAN address, for printing the URL the phone should open."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packet is actually sent; this just picks the outbound interface.
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _decode(image: str) -> np.ndarray:
    try:
        return detection.decode_frame(image)
    except detection.FrameDecodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _resolve_board_point(request: ManualDartRequest) -> tuple[float, float]:
    """Manual corrections may arrive as coordinates or as 'T20'-style values."""
    if request.x_mm is not None and request.y_mm is not None:
        return float(request.x_mm), float(request.y_mm)
    if request.segment is None:
        raise HTTPException(status_code=400, detail="provide either x_mm/y_mm or segment (+ ring)")
    ring = request.ring or board.RING_OUTER_SINGLE
    return board.point_for_score(int(request.segment), ring)


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.get("/status")
def get_status() -> dict:
    """Health check — the phone polls this for its connection indicator."""
    with state.lock:
        return {
            "ok": True,
            "version": APP_VERSION,
            "server_time": datetime.now(timezone.utc).isoformat(),
            "lan_ip": lan_ip(),
            "calibrated": state.calibration is not None,
            "calibration_rms_error_mm": state.calibration.rms_error_mm if state.calibration else None,
            "has_reference_frame": state.reference_gray is not None,
            "reference_age_s": round(time.time() - state.reference_captured_at, 1) if state.reference_captured_at else None,
            "needs_recalibration": state.needs_recalibration,
            "frames_processed": state.frames_processed,
            "ollama": {
                "url": config.OLLAMA_URL,
                "model": config.OLLAMA_MODEL,
                "available": ollama_client.is_available(),
            },
            "game": state.game.to_dict(),
        }


@app.get("/calibration")
def get_calibration() -> dict:
    with state.lock:
        if state.calibration is None:
            return {
                "calibrated": False,
                "reference_points": board.DEFAULT_REFERENCE_POINTS,
            }
        payload = state.calibration.to_dict()
        payload["calibrated"] = True
        payload["reference_points"] = board.DEFAULT_REFERENCE_POINTS
        payload["board_outline_px"] = calib.board_outline_image_points(state.calibration)
        return payload


@app.post("/calibrate")
def post_calibrate(request: CalibrateRequest) -> dict:
    """Compute and persist the image->board homography from clicked points."""
    board_points = request.board_points
    if board_points is None:
        if len(request.image_points) != len(board.DEFAULT_REFERENCE_POINTS):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"expected {len(board.DEFAULT_REFERENCE_POINTS)} clicked points to match the default "
                    "reference points, or supply board_points explicitly"
                ),
            )
        board_points = [[p["x_mm"], p["y_mm"]] for p in board.DEFAULT_REFERENCE_POINTS]

    try:
        result = calib.compute_calibration(
            request.image_points,
            board_points,
            frame_width=request.frame_width,
            frame_height=request.frame_height,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    except calib.CalibrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with state.lock:
        state.calibration = result
        calib.save(result)
        state.needs_recalibration = False
        if request.image:
            frame = _decode(request.image)
            state.reference_gray = detection.to_gray(frame)
            state.reference_captured_at = time.time()

    debug_log.log_event("calibrate", result.to_dict())
    payload = result.to_dict()
    payload["calibrated"] = True
    payload["board_outline_px"] = calib.board_outline_image_points(result)
    return payload


@app.delete("/calibration")
def delete_calibration() -> dict:
    with state.lock:
        state.calibration = None
        calib.clear()
        state.needs_recalibration = False
    return {"calibrated": False}


@app.post("/frame")
def post_frame(request: FrameRequest) -> dict:
    """Score a frame: detect tips, map to board space, tally new darts."""
    frame = _decode(request.image)

    with state.lock:
        if request.set_reference or state.reference_gray is None:
            state.reference_gray = detection.to_gray(frame)
            state.reference_captured_at = time.time()
            return {
                "status": "reference_captured",
                "new_darts": [],
                "tips": [],
                "game": state.game.to_dict(),
                "warnings": [],
            }

        if state.calibration is None:
            raise HTTPException(status_code=409, detail="not calibrated — run /calibrate first")

        reference = state.reference_gray
        tips, mask = detection.detect_tips(reference, frame, state.calibration)
        changed = detection.changed_fraction(mask)
        state.frames_processed += 1
        state.last_frame_at = time.time()

        warnings: list[str] = []
        # A huge diff is not eight darts — it is the camera being knocked, a
        # light being switched, or a person standing in front of the board.
        if changed > config.CAMERA_MOVED_FRACTION:
            state.needs_recalibration = True
            warnings.append(
                f"{changed:.0%} of the frame changed — the camera may have moved; recalibrate if scores look wrong"
            )
            record = {
                "status": "scene_changed",
                "changed_fraction": round(changed, 4),
                "tips": [t.to_dict() for t in tips],
            }
            debug_log.log_detection(frame, mask, None, record)
            return {
                "status": "scene_changed",
                "new_darts": [],
                "tips": [t.to_dict() for t in tips],
                "changed_fraction": round(changed, 4),
                "needs_recalibration": True,
                "game": state.game.to_dict(),
                "warnings": warnings,
            }

        new_darts = []
        for tip in tips:
            if tip.x_mm is None or tip.y_mm is None:
                continue
            if np.hypot(tip.x_mm, tip.y_mm) > board.BOARD_RADIUS_MM * 1.35:
                continue  # well off the board — not a dart in the scoring area
            if state.game.is_duplicate(tip.x_mm, tip.y_mm):
                continue  # already tallied this turn; the dart is still in the board
            if state.game.turn_complete:
                warnings.append("Turn already has three darts — start the next turn to keep scoring")
                break
            dart = state.game.add_dart_at(tip.x_mm, tip.y_mm, source="opencv")
            if dart is None:
                continue
            new_darts.append(dart.to_dict())
            if dart.low_confidence:
                warnings.append(
                    f"{dart.score.label} landed {dart.score.boundary_margin_mm:.1f}mm from a wire — worth verifying"
                )

        game_payload = state.game.to_dict()
        outline = calib.board_outline_image_points(state.calibration, steps=60) if state.calibration else None
        annotated = detection.annotate(frame, tips, outline) if new_darts else None
        record = {
            "status": "ok",
            "changed_fraction": round(changed, 4),
            "tips": [t.to_dict() for t in tips],
            "new_darts": new_darts,
            "game": game_payload,
        }
        debug_log.log_detection(frame if new_darts else None, mask if new_darts else None, annotated, record)

        return {
            "status": "ok",
            "new_darts": new_darts,
            "tips": [t.to_dict() for t in tips],
            "changed_fraction": round(changed, 4),
            "needs_recalibration": False,
            "game": game_payload,
            "warnings": warnings,
        }


@app.post("/verify")
def post_verify(request: VerifyRequest) -> dict:
    """Secondary sanity check via the vision model. Advisory only."""
    frame = _decode(request.image)
    image_b64 = detection.encode_jpeg_base64(frame)

    with state.lock:
        expected = request.expected_darts
        if expected is None:
            expected = len(state.game.current_turn)

    result = ollama_client.verify_frame(image_b64, model=request.model)
    warnings = ollama_client.compare(result, expected)
    payload = {
        "verify": result.to_dict(),
        "expected_darts": expected,
        "agrees": result.available and result.dart_count == expected,
        "warnings": warnings,
    }
    with state.lock:
        state.last_verify = payload
    debug_log.log_event("verify", {**payload, "raw_response": result.raw_response})
    return payload


@app.post("/reset")
def post_reset(request: ResetRequest) -> dict:
    """Clear game state and re-capture the clear-board reference frame."""
    mode = request.mode or MODE_COUNT_UP
    if mode not in GAME_MODES:
        raise HTTPException(status_code=400, detail=f"unknown mode {mode!r}; expected one of {list(GAME_MODES)}")

    with state.lock:
        state.game.reset(mode=mode, players=request.players, start_score=request.start_score)
        if request.image:
            frame = _decode(request.image)
            state.reference_gray = detection.to_gray(frame)
            state.reference_captured_at = time.time()
        else:
            # Force the next frame to become the new reference.
            state.reference_gray = None
            state.reference_captured_at = 0.0
        state.needs_recalibration = False
        payload = state.game.to_dict()

    debug_log.log_event("reset", {"mode": mode, "players": request.players})
    return {"ok": True, "game": payload}


@app.post("/turn/next")
def post_next_turn(request: NextTurnRequest = NextTurnRequest()) -> dict:
    """Bank this turn, hand over, and take a fresh clear-board reference.

    The darts are pulled out between turns, so the reference must be retaken —
    otherwise the next turn diffs against a board that still has darts in it.
    """
    with state.lock:
        state.game.new_turn()
        if request.image:
            frame = _decode(request.image)
            state.reference_gray = detection.to_gray(frame)
            state.reference_captured_at = time.time()
        else:
            state.reference_gray = None
            state.reference_captured_at = 0.0
        return {"ok": True, "game": state.game.to_dict()}


@app.post("/dart")
def post_manual_dart(request: ManualDartRequest) -> dict:
    """Add a dart by hand — bounce-outs, occluded darts, missed detections."""
    x_mm, y_mm = _resolve_board_point(request)
    with state.lock:
        dart = state.game.add_dart_at(x_mm, y_mm, source="manual")
        if dart is None:
            raise HTTPException(status_code=409, detail="turn is already complete")
        return {"ok": True, "dart": dart.to_dict(), "game": state.game.to_dict()}


@app.patch("/dart")
def patch_dart(request: EditDartRequest) -> dict:
    """Correct a dart the pipeline got wrong."""
    x_mm, y_mm = _resolve_board_point(request)
    with state.lock:
        dart = state.game.edit_dart(request.dart_id, x_mm, y_mm)
        if dart is None:
            raise HTTPException(status_code=404, detail=f"no dart {request.dart_id!r} in the current turn")
        return {"ok": True, "dart": dart.to_dict(), "game": state.game.to_dict()}


@app.post("/dart/undo")
def post_undo() -> dict:
    with state.lock:
        dart = state.game.undo_last_dart()
        if dart is None:
            raise HTTPException(status_code=409, detail="no darts to undo in the current turn")
        return {"ok": True, "removed": dart.to_dict(), "game": state.game.to_dict()}


@app.get("/game")
def get_game() -> dict:
    with state.lock:
        return state.game.to_dict()


@app.get("/board")
def get_board_geometry() -> dict:
    """Board constants, so the frontend diagram and the server never disagree."""
    return {
        "segment_order": board.SEGMENT_ORDER,
        "segment_arc_deg": board.SEGMENT_ARC_DEG,
        "radii_mm": {
            "inner_bull": board.R_INNER_BULL,
            "outer_bull": board.R_OUTER_BULL,
            "treble_inner": board.R_TREBLE_INNER,
            "treble_outer": board.R_TREBLE_OUTER,
            "double_inner": board.R_DOUBLE_INNER,
            "double_outer": board.R_DOUBLE_OUTER,
        },
        "reference_points": board.DEFAULT_REFERENCE_POINTS,
    }


# Serving the frontend from the same origin makes desktop-browser testing
# trivial (no CORS, no IP entry). The phone can use it too, or GitHub Pages.
# The redirect matters: index.html references its CSS/JS relatively, so it has
# to be served from inside /app/ or those requests land outside the mount.
if FRONTEND_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse(url="/app/")
