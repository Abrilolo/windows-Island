"""Unit tests for the Nook stdio JSON-Lines protocol and Paso 3 state machine."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from core.brain.ollama_client import AnalysisOutcome, OllamaBrain
from core.contracts.payload import (
    FinanceItem,
    FinanceKind,
    IngestPayload,
    NoteCategory,
    MealItem,
    ReminderItem,
    ReminderPriority,
)
from minimal_bridge.app import BridgeState
from core.phone.config import BridgeConfig
from core.phone.dispatcher import DispatchResult, PhoneDispatcher
from core.phone.outbox import OutboxStore


class _StubBrain(OllamaBrain):
    def analyze_text(self, user_text: str, **kwargs) -> AnalysisOutcome:
        payload = IngestPayload(
            source="nook-desktop",
            meals=[
                MealItem(
                    description="200g de pollo",
                    slotId="comida",
                    kcal=330.0,
                    proteinG=62.0,
                    carbsG=0.0,
                    fatG=7.0,
                )
            ],
            finances=[
                FinanceItem(
                    amountCents=12000,
                    description="Café",
                    kind=FinanceKind.EXTRA,
                    category="Comida",
                )
            ],
            reminders=[
                ReminderItem(
                    title="Pagar la luz",
                    hour=18,
                    minute=0,
                    dueDateIso="2026-11-04T18:00:00",
                    priority=ReminderPriority.HIGH,
                    phaseId="work",
                )
            ],
        )
        return AnalysisOutcome(payload=payload, used_fallback=False)


class _StubDispatcher(PhoneDispatcher):
    def __init__(self, config: BridgeConfig, outbox: OutboxStore, online: bool = False) -> None:
        super().__init__(config=config, outbox=outbox)
        self.online = online

    def flush_outbox(self, items=None) -> DispatchResult:
        target = items if items is not None else self.outbox.load_items()
        if self.online:
            self.outbox.clear()
            return DispatchResult(
                delivered=True,
                sent_batches=len(target),
                sent_entities=sum(i.payload.total_items() for i in target),
                remaining_batches=0,
                endpoint_url=self.config.phone_ingest_url,
            )
        return DispatchResult(
            delivered=False,
            sent_batches=0,
            sent_entities=0,
            remaining_batches=len(target),
            endpoint_url=self.config.phone_ingest_url,
            error_message="S24+ offline",
        )


def test_offline_queue_then_manual_sync(tmp_path: Path) -> None:
    outbox = OutboxStore(data_dir=tmp_path)
    config = BridgeConfig(
        phone_ingest_url="http://192.168.3.164:8765/api/v1/ingest",
        auto_sync_captures=True,
    )
    stub_dispatcher = _StubDispatcher(config=config, outbox=outbox, online=False)

    state = BridgeState(
        brain=_StubBrain(),
        config=config,
        outbox=outbox,
        dispatcher=stub_dispatcher,
        async_inference=False,
    )

    # Initially empty outbox -> no badge
    assert state.build_badge() == {"type": "badge", "badge": None}

    # 1) Submit while phone is offline -> queued in outbox.json, bell badge active
    changed = state.handle_message(
        {
            "type": "event",
            "id": "quick_capture",
            "kind": "submit",
            "value": "Comí 200g de pollo, gasté 120 en café y pagar la luz 18:00",
        }
    )
    assert changed is True
    assert len(state.pending_items) == 1
    assert len(outbox.load_items()) == 1
    assert state.build_badge() == {"type": "badge", "badge": {"kind": "glyph", "icon": "bell"}}

    # 2) Phone comes online -> click "sync_phone" -> outbox cleared, badge cleared
    stub_dispatcher.online = True
    changed = state.handle_message(
        {
            "type": "event",
            "id": "sync_phone",
            "kind": "click",
        }
    )
    assert changed is True
    assert len(state.pending_items) == 0
    assert outbox.load_items() == []
    assert state.build_badge() == {"type": "badge", "badge": None}


def test_ip_slash_command_updates_config(tmp_path: Path) -> None:
    outbox = OutboxStore(data_dir=tmp_path)
    config = BridgeConfig.load(tmp_path)
    state = BridgeState(
        brain=_StubBrain(),
        config=config,
        outbox=outbox,
        async_inference=False,
    )

    changed = state.handle_message(
        {
            "type": "event",
            "id": "quick_capture",
            "kind": "submit",
            "value": "/ip 192.168.3.164",
        }
    )
    assert changed is True
    assert state.config.phone_ingest_url == "http://192.168.3.164:8765/api/v1/ingest"
    reloaded = BridgeConfig.load(tmp_path)
    assert reloaded.phone_ingest_url == "http://192.168.3.164:8765/api/v1/ingest"


def test_stdio_live_process_roundtrip(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["NOOK_OLLAMA_URL"] = "http://127.0.0.1:1"
    env["NOOK_PHONE_URL"] = "http://127.0.0.1:2/api/v1/ingest"
    env["NOOK_BRIDGE_DATA_DIR"] = str(tmp_path)

    proc = subprocess.Popen(
        [sys.executable, str(repo_root / "plugins" / "minimal-bridge" / "main.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )
    input_events = (
        json.dumps(
            {
                "type": "event",
                "id": "quick_capture",
                "kind": "submit",
                "value": "Pagar la luz a las 18:00",
            },
            ensure_ascii=False,
        )
        + "\n"
    )
    stdout_data, stderr_data = proc.communicate(input=input_events, timeout=10)
    assert proc.returncode == 0, stderr_data

    lines = [json.loads(line) for line in stdout_data.strip().splitlines()]
    # Initial (3) + analyzing (3) + syncing (3) + offline queued final (3) = 12 lines
    assert len(lines) >= 9
    assert "Pagar la luz a las 18:00" in json.dumps(lines[-2], ensure_ascii=False)
    assert lines[-1] == {"type": "badge", "badge": {"kind": "glyph", "icon": "bell"}}


def test_connect_button_discovers_phone_updates_clean_status_and_auto_flushes_outbox(
    tmp_path: Path, monkeypatch
) -> None:
    outbox = OutboxStore(data_dir=tmp_path)
    config = BridgeConfig.load(tmp_path)
    stub_dispatcher = _StubDispatcher(config=config, outbox=outbox, online=False)

    # Pre-queue a pending item in outbox.json before connecting
    outbox.enqueue(
        raw_text="Gasté 120 en café",
        payload=IngestPayload(
            finances=[
                FinanceItem(
                    amountCents=12000,
                    description="Café",
                    kind=FinanceKind.EXTRA,
                    category="Comida",
                )
            ]
        ),
        item_id="pending_1",
    )

    discovered_ip: list[str | None] = [None]
    discover_calls: list[int] = []

    def fake_discover(*args, **kwargs):
        discover_calls.append(1)
        return discovered_ip[0]

    monkeypatch.setattr("core.phone.dispatcher.discover_phone", fake_discover)

    # 1) Startup triggers discover_phone() -> offline -> shows "○ Conectar" and button id="connect"
    state = BridgeState(
        brain=_StubBrain(),
        config=config,
        outbox=outbox,
        dispatcher=stub_dispatcher,
        async_inference=False,
    )
    assert len(discover_calls) == 1
    assert state.connected is False

    tile_offline_str = json.dumps(state.build_tile(), ensure_ascii=False)
    page_offline_str = json.dumps(state.build_page(), ensure_ascii=False)
    assert "○ Conectar" in tile_offline_str
    assert '"id": "connect"' in tile_offline_str
    assert "○ Conectar" in page_offline_str
    assert '"id": "connect"' in page_offline_str
    assert len(outbox.load_items()) == 1

    # 2) Phone comes online on new Wi-Fi IP -> user clicks "connect" button ->
    #    updates IP, sets status to "● Conectado", and auto-flushes outbox.json!
    discovered_ip[0] = "192.168.1.88"
    stub_dispatcher.online = True

    changed = state.handle_message(
        {
            "type": "event",
            "id": "connect",
            "kind": "click",
        }
    )
    assert changed is True
    assert len(discover_calls) == 2
    assert state.connected is True
    assert state.config.phone_ingest_url == "http://192.168.1.88:8765/api/v1/ingest"
    assert outbox.load_items() == []
    assert state.pending_items == []

    tile_online_str = json.dumps(state.build_tile(), ensure_ascii=False)
    page_online_str = json.dumps(state.build_page(), ensure_ascii=False)
    assert "● Conectado" in tile_online_str
    assert '"id": "connect"' in tile_online_str
    assert "● Conectado" in page_online_str
    assert '"id": "connect"' in page_online_str


def test_nota_command_parses_category_and_text() -> None:
    from minimal_bridge.app import parse_note_command

    assert parse_note_command("/nota comprar leche") == (NoteCategory.GENERAL, "comprar leche")
    assert parse_note_command("/nota trabajo: revisar PR") == (NoteCategory.WORK, "revisar PR")
    # Unknown prefix stays part of the text
    assert parse_note_command("/nota reunion: 5pm") == (NoteCategory.GENERAL, "reunion: 5pm")
    assert parse_note_command("/nota") == (NoteCategory.GENERAL, "")
    assert parse_note_command("/notas algo") is None
    assert parse_note_command("Comí 200g de pollo") is None


def test_nota_command_queues_note_without_ollama(tmp_path: Path) -> None:
    class _ExplodingBrain(OllamaBrain):
        def analyze_text(self, user_text: str, **kwargs) -> AnalysisOutcome:
            raise AssertionError("/nota must not call Ollama")

    outbox = OutboxStore(data_dir=tmp_path)
    config = BridgeConfig(
        phone_ingest_url="http://192.168.3.164:8765/api/v1/ingest",
        auto_sync_captures=False,
    )
    state = BridgeState(
        brain=_ExplodingBrain(),
        config=config,
        outbox=outbox,
        dispatcher=_StubDispatcher(config=config, outbox=outbox, online=False),
        async_inference=False,
    )

    changed = state.handle_message(
        {"type": "event", "id": "quick_capture", "kind": "submit", "value": "/nota trabajo: revisar PR"}
    )
    assert changed is True
    assert len(state.pending_items) == 1
    notes = state.pending_items[0].payload.notes
    assert [(n.category, n.text) for n in notes] == [(NoteCategory.WORK, "revisar PR")]
    assert state.build_badge() == {"type": "badge", "badge": {"kind": "glyph", "icon": "bell"}}
    body = state.pending_items[0].payload.to_launcher_dict()
    assert body["notes"][0]["category"] == "WORK"
    assert body["notes"][0]["text"] == "revisar PR"
