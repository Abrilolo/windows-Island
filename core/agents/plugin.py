"""Nook live plugin state for one agent: performance summary, recent sessions, and stages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import sys
import threading
from typing import Any, Callable

from core.agents.logs import (
    iter_claude_session_files,
    iter_codex_session_files,
    iter_gemini_session_files,
    parse_claude_session,
    parse_codex_session,
    parse_gemini_session,
)
from core.agents.models import SessionSummary
from core.agents.stats import Performance, SessionCache, summarize, within_days
from core.protocol import (
    badge_msg,
    badge_pulse,
    button,
    card,
    column,
    emit,
    page_msg,
    row,
    text,
    tile_msg,
)

WINDOW_DAYS = 7
RECENT_LIMIT = 8
ACTIVE_WINDOW = timedelta(minutes=2)
SESSION_PREFIX = "sess:"


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    label: str
    list_files: Callable[[], list]
    parse: Callable[[Any], SessionSummary]


AGENTS: dict[str, AgentSpec] = {
    "claude": AgentSpec("claude", "Claude", iter_claude_session_files, parse_claude_session),
    "codex": AgentSpec("codex", "Codex", iter_codex_session_files, parse_codex_session),
    "gemini": AgentSpec("gemini", "Gemini", iter_gemini_session_files, parse_gemini_session),
}


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


class AgentMonitorState:
    """Holds the scanned sessions and the selected session; builds tile, page, and badge."""

    def __init__(self, spec: AgentSpec, *, now: Callable[[], datetime] | None = None) -> None:
        self.spec = spec
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._cache = SessionCache(spec.parse)
        self._lock = threading.RLock()
        self.sessions: list[SessionSummary] = []
        self.selected_id: str | None = None
        self.last_error: str | None = None

    # --- data ---

    def refresh(self) -> None:
        with self._lock:
            try:
                self.sessions = self._cache.load(self.spec.list_files())
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 - surface any parser/IO failure in the UI
                self.last_error = f"{type(exc).__name__}: {exc}"

    def _recent(self) -> list[SessionSummary]:
        return within_days(self.sessions, WINDOW_DAYS, self._now())

    def _selected(self) -> SessionSummary | None:
        for session in self.sessions:
            if session.session_id == self.selected_id:
                return session
        return None

    def _is_active(self) -> bool:
        cutoff = self._now() - ACTIVE_WINDOW
        return any(s.ended_at is not None and s.ended_at >= cutoff for s in self.sessions)

    # --- events ---

    def handle_message(self, msg: dict[str, Any]) -> bool:
        if msg.get("type") != "event":
            return False
        control_id = str(msg.get("id") or "")
        kind = msg.get("kind")
        with self._lock:
            if control_id == "refresh" and kind == "click":
                self.refresh()
                return True
            if control_id == "close_detail" and kind == "click":
                self.selected_id = None
                return True
            if control_id.startswith(SESSION_PREFIX) and kind == "click":
                self.selected_id = control_id[len(SESSION_PREFIX):]
                return True
        return False

    # --- views ---

    def build_tile(self) -> dict[str, Any]:
        with self._lock:
            recent = self._recent()
            if self.last_error:
                subtitle = "Error leyendo logs"
            else:
                subtitle = f"{len(recent)} sesiones · últimos {WINDOW_DAYS} días"
            return tile_msg(
                column(
                    [
                        text(self.spec.label, size="body", bold=True),
                        text(subtitle, size="small", color="muted"),
                    ],
                    gap=2,
                )
            )

    def build_badge(self) -> dict[str, Any]:
        with self._lock:
            return badge_msg(badge_pulse() if self._is_active() else None)

    def build_page(self) -> dict[str, Any]:
        with self._lock:
            recent = self._recent()
            perf = summarize(recent)
            children: list[dict[str, Any]] = [
                row(
                    [
                        text(f"{self.spec.label} · últimos {WINDOW_DAYS} días", bold=True),
                        button("refresh", icon="arrows-clockwise"),
                    ],
                    justify="space-between",
                )
            ]
            if self.last_error:
                children.append(text(self.last_error, size="small", color="muted", mono=True))

            children.append(self._performance_card(perf))
            children.append(self._sessions_card(recent))

            selected = self._selected()
            if selected is not None:
                children.append(self._stages_card(selected))
            return page_msg(column(children, gap=8))

    def _performance_card(self, perf: Performance) -> dict[str, Any]:
        tools = ", ".join(f"{name} ×{count}" for name, count in perf.top_tools) or "—"
        return card(
            [
                text("Rendimiento", size="small", bold=True),
                text(
                    f"Sesiones: {perf.sessions} · Tiempo total: {_fmt_duration(perf.total_duration_s)}"
                    f" · Mediana: {_fmt_duration(perf.median_duration_s)}",
                    size="small",
                ),
                text(
                    f"Tool calls: {perf.tool_calls} · Errores: {perf.tool_errors}"
                    f" ({perf.error_rate:.0%})",
                    size="small",
                ),
                text(
                    f"Tokens in {_fmt_tokens(perf.input_tokens)} · out {_fmt_tokens(perf.output_tokens)}",
                    size="small",
                ),
                text(f"Top herramientas: {tools}", size="small", color="muted"),
            ],
            padding=8,
            gap=4,
        )

    def _sessions_card(self, recent: list[SessionSummary]) -> dict[str, Any]:
        children: list[dict[str, Any]] = [text("Sesiones recientes", size="small", bold=True)]
        if not recent:
            children.append(text("No hay sesiones en este periodo.", size="small", color="muted"))
        for session in recent[:RECENT_LIMIT]:
            label = f"{session.title[:40]} · {_fmt_duration(session.duration_s)}"
            children.append(
                button(f"{SESSION_PREFIX}{session.session_id}", label=label, icon="list-bullets")
            )
        return card(children, padding=8, gap=6)

    def _stages_card(self, session: SessionSummary) -> dict[str, Any]:
        children: list[dict[str, Any]] = [
            row(
                [
                    text(f"Etapas · {session.title[:50]}", size="small", bold=True),
                    button("close_detail", icon="x"),
                ],
                justify="space-between",
            ),
            text(
                f"Duración {_fmt_duration(session.duration_s)} · Turnos {session.user_turns}"
                f" · Tool calls {session.tool_calls} · Errores {session.tool_errors}",
                size="small",
                color="muted",
            ),
        ]
        stages = session.stages()
        if not stages:
            children.append(text("Sin herramientas registradas.", size="small", color="muted"))
        for index, (label, count) in enumerate(stages[:20], start=1):
            children.append(text(f"{index}. {label} ×{count}", size="small", mono=True))
        if len(stages) > 20:
            children.append(text(f"… {len(stages) - 20} etapas más", size="small", color="muted"))
        return card(children, padding=8, gap=4)


def render_all(state: AgentMonitorState) -> None:
    emit(state.build_tile())
    emit(state.build_page())
    emit(state.build_badge())


def run_loop(agent_id: str) -> None:
    """Stdio JSON-Lines loop for a Nook live plugin bound to one agent."""
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    state = AgentMonitorState(AGENTS[agent_id])
    state.refresh()
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


if __name__ == "__main__":
    run_loop("claude")
