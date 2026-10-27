"""PLECS component library browsing (reads the bundled Components.plecs)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def components_path(app: Path) -> Path | None:
    candidate = app / "Contents" / "Components.plecs"
    return candidate if candidate.is_file() else None


def _flatten(node: dict[str, Any], out: list[dict[str, Any]], parent: str = "") -> None:
    name = node.get("name") or ""
    path = f"{parent}/{name}" if parent else name
    kind = node.get("kind")
    children = [child for child in node.get("children", []) if isinstance(child, dict)]

    def prop(key: str) -> Any:
        for child in children:
            if child.get("kind") == "property" and child.get("name") == key:
                return child.get("value")
        return None

    if kind in ("component", "subsystem"):
        out.append(
            {
                "name": name,
                "type": node.get("type") or prop("Library type"),
                "path": path,
                "parameters": [child.get("name") for child in children if child.get("kind") == "parameter"],
            }
        )
    for child in children:
        _flatten(child, out, path)


def load_components(path: Path, fetch_tree: Callable[[str], dict[str, Any]]) -> list[dict[str, Any]]:
    key = str(path)
    mtime = path.stat().st_mtime
    cached = _CACHE.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    tree = fetch_tree(str(path))
    items: list[dict[str, Any]] = []
    _flatten(tree, items)
    _CACHE[key] = (mtime, items)
    return items


def search(items: list[dict[str, Any]], query: str, limit: int = 50) -> list[dict[str, Any]]:
    needle = (query or "").strip().lower()
    if not needle:
        return items[:limit]
    hits = [
        item
        for item in items
        if needle in (item.get("name") or "").lower()
        or needle in (item.get("type") or "").lower()
        or any(needle in (param or "").lower() for param in item.get("parameters", []))
    ]
    return hits[:limit]
