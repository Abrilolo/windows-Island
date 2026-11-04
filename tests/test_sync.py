"""Unit tests for `OutboxStore`, `BridgeConfig`, and `PhoneDispatcher` (`src/sync/`)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import urllib.error

from contracts.payload import (
    FinanceItem,
    FinanceKind,
    IngestPayload,
    NoteCategory,
    NoteItem,
)
from sync.config import BridgeConfig, DEFAULT_PHONE_URL, normalize_phone_url
from sync.dispatcher import PhoneDispatcher
from sync.outbox import OutboxStore


def test_default_phone_ip_and_url_normalization(tmp_path: Path) -> None:
    cfg = BridgeConfig.load(tmp_path)
    assert cfg.phone_ingest_url == "http://192.168.3.164:8765/api/v1/ingest"
    assert DEFAULT_PHONE_URL == "http://192.168.3.164:8765/api/v1/ingest"

    assert normalize_phone_url("192.168.3.164") == "http://192.168.3.164:8765/api/v1/ingest"
    assert normalize_phone_url("100.64.0.5:9000") == "http://100.64.0.5:9000/api/v1/ingest"
    assert (
        normalize_phone_url("http://192.168.3.164:8765/custom")
        == "http://192.168.3.164:8765/custom"
    )


def test_outbox_atomic_persistence_and_offline_retry(tmp_path: Path, monkeypatch) -> None:
    outbox = OutboxStore(data_dir=tmp_path)
    config = BridgeConfig(
        phone_ingest_url="http://192.168.3.164:8765/api/v1/ingest",
        request_timeout_sec=0.5,
    )
    dispatcher = PhoneDispatcher(config=config, outbox=outbox)

    p1 = IngestPayload(
        finances=[
            FinanceItem(
                amountCents=12000,
                description="Café",
                kind=FinanceKind.EXTRA,
                category="Comida",
            )
        ]
    )
    p2 = IngestPayload(
        notes=[
            NoteItem(
                category=NoteCategory.WORK,
                text="Checar pendientes del trabajo",
            )
        ]
    )

    outbox.enqueue(raw_text="Gasté 120 en café", payload=p1, item_id="item_1")
    outbox.enqueue(raw_text="Checar pendientes", payload=p2, item_id="item_2")

    # Verify disk persistence across a new OutboxStore instance
    reloaded = OutboxStore(data_dir=tmp_path).load_items()
    assert [i.id for i in reloaded] == ["item_2", "item_1"]

    # 1) Simulate Galaxy S24+ unreachable (offline)
    def fake_offline(req, timeout=None):
        raise urllib.error.URLError("Host unreachable")

    monkeypatch.setattr("urllib.request.urlopen", fake_offline)
    res_offline = dispatcher.flush_outbox()
    assert res_offline.delivered is False
    assert res_offline.remaining_batches == 2

    after_fail = outbox.load_items()
    assert len(after_fail) == 2
    assert after_fail[0].attempts == 1
    assert "inalcanzable" in (after_fail[0].last_error or "")

    # 2) Simulate Galaxy S24+ coming back online (HTTP 200 OK)
    captured_post: dict[str, Any] = {}

    class _FakeOK:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def fake_online(req, timeout=None):
        captured_post["url"] = req.full_url
        captured_post["payload"] = json.loads(req.data.decode("utf-8"))
        return _FakeOK()

    monkeypatch.setattr("urllib.request.urlopen", fake_online)
    res_online = dispatcher.flush_outbox()

    assert res_online.delivered is True
    assert res_online.sent_batches == 2
    assert res_online.sent_entities == 2
    assert res_online.remaining_batches == 0
    assert outbox.load_items() == []

    # Verify both payloads were merged into one atomic HTTP POST
    assert captured_post["url"] == "http://192.168.3.164:8765/api/v1/ingest"
    assert len(captured_post["payload"]["finances"]) == 1
    assert len(captured_post["payload"]["notes"]) == 1
