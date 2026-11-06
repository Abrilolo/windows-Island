"""Register (or remove) the Fenn island hooks in Claude Code and Codex user config.

    python scripts/install_hooks.py                 # dry run: shows what would change
    python scripts/install_hooks.py --apply         # writes, with a timestamped backup
    python scripts/install_hooks.py --uninstall --apply
    python scripts/install_hooks.py --agents claude --apply

Only entries whose command contains `fenn_hook.py` are added/removed; other hooks are kept as-is.
Codex asks you to review and trust new hooks (`/hooks` in the CLI) before they run.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = REPO_ROOT / "hooks" / "fenn_hook.py"
MARKER = "fenn_hook.py"
APPROVAL_WAIT = 120  # must match the plugin's FENN_AGENT_APPROVAL_TIMEOUT default
PERMISSION_TIMEOUT = APPROVAL_WAIT + 30

# event -> (timeout seconds, async)
EVENTS: dict[str, dict[str, tuple[int, bool]]] = {
    "claude": {
        "PermissionRequest": (PERMISSION_TIMEOUT, False),
        "Stop": (5, True),
        "Notification": (5, True),
    },
    "codex": {
        "PermissionRequest": (PERMISSION_TIMEOUT, False),
        "Stop": (5, True),
    },
}

CONFIG_FILES = {
    "claude": Path.home() / ".claude" / "settings.json",
    "codex": Path.home() / ".codex" / "hooks.json",
}


def _quote(path: Path) -> str:
    text = path.as_posix()
    return f'"{text}"' if " " in text else text


def hook_command(agent: str, python: Path) -> str:
    return f"{_quote(python)} {_quote(HOOK_SCRIPT)} {agent}"


def _is_ours(hook: dict) -> bool:
    return MARKER in str(hook.get("command") or "")


def strip_ours(hooks: dict) -> dict:
    """Remove every Fenn entry; drop matcher groups and events that end up empty."""
    cleaned: dict = {}
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            cleaned[event] = groups
            continue
        kept_groups = []
        for group in groups:
            if not isinstance(group, dict):
                kept_groups.append(group)
                continue
            inner = [h for h in group.get("hooks", []) if not (isinstance(h, dict) and _is_ours(h))]
            if inner:
                kept_groups.append({**group, "hooks": inner})
        if kept_groups:
            cleaned[event] = kept_groups
    return cleaned


def add_ours(hooks: dict, agent: str, python: Path) -> dict:
    result = strip_ours(hooks)
    for event, (timeout, run_async) in EVENTS[agent].items():
        entry: dict = {
            "type": "command",
            "command": hook_command(agent, python),
            "timeout": timeout,
            "statusMessage": "Fenn",
        }
        if run_async:
            entry["async"] = True
        result.setdefault(event, []).append({"hooks": [entry]})
    return result


def plan(agent: str, *, uninstall: bool, python: Path) -> tuple[Path, dict, dict]:
    path = CONFIG_FILES[agent]
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    hooks = current.get("hooks") or {}
    new_hooks = strip_ours(hooks) if uninstall else add_ours(hooks, agent, python)
    updated = {**current, "hooks": new_hooks}
    if not new_hooks:
        updated.pop("hooks")
    return path, current, updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agents", default="claude,codex", help="comma-separated: claude,codex")
    parser.add_argument("--uninstall", action="store_true", help="remove the Fenn hooks")
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    parser.add_argument("--python", default=sys.executable, help="interpreter the hooks will use")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parser.parse_args(argv)

    python = Path(args.python)
    agents = [a.strip() for a in args.agents.split(",") if a.strip()]
    for agent in agents:
        if agent not in CONFIG_FILES:
            parser.error(f"unknown agent: {agent}")

    for agent in agents:
        path, current, updated = plan(agent, uninstall=args.uninstall, python=python)
        changed = current != updated
        action = "quitar" if args.uninstall else "instalar"
        print(f"== {agent}: {path} ({action}) -> {'con cambios' if changed else 'sin cambios'}")
        ours = {
            event: [h for g in groups for h in g.get("hooks", []) if _is_ours(h)]
            for event, groups in (updated.get("hooks") or {}).items()
        }
        for event, entries in ours.items():
            for entry in entries:
                print(f"   {event}: {entry['command']} (timeout {entry['timeout']}s)")
        if not changed or not args.apply:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backup = path.with_name(f"{path.name}.bak-fenn-{datetime.now():%Y%m%d-%H%M%S}")
            shutil.copy2(path, backup)
            print(f"   respaldo: {backup}")
        path.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("   escrito.")

    if not args.apply:
        print("\nDry run. Añade --apply para escribir.")
    elif "codex" in agents and not args.uninstall:
        print("\nCodex: abre `codex` y usa /hooks para revisar y confiar en los hooks nuevos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
