"""Device Center: stateful Fenn live plugin connected to `OllamaBrain`, `OutboxStore`, and `PhoneDispatcher`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import os
import sys
import threading
from typing import Any, Callable
from urllib.parse import urlparse

from core.brain.ollama_client import OllamaBrain
from core.contracts.payload import IngestPayload, NoteCategory, NoteItem
from core.protocol import (
    badge_glyph,
    badge_msg,
    badge_ring,
    button,
    card,
    column,
    emit,
    grid,
    icon,
    list_item,
    list_view,
    page_msg,
    row,
    spacer,
    text,
    text_input,
    tile_msg,
)
from core.protocol.theme import ACCENT, DIM, FAINT
from core.phone.config import BridgeConfig, DEFAULT_PHONE_PORT, normalize_phone_url
import core.phone.dispatcher as _dispatcher_mod
from core.phone.dispatcher import PhoneDispatcher, discover_phone
from core.phone.outbox import OutboxStore, QueuedItem
from core.phone.phone_connector import (
    PhoneConnection,
    connect_to_phone,
    post_to_phone,
    send_message_to_phone,
)

_ORIGINAL_DISCOVER_PHONE = discover_phone

# `/nota [categoria:] texto` guarda directo en el módulo Notas del S24+ (sin Ollama).
_NOTE_COMMAND = "/nota"
_NOTE_CATEGORY_ALIASES: dict[str, NoteCategory] = {
    "general": NoteCategory.GENERAL,
    "trabajo": NoteCategory.WORK,
    "work": NoteCategory.WORK,
    "ideas": NoteCategory.IDEAS,
    "finanzas": NoteCategory.FINANCES,
    "dieta": NoteCategory.DIET,
    "escuela": NoteCategory.SCHOOL,
    "ejercicio": NoteCategory.EXERCISE,
    "comida": NoteCategory.FOOD,
}


def parse_note_command(value: str) -> tuple[NoteCategory, str] | None:
    """Parse `/nota [categoria:] texto`. Returns None if `value` is not a note command."""
    lowered = value.lower()
    if lowered != _NOTE_COMMAND and not lowered.startswith(_NOTE_COMMAND + " "):
        return None
    body = value[len(_NOTE_COMMAND):].strip()
    category = NoteCategory.GENERAL
    head, sep, rest = body.partition(":")
    if sep and head.strip().lower() in _NOTE_CATEGORY_ALIASES:
        category = _NOTE_CATEGORY_ALIASES[head.strip().lower()]
        body = rest.strip()
    return category, body


# Re-export PendingItem alias for backwards compatibility
PendingItem = QueuedItem

STATUS_CONNECTED = "● Conectado"
STATUS_DISCONNECTED = "○ Conectar"
DEVICE_NAME = os.environ.get("FENN_PHONE_NAME", "Galaxy S24+")


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
    last_sync_at: datetime | None = None
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

    def _transport(self) -> tuple[str, str]:
        """(icon, label) for the active phone link: ADB tunnel on localhost, else Wi-Fi."""
        host = urlparse(self.config.phone_ingest_url).hostname or ""
        if host in ("127.0.0.1", "localhost", "::1"):
            return "usb", "USB · ADB"
        return "wifi-high", (f"Wi-Fi · {host}" if host else "Wi-Fi")

    def _status_line(self) -> tuple[str, str]:
        """(text, color) for the connection state."""
        if self.is_syncing:
            return "◌ Sincronizando…", ACCENT
        if self.connected:
            return STATUS_CONNECTED, "green"
        return STATUS_DISCONNECTED, DIM

    def _last_sync_label(self) -> str:
        return self.last_sync_at.strftime("%H:%M") if self.last_sync_at else "—"

    def build_tile(self) -> dict[str, Any]:
        """One square cell (~104 pt): no buttons here, they overlap the name. Tap opens the page,
        whose card and header action reconnect."""
        with self._lock:
            status, status_color = self._status_line()
            transport_icon, transport = self._transport()
            queued = len(self.pending_items)
            if queued:
                detail_icon, detail = "tray", f"{queued} en cola"
            else:
                detail_icon, detail = "clock", f"sync {self._last_sync_label()}"

            def line(glyph: str, value: str, color: str) -> dict[str, Any]:
                return row([icon(glyph, size=12, color=color), text(value, size="small", color=color, wrap=False)], gap=4)

            return tile_msg(
                column(
                    [
                        row(
                            [
                                icon("device-mobile", size=16, color=status_color),
                                text(DEVICE_NAME, size="body", bold=True, wrap=False),
                            ],
                            gap=6,
                        ),
                        text(status, size="small", color=status_color, wrap=False),
                        line(transport_icon, transport, DIM),
                        line(detail_icon, detail, ACCENT if queued else DIM),
                    ],
                    gap=4,
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

    def _device_card(self) -> dict[str, Any]:
        status, status_color = self._status_line()
        transport_icon, transport = self._transport()
        queued = len(self.pending_items)

        def stat(label: str, value: str, glyph: str) -> dict[str, Any]:
            return card(
                [
                    row([icon(glyph, size=12, color=DIM), text(label, size="small", color=DIM)], gap=4),
                    text(value, size="body", bold=True, wrap=False),
                ],
                padding=8,
                gap=2,
            )

        return card(
            [
                row(
                    [
                        icon("device-mobile", size=28, color=status_color),
                        column(
                            [
                                text(DEVICE_NAME, size="body", bold=True, wrap=False),
                                text(status, size="small", color=status_color, wrap=False),
                            ],
                            gap=0,
                        ),
                        spacer(),
                        button(
                            "connect",
                            label="Reconectar" if self.connected else "Conectar",
                            icon="arrows-clockwise",
                        ),
                    ],
                    gap=8,
                    align="center",
                ),
                grid(
                    3,
                    [
                        stat("Enlace", transport, transport_icon),
                        stat("En cola", f"{queued} lote(s)" if queued else "vacía", "tray"),
                        stat("Última sync", self._last_sync_label(), "clock"),
                    ],
                    gap=6,
                ),
            ],
            padding=10,
            gap=8,
        )

    def build_page(self) -> dict[str, Any]:
        with self._lock:
            # The input goes first (as in the other Fenn plugins): it renders reliably at the top.
            children: list[dict[str, Any]] = [
                text_input(
                    "quick_capture",
                    value=self.input_value,
                    hint="Ej. Comí 200g de pollo... · /nota [trabajo:] texto → Notas",
                ),
                self._device_card(),
            ]

            if self.is_analyzing:
                children.append(
                    card(
                        [
                            row(
                                [
                                    icon("brain", size=14, color=ACCENT),
                                    text(f"Clasificando con Ollama ({self.brain.model})…", size="small", bold=True),
                                ],
                                gap=6,
                            ),
                            text(self.last_capture, size="small", color=DIM),
                        ],
                        padding=8,
                        gap=4,
                    )
                )
            elif self.last_preview_lines:
                if self.last_error:
                    glyph, color, header = "warning-circle", "orange", "Guardado sin IA (Ollama offline)"
                else:
                    glyph, color, header = "check-circle", "green", "Última captura clasificada"
                preview_nodes: list[dict[str, Any]] = [
                    row([icon(glyph, size=14, color=color), text(header, size="small", bold=True)], gap=6)
                ]
                for line in self.last_preview_lines[:5]:
                    preview_nodes.append(text(line, size="small", mono=True))
                children.append(card(preview_nodes, padding=8, gap=4))

            if self.pending_items:
                items: list[dict[str, Any]] = []
                for item in self.pending_items:
                    glyph = "note-pencil" if item.source == "note" else "tray"
                    for index, s_line in enumerate(item.summary_lines):
                        if len(items) >= 5:
                            break
                        items.append(list_item(f"queue:{item.id}:{index}", s_line, icon=glyph))
                    if len(items) >= 5:
                        break
                children.append(
                    card(
                        [
                            text(
                                f"Cola para el {DEVICE_NAME} ({len(self.pending_items)} lote(s))",
                                size="small",
                                bold=True,
                            ),
                            list_view(items),
                            row(
                                [
                                    button(
                                        "sync_phone",
                                        label=f"Enviar al {DEVICE_NAME}",
                                        icon="paper-plane-tilt",
                                        primary=True,
                                    ),
                                    button("clear_inbox", label="Limpiar", icon="trash"),
                                ],
                                gap=8,
                            ),
                        ],
                        padding=8,
                        gap=6,
                    )
                )

            children.append(
                text("/ip <dirección> cambia el destino · /nota guarda directo en Notas", size="small", color=FAINT)
            )

            return page_msg(
                column(children, gap=8, scroll=True),
                actions=[
                    {
                        "id": "connect",
                        "icon": "arrows-clockwise",
                        "tooltip": f"Reconectar {DEVICE_NAME}",
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

    def _complete_note(self, text_value: str, category: NoteCategory) -> None:
        """Queue a note for the Galaxy S24+ Notes module (no LLM), then auto-dispatch if enabled."""
        payload = IngestPayload(
            source="nook-desktop",
            notes=[NoteItem(category=category, text=text_value)],
        )
        with self._lock:
            self._capture_seq += 1
            queued_item = self.outbox.enqueue(
                raw_text=text_value,
                payload=payload,
                source="note",
                item_id=f"note_{self._capture_seq}_{payload.sentAt}",
            )
            self.pending_items = self.outbox.load_items()
            self.last_preview_lines = payload.format_preview_lines()
            self.last_error = None

        if self.config.auto_sync_captures and self.dispatcher is not None:
            with self._lock:
                self.is_syncing = True
            if self.on_async_update is not None:
                self.on_async_update(self)
            self._execute_sync()
            return

        with self._lock:
            self.last_sync_info = f"📝 Nota en cola ({queued_item.id})"
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
                self.last_sync_at = datetime.now()
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

                note = parse_note_command(value)
                if note is not None:
                    category, note_text = note
                    with self._lock:
                        self.input_value = ""
                    if not note_text:
                        return True
                    if self.async_inference:
                        self._spawn_worker(self._complete_note, note_text, category)
                    else:
                        self._complete_note(note_text, category)
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
