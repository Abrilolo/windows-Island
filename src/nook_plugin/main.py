"""Stateful Nook live plugin connected to `OllamaBrain`, `OutboxStore`, and `PhoneDispatcher`."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import sys
import threading
from typing import Any, Callable

from brain.ollama_client import OllamaBrain
from nook_plugin.protocol import (
    badge_glyph,
    badge_msg,
    badge_ring,
    button,
    card,
    column,
    emit,
    page_msg,
    row,
    text,
    text_input,
    tile_msg,
)
from sync.config import BridgeConfig, DEFAULT_PHONE_PORT, normalize_phone_url
import sync.dispatcher as _dispatcher_mod
from sync.dispatcher import PhoneDispatcher, discover_phone
from sync.outbox import OutboxStore, QueuedItem
from sync.phone_connector import (
    PhoneConnection,
    connect_to_phone,
    post_to_phone,
    send_message_to_phone,
)

_ORIGINAL_DISCOVER_PHONE = discover_phone

# Re-export PendingItem alias for backwards compatibility
PendingItem = QueuedItem

STATUS_CONNECTED = "● Conectado"
STATUS_DISCONNECTED = "○ Conectar"


@dataclass
class BridgeState:
    """Thread-safe UI, Ollama inference, UDP discovery, and persistent offline outbox state for Nook."""

    brain: OllamaBrain = field(default_factory=OllamaBrain)
    config: BridgeConfig = field(default_factory=BridgeConfig.load)
    outbox: OutboxStore = field(default_factory=OutboxStore)
    dispatcher: PhoneDispatcher | None = None
    async_inference: bool = True
    auto_discover: bool = True
    on_async_update: Callable[[BridgeState], None] | None = None

    connected: bool = False
    discovered_ip: str | None = None
    status_text: str = STATUS_DISCONNECTED
    is_analyzing: bool = False
    is_syncing: bool = False
    last_capture: str = ""
    last_preview_lines: list[str] = field(default_factory=list)
    last_error: str | None = None
    last_sync_info: str | None = None
    input_value: str = ""
    pending_items: list[QueuedItem] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _workers: list[threading.Thread] = field(default_factory=list, repr=False)
    _capture_seq: int = 0

    def __post_init__(self) -> None:
        if self.dispatcher is None:
            self.dispatcher = PhoneDispatcher(
                config=self.config,
                outbox=self.outbox,
            )
        if not self.pending_items:
            self.pending_items = self.outbox.load_items()
        self.status_text = STATUS_CONNECTED if self.connected else STATUS_DISCONNECTED

        if self.auto_discover:
            if not os.environ.get("NOOK_PHONE_URL"):
                self.connect_phone()
        elif self.connected and self.pending_items and self.dispatcher is not None:
            if self.async_inference:
                self._spawn_worker(self._execute_sync)
            else:
                self._execute_sync()

    @property
    def is_connected(self) -> bool:
        return self.connected

    @property
    def connection_status_label(self) -> str:
        return STATUS_CONNECTED if self.connected else STATUS_DISCONNECTED

    def total_structured_entities(self) -> int:
        with self._lock:
            return sum(item.payload.total_items() for item in self.pending_items)

    def build_tile(self) -> dict[str, Any]:
        with self._lock:
            conn_status = STATUS_CONNECTED if self.connected else STATUS_DISCONNECTED
            return tile_msg(
                column(
                    [
                        row(
                            [
                                text("Minimal Bridge", size="body", bold=True),
                                button(
                                    "connect",
                                    label="Reconectar" if self.connected else STATUS_DISCONNECTED,
                                    icon="arrows-clockwise",
                                ),
                            ],
                            gap=6,
                            justify="between",
                        ),
                        text(conn_status, size="small", color="muted"),
                    ],
                    gap=2,
                )
            )

    def build_badge(self) -> dict[str, Any]:
        with self._lock:
            if self.is_analyzing:
                return badge_msg(badge_ring(0.5, "IA"))
            if self.is_syncing:
                return badge_msg(badge_ring(0.75, "SYNC"))
            if self.pending_items:
                return badge_msg(badge_glyph("bell"))
            return badge_msg(None)

    def build_page(self) -> dict[str, Any]:
        with self._lock:
            conn_status = STATUS_CONNECTED if self.connected else STATUS_DISCONNECTED
            children: list[dict[str, Any]] = [
                row(
                    [
                        text(conn_status, size="small", bold=True),
                        button(
                            "connect",
                            label="Reconectar" if self.connected else STATUS_DISCONNECTED,
                            icon="arrows-clockwise",
                        ),
                    ],
                    gap=8,
                    justify="between",
                ),
                text_input(
                    "quick_capture",
                    value=self.input_value,
                    hint="Ej. Comí 200g de pollo, gasté 120 en café y pagar la luz 18:00",
                ),
            ]

            if self.is_analyzing:
                children.append(
                    card(
                        [
                            text(
                                f"🧠 Clasificando con Ollama ({self.brain.model})...",
                                size="small",
                                bold=True,
                            ),
                            text(self.last_capture, size="small", color="muted"),
                        ],
                        padding=8,
                        gap=4,
                    )
                )
            elif self.last_preview_lines:
                header = (
                    "⚠️ Captura guardada en modo fallback (Ollama offline):"
                    if self.last_error
                    else "✨ Última captura clasificada (Room v6):"
                )
                preview_nodes: list[dict[str, Any]] = [
                    text(header, size="small", bold=True)
                ]
                for line in self.last_preview_lines[:5]:
                    preview_nodes.append(text(line, size="small", mono=True))
                children.append(card(preview_nodes, padding=8, gap=4))

            if self.pending_items:
                inbox_rows: list[dict[str, Any]] = [
                    text(
                        f"Cola Offline para S24+ ({len(self.pending_items)} lote(s)):",
                        size="small",
                        bold=True,
                    )
                ]
                shown_lines = 0
                for item in self.pending_items:
                    for s_line in item.summary_lines:
                        if shown_lines >= 5:
                            break
                        inbox_rows.append(
                            row(
                                [text(f"• {s_line}", size="small")],
                                gap=6,
                            )
                        )
                        shown_lines += 1
                    if shown_lines >= 5:
                        break

                inbox_rows.append(
                    row(
                        [
                            button(
                                "sync_phone",
                                label="Enviar todo al S24+",
                                icon="paper-plane-tilt",
                                primary=True,
                            ),
                            button(
                                "clear_inbox",
                                label="Limpiar",
                                icon="trash",
                            ),
                        ],
                        gap=8,
                    )
                )
                children.append(card(inbox_rows, padding=8, gap=6))

            return page_msg(
                column(children, gap=8, scroll=True),
                actions=[
                    {
                        "id": "connect",
                        "icon": "arrows-clockwise",
                        "tooltip": "Reconectar S24+",
                    }
                ],
            )

    def wait_pending_workers(self, timeout: float = 5.0) -> None:
        """Wait for any in-flight background Ollama, discovery, or HTTP sync threads to complete."""
        with self._lock:
            workers = list(self._workers)
        for w in workers:
            w.join(timeout=timeout)

    def _spawn_worker(self, target: Callable[..., None], *args: Any) -> None:
        worker = threading.Thread(target=target, args=args, daemon=True)
        with self._lock:
            self._workers = [w for w in self._workers if w.is_alive()]
            self._workers.append(worker)
        worker.start()

    def _invoke_discover(self) -> str | None:
        """Invoke `discover_phone` respecting monkeypatches on either `nook_plugin.main` or `sync.dispatcher`."""
        fn = (
            discover_phone
            if discover_phone is not _ORIGINAL_DISCOVER_PHONE
            else _dispatcher_mod.discover_phone
        )
        try:
            return fn(
                port=DEFAULT_PHONE_PORT,
                timeout=1.5,
                config=self.config,
                data_dir=self.outbox.data_dir,
            )
        except TypeError:
            return fn()

    def connect_phone(self) -> None:
        """Run `discover_phone()` (async or sync) and auto-flush pending outbox items if connected."""
        if self.async_inference:
            self._spawn_worker(self._execute_connect)
        else:
            self._execute_connect()

    def _execute_connect(self) -> None:
        """Execute UDP discovery, update connection state, and flush `outbox.json` if connected."""
        ip = self._invoke_discover()
        with self._lock:
            if ip:
                self.connected = True
                self.discovered_ip = ip
                self.config.phone_ingest_url = normalize_phone_url(f"{ip}:{DEFAULT_PHONE_PORT}")
                self.config.save(self.outbox.data_dir)
                self.status_text = STATUS_CONNECTED
                self.last_sync_info = STATUS_CONNECTED
            else:
                self.connected = False
                self.status_text = STATUS_DISCONNECTED
                self.last_sync_info = STATUS_DISCONNECTED

            self.pending_items = self.outbox.load_items()
            should_flush = self.connected and bool(self.pending_items) and self.dispatcher is not None
            if should_flush:
                self.is_syncing = True

        if self.on_async_update is not None:
            self.on_async_update(self)

        if should_flush:
            self._execute_sync()

    def _complete_capture(self, raw_text: str) -> None:
        """Execute Ollama extraction, persist in `outbox.json`, and auto-dispatch if enabled."""
        outcome = self.brain.analyze_text(raw_text, source="nook-desktop")
        with self._lock:
            self._capture_seq += 1
            queued_item = self.outbox.enqueue(
                raw_text=raw_text,
                payload=outcome.payload,
                source="capture",
                used_fallback=outcome.used_fallback,
                item_id=f"cap_{self._capture_seq}_{outcome.payload.sentAt}",
            )
            self.pending_items = self.outbox.load_items()
            self.last_preview_lines = outcome.payload.format_preview_lines()
            self.last_error = outcome.error_message
            self.is_analyzing = False

        if self.config.auto_sync_captures and self.dispatcher is not None:
            with self._lock:
                self.is_syncing = True
            if self.on_async_update is not None:
                self.on_async_update(self)
            self._execute_sync()
            return

        with self._lock:
            self.last_sync_info = f"📥 Guardado en cola ({queued_item.id})"
            self.status_text = STATUS_CONNECTED if self.connected else STATUS_DISCONNECTED
        if self.on_async_update is not None:
            self.on_async_update(self)

    def _execute_sync(self) -> None:
        """Flush `outbox.json` to the Galaxy S24+ and update UI state."""
        assert self.dispatcher is not None
        with self._lock:
            items_snapshot = list(self.pending_items)

        result = self.dispatcher.flush_outbox(items_snapshot)
        if (
            not result.delivered
            and type(self.dispatcher) is PhoneDispatcher
            and not os.environ.get("NOOK_PHONE_URL")
        ):
            ip = self._invoke_discover()
            if ip:
                with self._lock:
                    self.discovered_ip = ip
                    self.config.phone_ingest_url = normalize_phone_url(
                        f"{ip}:{DEFAULT_PHONE_PORT}"
                    )
                    self.config.save(self.outbox.data_dir)
                result = self.dispatcher.flush_outbox(items_snapshot)

        with self._lock:
            self.is_syncing = False
            self.pending_items = self.outbox.load_items()
            if result.delivered:
                self.connected = True
                self.status_text = STATUS_CONNECTED
                self.last_sync_info = STATUS_CONNECTED
            else:
                self.connected = False
                self.status_text = STATUS_DISCONNECTED
                self.last_sync_info = STATUS_DISCONNECTED

        if self.on_async_update is not None:
            self.on_async_update(self)

    def handle_message(self, msg: dict[str, Any]) -> bool:
        """Process a single incoming JSON message from Nook stdin.

        Returns True if the UI state changed immediately and should be re-emitted.
        """
        msg_type = msg.get("type")

        if msg_type == "event":
            control_id = msg.get("id")
            kind = msg.get("kind")
            value = str(msg.get("value") or "").strip()

            if control_id == "connect" and kind in ("click", None):
                self.connect_phone()
                return True

            if control_id == "quick_capture" and kind == "submit":
                if not value:
                    return False

                # Quick command `/ip <address>` to update phone endpoint on the fly
                if value.lower().startswith("/ip "):
                    raw_ip = value[4:].strip()
                    with self._lock:
                        self.config.phone_ingest_url = normalize_phone_url(raw_ip)
                        self.config.save(self.outbox.data_dir)
                        self.input_value = ""
                        self.status_text = STATUS_CONNECTED if self.connected else STATUS_DISCONNECTED
                    return True

                with self._lock:
                    self.last_capture = value
                    self.input_value = ""
                    self.is_analyzing = True

                if self.async_inference:
                    self._spawn_worker(self._complete_capture, value)
                else:
                    self._complete_capture(value)
                return True

            if control_id == "sync_phone" and kind in ("click", None):
                with self._lock:
                    if not self.pending_items:
                        return True
                    self.is_syncing = True

                if self.async_inference:
                    self._spawn_worker(self._execute_sync)
                else:
                    self._execute_sync()
                return True

            if control_id == "clear_inbox" and kind in ("click", None):
                with self._lock:
                    self.outbox.clear()
                    self.pending_items.clear()
                    self.last_preview_lines.clear()
                    self.last_error = None
                return True

        elif msg_type in ("page_open", "hotkey"):
            with self._lock:
                self.pending_items = self.outbox.load_items()
                is_conn = self.connected
                should_flush = self.connected and bool(self.pending_items) and self.dispatcher is not None
                if should_flush:
                    self.is_syncing = True
            if not is_conn:
                self.connect_phone()
            elif should_flush:
                if self.async_inference:
                    self._spawn_worker(self._execute_sync)
                else:
                    self._execute_sync()
            return True

        return False


def render_all(state: BridgeState) -> None:
    """Emit tile, page, and badge views to Nook stdout."""
    emit(state.build_tile())
    emit(state.build_page())
    emit(state.build_badge())


def run_loop(
    *,
    async_inference: bool = True,
    brain: OllamaBrain | None = None,
) -> None:
    """Main entry point for the Nook live plugin over stdio."""
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    state = BridgeState(
        brain=brain or OllamaBrain(),
        async_inference=async_inference,
        auto_discover=False,
        on_async_update=render_all if async_inference else None,
    )
    render_all(state)
    if not os.environ.get("NOOK_PHONE_URL"):
        state.connect_phone()

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        if isinstance(msg, dict) and state.handle_message(msg):
            render_all(state)

    state.wait_pending_workers()


if __name__ == "__main__":
    run_loop()
