"""Phase 1: approvals from the island (broker, local hook server, hook script, UI, installer)."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from core.agents.approvals import ApprovalBroker, summarize_tool_input
from core.agents.hook_server import HookServer
from core.agents.plugin import AGENTS, APPROVAL_PREFIX, AiAgentsState

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = REPO_ROOT / "hooks" / "fenn_hook.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import install_hooks  # noqa: E402

BASH_REQUEST = {
    "session_id": "s1",
    "cwd": "C:\\Workspace\\20-Personal\\Labs\\nook-bridge",
    "hook_event_name": "PermissionRequest",
    "tool_name": "Bash",
    "tool_input": {"command": "pytest tests/ -q", "description": "Run the test suite"},
}


def _wait_for_pending(broker: ApprovalBroker, count: int = 1, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if len(broker.pending()) >= count:
            return
        time.sleep(0.02)
    raise AssertionError("request never reached the broker")


@pytest.fixture()
def server():
    broker = ApprovalBroker(wait_timeout=5)
    events: list[dict] = []
    srv = HookServer("claude", broker, port=0, on_event=events.append)
    srv.start()
    yield srv, broker, events
    srv.stop()


def _post(srv: HookServer, path: str, payload: dict, token: str | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{srv.port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Fenn-Token": token or srv.token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


# --- broker ---


def test_summary_prefers_command_and_path() -> None:
    assert summarize_tool_input("Bash", {"command": "ls", "description": "list"}) == ("ls", "list")
    assert summarize_tool_input("Edit", {"file_path": "a.py", "old_string": "x"})[0] == "a.py"
    assert summarize_tool_input("mcp__x__y", {"q": 1})[0] == '{"q": 1}'


def test_broker_allow_and_timeout() -> None:
    changes: list[int] = []
    broker = ApprovalBroker(wait_timeout=0.2, on_change=lambda: changes.append(1))
    request = broker.submit("claude", BASH_REQUEST)
    assert request.summary == "pytest tests/ -q"
    assert request.project == "nook-bridge"
    threading.Timer(0.05, lambda: broker.resolve(request.request_id, "allow")).start()
    assert broker.wait(request) == "allow"
    assert broker.pending() == []

    late = broker.submit("claude", BASH_REQUEST)
    assert broker.wait(late) is None  # timeout -> no decision, terminal prompt takes over
    assert changes  # UI was notified


def test_broker_terminal_and_release_give_no_decision() -> None:
    broker = ApprovalBroker(wait_timeout=5)
    request = broker.submit("codex", BASH_REQUEST)
    assert broker.resolve(request.request_id, "terminal")
    assert broker.wait(request) is None
    assert not broker.resolve("missing", "allow")
    assert not broker.resolve(request.request_id, "bogus")

    other = broker.submit("codex", BASH_REQUEST)
    broker.release_all()
    assert broker.wait(other) is None


# --- server ---


def test_server_rejects_bad_token_and_bad_json(server) -> None:
    srv, broker, _ = server
    assert _post(srv, "/v1/permission", BASH_REQUEST, token="nope")[0] == 401
    assert broker.pending() == []
    request = urllib.request.Request(
        f"http://127.0.0.1:{srv.port}/v1/event",
        data=b"not json",
        headers={"X-Fenn-Token": srv.token},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(request, timeout=5)
    assert err.value.code == 400


def test_server_permission_roundtrip(server) -> None:
    srv, broker, _ = server
    result: dict = {}
    worker = threading.Thread(target=lambda: result.update(reply=_post(srv, "/v1/permission", BASH_REQUEST)))
    worker.start()
    _wait_for_pending(broker)
    broker.resolve(broker.pending()[0].request_id, "deny")
    worker.join(5)
    status, body = result["reply"]
    assert status == 200 and body["decision"] == "deny"


def test_server_events_and_endpoint_file(server, tmp_path: Path) -> None:
    srv, _, events = server
    assert _post(srv, "/v1/event", {"hook_event_name": "Stop"}) == (200, {"ok": True})
    assert events == [{"hook_event_name": "Stop"}]
    endpoint = json.loads(srv.write_endpoint_file(tmp_path).read_text(encoding="utf-8"))
    assert endpoint["port"] == srv.port and endpoint["token"] == srv.token


# --- hook script (subprocess, as the agents run it) ---


def _run_hook(agent: str, payload: dict, endpoint_file: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["FENN_HOOK_ENDPOINT_FILE"] = str(endpoint_file)
    return subprocess.run(
        [sys.executable, str(HOOK_SCRIPT), agent],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_hook_script_returns_island_decision(server, tmp_path: Path) -> None:
    srv, broker, _ = server
    endpoint = srv.write_endpoint_file(tmp_path)
    threading.Thread(
        target=lambda: (_wait_for_pending(broker), broker.resolve(broker.pending()[0].request_id, "allow"))
    ).start()
    proc = _run_hook("claude", BASH_REQUEST, endpoint)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {
        "hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}
    }


def test_hook_script_deny_includes_message(server, tmp_path: Path) -> None:
    srv, broker, _ = server
    endpoint = srv.write_endpoint_file(tmp_path)
    threading.Thread(
        target=lambda: (_wait_for_pending(broker), broker.resolve(broker.pending()[0].request_id, "deny"))
    ).start()
    decision = json.loads(_run_hook("codex", BASH_REQUEST, endpoint).stdout)["hookSpecificOutput"]["decision"]
    assert decision["behavior"] == "deny" and decision["message"]


def test_hook_script_fails_open(tmp_path: Path) -> None:
    # No endpoint file (Fenn not running): no output, exit 0, immediately.
    started = time.time()
    proc = _run_hook("claude", BASH_REQUEST, tmp_path / "missing.json")
    assert (proc.returncode, proc.stdout) == (0, "")
    assert time.time() - started < 10

    # Endpoint file points to a closed port: same.
    dead = tmp_path / "dead.json"
    dead.write_text(json.dumps({"port": 1, "token": "x"}), encoding="utf-8")
    proc = _run_hook("claude", BASH_REQUEST, dead)
    assert (proc.returncode, proc.stdout) == (0, "")

    # Unknown agent or garbage input never breaks the agent.
    assert _run_hook("gemini", BASH_REQUEST, dead).returncode == 0


# --- UI ---


def test_state_shows_pending_approval_and_resolves_from_click(tmp_path: Path) -> None:
    broker = ApprovalBroker(wait_timeout=5)
    specs = [replace(spec, list_files=lambda: []) for spec in AGENTS.values()]
    state = AiAgentsState(specs, broker=broker)
    request = broker.submit("claude", BASH_REQUEST)

    tile = json.dumps(state.build_tile(), ensure_ascii=False)
    assert "Aprobación" in tile and "pytest tests/ -q" in tile
    assert state.build_badge()["badge"] == {"kind": "pulse"}
    page = json.dumps(state.build_page(), ensure_ascii=False)
    assert f"{APPROVAL_PREFIX}allow:{request.request_id}" in page
    assert f"{APPROVAL_PREFIX}terminal:{request.request_id}" in page

    state.handle_message({"type": "event", "id": f"{APPROVAL_PREFIX}allow:{request.request_id}", "kind": "click"})
    assert broker.wait(request, timeout=0) == "allow"
    assert "Aprobación" not in json.dumps(state.build_tile(), ensure_ascii=False)


def test_state_records_hook_events() -> None:
    specs = [replace(spec, list_files=lambda: []) for spec in AGENTS.values()]
    state = AiAgentsState(specs, broker=ApprovalBroker())
    state.handle_hook_event({"hook_event_name": "Stop", "cwd": "C:/Workspace/demo", "fenn_agent": "codex"})
    assert "Codex: terminó su turno · demo" in (state.last_event or "")


# --- installer ---


def test_installer_merges_without_touching_other_hooks(tmp_path: Path, monkeypatch) -> None:
    other = {"type": "http", "url": "http://127.0.0.1:47823/other", "timeout": 305}
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({"theme": "dark", "hooks": {"PermissionRequest": [{"hooks": [other]}]}}), encoding="utf-8"
    )
    monkeypatch.setitem(install_hooks.CONFIG_FILES, "claude", settings)
    python = Path("C:/py/python.exe")

    install_hooks.main(["--agents", "claude", "--apply", "--python", str(python)])
    install_hooks.main(["--agents", "claude", "--apply", "--python", str(python)])  # idempotent
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["theme"] == "dark"
    perm = [h for g in data["hooks"]["PermissionRequest"] for h in g["hooks"]]
    assert perm[0] == other
    ours = [h for h in perm if "fenn_hook.py" in h.get("command", "")]
    assert len(ours) == 1 and ours[0]["command"].endswith(" claude")
    assert data["hooks"]["Stop"][0]["hooks"][0]["async"] is True
    assert list(tmp_path.glob("settings.json.bak-fenn-*"))

    install_hooks.main(["--agents", "claude", "--uninstall", "--apply"])
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["hooks"] == {"PermissionRequest": [{"hooks": [other]}]}


def test_hook_script_accepts_bom_from_powershell(server, tmp_path: Path) -> None:
    srv, broker, _ = server
    endpoint = srv.write_endpoint_file(tmp_path)
    threading.Thread(
        target=lambda: (_wait_for_pending(broker), broker.resolve(broker.pending()[0].request_id, "allow"))
    ).start()
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["FENN_HOOK_ENDPOINT_FILE"] = str(endpoint)
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT), "claude"],
        input="\ufeff" + json.dumps(BASH_REQUEST),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
    )
    assert json.loads(proc.stdout)["hookSpecificOutput"]["decision"]["behavior"] == "allow"
