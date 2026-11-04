"""Zero-dependency HTTP client for on-demand Ollama inference with Structured Outputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
import urllib.error
import urllib.request
from typing import Any

from brain.prompts import build_system_prompt
from contracts.payload import (
    IngestPayload,
    LLMExtractionResult,
    NoteCategory,
    NoteItem,
)

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5:3b"


class OllamaError(RuntimeError):
    """Raised when the local Ollama server is unreachable or returns an invalid payload."""


@dataclass
class AnalysisOutcome:
    """Result of analyzing user text or an email through OllamaBrain."""

    payload: IngestPayload
    used_fallback: bool = False
    error_message: str | None = None
    model_used: str = DEFAULT_OLLAMA_MODEL


class OllamaBrain:
    """On-demand client for Ollama `/api/chat` using JSON Schema Structured Outputs."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout_sec: float = 30.0,
        keep_alive: str = "5m",
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("NOOK_OLLAMA_URL") or DEFAULT_OLLAMA_URL
        ).rstrip("/")
        self.model = (
            model or os.environ.get("NOOK_OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL
        )
        self.timeout_sec = timeout_sec
        self.keep_alive = keep_alive

    def list_installed_models(self, timeout_sec: float = 2.0) -> list[str]:
        """Return the list of model names currently installed in Ollama (`/api/tags`)."""
        req = urllib.request.Request(
            f"{self.base_url}/api/tags",
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return [
                    str(m.get("name"))
                    for m in data.get("models", [])
                    if m.get("name")
                ]
        except Exception:
            return []

    def is_available(self, timeout_sec: float = 1.5) -> bool:
        """Quick check if the Ollama HTTP server responds on `/api/tags`."""
        req = urllib.request.Request(
            f"{self.base_url}/api/tags",
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                return resp.status == 200
        except Exception:
            return False

    def extract_structured(
        self,
        user_text: str,
        *,
        now: datetime | None = None,
    ) -> LLMExtractionResult:
        """Call Ollama `/api/chat` with `format=LLMExtractionResult.model_json_schema()`."""
        cleaned = user_text.strip()
        if not cleaned:
            return LLMExtractionResult()

        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": build_system_prompt(now)},
                {"role": "user", "content": cleaned},
            ],
            "format": LLMExtractionResult.model_json_schema(),
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": 0.1,
                "num_ctx": 2048,
            },
        }

        data = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                raw_response = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            if exc.code == 404 and "not found" in detail.lower():
                installed = self.list_installed_models()
                if installed and installed[0] != self.model:
                    self.model = installed[0]
                    return self.extract_structured(user_text, now=now)
            raise OllamaError(
                f"Ollama HTTP {exc.code}: {detail or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise OllamaError(
                f"No se pudo conectar con Ollama en {self.base_url}: {exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise OllamaError(
                f"Tiempo de espera agotado ({self.timeout_sec}s) llamando a Ollama"
            ) from exc

        try:
            envelope = json.loads(raw_response)
            content_str = envelope.get("message", {}).get("content", "")
            if not content_str:
                raise ValueError("Respuesta de Ollama sin 'message.content'")
            return LLMExtractionResult.model_validate_json(content_str)
        except Exception as exc:
            raise OllamaError(
                f"Respuesta de Ollama no cumple el contrato Room v6: {exc}"
            ) from exc

    def analyze_text(
        self,
        user_text: str,
        *,
        now: datetime | None = None,
        source: str = "nook-desktop",
        fallback_on_error: bool = True,
    ) -> AnalysisOutcome:
        """Analyze natural language text into a Room v6 `IngestPayload`.

        If Ollama is offline or fails and `fallback_on_error=True`, preserves the user's
        input as a `NoteItem(category=GENERAL)` so no capture is ever lost.
        """
        cleaned = user_text.strip()
        if not cleaned:
            return AnalysisOutcome(
                payload=IngestPayload(source=source),
                model_used=self.model,
            )

        try:
            extraction = self.extract_structured(cleaned, now=now)
            # If the LLM returned all empty lists for non-empty input, preserve as GENERAL note
            if extraction.is_empty():
                extraction.notes.append(
                    NoteItem(category=NoteCategory.GENERAL, text=cleaned)
                )
            return AnalysisOutcome(
                payload=extraction.to_ingest_payload(source=source),
                used_fallback=False,
                model_used=self.model,
            )
        except OllamaError as exc:
            if not fallback_on_error:
                raise
            fallback_extraction = LLMExtractionResult(
                notes=[NoteItem(category=NoteCategory.GENERAL, text=cleaned)]
            )
            return AnalysisOutcome(
                payload=fallback_extraction.to_ingest_payload(source=source),
                used_fallback=True,
                error_message=str(exc),
                model_used=self.model,
            )
