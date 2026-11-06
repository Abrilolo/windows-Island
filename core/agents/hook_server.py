"""Local HTTP receiver for agent hooks, run inside the agent's live Fenn plugin.

Security: binds to 127.0.0.1 only and requires the per-run token stored in `hooks.json`
(inside the plugin's data dir). Anything else on the machine without that file cannot approve.

Endpoints (JSON in / JSON out):
- GET  /v1/health                     -> {"ok": true, "agent": ...}
- POST /v1/permission  (token)        -> blocks until decided/timeout -> {"decision": "allow"|"deny"|null}
- POST /v1/event       (token)        -> {"ok": true}  (Stop, Notification, SessionStart, ...)
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import threading
from typing import Any, Callable

from core.agents.approvals import ApprovalBroker

TOKEN_HEADER = "X-Fenn-Token"
ENDPOINT_FILE = "hooks.json"
MAX_BODY = 1_000_000

# One receiver for all agents (the ai-agents plugin). 8765 belongs to the phone; never reuse it.
HOOK_PORT = 8787
HOOK_AGENTS = ("claude", "codex")  # agents whose hooks can decide approvals
AGENT_FIELD = "fenn_agent"  # added by hooks/fenn_hook.py to every payload


class _QuietServer(ThreadingHTTPServer):
    """Ignore clients that drop the connection (keep-alive resets, hook cancelled by the agent)."""

    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def plugin_data_dir(plugin_id: str) -> Path:
    """`FENN_DATA_DIR` when running under Fenn, else `%APPDATA%\\Fenn\\plugin-data\\<id>`."""
    env_dir = os.environ.get("FENN_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Fenn" / "plugin-data" / plugin_id


class HookServer:
    def __init__(
        self,
        agent: str,
        broker: ApprovalBroker,
        *,
        port: int,
        token: str | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        host: str = "127.0.0.1",
    ) -> None:
        self.agent = agent
        self.broker = broker
        self.token = token or secrets.token_urlsafe(24)
        self.on_event = on_event
        self._httpd = _QuietServer((host, port), self._handler_class())
        self.port = self._httpd.server_address[1]
        self._thread: threading.Thread | None = None

    # --- lifecycle ---

    def start(self) -> None:
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="hook-server", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.broker.release_all()
        self._httpd.shutdown()
        self._httpd.server_close()

    def write_endpoint_file(self, data_dir: Path) -> Path:
        """Publish port + token for `hooks/fenn_hook.py` (rewritten on every plugin start)."""
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / ENDPOINT_FILE
        payload = {
            "agent": self.agent,
            "port": self.port,
            "token": self.token,
            "wait_timeout": self.broker.wait_timeout,
            "pid": os.getpid(),
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)
        return path

    # --- HTTP ---

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt: str, *args: Any) -> None:  # keep stdout clean for Fenn
                return

            def _send(self, status: int, body: dict[str, Any]) -> None:
                data = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authorized(self) -> bool:
                supplied = self.headers.get(TOKEN_HEADER) or ""
                return secrets.compare_digest(supplied, server.token)

            def _read_json(self) -> dict[str, Any] | None:
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    return None
                if length <= 0 or length > MAX_BODY:
                    return None
                try:
                    data = json.loads(self.rfile.read(length).decode("utf-8-sig"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return None
                return data if isinstance(data, dict) else None

            def do_GET(self) -> None:  # noqa: N802 - http.server API
                if self.path == "/v1/health":
                    self._send(200, {"ok": True, "agent": server.agent})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802 - http.server API
                # Read the body first: answering before draining it makes Windows reset
                # the connection, and the client sees an error instead of our status.
                payload = self._read_json()
                if self.path not in ("/v1/permission", "/v1/event"):
                    self._send(404, {"error": "not found"})
                    return
                if not self._authorized():
                    self._send(401, {"error": "bad token"})
                    return
                if payload is None:
                    self._send(400, {"error": "invalid json"})
                    return

                if self.path == "/v1/event":
                    if server.on_event:
                        try:
                            server.on_event(payload)
                        except Exception as exc:  # noqa: BLE001 - never fail the agent's hook
                            print(f"[hook-server] on_event failed: {exc!r}", file=sys.stderr)
                    self._send(200, {"ok": True})
                    return

                agent = str(payload.get(AGENT_FIELD) or server.agent)
                request = server.broker.submit(agent, payload)
                decision = server.broker.wait(request)
                self._send(200, {"decision": decision, "request_id": request.request_id})

        return Handler
