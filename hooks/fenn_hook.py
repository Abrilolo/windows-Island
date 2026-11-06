"""Agent hook -> Fenn island bridge (Claude Code and Codex command hooks).

Usage (registered by scripts/install_hooks.py):
    python hooks/fenn_hook.py claude     # reads the hook JSON from stdin
    python hooks/fenn_hook.py codex

- PermissionRequest: asks the island and blocks until the user decides or the wait times out.
  "allow"/"deny" are returned to the agent; no decision prints nothing, so the agent shows its
  normal terminal prompt.
- Any other event (Stop, Notification, SessionStart, SessionEnd): fire-and-forget notification.

Fail-open by design: if Fenn or the plugin is not running, the file is missing, the token is wrong
or anything errors, the script exits 0 with no output and the agent behaves as if it wasn't there.
Standard library only, so it runs with any Python 3.8+.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

AGENTS = ("claude", "codex")
PLUGIN_ID = "ai-agents"  # the Fenn plugin that receives every agent's hooks
EVENT_TIMEOUT = 1.5
DENY_MESSAGE = "Rechazado desde la isla de Fenn."


def endpoint_file(agent: str) -> Path:
    override = os.environ.get("FENN_HOOK_ENDPOINT_FILE")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Fenn" / "plugin-data" / PLUGIN_ID / "hooks.json"


def load_endpoint(agent: str) -> dict | None:
    try:
        data = json.loads(endpoint_file(agent).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("port") or not data.get("token"):
        return None
    return data


def post(endpoint: dict, path: str, payload: dict, timeout: float) -> dict | None:
    request = urllib.request.Request(
        f"http://127.0.0.1:{int(endpoint['port'])}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Fenn-Token": str(endpoint["token"])},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def decision_output(decision: str) -> dict:
    """Same shape for Claude Code and Codex `PermissionRequest` hooks."""
    payload: dict = {"behavior": decision}
    if decision == "deny":
        payload["message"] = DENY_MESSAGE
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": payload}}


def run(agent: str, raw_input: str) -> str:
    """Return what to print on stdout ("" = no decision / nothing to say)."""
    try:
        raw_input = raw_input.lstrip("﻿")  # PowerShell pipes add a BOM
        payload = json.loads(raw_input) if raw_input.strip() else {}
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    endpoint = load_endpoint(agent)
    if endpoint is None:
        return ""
    payload["fenn_agent"] = agent

    if payload.get("hook_event_name") == "PermissionRequest":
        wait = float(endpoint.get("wait_timeout") or 120)
        reply = post(endpoint, "/v1/permission", payload, timeout=wait + 10)
        decision = (reply or {}).get("decision")
        if decision in ("allow", "deny"):
            return json.dumps(decision_output(decision))
        return ""

    post(endpoint, "/v1/event", payload, timeout=EVENT_TIMEOUT)
    return ""


def main() -> int:
    agent = sys.argv[1] if len(sys.argv) > 1 else ""
    if agent not in AGENTS:
        print(f"usage: fenn_hook.py {{{'|'.join(AGENTS)}}}", file=sys.stderr)
        return 0  # never break the agent because of a bad registration
    try:
        # Agents send UTF-8; read bytes so the console code page (cp1252) can't mangle it.
        out = run(agent, sys.stdin.buffer.read().decode("utf-8-sig", errors="replace"))
    except Exception as exc:  # noqa: BLE001 - fail open
        print(f"fenn_hook: {exc!r}", file=sys.stderr)
        return 0
    if out:
        sys.stdout.write(out + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
