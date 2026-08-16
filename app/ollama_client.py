"""Ollama vision verification — the *secondary* check, never the scorer.

The VLM is asked one narrow question it can actually answer reliably: how many
darts are visible in the board. It is never asked where they landed, because
that is precise spatial localisation and vision models are poor at it — the
homography does that job exactly.

The entire model interaction lives in this module so swapping llama3.2-vision
for qwen3-vl (or anything else) is a config change, not a refactor.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

import httpx

from . import config

VERIFY_PROMPT = (
    "You are looking at a photo of a dartboard. Answer ONLY with a single JSON "
    "object and no other text, using exactly this shape:\n"
    '{"dart_count": <integer>, "hand_or_person_visible": <true|false>, '
    '"board_fully_visible": <true|false>, "notes": "<short string>"}\n\n'
    "dart_count is how many darts are currently stuck in the board face. Do not "
    "count darts held in a hand, lying on the floor, or in a holder. If you are "
    "unsure, give your best single estimate. Do not describe scores or segment "
    "numbers."
)


@dataclass
class VerifyResult:
    """Outcome of a verification call. `available` is False if Ollama is down."""

    available: bool
    dart_count: Optional[int] = None
    hand_or_person_visible: Optional[bool] = None
    board_fully_visible: Optional[bool] = None
    notes: str = ""
    model: str = ""
    latency_ms: int = 0
    error: str = ""
    raw_response: str = ""

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "dart_count": self.dart_count,
            "hand_or_person_visible": self.hand_or_person_visible,
            "board_fully_visible": self.board_fully_visible,
            "notes": self.notes,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


def _extract_json(text: str) -> Optional[dict]:
    """Pull the first JSON object out of a model response.

    Vision models like to wrap JSON in prose or a code fence even when told not
    to, so we take the first balanced-looking object rather than trusting the
    whole string to parse.
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*?\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _coerce_int(value) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    if isinstance(value, str):
        match = re.search(r"-?\d+", value)
        if match:
            return int(match.group(0))
    return None


def _coerce_bool(value) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes"):
            return True
        if lowered in ("false", "no"):
            return False
    return None


def is_available(timeout_s: float = 2.0) -> bool:
    """Cheap reachability probe used by /status so the UI can grey out verify."""
    try:
        response = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=timeout_s)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def installed_models(timeout_s: float = 2.0) -> list[str]:
    try:
        response = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=timeout_s)
        response.raise_for_status()
        return [m.get("name", "") for m in response.json().get("models", [])]
    except (httpx.HTTPError, json.JSONDecodeError, ValueError):
        return []


def verify_frame(image_base64: str, model: Optional[str] = None, prompt: str = VERIFY_PROMPT) -> VerifyResult:
    """Ask the vision model how many darts it can see in this frame."""
    model = model or config.OLLAMA_MODEL
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [image_base64],
        "stream": False,
        # Low temperature: this is a counting task, not a creative one.
        "options": {"temperature": 0.0},
        "format": "json",
    }
    try:
        response = httpx.post(
            f"{config.OLLAMA_URL}/api/generate", json=payload, timeout=config.OLLAMA_TIMEOUT_S
        )
        response.raise_for_status()
        body = response.json()
    except httpx.TimeoutException:
        return VerifyResult(available=False, model=model, error="Ollama timed out")
    except httpx.HTTPError as exc:
        return VerifyResult(available=False, model=model, error=f"Ollama request failed: {exc}")
    except (json.JSONDecodeError, ValueError) as exc:
        return VerifyResult(available=False, model=model, error=f"Ollama returned non-JSON: {exc}")

    raw = body.get("response", "")
    latency_ms = int(body.get("total_duration", 0) / 1_000_000)
    parsed = _extract_json(raw)
    if parsed is None:
        return VerifyResult(
            available=True,
            model=model,
            latency_ms=latency_ms,
            error="could not parse a JSON object from the model response",
            raw_response=raw[:500],
        )

    return VerifyResult(
        available=True,
        dart_count=_coerce_int(parsed.get("dart_count")),
        hand_or_person_visible=_coerce_bool(parsed.get("hand_or_person_visible")),
        board_fully_visible=_coerce_bool(parsed.get("board_fully_visible")),
        notes=str(parsed.get("notes", ""))[:300],
        model=model,
        latency_ms=latency_ms,
        raw_response=raw[:500],
    )


def compare(verify: VerifyResult, opencv_count: int) -> list[str]:
    """Turn a verify result into UI warnings. Never overrides the OpenCV score."""
    warnings: list[str] = []
    if not verify.available:
        return warnings
    if verify.dart_count is not None and verify.dart_count != opencv_count:
        warnings.append(
            f"{verify.model} sees {verify.dart_count} dart(s) but detection found {opencv_count}"
        )
    if verify.hand_or_person_visible:
        warnings.append("A hand or person is in frame — detections may be false positives")
    if verify.board_fully_visible is False:
        warnings.append("The board is not fully visible — check the camera framing")
    return warnings
