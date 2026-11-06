"""Every plugins/<id>/ folder must be a valid Fenn plugin that boots from the repo checkout."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIRS = sorted(p for p in (REPO_ROOT / "plugins").iterdir() if (p / "plugin.toml").is_file())
AGENT_PLUGINS = ["claude-agent", "codex-agent", "gemini-agent"]


@pytest.mark.parametrize("plugin_dir", PLUGIN_DIRS, ids=lambda p: p.name)
def test_manifest_matches_fenn_rules(plugin_dir: Path) -> None:
    manifest = tomllib.loads((plugin_dir / "plugin.toml").read_text(encoding="utf-8"))
    assert manifest["id"] == plugin_dir.name
    assert manifest["name"]
    assert manifest["run"] == ["python", "main.py"]
    assert manifest.get("size", "small") in {"small", "wide", "large"}
    assert manifest.get("mode", "live") in {"live", "poll"}
    assert (plugin_dir / "main.py").is_file()


def test_plugin_ids_and_hotkeys_are_unique() -> None:
    manifests = [tomllib.loads((p / "plugin.toml").read_text(encoding="utf-8")) for p in PLUGIN_DIRS]
    ids = [m["id"] for m in manifests]
    hotkeys = [m["hotkey"].lower() for m in manifests if "hotkey" in m]
    assert len(ids) == len(set(ids))
    assert len(hotkeys) == len(set(hotkeys))


@pytest.mark.parametrize("plugin_id", AGENT_PLUGINS)
def test_agent_plugin_boots_and_draws_tile(plugin_id: str, tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    for var in ("AGENT_MONITOR_CLAUDE_DIR", "AGENT_MONITOR_CODEX_DIR", "AGENT_MONITOR_GEMINI_DIR"):
        env[var] = str(tmp_path / "empty-logs")

    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "plugins" / plugin_id / "main.py")],
        input="",
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=REPO_ROOT / "plugins" / plugin_id,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    messages = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert {m["type"] for m in messages} >= {"tile", "page", "badge"}
