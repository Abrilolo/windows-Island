"""Unit tests for the Minimal Launcher Room v6 contracts (`core/contracts/payload.py`)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.contracts.payload import (
    FinanceKind,
    IngestPayload,
    LLMExtractionResult,
    NoteCategory,
)


def test_user_spec_contract_roundtrip() -> None:
    """Validate the exact JSON payload contract from the Minimal Launcher Room v6 spec."""
    raw_spec = {
        "source": "nook-desktop",
        "sentAt": 1762128000000,
        "reminders": [
            {
                "title": "Pagar la luz",
                "hour": 18,
                "minute": 0,
                "dueDateIso": "2026-11-03T18:00:00",
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
                "description": "200g de pechuga de pollo",
                "servings": 1.0,
                "slotId": "comida",
                "kcal": 330.0,
                "proteinG": 62.0,
                "carbsG": 0.0,
                "fatG": 7.0,
                "fiberG": 0.0,
            }
        ],
        "workouts": [
            {
                "exercise": "Press de banca",
                "sets": 4,
                "reps": 10,
                "weightKg": 70.0,
                "notes": "Buena técnica",
            }
        ],
        "notes": [
            {
                "category": "WORK",
                "text": "Revisar contrato pendiente",
            }
        ],
    }

    payload = IngestPayload.model_validate(raw_spec)
    assert payload.source == "nook-desktop"
    assert payload.sentAt == 1762128000000
    assert payload.total_items() == 5
    assert payload.finances[0].kind == FinanceKind.EXTRA
    assert payload.notes[0].category == NoteCategory.WORK
    assert payload.to_launcher_dict() == raw_spec


def test_strict_enums_reject_invalid_values() -> None:
    with pytest.raises(ValidationError):
        IngestPayload.model_validate(
            {
                "finances": [
                    {
                        "amountCents": 5000,
                        "description": "Test",
                        "kind": "INVALID_KIND",
                        "category": "Test",
                    }
                ]
            }
        )

    with pytest.raises(ValidationError):
        IngestPayload.model_validate(
            {
                "notes": [
                    {
                        "category": "RANDOM_CATEGORY",
                        "text": "Texto",
                    }
                ]
            }
        )


def test_ollama_json_schema_excludes_network_envelope() -> None:
    schema = LLMExtractionResult.model_json_schema()
    props = schema["properties"]
    assert set(props.keys()) == {"reminders", "finances", "meals", "workouts", "notes"}
    assert "source" not in props
    assert "sentAt" not in props
