"""Read the PLECS component library from ``Components.plecs`` text (no RPC needed).

The RPC route returns a 43 MB base64 tree; the same information (≈10k components with
default parameters) is a 13 MB text file, parseable in under a second and cacheable.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from . import plecsfile
from .paths import output_dir


class LibraryParseError(ValueError):
    """Components.plecs could not be parsed into a usable catalogue."""


def components_file(explicit: str | None = None) -> Path | None:
    """Locate Components.plecs for the installed PLECS (or PLECS_LIBRARY_PATH)."""
    for override in (explicit, os.getenv("PLECS_LIBRARY_PATH")):
        if override:
            candidate = Path(override).expanduser()
            if candidate.is_file():
                return candidate

    from .launcher import find_plecs_app

    app = find_plecs_app()
    roots: list[Path] = []
    if app is not None:
        parents = [app, app.parent, app.parent.parent]
        for root in parents:
            roots.extend([root / "Contents" / "Components.plecs", root / "Components.plecs"])
    for root in (Path("/opt"), Path("/usr/local")):
        try:
            roots.extend(root.glob("**/Components.plecs"))
        except OSError:
            continue

    if sys.platform == "win32":
        from .launcher import windows_roots

        for root in windows_roots():
            for pattern in ("Plexim/**/Components.plecs", "**/PLECS*/Components.plecs"):
                try:
                    roots.extend(root.glob(pattern))
                except OSError:
                    continue

    for candidate in roots:
        if candidate.is_file():
            return candidate
    return None


def cache_file(source: Path) -> Path:
    stat = source.stat()
    name = f"components-{source.stem}-{int(stat.st_mtime)}-{stat.st_size}.json"
    return output_dir().parent / "cache" / name


def _items_from_text(text: str) -> list[dict[str, Any]]:
    root = plecsfile.parse(text)
    items: list[dict[str, Any]] = []
    for node in plecsfile.components(root):
        kind = (node.get("Type") or "").strip('"') or None
        name = plecsfile.component_name(node)
        parameters: dict[str, str] = {}
        for child in node.children:
            if child.keyword != "Parameter":
                continue
            variable = (child.get("Variable") or "").strip('"')
            if variable:
                parameters[variable] = (child.get("Value") or "").strip('"')
        terminals = sum(1 for child in node.children if child.keyword == "Terminal")
        items.append(
            {
                "type": kind,
                "name": name,
                "parameters": parameters,
                "terminal_count": terminals or None,
            }
        )
    return items


def load_items(source: Path | None = None, refresh: bool = False) -> list[dict[str, Any]]:
    path = source or components_file()
    if path is None:
        raise FileNotFoundError("Components.plecs not found; set PLECS_LIBRARY_PATH")
    cache = cache_file(path)
    if not refresh and cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    text = path.read_text(encoding="utf-8", errors="replace")
    items = _items_from_text(text)
    if not items:
        raise LibraryParseError(f"parsed 0 components from {path}")
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return items


def _param_keys(item: dict[str, Any]) -> list[str]:
    params = item.get("parameters") or []
    return list(params.keys()) if isinstance(params, dict) else list(params)


def _param_values(item: dict[str, Any]) -> list[str]:
    params = item.get("parameters") or {}
    return list(params.values()) if isinstance(params, dict) else []


def search(items: list[dict[str, Any]], query: str, limit: int = 50) -> list[dict[str, Any]]:
    needle = (query or "").strip().lower()
    if not needle:
        return items[:limit]
    hits = [
        item
        for item in items
        if needle in (item.get("name") or "").lower()
        or needle in (item.get("type") or "").lower()
        or any(needle in str(key).lower() for key in _param_keys(item))
        or any(needle in str(value).lower() for value in _param_values(item))
    ]
    return hits[:limit]


_TEMPLATE_CACHE: dict[str, tuple[float, dict[str, str]]] = {}


def load_templates(refresh: bool = False) -> dict[str, str]:
    """Raw component blocks keyed by Type (used as templates for model editing)."""
    path = components_file()
    if path is None:
        raise FileNotFoundError("Components.plecs not found; set PLECS_LIBRARY_PATH")
    key = str(path)
    mtime = path.stat().st_mtime
    cached = _TEMPLATE_CACHE.get(key)
    if cached and cached[0] == mtime and not refresh:
        return cached[1]
    templates = plecsfile.library_templates(path.read_text(encoding="utf-8", errors="replace"))
    _TEMPLATE_CACHE[key] = (mtime, templates)
    return templates
