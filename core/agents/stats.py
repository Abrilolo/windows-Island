"""Aggregation over parsed sessions plus an mtime-keyed parse cache."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Callable, Iterable

from core.agents.models import SessionSummary


@dataclass(frozen=True)
class Performance:
    sessions: int
    total_duration_s: float
    median_duration_s: float | None
    tool_calls: int
    tool_errors: int
    input_tokens: int
    output_tokens: int
    top_tools: list[tuple[str, int]]

    @property
    def error_rate(self) -> float:
        return self.tool_errors / self.tool_calls if self.tool_calls else 0.0


def summarize(sessions: Iterable[SessionSummary], top_n: int = 3) -> Performance:
    items = list(sessions)
    durations = [s.duration_s for s in items if s.duration_s is not None]
    tools: Counter[str] = Counter()
    for session in items:
        tools.update(session.tool_names)
    return Performance(
        sessions=len(items),
        total_duration_s=sum(durations),
        median_duration_s=median(durations) if durations else None,
        tool_calls=sum(s.tool_calls for s in items),
        tool_errors=sum(s.tool_errors for s in items),
        input_tokens=sum(s.input_tokens for s in items),
        output_tokens=sum(s.output_tokens for s in items),
        top_tools=tools.most_common(top_n),
    )


def within_days(
    sessions: Iterable[SessionSummary], days: int, now: datetime
) -> list[SessionSummary]:
    """Sessions that started within the last `days` days, newest first."""
    cutoff = now - timedelta(days=days)
    recent = [s for s in sessions if s.started_at is not None and s.started_at >= cutoff]
    return sorted(recent, key=lambda s: s.started_at or cutoff, reverse=True)


class SessionCache:
    """Re-parses a log file only when its mtime or size changes."""

    def __init__(self, parse: Callable[[Path], SessionSummary]) -> None:
        self._parse = parse
        self._entries: dict[str, tuple[float, int, SessionSummary]] = {}

    def load(self, paths: Iterable[Path]) -> list[SessionSummary]:
        result: list[SessionSummary] = []
        live_keys: set[str] = set()
        for path in paths:
            key = str(path)
            try:
                stat = path.stat()
            except OSError:
                continue
            live_keys.add(key)
            cached = self._entries.get(key)
            if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
                result.append(cached[2])
                continue
            try:
                summary = self._parse(path)
            except OSError:
                continue
            self._entries[key] = (stat.st_mtime, stat.st_size, summary)
            result.append(summary)
        for stale in set(self._entries) - live_keys:
            del self._entries[stale]
        return result
