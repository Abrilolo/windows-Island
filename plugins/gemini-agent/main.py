"""Entrypoint Fenn runs for the Gemini session monitor plugin."""

from __future__ import annotations

from pathlib import Path
import sys

_HERE = Path(__file__).resolve().parent
for _root in (_HERE, _HERE.parents[1]):  # installed copy, then repo checkout
    if (_root / "core").is_dir():
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        break

from core.agents.plugin import run_loop  # noqa: E402

if __name__ == "__main__":
    run_loop("gemini")
