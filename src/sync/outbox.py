"""Atomic persistent offline outbox queue stored in `%APPDATA%\\Nook\\plugin-data\\minimal-bridge\\outbox.json`."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
import uuid

from pydantic import BaseModel, ConfigDict, Field

from contracts.payload import IngestPayload
from sync.config import get_plugin_data_dir


class QueuedItem(BaseModel):
    """Single pending item persisted in `outbox.json` until the Galaxy S24+ acknowledges it."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: f"q_{uuid.uuid4().hex[:8]}")
    source: str = Field(default="capture", description="'capture' or 'mail'")
    raw_text: str = Field(..., description="Original text or email subject")
    payload: IngestPayload = Field(..., description="Validated Room v6 payload")
    used_fallback: bool = Field(default=False)
    created_at_ms: int = Field(default_factory=lambda: int(time.time() * 1000))
    attempts: int = Field(default=0)
    last_error: str | None = Field(default=None)

    @property
    def summary_lines(self) -> list[str]:
        lines = self.payload.format_preview_lines()
        if not lines:
            return [self.raw_text]
        if self.used_fallback:
            return [f"{lines[0]} (IA fallback)"] + lines[1:]
        return lines


class _OutboxFileEnvelope(BaseModel):
    version: int = 1
    items: list[QueuedItem] = Field(default_factory=list)


class OutboxStore:
    """Thread-safe persistent outbox backed by `outbox.json`."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = get_plugin_data_dir(data_dir)
        self.file_path = self.data_dir / "outbox.json"
        self._lock = threading.RLock()

    def load_items(self) -> list[QueuedItem]:
        """Read all queued items from disk (returns empty list if missing or corrupt)."""
        with self._lock:
            if not self.file_path.exists():
                return []
            try:
                raw = self.file_path.read_text(encoding="utf-8")
                envelope = _OutboxFileEnvelope.model_validate_json(raw)
                return list(envelope.items)
            except Exception:
                return []

    def save_items(self, items: list[QueuedItem]) -> None:
        """Atomically persist the entire queue to `outbox.json`."""
        with self._lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            envelope = _OutboxFileEnvelope(version=1, items=items)
            tmp_path = self.file_path.with_suffix(".json.tmp")
            payload_str = json.dumps(
                envelope.model_dump(mode="json"),
                indent=2,
                ensure_ascii=False,
            )
            tmp_path.write_text(payload_str, encoding="utf-8")
            os.replace(tmp_path, self.file_path)

    def enqueue(
        self,
        *,
        raw_text: str,
        payload: IngestPayload,
        source: str = "capture",
        used_fallback: bool = False,
        item_id: str | None = None,
    ) -> QueuedItem:
        """Prepend a new item to the persistent outbox and return it."""
        with self._lock:
            items = self.load_items()
            new_item = QueuedItem(
                id=item_id or f"q_{uuid.uuid4().hex[:8]}",
                source=source,
                raw_text=raw_text,
                payload=payload,
                used_fallback=used_fallback,
            )
            items.insert(0, new_item)
            self.save_items(items)
            return new_item

    def remove_ids(self, item_ids: set[str]) -> list[QueuedItem]:
        """Remove delivered items by ID and return the remaining queue."""
        with self._lock:
            remaining = [i for i in self.load_items() if i.id not in item_ids]
            self.save_items(remaining)
            return remaining

    def mark_attempt_failed(self, item_ids: set[str], error_msg: str) -> list[QueuedItem]:
        """Increment retry counter and record the last network error on matching items."""
        with self._lock:
            items = self.load_items()
            for item in items:
                if item.id in item_ids:
                    item.attempts += 1
                    item.last_error = error_msg
            self.save_items(items)
            return items

    def clear(self) -> None:
        """Remove all items from the outbox."""
        with self._lock:
            self.save_items([])
