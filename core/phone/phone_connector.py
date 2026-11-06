"""Reusable Galaxy S24+ (`Minimal Launcher`) connection & messaging helper for any Nook/Fenn plugin.

Provides a single entry point (`connect_to_phone`) that resolves the phone across:
1. UDP LAN auto-discovery (`NOOK_DISCOVER` broadcast + ARP neighbors on `:8765`).
2. Direct HTTP health probe (`GET /api/v1/health`) on known/saved LAN IPs when UDP broadcast is dropped.
3. Automatic ADB USB/Wireless port-forwarding (`adb forward tcp:8765 tcp:8765` -> `127.0.0.1:8765`)
   when Guest Wi-Fi AP client isolation blocks direct traffic between wireless clients.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any
import urllib.error
import urllib.request

from core.contracts.payload import IngestPayload
from core.phone.config import (
    BridgeConfig,
    DEFAULT_PHONE_PORT,
    build_phone_health_url,
    build_phone_ingest_url,
    normalize_phone_url,
)

DISCOVER_MAGIC = "NOOK_DISCOVER"
BROADCAST_ADDR = "255.255.255.255"
_SIO_UDP_CONNRESET = 0x9800000C


@dataclass(frozen=True)
class PhoneConnection:
    """Resolved connection state to the Galaxy S24+ (`Minimal Launcher`)."""

    connected: bool
    ip: str | None
    port: int = DEFAULT_PHONE_PORT
    transport: str = "offline"  # "udp" | "http" | "adb" | "offline"
    client_ip: str = "PC"

    @property
    def base_url(self) -> str:
        host = self.ip or "127.0.0.1"
        return f"http://{host}:{self.port}"

    @property
    def ingest_url(self) -> str:
        return build_phone_ingest_url(self.ip or "127.0.0.1", self.port)

    @property
    def health_url(self) -> str:
        return build_phone_health_url(self.ip or "127.0.0.1", self.port)

    @property
    def message_url(self) -> str:
        return f"{self.base_url}/api/v1/message"


def _detect_local_ipv4() -> str | None:
    """Determine the primary outbound LAN IPv4 address (e.g., `192.168.3.162`)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.168.0.1", 80))
            ip = probe.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return None


def _extract_ip_from_url(url: str) -> str | None:
    """Extract the host/IP portion from an HTTP URL."""
    try:
        without_scheme = url.split("://", 1)[-1]
        host_port = without_scheme.split("/", 1)[0]
        host = host_port.split(":", 1)[0].strip()
        return host or None
    except Exception:
        return None


def _resolve_health_fn():
    """Respect monkeypatches on either `core.phone.dispatcher.ping_phone_health` or `core.phone.phone_connector.ping_phone_health`."""
    disp_mod = sys.modules.get("core.phone.dispatcher")
    if disp_mod is not None:
        candidate = getattr(disp_mod, "ping_phone_health", None)
        if candidate is not None and candidate is not ping_phone_health:
            return candidate
    return ping_phone_health


def ping_phone_health(
    ip: str,
    port: int = DEFAULT_PHONE_PORT,
    timeout: float = 1.5,
) -> bool:
    """Send `GET http://<IP>:<port>/api/v1/health` to activate the `● PC` indicator on S24+."""
    health_url = build_phone_health_url(ip, port)
    client_ip = _detect_local_ipv4() or "PC"
    req = urllib.request.Request(
        health_url,
        headers={
            "User-Agent": "nook-bridge/0.1.0",
            "X-Nook-Client-Ip": client_ip,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            return 200 <= status < 300
    except Exception:
        return False


def _get_arp_neighbor_ips(prefix_a_b: str) -> list[str]:
    """Read active LAN neighbor IPs from Windows `arp -a` without flooding the ARP table."""
    ips: list[str] = []
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            ["arp", "-a"],
            capture_output=True,
            text=True,
            timeout=0.5,
            check=False,
            creationflags=creationflags,
        )
        for token in proc.stdout.split():
            if token.startswith(f"{prefix_a_b}.") and not token.endswith(".255"):
                parts = token.split(".")
                if len(parts) == 4 and all(p.isdigit() for p in parts):
                    if token not in ips:
                        ips.append(token)
    except Exception:
        pass
    return ips


def _try_adb_forward_phone(
    port: int = DEFAULT_PHONE_PORT,
    timeout: float = 1.5,
) -> str | None:
    """Bridge `127.0.0.1:<port>` to the S24+ via `adb forward` when Wi-Fi AP isolation blocks LAN."""
    health_check = _resolve_health_fn()

    # 1) If an ADB tunnel or local listener is already active on 127.0.0.1:<port>, verify it
    if health_check("127.0.0.1", port=port, timeout=min(0.35, timeout)):
        return "127.0.0.1"

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            ["adb", "forward", f"tcp:{port}", f"tcp:{port}"],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
            creationflags=creationflags,
        )
        if proc.returncode == 0 and health_check(
            "127.0.0.1", port=port, timeout=min(0.6, timeout)
        ):
            return "127.0.0.1"
    except Exception:
        pass
    return None


