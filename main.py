"""Root entrypoint invoked by Nook (`run = ["python", "main.py"]`)."""

from __future__ import annotations

from pathlib import Path
import sys

# Ensure `src/` is importable whether executed from repo root or %APPDATA%\Nook\plugins\minimal-bridge
SRC_DIR = Path(__file__).resolve().parent / "src"
if SRC_DIR.exists() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from nook_plugin.main import run_loop

if __name__ == "__main__":
    run_loop()
