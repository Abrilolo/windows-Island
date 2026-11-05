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
from sync.dispatcher import (
    PhoneConnection,
    PhoneDispatcher,
    _try_adb_forward_phone,
    connect_to_phone,
    discover_phone,
    send_message_to_phone,
)
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


def test_discover_phone_udp_broadcast_saves_ip_and_pings_health(
    tmp_path: Path, monkeypatch
) -> None:
    sent_udp: dict[str, Any] = {}
    health_requests: list[tuple[str, str]] = []

    class _FakeUDPSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def setsockopt(self, level, optname, value):
            sent_udp["broadcast_opt"] = (level, optname, value)

        def settimeout(self, timeout):
            sent_udp["timeout"] = timeout

        def sendto(self, data: bytes, addr: tuple[str, int]):
            sent_udp["data"] = data.decode("utf-8")
            sent_udp["addr"] = addr

        def recvfrom(self, bufsize: int):
            reply = json.dumps(
                {"status": "ok", "app": "minimal-launcher", "port": 8765}
            ).encode("utf-8")
            return reply, ("192.168.1.42", 8765)

    class _FakeHealthResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"status":"ok"}'

    def fake_urlopen(req, timeout=None):
        health_requests.append((req.get_method(), req.full_url))
        return _FakeHealthResp()

    monkeypatch.setattr("socket.socket", lambda *a, **kw: _FakeUDPSocket())
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    cfg = BridgeConfig.load(tmp_path)
    ip = discover_phone(port=8765, timeout=1.5, config=cfg, data_dir=tmp_path)

    assert ip == "192.168.1.42"
    assert sent_udp["data"] == "NOOK_DISCOVER"
    assert sent_udp["addr"] == ("255.255.255.255", 8765)
    assert sent_udp["timeout"] == 1.5
    assert cfg.phone_ingest_url == "http://192.168.1.42:8765/api/v1/ingest"
    assert BridgeConfig.load(tmp_path).phone_ingest_url == "http://192.168.1.42:8765/api/v1/ingest"
    assert health_requests == [("GET", "http://192.168.1.42:8765/api/v1/health")]


def test_adb_forward_fallback_when_wifi_isolated(monkeypatch) -> None:
    calls: list[str] = []

    def fake_health(ip: str, port: int = 8765, timeout: float = 1.5) -> bool:
        calls.append(f"health:{ip}:{port}")
        # First check before adb forward fails, second check after adb forward succeeds
        return len(calls) >= 2

    class _FakeProc:
        returncode = 0

    def fake_run(cmd, **kwargs):
        calls.append(" ".join(cmd))
        return _FakeProc()

    monkeypatch.setattr("sync.dispatcher.ping_phone_health", fake_health)
    monkeypatch.setattr("subprocess.run", fake_run)

    resolved = _try_adb_forward_phone(port=8765, timeout=1.0)
    assert resolved == "127.0.0.1"
    assert calls == [
        "health:127.0.0.1:8765",
        "adb forward tcp:8765 tcp:8765",
        "health:127.0.0.1:8765",
    ]


def test_reusable_connect_to_phone_and_send_message(tmp_path: Path, monkeypatch) -> None:
    def fake_adb_forward(port: int = 8765, timeout: float = 1.5) -> str | None:
        return "127.0.0.1"

    class _FakeDeadSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def setsockopt(self, *args):
            pass

        def settimeout(self, *args):
            pass

        def sendto(self, *args):
            pass

        def recvfrom(self, *args):
            raise TimeoutError("UDP blocked")

    monkeypatch.setattr("socket.socket", lambda *a, **kw: _FakeDeadSocket())
    monkeypatch.setattr("sync.phone_connector.ping_phone_health", lambda *a, **kw: False)
    monkeypatch.setattr("sync.phone_connector._try_adb_forward_phone", fake_adb_forward)

    cfg = BridgeConfig.load(tmp_path)
    conn = connect_to_phone(config=cfg, data_dir=tmp_path, allow_adb=True)
    assert isinstance(conn, PhoneConnection)
    assert conn.connected is True
    assert conn.ip == "127.0.0.1"
    assert conn.transport == "adb"
    assert conn.ingest_url == "http://127.0.0.1:8765/api/v1/ingest"
    assert conn.message_url == "http://127.0.0.1:8765/api/v1/message"

    sent_req: dict[str, Any] = {}

    class _FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def fake_urlopen(req, timeout=None):
        sent_req["url"] = req.full_url
        sent_req["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    ok, err = send_message_to_phone("Sesión terminada", source="Claude", config=cfg, data_dir=tmp_path)
    assert ok is True
    assert err is None
    assert sent_req["url"] == "http://127.0.0.1:8765/api/v1/message"
    assert sent_req["body"] == {"from": "Claude", "text": "Sesión terminada"}