def connect_to_phone(
    port: int = DEFAULT_PHONE_PORT,
    timeout: float = 1.5,
    *,
    saved_ip: str | None = None,
    config: BridgeConfig | None = None,
    data_dir: Path | None = None,
    allow_adb: bool | None = None,
) -> PhoneConnection:
    """Connect to the Galaxy S24+ (`Minimal Launcher`) via UDP LAN, HTTP LAN, or ADB tunnel.

    Can be used standalone by any Nook/Fenn plugin without requiring `OutboxStore` or `BridgeState`.
    """
    active_cfg = config if config is not None else BridgeConfig.load(data_dir)
    candidate_saved_ip = saved_ip or _extract_ip_from_url(active_cfg.phone_ingest_url)
    payload_bytes = DISCOVER_MAGIC.encode("utf-8")
    health_check = _resolve_health_fn()
    local_ip: str | None = None

    data: bytes | None = None
    addr: tuple[str, int] | None = None

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            is_real_socket = hasattr(sock, "fileno")
            if is_real_socket:
                # Prevent Windows [WinError 10054] ICMP port unreachable from aborting recvfrom
                try:
                    sock.ioctl(_SIO_UDP_CONNRESET, b"\x00\x00\x00\x00")
                except (AttributeError, OSError):
                    pass

                # Bind to the active Wi-Fi interface so Windows routes broadcast to Wi-Fi
                local_ip = _detect_local_ipv4()
                if local_ip:
                    try:
                        sock.bind((local_ip, 0))
                    except OSError:
                        pass

            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(timeout)

            # 1) Primary UDP broadcast required by specification
            sock.sendto(payload_bytes, (BROADCAST_ADDR, port))

            # 2) On real Windows networks, also send to subnet broadcasts + known/ARP neighbors
            if is_real_socket:
                targets: list[str] = []
                for candidate in (candidate_saved_ip, "192.168.0.75", "192.168.3.164"):
                    if (
                        candidate
                        and candidate != BROADCAST_ADDR
                        and not candidate.startswith("127.")
                        and candidate not in targets
                    ):
                        targets.append(candidate)
                if local_ip:
                    parts = local_ip.split(".")
                    if len(parts) == 4:
                        prefix_a_b = f"{parts[0]}.{parts[1]}"
                        for third in (3, 0, int(parts[2]), 1, 2):
                            bcast = f"{prefix_a_b}.{third}.255"
                            if bcast not in targets:
                                targets.append(bcast)
                        for neighbor_ip in _get_arp_neighbor_ips(prefix_a_b):
                            if neighbor_ip != local_ip and neighbor_ip not in targets:
                                targets.append(neighbor_ip)

                for target_ip in targets:
                    try:
                        sock.sendto(payload_bytes, (target_ip, port))
                    except OSError:
                        pass

                # Phase 1 (first ~0.55s): Wait for broadcast + priority/ARP targets without ARP flood
                phase1_end = time.monotonic() + min(0.55, timeout * 0.5)
                resent_once = False
                half_phase1 = time.monotonic() + min(0.25, timeout * 0.25)
                while time.monotonic() < phase1_end:
                    sock.settimeout(max(0.05, min(0.18, phase1_end - time.monotonic())))
                    try:
                        chunk, sender = sock.recvfrom(4096)
                    except ConnectionResetError:
                        continue
                    except (TimeoutError, socket.timeout):
                        if not resent_once and time.monotonic() >= half_phase1:
                            resent_once = True
                            try:
                                sock.sendto(payload_bytes, (BROADCAST_ADDR, port))
                            except OSError:
                                pass
                            for target_ip in targets:
                                try:
                                    sock.sendto(payload_bytes, (target_ip, port))
                                except OSError:
                                    pass
                        continue
                    if local_ip and sender[0] == local_ip:
                        continue
                    if chunk.strip() == payload_bytes:
                        continue
                    data, addr = chunk, sender
                    break
            else:
                data, addr = sock.recvfrom(4096)
    except Exception:
        data, addr = None, None

    client_ip_label = local_ip or _detect_local_ipv4() or "PC"

    if data is not None and addr is not None:
        try:
            reply = json.loads(data.decode("utf-8", errors="replace").strip())
        except Exception:
            reply = None

        if (
            isinstance(reply, dict)
            and reply.get("status") == "ok"
            and reply.get("app") == "minimal-launcher"
        ):
            ip = str(addr[0]).strip()
            if ip:
                try:
                    resolved_port = int(reply.get("port", port))
                except (TypeError, ValueError):
                    resolved_port = port

                active_cfg.phone_ingest_url = build_phone_ingest_url(ip, resolved_port)
                active_cfg.save(data_dir)
                health_check(ip, port=resolved_port, timeout=timeout)
                return PhoneConnection(
                    connected=True,
                    ip=ip,
                    port=resolved_port,
                    transport="udp",
                    client_ip=client_ip_label,
                )

    # Fallback 1: if UDP is blocked by router AP isolation, check priority IPs via HTTP GET /api/v1/health
    http_candidates: list[str] = []
    for candidate in (candidate_saved_ip, "192.168.3.164", "192.168.0.75"):
        if candidate and not candidate.startswith("127.") and candidate not in http_candidates:
            http_candidates.append(candidate)
    for candidate in http_candidates:
        if health_check(candidate, port=port, timeout=min(0.45, timeout)):
            active_cfg.phone_ingest_url = build_phone_ingest_url(candidate, port)
            active_cfg.save(data_dir)
            return PhoneConnection(
                connected=True,
                ip=candidate,
                port=port,
                transport="http",
                client_ip=client_ip_label,
            )

    # Fallback 2: if guest Wi-Fi client isolation blocks LAN, bridge via ADB USB/Wireless tunnel (`127.0.0.1:<port>`)
    use_adb = allow_adb if allow_adb is not None else not bool(os.environ.get("PYTEST_CURRENT_TEST"))
    if use_adb:
        adb_ip = _try_adb_forward_phone(port=port, timeout=timeout)
        if adb_ip:
            active_cfg.phone_ingest_url = build_phone_ingest_url(adb_ip, port)
            active_cfg.save(data_dir)
            return PhoneConnection(
                connected=True,
                ip=adb_ip,
                port=port,
                transport="adb",
                client_ip=client_ip_label,
            )

    return PhoneConnection(
        connected=False,
        ip=None,
        port=port,
        transport="offline",
        client_ip=client_ip_label,
    )


