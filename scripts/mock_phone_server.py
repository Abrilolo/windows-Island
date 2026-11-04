"""Lightweight local HTTP receiver simulating the Galaxy S24+ `/api/v1/ingest` endpoint."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import sys


class _IngestHandler(BaseHTTPRequestHandler):
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


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = HTTPServer(("0.0.0.0", port), _IngestHandler)
    print(f"📱 Mock Galaxy S24+ escuchando en http://0.0.0.0:{port}/api/v1/ingest ...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando servidor mock.")


if __name__ == "__main__":
    main()
