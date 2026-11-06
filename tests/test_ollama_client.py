"""Unit tests for `OllamaBrain` Structured Outputs and offline fallback."""

from __future__ import annotations

from datetime import datetime
import io
import json
import urllib.error
from typing import Any

from core.brain.ollama_client import OllamaBrain
from core.contracts.payload import FinanceKind, NoteCategory


class _FakeHTTPResponse:
    def __init__(self, body: dict[str, Any], status: int = 200) -> None:
        self._bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._bytes

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, *args: object) -> None:
        pass


def test_analyze_multi_intent_sentence_with_mocked_ollama(monkeypatch) -> None:
    captured_request: dict[str, Any] = {}

    def fake_urlopen(req, timeout=None):
        captured_request["url"] = req.full_url
        captured_request["body"] = json.loads(req.data.decode("utf-8"))
        llm_json = {
            "reminders": [
                {
                    "title": "Pagar la luz",
                    "hour": 18,
                    "minute": 0,
                    "dueDateIso": "2026-11-04T18:00:00",
                    "priority": "high",
                    "phaseId": "work",
                }
            ],
            "finances": [
                {
                    "amountCents": 12000,
                    "description": "Café",
                    "kind": "EXTRA",
                    "category": "Comida",
                    "pendingFromOthersCents": 0,
                }
            ],
            "meals": [
                {
                    "description": "200g de pollo",
                    "servings": 1.0,
                    "slotId": "comida",
                    "kcal": 330.0,
                    "proteinG": 62.0,
                    "carbsG": 0.0,
                    "fatG": 7.0,
                    "fiberG": 0.0,
                }
            ],
            "workouts": [],
            "notes": [],
        }
        return _FakeHTTPResponse(
            {
                "model": "qwen2.5:3b",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(llm_json, ensure_ascii=False),
                },
                "done": True,
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    brain = OllamaBrain(base_url="http://localhost:11434", model="qwen2.5:3b")
    outcome = brain.analyze_text(
        "Comí 200g de pollo, gasté 120 en café y recuérdame pagar la luz a las 18:00",
        now=datetime(2026, 11, 4, 12, 30, 0),
    )

    assert outcome.used_fallback is False
    assert outcome.error_message is None
    assert captured_request["url"] == "http://localhost:11434/api/chat"
    assert captured_request["body"]["stream"] is False
    assert "properties" in captured_request["body"]["format"]

    payload = outcome.payload
    assert payload.source == "nook-desktop"
    assert len(payload.meals) == 1
    assert payload.meals[0].proteinG == 62.0
    assert len(payload.finances) == 1
    assert payload.finances[0].amountCents == 12000
    assert payload.finances[0].kind == FinanceKind.EXTRA
    assert len(payload.reminders) == 1
    assert payload.reminders[0].hour == 18


def test_offline_ollama_graceful_fallback(monkeypatch) -> None:
    def fake_urlopen_offline(req, timeout=None):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen_offline)

    brain = OllamaBrain(base_url="http://localhost:11434", timeout_sec=0.2)
    outcome = brain.analyze_text("Revisar contrato mañana")

    assert outcome.used_fallback is True
    assert outcome.error_message is not None
    assert len(outcome.payload.notes) == 1
    assert outcome.payload.notes[0].category == NoteCategory.GENERAL
    assert outcome.payload.notes[0].text == "Revisar contrato mañana"
