"""Stateful Nook live plugin connected to `OllamaBrain`, `OutboxStore`, and `PhoneDispatcher`."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
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
from sync.config import BridgeConfig, normalize_phone_url
from sync.dispatcher import PhoneDispatcher
from sync.outbox import OutboxStore, QueuedItem

# Re-export PendingItem alias for backwards compatibility
PendingItem = QueuedItem


@dataclass
class BridgeState:
    """Thread-safe UI, Ollama inference, and persistent offline outbox state for Nook."""

    brain: OllamaBrain = field(default_factory=OllamaBrain)
    config: BridgeConfig = field(default_factory=BridgeConfig.load)
    outbox: OutboxStore = field(default_factory=OutboxStore)
    dispatcher: PhoneDispatcher | None = None
    async_inference: bool = True
    on_async_update: Callable[[BridgeState], None] | None = None

    status_text: str = "Listo"
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

    def total_structured_entities(self) -> int:
        with self._lock:
            return sum(item.payload.total_items() for item in self.pending_items)

    def build_tile(self) -> dict[str, Any]:
        with self._lock:
            if self.is_analyzing:
                subtitle = "🧠 Analizando con IA..."
            elif self.is_syncing:
                subtitle = "📡 Enviando al S24+..."
            elif self.pending_items:
                subtitle = (
                    f"{len(self.pending_items)} en cola "
                    f"({self.total_structured_entities()} ítems)"
                )
            else:
                subtitle = self.status_text

            return tile_msg(
                column(
                    [
                        row(
                            [
                                text("Minimal Bridge", size="body", bold=True),
                            ],
                            gap=6,
                        ),
                        text(subtitle, size="small", color="muted"),
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
            children: list[dict[str, Any]] = [
                text_input(
                    "quick_capture",
                    value=self.input_value,
                    hint="Ej. Comí 200g de pollo, gasté 120 en café (o /ip 192.168.3.164)",
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
                if self.last_sync_info:
                    preview_nodes.append(
                        text(self.last_sync_info, size="small", color="muted")
                    )
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
            else:
                status_line = (
                    self.last_sync_info
                    or f"Sin pendientes · Destino: {self.config.phone_ingest_url}"
                )
                children.append(
                    card(
                        [
                            text(
                                status_line,
                                size="small",
                                color="muted",
                            )
                        ],
                        padding=8,
                    )
                )

            return page_msg(
                column(children, gap=8, scroll=True),
                actions=[
                    {
                        "id": "sync_phone",
                        "icon": "arrows-clockwise",
                        "tooltip": f"Sincronizar con {self.config.phone_ingest_url}",
                    }
                ],
            )

    def wait_pending_workers(self, timeout: float = 5.0) -> None:
        """Wait for any in-flight background Ollama or HTTP sync threads to complete."""
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
            self.status_text = (
                "En cola (fallback)"
                if outcome.used_fallback
                else f"En cola ({outcome.payload.total_items()} ítems)"
            )
        if self.on_async_update is not None:
            self.on_async_update(self)

    def _execute_sync(self) -> None:
        """Flush `outbox.json` to the Galaxy S24+ and update UI state."""
        assert self.dispatcher is not None
        with self._lock:
            items_snapshot = list(self.pending_items)

        result = self.dispatcher.flush_outbox(items_snapshot)
        with self._lock:
            self.is_syncing = False
            self.pending_items = self.outbox.load_items()
            if result.delivered:
                self.status_text = f"✅ Enviado ({result.sent_entities})"
                self.last_sync_info = (
                    f"✅ Enviado al S24+ ({result.sent_entities} ítems) -> {result.endpoint_url}"
                )
            else:
                self.status_text = f"📥 En cola ({len(self.pending_items)})"
                self.last_sync_info = (
                    f"📥 En cola local · {result.error_message}"
                )

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
                        self.status_text = "IP actualizada"
                        self.last_sync_info = (
                            f"📱 Nuevo endpoint S24+: {self.config.phone_ingest_url}"
                        )
                    return True

                with self._lock:
                    self.last_capture = value
                    self.input_value = ""
                    self.is_analyzing = True
                    self.status_text = "Analizando con IA..."

                if self.async_inference:
                    self._spawn_worker(self._complete_capture, value)
                else:
                    self._complete_capture(value)
                return True

            if control_id == "sync_phone" and kind == "click":
                with self._lock:
                    if not self.pending_items:
                        self.status_text = "Cola vacía"
                        return True
                    self.is_syncing = True
                    self.status_text = "Sincronizando..."

                if self.async_inference:
                    self._spawn_worker(self._execute_sync)
                else:
                    self._execute_sync()
                return True

            if control_id == "clear_inbox" and kind == "click":
                with self._lock:
                    self.outbox.clear()
                    self.pending_items.clear()
                    self.last_preview_lines.clear()
                    self.last_error = None
                    self.last_sync_info = "🗑️ Cola local vaciada"
                    self.status_text = "Bandeja limpia"
                return True

        elif msg_type in ("page_open", "hotkey"):
            with self._lock:
                self.pending_items = self.outbox.load_items()
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
        on_async_update=render_all if async_inference else None,
    )
    render_all(state)

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
