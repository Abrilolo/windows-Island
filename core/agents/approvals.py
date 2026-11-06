"""Pending tool-approval requests coming from agent hooks (Claude Code / Codex `PermissionRequest`).

The hook process blocks on `ApprovalBroker.wait()` while the island shows the request.
Outcomes:
- "allow" / "deny": the user decided on the island; the hook returns that decision to the agent.
- None: no decision (timeout, "answer in terminal", or plugin shutdown); the hook returns nothing and
  the agent falls back to its normal terminal prompt. We never decide on the user's behalf.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import secrets
import threading
import time
from typing import Any, Callable

ALLOW = "allow"
DENY = "deny"
TERMINAL = "terminal"  # release the hook without a decision
DECISIONS = {ALLOW, DENY, TERMINAL}

SUMMARY_LIMIT = 400


@dataclass
class ApprovalRequest:
    request_id: str
    agent: str
    tool_name: str
    summary: str
    description: str
    cwd: str
    session_id: str
    created_at: float
    expires_at: float
    decision: str | None = None
    _done: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def project(self) -> str:
        """Last path component of the session's working directory."""
        cleaned = self.cwd.replace("\\", "/").rstrip("/")
        return cleaned.rsplit("/", 1)[-1] if cleaned else ""

    def seconds_left(self, now: float | None = None) -> int:
        return max(0, int(self.expires_at - (now if now is not None else time.time())))


def summarize_tool_input(tool_name: str, tool_input: Any) -> tuple[str, str]:
    """Return (summary, description) for the island: the command/path first, the reason second."""
    description = ""
    if isinstance(tool_input, dict):
        description = str(tool_input.get("description") or "")
        for key in ("command", "file_path", "path", "url", "pattern", "notebook_path"):
            value = tool_input.get(key)
            if value:
                return _clip(str(value)), description
        if tool_input:
            return _clip(json.dumps(tool_input, ensure_ascii=False)), description
        return tool_name, description
    if tool_input:
        return _clip(str(tool_input)), description
    return tool_name, description


def _clip(value: str) -> str:
    value = value.strip()
    return value if len(value) <= SUMMARY_LIMIT else value[: SUMMARY_LIMIT - 1] + "…"


class ApprovalBroker:
    """Thread-safe registry of pending approvals; notifies the UI on every change."""

    def __init__(
        self,
        *,
        wait_timeout: float = 120.0,
        on_change: Callable[[], None] | None = None,
        on_new_request: Callable[[ApprovalRequest], None] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.wait_timeout = wait_timeout
        self._on_change = on_change
        self._on_new_request = on_new_request
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: dict[str, ApprovalRequest] = {}

    def submit(self, agent: str, payload: dict[str, Any]) -> ApprovalRequest:
        tool_name = str(payload.get("tool_name") or "tool")
        summary, description = summarize_tool_input(tool_name, payload.get("tool_input"))
        now = self._clock()
        request = ApprovalRequest(
            request_id=secrets.token_hex(4),
            agent=agent,
            tool_name=tool_name,
            summary=summary,
            description=description,
            cwd=str(payload.get("cwd") or ""),
            session_id=str(payload.get("session_id") or ""),
            created_at=now,
            expires_at=now + self.wait_timeout,
        )
        with self._lock:
            self._pending[request.request_id] = request
        if self._on_new_request:
            self._on_new_request(request)
        self._changed()
        return request

    def wait(self, request: ApprovalRequest, timeout: float | None = None) -> str | None:
        """Block until the user decides or the timeout passes. Returns "allow", "deny" or None."""
        request._done.wait(self.wait_timeout if timeout is None else timeout)
        with self._lock:
            self._pending.pop(request.request_id, None)
        self._changed()
        return request.decision if request.decision in (ALLOW, DENY) else None

    def resolve(self, request_id: str, decision: str) -> bool:
        if decision not in DECISIONS:
            return False
        with self._lock:
            request = self._pending.pop(request_id, None)
        if request is None:
            return False
        request.decision = decision
        request._done.set()
        self._changed()
        return True

    def release_all(self) -> None:
        """Let every waiting hook go without a decision (plugin shutting down)."""
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for request in pending:
            request._done.set()
        if pending:
            self._changed()

    def pending(self) -> list[ApprovalRequest]:
        with self._lock:
            return sorted(self._pending.values(), key=lambda r: r.created_at)

    def _changed(self) -> None:
        if self._on_change:
            self._on_change()
