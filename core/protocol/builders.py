"""Pure builders for the Nook stdio JSON-Lines UI protocol (nooknotch.xyz/docs)."""

from __future__ import annotations

import json
import sys
import threading
from typing import Any

_STDOUT_LOCK = threading.Lock()


def emit(message: dict[str, Any]) -> None:
    """Thread-safe write of a single JSON-Line message to stdout with immediate flush."""
    line = json.dumps(message, ensure_ascii=False) + "\n"
    with _STDOUT_LOCK:
        sys.stdout.write(line)
        sys.stdout.flush()


# --- Top-level Nook protocol messages (Plugin -> Nook) ---


def tile_msg(view: dict[str, Any]) -> dict[str, Any]:
    """Build a `tile` update message."""
    return {"type": "tile", "view": view}


def page_msg(
    view: dict[str, Any],
    actions: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build a `page` update message with optional header actions."""
    msg: dict[str, Any] = {"type": "page", "view": view}
    if actions:
        msg["actions"] = actions
    return msg


def badge_msg(badge: dict[str, Any] | None) -> dict[str, Any]:
    """Build a `badge` update message for the collapsed notch pill (None clears it)."""
    return {"type": "badge", "badge": badge}


def badge_glyph(icon: str = "bell") -> dict[str, Any]:
    """Small Phosphor icon on the right side of the collapsed pill."""
    return {"kind": "glyph", "icon": icon}


def badge_pulse() -> dict[str, Any]:
    """Pulsing dot indicating pending notifications in the pill."""
    return {"kind": "pulse"}


def badge_ring(progress: float, label: str) -> dict[str, Any]:
    """Progress ring with a short label in the pill."""
    return {"kind": "ring", "progress": max(0.0, min(1.0, progress)), "label": label}


# --- Layout & UI View Components ---


def row(
    children: list[dict[str, Any]],
    *,
    gap: int = 8,
    align: str = "center",
    justify: str | None = None,
) -> dict[str, Any]:
    comp: dict[str, Any] = {
        "type": "row",
        "gap": gap,
        "align": align,
        "children": children,
    }
    if justify:
        comp["justify"] = justify
    return comp


def column(
    children: list[dict[str, Any]],
    *,
    gap: int = 6,
    align: str = "start",
    justify: str | None = None,
    scroll: bool = False,
) -> dict[str, Any]:
    comp: dict[str, Any] = {
        "type": "column",
        "gap": gap,
        "align": align,
        "children": children,
    }
    if justify:
        comp["justify"] = justify
    if scroll:
        comp["scroll"] = True
    return comp


def card(
    children: list[dict[str, Any]],
    *,
    padding: int = 10,
    gap: int = 6,
) -> dict[str, Any]:
    return {
        "type": "card",
        "padding": padding,
        "gap": gap,
        "children": children,
    }


def text(
    content: str,
    *,
    size: str = "body",
    bold: bool = False,
    color: str | None = None,
    wrap: bool = True,
    mono: bool = False,
) -> dict[str, Any]:
    comp: dict[str, Any] = {
        "type": "text",
        "text": content,
        "size": size,
        "wrap": wrap,
    }
    if bold:
        comp["bold"] = True
    if color:
        comp["color"] = color
    if mono:
        comp["mono"] = True
    return comp


def text_input(
    control_id: str,
    *,
    value: str = "",
    hint: str = "",
    live: bool = False,
    width: int | None = None,
) -> dict[str, Any]:
    """Interactive text field (`type: "input"` in Nook protocol, submits on Enter)."""
    comp: dict[str, Any] = {
        "type": "input",
        "id": control_id,
        "value": value,
        "hint": hint,
    }
    if live:
        comp["live"] = True
    if width is not None:
        comp["width"] = width
    return comp


def button(
    control_id: str,
    *,
    label: str | None = None,
    icon: str | None = None,
    primary: bool = False,
    width: int | None = None,
) -> dict[str, Any]:
    comp: dict[str, Any] = {
        "type": "button",
        "id": control_id,
    }
    if label is not None:
        comp["label"] = label
    if icon is not None:
        comp["icon"] = icon
    if primary:
        comp["primary"] = True
    if width is not None:
        comp["width"] = width
    return comp
