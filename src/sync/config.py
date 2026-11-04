"""Persistent configuration for `minimal-bridge` stored in `%APPDATA%\\Nook\\plugin-data\\minimal-bridge`."""

from __future__ import annotations

import json
import os
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field

PLUGIN_ID = "minimal-bridge"
DEFAULT_PHONE_IP = "192.168.3.164"
DEFAULT_PHONE_PORT = 8765
DEFAULT_PHONE_URL = f"http://{DEFAULT_PHONE_IP}:{DEFAULT_PHONE_PORT}/api/v1/ingest"


def get_plugin_data_dir(custom_dir: Path | None = None) -> Path:
    """Resolve `%APPDATA%\\Nook\\plugin-data\\minimal-bridge` (or override for tests)."""
    if custom_dir is not None:
        custom_dir.mkdir(parents=True, exist_ok=True)
        return custom_dir

    env_override = os.environ.get("NOOK_BRIDGE_DATA_DIR")
    if env_override:
        path = Path(env_override)
        path.mkdir(parents=True, exist_ok=True)
        return path

    appdata = os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata)
    else:
        base = Path.home() / "AppData" / "Roaming"

    data_dir = base / "Nook" / "plugin-data" / PLUGIN_ID
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Fallback inside local workspace if sandbox restricts %APPDATA%
        data_dir = Path.cwd() / ".nook-data"
        data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def normalize_phone_url(raw: str) -> str:
    """Convert an IP, host:port, or full URL into a canonical `/api/v1/ingest` endpoint."""
    cleaned = raw.strip()
    if not cleaned:
        return DEFAULT_PHONE_URL
    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"http://{cleaned}"

    # Parse host/port/path
    without_scheme, scheme = (
        (cleaned[8:], "https://")
        if cleaned.startswith("https://")
        else (cleaned[7:], "http://")
    )
    parts = without_scheme.split("/", 1)
    host_port = parts[0]
    path = "/" + parts[1] if len(parts) > 1 else ""

    if ":" not in host_port:
        host_port = f"{host_port}:{DEFAULT_PHONE_PORT}"
    if not path or path == "/":
        path = "/api/v1/ingest"

    return f"{scheme}{host_port}{path}"


class BridgeConfig(BaseModel):
    """User-editable configuration persisted in `config.json`."""

    model_config = ConfigDict(extra="ignore")

    phone_ingest_url: str = Field(default=DEFAULT_PHONE_URL)
    auto_sync_captures: bool = Field(default=True)
    request_timeout_sec: float = Field(default=3.5)

    @classmethod
    def load(cls, data_dir: Path | None = None) -> BridgeConfig:
        target_dir = get_plugin_data_dir(data_dir)
        cfg_file = target_dir / "config.json"

        env_url = os.environ.get("NOOK_PHONE_URL")
        if cfg_file.exists():
            try:
                raw = json.loads(cfg_file.read_text(encoding="utf-8"))
                cfg = cls.model_validate(raw)
                if env_url:
                    cfg.phone_ingest_url = normalize_phone_url(env_url)
                return cfg
            except Exception:
                pass

        cfg = cls(
            phone_ingest_url=normalize_phone_url(env_url)
            if env_url
            else DEFAULT_PHONE_URL
        )
        cfg.save(target_dir)
        return cfg

    def save(self, data_dir: Path | None = None) -> Path:
        target_dir = get_plugin_data_dir(data_dir)
        cfg_file = target_dir / "config.json"
        tmp_file = target_dir / "config.json.tmp"
        try:
            tmp_file.write_text(
                json.dumps(self.model_dump(mode="json"), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(tmp_file, cfg_file)
        except OSError:
            pass
        return cfg_file
