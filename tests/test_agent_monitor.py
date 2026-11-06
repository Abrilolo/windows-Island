"""Tests for the Claude/Codex session monitor parsers, stats, and Nook view."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from core.agents.logs import (
    iter_claude_session_files,
    iter_codex_session_files,
    parse_claude_session,
    parse_codex_session,
)
from core.agents.models import SessionSummary, stage_for_tool
from dataclasses import replace

from core.agents.plugin import AGENTS, AgentMonitorState, SESSION_PREFIX
from core.agents.stats import SessionCache, summarize, within_days

T0 = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)


def _ts(seconds: int) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def _claude_fixture(path: Path) -> Path:
    usage = {"input_tokens": 10, "output_tokens": 5}
    return _write_jsonl(
        path,
        [
            {"type": "user", "timestamp": _ts(0), "sessionId": "sess-claude", "message": {"role": "user", "content": "Arregla el parser de logs"}},
            {"type": "assistant", "timestamp": _ts(5), "message": {"id": "m1", "usage": usage, "content": [
                {"type": "tool_use", "id": "t1", "name": "Read"},
                {"type": "tool_use", "id": "t2", "name": "Grep"},
            ]}},
            # Same message id repeated (streamed block): usage must not double count, tool id dedupes.
            {"type": "assistant", "timestamp": _ts(6), "message": {"id": "m1", "usage": usage, "content": [
                {"type": "tool_use", "id": "t2", "name": "Grep"},
            ]}},
            {"type": "user", "timestamp": _ts(7), "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "boom"},
            ]}},
            {"type": "assistant", "timestamp": _ts(20), "message": {"id": "m2", "usage": {"input_tokens": 3, "output_tokens": 7}, "content": [
                {"type": "tool_use", "id": "t3", "name": "Edit"},
                {"type": "tool_use", "id": "t4", "name": "Edit"},
            ]}},
            {"type": "ai-title", "timestamp": _ts(21), "aiTitle": "Parser de logs"},
        ],
    )


def _codex_fixture(path: Path) -> Path:
    return _write_jsonl(
        path,
        [
            {"type": "session_meta", "timestamp": _ts(0), "payload": {"id": "sess-codex", "cwd": "C:\\work\\nook-bridge"}},
            {"type": "event_msg", "timestamp": _ts(1), "payload": {"type": "task_started"}},
            {"type": "response_item", "timestamp": _ts(2), "payload": {"type": "custom_tool_call", "name": "exec"}},
            {"type": "event_msg", "timestamp": _ts(3), "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 100, "output_tokens": 10}}}},
            {"type": "response_item", "timestamp": _ts(4), "payload": {"type": "function_call", "name": "apply_patch"}},
            {"type": "event_msg", "timestamp": _ts(9), "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 250, "output_tokens": 40}}}},
            {"type": "event_msg", "timestamp": _ts(10), "payload": {"type": "task_complete"}},
        ],
    )


def test_stage_mapping_and_collapse() -> None:
    assert stage_for_tool("Read") == "explorar"
    assert stage_for_tool("Edit") == "editar"
    assert stage_for_tool("Bash") == "ejecutar"
    assert stage_for_tool("mcp__x__frobnicate") == "otro"  # must not match "cat"
    assert stage_for_tool("mcp__github__get_issue") == "explorar"

    session = SessionSummary(agent="claude", session_id="s", title="t", path="p")
    session.tool_names = ["Read", "Grep", "Edit", "Edit", "Bash"]
    assert session.stages() == [("explorar", 2), ("editar", 2), ("ejecutar", 1)]


def test_parse_claude_session(tmp_path: Path) -> None:
    summary = parse_claude_session(_claude_fixture(tmp_path / "proj" / "abc.jsonl"))

    assert summary.agent == "claude"
    assert summary.session_id == "sess-claude"
    assert summary.title == "Parser de logs"  # ai-title wins over first prompt
    assert summary.user_turns == 1
    assert summary.tool_calls == 4  # Read, Grep, Edit, Edit (duplicated Grep ignored)
    assert summary.tool_errors == 1
    assert summary.input_tokens == 13  # m1 counted once, plus m2
    assert summary.output_tokens == 12
    assert summary.duration_s == 21.0  # ai-title record at t=21s counts as activity


def test_parse_codex_session(tmp_path: Path) -> None:
    summary = parse_codex_session(_codex_fixture(tmp_path / "rollout-x.jsonl"))

    assert summary.agent == "codex"
    assert summary.session_id == "sess-codex"
    assert summary.title == "nook-bridge"
    assert summary.user_turns == 1
    assert summary.tool_names == ["exec", "apply_patch"]
    assert summary.input_tokens == 250  # cumulative counter: last value wins
    assert summary.output_tokens == 40
    assert summary.duration_s == 10.0


def test_file_discovery_skips_subagents(tmp_path: Path) -> None:
    _claude_fixture(tmp_path / "proj" / "top.jsonl")
    _claude_fixture(tmp_path / "proj" / "subagents" / "nested.jsonl")
    files = iter_claude_session_files(tmp_path)
    assert [p.name for p in files] == ["top.jsonl"]

    _codex_fixture(tmp_path / "2026" / "11" / "04" / "rollout-a.jsonl")
    assert [p.name for p in iter_codex_session_files(tmp_path)] == ["rollout-a.jsonl"]


def test_summarize_and_window(tmp_path: Path) -> None:
    fresh = parse_claude_session(_claude_fixture(tmp_path / "p" / "a.jsonl"))
    old_path = _write_jsonl(
        tmp_path / "p" / "old.jsonl",
        [{"type": "user", "timestamp": "2020-01-01T00:00:00Z", "message": {"content": "viejo"}}],
    )
    old = parse_claude_session(old_path)

    now = T0 + timedelta(hours=1)
    recent = within_days([old, fresh], days=7, now=now)
    assert recent == [fresh]

    perf = summarize(recent)
    assert perf.sessions == 1
    assert perf.tool_calls == 4
    assert perf.error_rate == 0.25
    assert perf.top_tools[0] == ("Edit", 2)


def test_cache_reparses_only_on_change(tmp_path: Path) -> None:
    path = _claude_fixture(tmp_path / "p" / "c.jsonl")
    calls: list[Path] = []

    def parse(p: Path) -> SessionSummary:
        calls.append(p)
        return parse_claude_session(p)

    cache = SessionCache(parse)
    cache.load([path])
    cache.load([path])
    assert len(calls) == 1

    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")  # size changes
    cache.load([path])
    assert len(calls) == 2


def test_nook_view_selects_session_and_shows_stages(tmp_path: Path) -> None:
    _claude_fixture(tmp_path / "p" / "abc.jsonl")
    spec = replace(AGENTS["claude"], list_files=lambda: iter_claude_session_files(tmp_path))
    state = AgentMonitorState(spec, now=lambda: T0 + timedelta(hours=1))
    state.refresh()

    tile = state.build_tile()
    assert "1 sesiones" in json.dumps(tile, ensure_ascii=False)
    assert state.build_badge() == {"type": "badge", "badge": None}

    page_text = json.dumps(state.build_page(), ensure_ascii=False)
    assert f"{SESSION_PREFIX}sess-claude" in page_text
    assert "Etapas" not in page_text

    assert state.handle_message({"type": "event", "id": f"{SESSION_PREFIX}sess-claude", "kind": "click"})
    detail = json.dumps(state.build_page(), ensure_ascii=False)
    assert "Etapas" in detail
    assert "1. explorar ×2" in detail

    assert state.handle_message({"type": "event", "id": "close_detail", "kind": "click"})
    assert "Etapas" not in json.dumps(state.build_page(), ensure_ascii=False)


def test_nook_view_pulses_when_session_is_active(tmp_path: Path) -> None:
    _claude_fixture(tmp_path / "p" / "abc.jsonl")
    spec = replace(AGENTS["claude"], list_files=lambda: iter_claude_session_files(tmp_path))
    state = AgentMonitorState(spec, now=lambda: T0 + timedelta(seconds=30))
    state.refresh()
    assert state.build_badge()["badge"] == {"kind": "pulse"}
