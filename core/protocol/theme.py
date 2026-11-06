"""Design tokens for Fenn views (see docs/design-system.md).

Prefer theme names so plugins follow the user's light/dark theme and accent color.
"""

from __future__ import annotations

# Theme colors (follow Fenn's light/dark theme and the user's accent).
TEXT = "text"
DIM = "dim"
FAINT = "faint"
ACCENT = "accent"
ON_ACCENT = "on_accent"

# Status -> fixed color.
STATUS_COLOR: dict[str, str] = {
    "running": "green",
    "waiting": "orange",  # waiting for approval or user input
    "error": "red",
    "idle": FAINT,
}

# Status -> Phosphor icon (https://phosphoricons.com).
STATUS_ICON: dict[str, str] = {
    "running": "circle-notch",
    "waiting": "hand-palm",
    "error": "warning-circle",
    "idle": "moon",
}

# Local ports. 8765 belongs to the phone (Minimal Launcher); never reuse it.
PHONE_PORT = 8765
AGENT_HOOKS_PORT = 8787  # ai-agents plugin; source of truth: core.agents.hook_server.HOOK_PORT
