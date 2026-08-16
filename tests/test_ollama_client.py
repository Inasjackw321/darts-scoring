"""The vision model is the least predictable component, so the parsing around
it is tested hard: it must never take the scoring path down with it."""

import httpx
import pytest

from app import config, ollama_client
from app.ollama_client import VerifyResult, _extract_json, compare, verify_frame


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self):
        return self._payload


def test_extract_json_handles_bare_json():
    assert _extract_json('{"dart_count": 3}') == {"dart_count": 3}


def test_extract_json_handles_code_fences_and_prose():
    fenced = '```json\n{"dart_count": 2}\n```'
    assert _extract_json(fenced) == {"dart_count": 2}
    chatty = 'Sure! Here is the result: {"dart_count": 1} Hope that helps.'
    assert _extract_json(chatty) == {"dart_count": 1}


def test_extract_json_returns_none_for_unparseable_text():
    assert _extract_json("I can see some darts on the board.") is None


def test_verify_frame_parses_a_good_response(monkeypatch):
    monkeypatch.setattr(
        ollama_client.httpx,
        "post",
        lambda *a, **k: FakeResponse({
            "response": '{"dart_count": 3, "hand_or_person_visible": false, "board_fully_visible": true, "notes": "clear"}',
            "total_duration": 2_500_000_000,
        }),
    )
    result = verify_frame("ZmFrZQ==")
    assert result.available is True
    assert result.dart_count == 3
    assert result.hand_or_person_visible is False
    assert result.latency_ms == 2500


def test_verify_frame_coerces_sloppy_types(monkeypatch):
    """Vision models return "3 darts" and "yes" as often as clean JSON."""
    monkeypatch.setattr(
        ollama_client.httpx,
        "post",
        lambda *a, **k: FakeResponse({
            "response": '{"dart_count": "3 darts", "hand_or_person_visible": "yes"}',
        }),
    )
    result = verify_frame("ZmFrZQ==")
    assert result.dart_count == 3
    assert result.hand_or_person_visible is True


def test_verify_frame_survives_garbage(monkeypatch):
    monkeypatch.setattr(
        ollama_client.httpx,
        "post",
        lambda *a, **k: FakeResponse({"response": "there are some darts"}),
    )
    result = verify_frame("ZmFrZQ==")
    assert result.available is True
    assert result.dart_count is None
    assert "could not parse" in result.error


def test_verify_frame_survives_ollama_being_down(monkeypatch):
    def explode(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(ollama_client.httpx, "post", explode)
    result = verify_frame("ZmFrZQ==")
    assert result.available is False
    assert "failed" in result.error


def test_verify_frame_survives_a_timeout(monkeypatch):
    def explode(*args, **kwargs):
        raise httpx.TimeoutException("too slow")

    monkeypatch.setattr(ollama_client.httpx, "post", explode)
    result = verify_frame("ZmFrZQ==")
    assert result.available is False
    assert "timed out" in result.error


def test_model_is_swappable(monkeypatch):
    captured = {}

    def capture(url, json=None, timeout=None):
        captured.update(json)
        return FakeResponse({"response": '{"dart_count": 1}'})

    monkeypatch.setattr(ollama_client.httpx, "post", capture)
    verify_frame("ZmFrZQ==", model="qwen3-vl:8b")
    assert captured["model"] == "qwen3-vl:8b"
    assert captured["stream"] is False
    assert captured["images"] == ["ZmFrZQ=="]


def test_compare_flags_a_count_mismatch():
    warnings = compare(VerifyResult(available=True, dart_count=3, model="m"), opencv_count=2)
    assert len(warnings) == 1
    assert "3 dart(s)" in warnings[0]


def test_compare_is_silent_when_counts_agree():
    assert compare(VerifyResult(available=True, dart_count=2, model="m"), 2) == []


def test_compare_flags_a_person_in_frame():
    result = VerifyResult(available=True, dart_count=2, hand_or_person_visible=True, model="m")
    assert any("hand or person" in w.lower() for w in compare(result, 2))


def test_compare_says_nothing_when_ollama_is_unavailable():
    assert compare(VerifyResult(available=False, error="down"), 2) == []


def test_is_available_returns_false_when_ollama_is_down(monkeypatch):
    def explode(*args, **kwargs):
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(ollama_client.httpx, "get", explode)
    assert ollama_client.is_available() is False
    assert ollama_client.installed_models() == []


def test_default_model_comes_from_config():
    assert config.OLLAMA_MODEL == "llama3.2-vision"
