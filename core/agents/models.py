"""Normalized session summary shared by the Claude, Codex, and Gemini log parsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re

# Stage label -> tool-name words. Names are split into words (e.g. "apply_patch" -> "apply", "patch")
# and matched whole, so "frobnicate" does not match "cat". First matching stage wins.
_STAGE_RULES: tuple[tuple[str, frozenset[str]], ...] = (
    ("explorar", frozenset({"read", "grep", "glob", "search", "list", "view", "cat", "get", "rg", "ls"})),
    ("editar", frozenset({"edit", "write", "patch", "multiedit", "notebook"})),
    ("ejecutar", frozenset({"bash", "shell", "exec", "powershell", "run", "test", "command"})),
)
_WORD_SPLIT = re.compile(r"[^a-z]+")


def stage_for_tool(tool_name: str) -> str:
    """Map a raw tool name to a human-readable stage label."""
    words = {w for w in _WORD_SPLIT.split(tool_name.lower()) if w}
    for label, keywords in _STAGE_RULES:
        if words & keywords:
            return label
    return "otro"


@dataclass
class SessionSummary:
    """Metrics for one agent session, parsed from its local log file."""

    agent: str
    session_id: str
    title: str
    path: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    user_turns: int = 0
    tool_errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_names: list[str] = field(default_factory=list)
    pending_approval: str | None = None

    @property
    def tool_calls(self) -> int:
        return len(self.tool_names)

    @property
    def duration_s(self) -> float | None:
        if self.started_at is None or self.ended_at is None:
            return None
        return max(0.0, (self.ended_at - self.started_at).total_seconds())

    def stages(self) -> list[tuple[str, int]]:
        """Collapse consecutive tool calls of the same stage into (label, count) runs."""
        runs: list[tuple[str, int]] = []
        for name in self.tool_names:
            label = stage_for_tool(name)
            if runs and runs[-1][0] == label:
                runs[-1] = (label, runs[-1][1] + 1)
            else:
                runs.append((label, 1))
        return runs