def discover_phone(
    port: int = DEFAULT_PHONE_PORT,
    timeout: float = 1.5,
    *,
    config: BridgeConfig | None = None,
    data_dir: Path | None = None,
) -> str | None:
    """Discover the Galaxy S24+ and return its reachable IP (`192.168.x.x` or `127.0.0.1`), or `None`."""
    conn = connect_to_phone(
        port=port,
        timeout=timeout,
        config=config,
        data_dir=data_dir,
    )
    return conn.ip if conn.connected else None


def post_to_phone(
    payload: dict[str, Any] | IngestPayload,
    *,
    endpoint: str = "/api/v1/ingest",
    port: int = DEFAULT_PHONE_PORT,
    timeout: float = 3.5,
    auto_reconnect: bool = True,
    config: BridgeConfig | None = None,
    data_dir: Path | None = None,
) -> tuple[bool, str | None]:
    """Send a JSON dict or `IngestPayload` to the Galaxy S24+, auto-reconnecting via LAN/ADB if needed."""
    active_cfg = config if config is not None else BridgeConfig.load(data_dir)
    body_dict = (
        payload.to_launcher_dict()
        if isinstance(payload, IngestPayload)
        else dict(payload)
    )
    body_bytes = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")
    client_ip = _detect_local_ipv4() or "PC"

    def _build_target_url(cfg: BridgeConfig) -> str:
        if endpoint == "/api/v1/ingest":
            return cfg.phone_ingest_url
        base = cfg.phone_ingest_url.split("/api/", 1)[0]
        clean_ep = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        return f"{base}{clean_ep}"

    def _attempt(url: str) -> tuple[bool, str | None, bool]:
        req = urllib.request.Request(
            url,
            data=body_bytes,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "nook-bridge/0.1.0",
                "X-Nook-Client-Ip": client_ip,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", 200)
                if 200 <= status < 300:
                    return True, None, False
                return False, f"HTTP {status}", False
        except urllib.error.HTTPError as exc:
            return False, f"HTTP {exc.code}: {exc.reason}", False
        except urllib.error.URLError as exc:
            return False, f"S24+ inalcanzable ({exc.reason})", True
        except TimeoutError:
            return False, f"Tiempo agotado ({timeout}s)", True
        except Exception as exc:
            return False, str(exc), True

    ok, err, should_retry = _attempt(_build_target_url(active_cfg))
    if ok or not should_retry or not auto_reconnect:
        return ok, err

    conn = connect_to_phone(port=port, config=active_cfg, data_dir=data_dir)
    if not conn.connected or not conn.ip:
        return False, err

    active_cfg.phone_ingest_url = normalize_phone_url(f"{conn.ip}:{conn.port}")
    active_cfg.save(data_dir)
    ok2, err2, _ = _attempt(_build_target_url(active_cfg))
    return ok2, err2


def send_message_to_phone(
    text: str,
    *,
    source: str = "PC",
    port: int = DEFAULT_PHONE_PORT,
    timeout: float = 3.5,
    config: BridgeConfig | None = None,
    data_dir: Path | None = None,
) -> tuple[bool, str | None]:
    """Send a plain text message to the `PC` feed on the Galaxy S24+ (`POST /api/v1/message`)."""
    cleaned = text.strip()
    if not cleaned:
        return False, "Mensaje vacío"
    return post_to_phone(
        {"from": source, "text": cleaned},
        endpoint="/api/v1/message",
        port=port,
        timeout=timeout,
        auto_reconnect=True,
        config=config,
        data_dir=data_dir,
    )
