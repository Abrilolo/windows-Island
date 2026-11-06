"""Static checks for Fenn views, for tests (see docs/design-system.md, "Reglas del renderizador")."""

from __future__ import annotations

from typing import Any


def rows_that_stretch(node: Any) -> list[dict[str, Any]]:
    """Rows Fenn would stretch to the full available height (align center/end, no flexible spacer).

    Inside a scrolling page such a row becomes infinitely tall and the page shows up empty.
    """
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("type") == "row" and node.get("align", "start") != "start":
            children = node.get("children") or []
            if not any(isinstance(c, dict) and c.get("type") == "spacer" and "size" not in c for c in children):
                found.append(node)
        for value in node.values():
            found.extend(rows_that_stretch(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(rows_that_stretch(value))
    return found
