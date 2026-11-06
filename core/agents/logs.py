"""Parsers for local Claude Code, Codex, and Gemini/Antigravity session logs (JSON Lines)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Iterator

from core.agents.models import SessionSummary


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _iter_json_lines(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield record


def _touch_bounds(summary: SessionSummary, ts: datetime | None) -> None:
    if ts is None:
        return
    if summary.started_at is None or ts < summary.started_at:
        summary.started_at = ts
    if summary.ended_at is None or ts > summary.ended_at:
        summary.ended_at = ts


# --- Claude Code: ~/.claude/projects/<project>/<session>.jsonl ---


def claude_root() -> Path:
    override = os.environ.get("AGENT_MONITOR_CLAUDE_DIR")
    return Path(override) if override else Path.home() / ".claude" / "projects"


def iter_claude_session_files(root: Path | None = None) -> list[Path]:
    """Top-level session files only (subagent transcripts are folded into their parent)."""
    base = root or claude_root()
    if not base.is_dir():
        return []
    return sorted(base.glob("*/*.jsonl"))


def parse_claude_session(path: Path) -> SessionSummary:
    summary = SessionSummary(
        agent="claude",
        session_id=path.stem,
        title=path.stem,
        path=str(path),
    )
    seen_message_ids: set[str] = set()
    seen_tool_ids: set[str] = set()
    ai_title: str | None = None
    first_prompt: str | None = None

    for record in _iter_json_lines(path):
        _touch_bounds(summary, _parse_ts(record.get("timestamp")))
        session_id = record.get("sessionId")
        if isinstance(session_id, str) and session_id:
            summary.session_id = session_id

        kind = record.get("type")
        if kind == "ai-title":
            title = record.get("aiTitle")
            if isinstance(title, str) and title.strip():
                ai_title = title.strip()
            continue

        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        content = message.get("content")

        if kind == "user":
            if isinstance(content, str):
                if content.strip():
                    summary.user_turns += 1
                    first_prompt = first_prompt or content.strip()[:80]
            elif isinstance(content, list):
                has_text = False
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result" and block.get("is_error"):
                        summary.tool_errors += 1
                    elif block.get("type") == "text" and str(block.get("text", "")).strip():
                        has_text = True
                if has_text:
                    summary.user_turns += 1

        elif kind == "assistant":
            message_id = message.get("id")
            usage = message.get("usage")
            if isinstance(usage, dict) and (message_id is None or message_id not in seen_message_ids):
                if message_id is not None:
                    seen_message_ids.add(message_id)
                summary.input_tokens += int(usage.get("input_tokens") or 0)
                summary.output_tokens += int(usage.get("output_tokens") or 0)
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    block_id = block.get("id")
                    if block_id is not None:
                        if block_id in seen_tool_ids:
                            continue
                        seen_tool_ids.add(block_id)
                    summary.tool_names.append(str(block.get("name") or "unknown"))

    summary.title = ai_title or first_prompt or summary.title
    return summary


# --- Codex: ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl ---


def codex_root() -> Path:
    override = os.environ.get("AGENT_MONITOR_CODEX_DIR")
    if override:
        return Path(override)
    codex_home = os.environ.get("CODEX_HOME")
    base = Path(codex_home) if codex_home else Path.home() / ".codex"
    return base / "sessions"


def iter_codex_session_files(root: Path | None = None) -> list[Path]:
    base = root or codex_root()
    if not base.is_dir():
        return []
    return sorted(base.rglob("rollout-*.jsonl"))


def parse_codex_session(path: Path) -> SessionSummary:
    summary = SessionSummary(
        agent="codex",
        session_id=path.stem,
        title=path.stem,
        path=str(path),
    )
    last_totals: dict[str, Any] | None = None

    for record in _iter_json_lines(path):
        _touch_bounds(summary, _parse_ts(record.get("timestamp")))
        kind = record.get("type")
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        payload_kind = payload.get("type")

        if kind == "session_meta":
            session_id = payload.get("id") or payload.get("session_id")
            if isinstance(session_id, str) and session_id:
                summary.session_id = session_id
            cwd = payload.get("cwd")
            if isinstance(cwd, str) and cwd:
                summary.title = Path(cwd).name or summary.title

        elif kind == "event_msg":
            if payload_kind == "task_started":
                summary.user_turns += 1
            elif payload_kind == "token_count":
                info = payload.get("info")
                totals = info.get("total_token_usage") if isinstance(info, dict) else None
                if isinstance(totals, dict):
                    last_totals = totals  # cumulative counter: the last value wins

        elif kind == "response_item" and payload_kind in ("custom_tool_call", "function_call"):
            summary.tool_names.append(str(payload.get("name") or "unknown"))

    if last_totals:
        summary.input_tokens = int(last_totals.get("input_tokens") or 0)
        summary.output_tokens = int(last_totals.get("output_tokens") or 0)
    return summary


# --- Gemini / Antigravity: ~/.gemini/antigravity/brain/<conv_id>/.system_generated/logs/transcript.jsonl ---


def gemini_root() -> Path:
    override = os.environ.get("AGENT_MONITOR_GEMINI_DIR")
    if override:
        return Path(override)
    return Path.home() / ".gemini" / "antigravity" / "brain"


def iter_gemini_session_files(root: Path | None = None) -> list[Path]:
    base = root or gemini_root()
    if not base.is_dir():
        return []
    direct = list(base.glob("*/.system_generated/logs/transcript.jsonl"))
    flat = list(base.glob("*.jsonl"))
    return sorted(set(direct + flat))


def parse_gemini_session(path: Path) -> SessionSummary:
    conv_id = path.parent.parent.parent.name if path.name == "transcript.jsonl" else path.stem
    summary = SessionSummary(
        agent="gemini",
        session_id=conv_id,
        title=conv_id[:36],
        path=str(path),
    )
    first_prompt: str | None = None

    for record in _iter_json_lines(path):
        _touch_bounds(summary, _parse_ts(record.get("created_at") or record.get("timestamp")))
        step_type = record.get("type")
        status = record.get("status")
        if status == "ERROR":
            summary.tool_errors += 1

        if step_type == "USER_INPUT":
            summary.user_turns += 1
            content = str(record.get("content") or "").strip()
            if content and not first_prompt:
                # Extract text inside <USER_REQUEST> if present
                if "<USER_REQUEST>" in content and "</USER_REQUEST>" in content:
                    inner = content.split("<USER_REQUEST>", 1)[1].split("</USER_REQUEST>", 1)[0].strip()
                    first_prompt = inner[:80] if inner else content[:80]
                else:
                    first_prompt = content[:80]

        elif step_type == "PLANNER_RESPONSE":
            tool_calls = record.get("tool_calls")
            if isinstance(tool_calls, list):
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        name = str(tc.get("name") or tc.get("tool_name") or "tool")
                        summary.tool_names.append(name)

    if first_prompt:
        summary.title = first_prompt
    return summary
