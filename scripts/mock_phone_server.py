"""Lightweight local UDP + HTTP receiver simulating the Galaxy S24+ (`Minimal Launcher`)."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import socket
import sys
import threading


class _IngestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.startswith("/api/v1/health"):
            print("🟢 [Mock S24+] GET /api/v1/health -> Indicador ● PC encendido", flush=True)
            resp = json.dumps({"status": "ok", "pc": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8", errors="replace")
        print("\n" + "=" * 60)
        print(f"📱 [Mock S24+] Recibido POST {self.path}")
        try:
            parsed = json.loads(raw_body)
            print(json.dumps(parsed, indent=2, ensure_ascii=False))
        except Exception:
            print(raw_body)
        print("=" * 60, flush=True)

        resp = json.dumps({"status": "ok", "ingested": True}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)


def _udp_discovery_responder(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
        while True:
            data, addr = sock.recvfrom(4096)
            if data.decode("utf-8", errors="replace").strip() == "NOOK_DISCOVER":
                reply = json.dumps(
                    {"status": "ok", "app": "minimal-launcher", "port": port}
                ).encode("utf-8")
                sock.sendto(reply, addr)
                print(f"📡 [Mock S24+] UDP NOOK_DISCOVER respondido a {addr[0]}:{addr[1]}", flush=True)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    udp_thread = threading.Thread(target=_udp_discovery_responder, args=(port,), daemon=True)
    udp_thread.start()
    server = HTTPServer(("0.0.0.0", port), _IngestHandler)
    print(f"📱 Mock Galaxy S24+ escuchando UDP+HTTP en 0.0.0.0:{port} ...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando servidor mock.")


if __name__ == "__main__":
    main()
