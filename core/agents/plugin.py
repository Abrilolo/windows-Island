"""Fenn live plugin "AI Agents": Claude Code, Codex and Gemini in one tile.

- Tile (large): "N activos", 14-day activity sparkline, one icon per agent (lit when active).
- Page: pending approvals, one card per agent (sparkline + success ring), recent sessions, stages.
- Approvals arrive from agent hooks through the local HookServer (see core/agents/hook_server.py).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
import sys
import threading
from typing import Any, Callable

from core.agents.approvals import ALLOW, DENY, TERMINAL, ApprovalBroker, ApprovalRequest
from core.agents.hook_server import AGENT_FIELD, HOOK_PORT, HookServer, plugin_data_dir
from core.agents.logs import (
    iter_claude_session_files,
    iter_codex_session_files,
    iter_gemini_session_files,
    parse_claude_session,
    parse_codex_session,
    parse_gemini_session,
)
from core.agents.models import SessionSummary, stage_for_tool
from core.agents.stats import Performance, SessionCache, summarize, within_days
from core.protocol import (
    active_msg,
    badge_glyph,
    badge_msg,
    badge_pulse,
    button,
    card,
    column,
    emit,
    grid,
    icon,
    list_item,
    list_view,
    page_msg,
    progress,
    ring,
    row,
    show_msg,
    spacer,
    sparkline,
    text,
    tile_msg,
)

PLUGIN_ID = "ai-agents"
WINDOW_DAYS = 7
ACTIVITY_DAYS = 14
RECENT_LIMIT = 8
ACTIVE_WINDOW = timedelta(minutes=2)
SESSION_PREFIX = "sess:"  # sess:<agent>:<session_id>
APPROVAL_PREFIX = "appr:"  # appr:<allow|deny|terminal>:<request_id>
APPROVAL_WAIT_SECONDS = float(os.environ.get("FENN_AGENT_APPROVAL_TIMEOUT", "120"))

GREEN = "green"
ORANGE = "orange"


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    label: str
    list_files: Callable[[], list]
    parse: Callable[[Any], SessionSummary]
    icon: str = "robot"
    color: str = "accent"


AGENTS: dict[str, AgentSpec] = {
    "claude": AgentSpec(
        "claude", "Claude Code", iter_claude_session_files, parse_claude_session, "asterisk", "#D97757"
    ),
    "codex": AgentSpec(
        "codex", "Codex", iter_codex_session_files, parse_codex_session, "open-ai-logo", "#10A37F"
    ),
    "gemini": AgentSpec(
        "gemini", "Gemini", iter_gemini_session_files, parse_gemini_session, "sparkle", "#4F8EF7"
    ),
}

HOOK_EVENT_LABELS = {
    "Stop": "terminó su turno",
    "SessionStart": "sesión iniciada",
    "SessionEnd": "sesión cerrada",
}
STAGE_ORDER = ("explorar", "editar", "ejecutar", "otro")
STAGE_COLORS = {"explorar": "blue", "editar": "purple", "ejecutar": "teal", "otro": "faint"}


# --- formatting ---------------------------------------------------------------


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _fmt_tokens(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return str(value)


def _fmt_ago(moment: datetime | None, now: datetime) -> str:
    if moment is None:
        return "—"
    seconds = max(0, int((now - moment).total_seconds()))
    if seconds < 90:
        return "ahora"
    if seconds < 3600:
        return f"hace {seconds // 60} min"
    if seconds < 86400:
        return f"hace {seconds // 3600} h"
    return f"hace {seconds // 86400} d"


def _project_name(cwd: str) -> str:
    cleaned = cwd.replace("\\", "/").rstrip("/")
    return cleaned.rsplit("/", 1)[-1] if cleaned else ""


def _activos(count: int) -> str:
    return f"{count} activo" if count == 1 else f"{count} activos"


def _status_dot(on: bool) -> dict[str, Any]:
    return icon("circle", size=8, color=GREEN if on else "faint", fill=True)


# --- state --------------------------------------------------------------------


class AiAgentsState:
    """Sessions of every agent, pending approvals, and the views built from them."""

    def __init__(
        self,
        specs: list[AgentSpec] | None = None,
        *,
        now: Callable[[], datetime] | None = None,
        broker: ApprovalBroker | None = None,
    ) -> None:
        self.specs = specs if specs is not None else list(AGENTS.values())
        self.broker = broker
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._caches = {spec.agent_id: SessionCache(spec.parse) for spec in self.specs}
        self._lock = threading.RLock()
        self.sessions: dict[str, list[SessionSummary]] = {spec.agent_id: [] for spec in self.specs}
        self.errors: dict[str, str] = {}
        self.selected: tuple[str, str] | None = None
        self.tile_size = "large"
        self.hooks_status: str | None = None
        self.last_event: str | None = None

    def spec(self, agent_id: str) -> AgentSpec | None:
        return next((s for s in self.specs if s.agent_id == agent_id), None)

    # --- data ---

    def refresh(self) -> None:
        with self._lock:
            for spec in self.specs:
                try:
                    self.sessions[spec.agent_id] = self._caches[spec.agent_id].load(spec.list_files())
                    self.errors.pop(spec.agent_id, None)
                except Exception as exc:  # noqa: BLE001 - surface any parser/IO failure in the UI
                    self.errors[spec.agent_id] = f"{type(exc).__name__}: {exc}"

    def recent(self, agent_id: str | None = None) -> list[SessionSummary]:
        now = self._now()
        agents = [agent_id] if agent_id else [s.agent_id for s in self.specs]
        merged = [s for a in agents for s in within_days(self.sessions.get(a, []), WINDOW_DAYS, now)]
        return sorted(merged, key=lambda s: s.ended_at or s.started_at or now, reverse=True)

    def is_active(self, agent_id: str) -> bool:
        cutoff = self._now() - ACTIVE_WINDOW
        return any(s.ended_at is not None and s.ended_at >= cutoff for s in self.sessions.get(agent_id, []))

    def active_count(self) -> int:
        return sum(1 for spec in self.specs if self.is_active(spec.agent_id))

    def activity(self, agent_id: str | None = None, days: int = ACTIVITY_DAYS) -> list[int]:
        """Tool calls per local day, oldest first (the sparkline)."""
        today = self._now().astimezone().date()
        buckets = [0] * days
        agents = [agent_id] if agent_id else [s.agent_id for s in self.specs]
        for agent in agents:
            for session in self.sessions.get(agent, []):
                moment = session.started_at or session.ended_at
                if moment is None:
                    continue
                offset = (today - moment.astimezone().date()).days
                if 0 <= offset < days:
                    buckets[days - 1 - offset] += max(1, session.tool_calls)
        return buckets

    def pending_approvals(self) -> list[ApprovalRequest]:
        return self.broker.pending() if self.broker is not None else []

    def _selected_session(self) -> SessionSummary | None:
        if self.selected is None:
            return None
        agent, session_id = self.selected
        return next((s for s in self.sessions.get(agent, []) if s.session_id == session_id), None)

    # --- events ---

    def handle_message(self, msg: dict[str, Any]) -> bool:
        kind_of_msg = msg.get("type")
        if kind_of_msg == "layout":
            if msg.get("target") == "tile" and msg.get("size") in ("small", "wide", "large"):
                with self._lock:
                    changed = self.tile_size != msg["size"]
                    self.tile_size = msg["size"]
                return changed
            return False
        if kind_of_msg != "event":
            return False
        control_id = str(msg.get("id") or "")
        kind = msg.get("kind")
        if control_id.startswith(APPROVAL_PREFIX) and kind == "click":
            # The broker notifies on_change, which redraws; no redraw needed here.
            decision, _, request_id = control_id[len(APPROVAL_PREFIX):].partition(":")
            if self.broker is not None:
                self.broker.resolve(request_id, decision)
            return False
        with self._lock:
            if control_id == "refresh" and kind == "click":
                self.refresh()
                return True
            if control_id == "close_detail" and kind == "click":
                self.selected = None
                return True
            if control_id.startswith(SESSION_PREFIX) and kind == "click":
                agent, _, session_id = control_id[len(SESSION_PREFIX):].partition(":")
                self.selected = None if self.selected == (agent, session_id) else (agent, session_id)
                return True
        return False

    def handle_hook_event(self, payload: dict[str, Any]) -> None:
        """Non-blocking hook events (Stop, Notification, SessionStart, SessionEnd)."""
        event = str(payload.get("hook_event_name") or "")
        spec = self.spec(str(payload.get(AGENT_FIELD) or ""))
        who = spec.label if spec else "Agente"
        if event == "Notification":
            label = str(payload.get("message") or "notificación")
        else:
            label = HOOK_EVENT_LABELS.get(event, event or "evento")
        project = _project_name(str(payload.get("cwd") or ""))
        stamp = self._now().astimezone().strftime("%H:%M")
        with self._lock:
            self.last_event = f"{stamp} · {who}: {label}" + (f" · {project}" if project else "")
        if event in ("Stop", "SessionEnd"):
            self.refresh()

    # --- tile ---

    def build_tile(self) -> dict[str, Any]:
        pending = self.pending_approvals()
        if pending:
            return tile_msg(self._approval_tile(pending))
        with self._lock:
            if self.tile_size == "small":
                return tile_msg(self._small_tile())
            if self.tile_size == "wide":
                return tile_msg(self._wide_tile())
            return tile_msg(self._large_tile())

    def _status_line(self) -> dict[str, Any]:
        active = self.active_count()
        # Trailing spacer: Fenn then centers the row vertically without stretching it.
        return row(
            [_status_dot(active > 0), text(_activos(active), size="small", color=GREEN if active else "dim"), spacer()],
            gap=4,
            align="center",
        )

    def _large_tile(self) -> dict[str, Any]:
        agent_icons = [
            icon(
                spec.icon,
                size=14,
                color=spec.color if self.is_active(spec.agent_id) or self.recent(spec.agent_id) else "faint",
                fill=self.is_active(spec.agent_id),
            )
            for spec in self.specs
        ]
        # Flat rows only: a column nested in a row stretches to the full tile height in Fenn.
        return column(
            [
                row(
                    [icon("robot", size=16, color="accent", fill=True), text("AI Agents", size="small", bold=True, wrap=False), spacer()],
                    gap=4,
                    align="center",
                ),
                self._status_line(),
                sparkline(self.activity(), color="accent", height=24),
                row(agent_icons, gap=8),
            ],
            gap=4,
        )

    def _wide_tile(self) -> dict[str, Any]:
        active = self.active_count()
        return row(
            [
                icon("robot", size=18, color="accent", fill=True),
                text("AI Agents", size="small", bold=True, wrap=False),
                spacer(),
                _status_dot(active > 0),
                text(str(active), size="small", color=GREEN if active else "dim"),
            ],
            gap=4,
        )

    def _small_tile(self) -> dict[str, Any]:
        active = self.active_count()
        return column(
            [icon("robot", size=20, color="accent", fill=True), text(str(active), size="small", bold=True)],
            gap=0,
            align="center",
        )

    def _approval_tile(self, pending: list[ApprovalRequest]) -> dict[str, Any]:
        first = pending[0]
        spec = self.spec(first.agent)
        extra = f" +{len(pending) - 1}" if len(pending) > 1 else ""
        header = row(
            [icon("hand-palm", size=16, color=ORANGE, fill=True), text(f"Aprobación{extra}", size="small", bold=True, color=ORANGE)],
            gap=4,
        )
        if self.tile_size == "wide":
            return row([icon("hand-palm", size=16, color=ORANGE, fill=True),
                        text(first.summary, size="small", mono=True, wrap=False)], gap=4)
        if self.tile_size == "small":
            return icon("hand-palm", size=22, color=ORANGE, fill=True)
        who = row(
            [icon(spec.icon if spec else "robot", size=12, color=spec.color if spec else "accent"),
             text(spec.label if spec else first.agent, size="small", color="dim", wrap=False)],
            gap=4,
        )
        return column([header, who, text(first.summary, size="small", mono=True, wrap=False),
                       text("Toca para decidir", size="small", color="faint")], gap=3)

    # --- badge ---

    def build_badge(self) -> dict[str, Any]:
        if self.pending_approvals():
            return badge_msg(badge_pulse())
        with self._lock:
            return badge_msg(badge_glyph("robot") if self.active_count() else None)

    # --- page ---

    def build_page(self) -> dict[str, Any]:
        children: list[dict[str, Any]] = [self._approval_card(r) for r in self.pending_approvals()]
        with self._lock:
            recent = self.recent()
            children.append(self._page_header(recent))
            children.append(grid(len(self.specs), [self._agent_card(spec) for spec in self.specs], gap=8))
            children.append(self._sessions_section(recent))
            selected = self._selected_session()
            if selected is not None:
                children.append(self._stages_card(selected))
            footer = [f"Hooks: {self.hooks_status}"] if self.hooks_status else []
            if self.last_event:
                footer.append(f"Último evento: {self.last_event}")
            for line in footer:
                children.append(text(line, size="small", color="faint"))
            for agent, error in sorted(self.errors.items()):
                children.append(text(f"{agent}: {error}", size="small", color="red", mono=True))
            return page_msg(
                column(children, gap=10, scroll=True),
                actions=[{"id": "refresh", "icon": "arrows-clockwise", "tooltip": "Actualizar"}],
            )

    def _page_header(self, recent: list[SessionSummary]) -> dict[str, Any]:
        """Fenn already shows "AI Agents" and the back arrow above the page."""
        active = self.active_count()
        return row(
            [
                _status_dot(active > 0),
                text(_activos(active), size="small", bold=True, color=GREEN if active else "dim"),
                text(f"· {len(recent)} sesiones · últimos {WINDOW_DAYS} días", size="small", color="dim", wrap=False),
                spacer(),
            ],
            gap=6,
            align="center",
        )

    def _agent_card(self, spec: AgentSpec) -> dict[str, Any]:
        recent = self.recent(spec.agent_id)
        perf: Performance = summarize(recent)
        success = 1.0 - perf.error_rate if perf.tool_calls else 0.0
        ring_color = GREEN if success >= 0.9 else ORANGE if success >= 0.7 else "red"
        last = recent[0].ended_at if recent else None
        tokens = perf.input_tokens + perf.output_tokens
        return card(
            [
                row(
                    [
                        icon(spec.icon, size=18, color=spec.color, fill=self.is_active(spec.agent_id)),
                        text(spec.label, size="small", bold=True, wrap=False),
                        spacer(),
                        _status_dot(self.is_active(spec.agent_id)),
                    ],
                    gap=6,
                    align="center",
                ),
                text(f"{perf.sessions} sesiones · {_fmt_ago(last, self._now())}", size="small", color="dim", wrap=False),
                sparkline(self.activity(spec.agent_id), color=spec.color, height=30),
                row(
                    [
                        ring(success, label=f"{success:.0%}" if perf.tool_calls else "—", size=34, color=ring_color),
                        column(
                            [
                                text(f"{perf.tool_calls} tools", size="small", wrap=False),
                                text(
                                    f"{_fmt_tokens(tokens)} tokens" if tokens else "tokens: —",
                                    size="small",
                                    color="dim",
                                    wrap=False,
                                ),
                            ],
                            gap=0,
                        ),
                        spacer(),
                    ],
                    gap=8,
                    align="center",
                ),
            ],
            padding=10,
            gap=6,
        )

    def _sessions_section(self, recent: list[SessionSummary]) -> dict[str, Any]:
        header = text("Sesiones recientes", size="small", bold=True, color="dim")
        if not recent:
            return column([header, text("No hay sesiones en este periodo.", size="small", color="faint")], gap=4)
        now = self._now()
        items = []
        for session in recent[:RECENT_LIMIT]:
            spec = self.spec(session.agent) or AGENTS.get(session.agent)
            label = spec.label if spec else session.agent
            items.append(
                list_item(
                    f"{SESSION_PREFIX}{session.agent}:{session.session_id}",
                    session.title[:70] or "(sin título)",
                    subtitle=f"{label} · {_fmt_ago(session.ended_at, now)} · {session.tool_calls} tools",
                    icon=spec.icon if spec else "robot",
                    trailing=_fmt_duration(session.duration_s),
                    selected=self.selected == (session.agent, session.session_id),
                )
            )
        return column([header, list_view(items)], gap=4)

    def _stages_card(self, session: SessionSummary) -> dict[str, Any]:
        totals = Counter(stage_for_tool(name) for name in session.tool_names)
        biggest = max(totals.values(), default=0)
        children: list[dict[str, Any]] = [
            row(
                [
                    text(f"Etapas · {session.title[:50]}", size="small", bold=True),
                    spacer(),
                    button("close_detail", icon="x"),
                ]
            ),
            text(
                f"Duración {_fmt_duration(session.duration_s)} · Turnos {session.user_turns}"
                f" · Tool calls {session.tool_calls} · Errores {session.tool_errors}",
                size="small",
                color="dim",
            ),
        ]
        if not totals:
            children.append(text("Sin herramientas registradas.", size="small", color="dim"))
        for stage in STAGE_ORDER:
            count = totals.get(stage, 0)
            if not count:
                continue
            children.append(
                row(
                    [
                        text(stage, size="small", wrap=False),
                        spacer(),
                        text(f"×{count}", size="small", color="dim", mono=True),
                    ]
                )
            )
            children.append(progress(count / biggest, color=STAGE_COLORS[stage]))
        runs = session.stages()
        if runs:
            sequence = " → ".join(f"{label} ×{count}" for label, count in runs[:12])
            if len(runs) > 12:
                sequence += f" → … {len(runs) - 12} más"
            children.append(text(sequence, size="small", color="faint", mono=True))
        return card(children, padding=10, gap=4)

    def _approval_card(self, request: ApprovalRequest) -> dict[str, Any]:
        spec = self.spec(request.agent)
        where = f" · {request.project}" if request.project else ""
        body: list[dict[str, Any]] = [
            row(
                [
                    icon("hand-palm", color=ORANGE, fill=True),
                    icon(spec.icon if spec else "robot", size=16, color=spec.color if spec else "accent"),
                    text(f"{spec.label if spec else request.agent} pide permiso{where}", bold=True),
                    spacer(),
                    text(f"expira en {request.seconds_left()} s", size="small", color="dim"),
                ],
                gap=6,
            ),
            text(request.tool_name, size="small", color="dim"),
            text(request.summary, mono=True),
        ]
        if request.description:
            body.append(text(request.description, size="small", color="dim"))
        rid = request.request_id
        body.append(
            row(
                [
                    spacer(),
                    button(f"{APPROVAL_PREFIX}{TERMINAL}:{rid}", label="Terminal", icon="terminal-window"),
                    button(f"{APPROVAL_PREFIX}{DENY}:{rid}", label="Rechazar", icon="x"),
                    button(f"{APPROVAL_PREFIX}{ALLOW}:{rid}", label="Aprobar", icon="check", primary=True),
                ]
            )
        )
        return card(body, padding=12, gap=6)


# --- runtime -------------------------------------------------------------------


def render_all(state: AiAgentsState) -> None:
    emit(state.build_tile())
    emit(state.build_page())
    emit(state.build_badge())
    emit(active_msg(bool(state.pending_approvals())))


def start_hook_server(state: AiAgentsState) -> HookServer | None:
    """Start the local receiver for Claude Code / Codex hooks."""
    if state.broker is None:
        return None
    port = int(os.environ.get("FENN_AGENT_HOOK_PORT", HOOK_PORT))  # override for tests/dev (0 = random)

    def on_event(payload: dict[str, Any]) -> None:
        state.handle_hook_event(payload)
        render_all(state)

    try:
        server = HookServer("claude", state.broker, port=port, on_event=on_event)
    except OSError as exc:
        state.hooks_status = f"desactivados (puerto {port} ocupado)"
        print(f"[{PLUGIN_ID}] hook server disabled: {exc!r}", file=sys.stderr)
        return None
    server.start()
    server.write_endpoint_file(plugin_data_dir(PLUGIN_ID))
    state.hooks_status = f"escuchando en 127.0.0.1:{server.port}"
    return server


def run_loop() -> None:
    """Stdio JSON-Lines loop for the AI Agents live plugin."""
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    holder: dict[str, AiAgentsState] = {}

    def on_change() -> None:
        state_ref = holder.get("state")
        if state_ref is not None:
            render_all(state_ref)

    def on_new_request(_request: ApprovalRequest) -> None:
        emit(show_msg())  # open the notch, pinned on this plugin's page

    broker = ApprovalBroker(
        wait_timeout=APPROVAL_WAIT_SECONDS, on_change=on_change, on_new_request=on_new_request
    )
    state = AiAgentsState(broker=broker)
    state.refresh()
    server = start_hook_server(state)
    holder["state"] = state
    render_all(state)

    try:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "shutdown":
                break
            if state.handle_message(msg):
                render_all(state)
    finally:
        if server is not None:
            server.stop()


if __name__ == "__main__":
    run_loop()
