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
    align: str = "start",
    justify: str | None = None,
) -> dict[str, Any]:
    """Left-to-right children.

    Keep align="start" unless the row is the whole tile: in Fenn (egui), a row with
    align "center"/"end" and no `spacer` takes ALL the available height, so inside a
    column it pushes everything after it out of view, and inside a scrolling page it
    becomes infinitely tall (empty page). `justify` is ignored by Fenn; use spacer().
    """
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


def spacer(size: int | None = None) -> dict[str, Any]:
    """Fixed gap, or (with no size) pushes everything after it to the far end of a row."""
    comp: dict[str, Any] = {"type": "spacer"}
    if size is not None:
        comp["size"] = size
    return comp


def icon(name: str, *, size: int | None = None, color: str | None = None, fill: bool = False) -> dict[str, Any]:
    """Phosphor icon (https://phosphoricons.com)."""
    comp: dict[str, Any] = {"type": "icon", "icon": name}
    if size is not None:
        comp["size"] = size
    if color:
        comp["color"] = color
    if fill:
        comp["fill"] = True
    return comp


# --- One-shot plugin -> Fenn messages ---


def show_msg() -> dict[str, Any]:
    """Open the notch, pinned, on this plugin's page (use for alerts)."""
    return {"type": "show"}


def open_page_msg() -> dict[str, Any]:
    return {"type": "open_page"}


def active_msg(active: bool) -> dict[str, Any]:
    """Light (or unlight) the tile with the accent color."""
    return {"type": "active", "active": active}


def open_target_msg(target: str) -> dict[str, Any]:
    """Open a URL, file, or folder with its default app."""
    return {"type": "open", "target": target}


def log_msg(message: str, level: str = "info") -> dict[str, Any]:
    return {"type": "log", "level": level, "message": message}


def _node(type_: str, **fields: Any) -> dict[str, Any]:
    """Component with only the fields that are set (mirrors Fenn's SDK `_node`)."""
    comp: dict[str, Any] = {"type": type_}
    comp.update({k: v for k, v in fields.items() if v is not None})
    return comp


def grid(columns: int, children: list[dict[str, Any]], *, gap: int | None = None) -> dict[str, Any]:
    """Equal-width cells (dashboards)."""
    return _node("grid", columns=columns, children=children, gap=gap)


def divider() -> dict[str, Any]:
    return {"type": "divider"}


def progress(value: float, *, color: str | None = None, width: int | None = None) -> dict[str, Any]:
    """Thin bar, value 0..1."""
    return _node("progress", value=max(0.0, min(1.0, value)), color=color, width=width)


def ring(
    value: float, *, label: str | None = None, size: int | None = None, color: str | None = None
) -> dict[str, Any]:
    """Circular progress ring with a short label inside."""
    return _node("ring", value=max(0.0, min(1.0, value)), label=label, size=size, color=color)


def sparkline(
    values: list[float],
    *,
    max_value: float | None = None,
    color: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> dict[str, Any]:
    """Area chart; newest value on the right."""
    return _node("sparkline", values=list(values), max=max_value, color=color, width=width, height=height)


def list_item(
    item_id: str,
    title: str,
    *,
    subtitle: str | None = None,
    icon: str | None = None,
    trailing: str | None = None,
    selected: bool | None = None,
) -> dict[str, Any]:
    comp: dict[str, Any] = {"id": item_id, "title": title}
    for key, value in (("subtitle", subtitle), ("icon", icon), ("trailing", trailing), ("selected", selected)):
        if value is not None:
            comp[key] = value
    return comp


def list_view(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Clickable rows; a click sends an event with the item's id."""
    return {"type": "list", "items": items}


def chips(control_id: str, options: list[str], *, selected: int = 0) -> dict[str, Any]:
    """Segmented choice; sends "change" with {"index", "label"}."""
    return {"type": "chips", "id": control_id, "options": options, "selected": selected}


def image(
    *,
    path: str | None = None,
    base64: str | None = None,
    width: int | None = None,
    height: int | None = None,
    rounding: int | None = None,
) -> dict[str, Any]:
    return _node("image", path=path, base64=base64, width=width, height=height, rounding=rounding)
