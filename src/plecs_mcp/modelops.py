"""File-level model operations that do not need a running PLECS (scan / clone)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .paths import check_writable


def scan_text(path: str | Path, pattern: str, ignore_case: bool = False, max_hits: int = 200) -> dict[str, Any]:
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(str(target))
    flags = re.IGNORECASE if ignore_case else 0
    regex = re.compile(pattern, flags)
    hits: list[dict[str, Any]] = []
    for number, line in enumerate(target.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if regex.search(line):
            hits.append({"line": number, "text": line.strip()[:400]})
            if len(hits) >= max_hits:
                break
    return {"path": str(target), "pattern": pattern, "hits": hits, "truncated": len(hits) >= max_hits}


def clone_model(
    source: str | Path,
    target: str | Path,
    name: str | None = None,
    replacements: list[dict[str, str]] | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Copy a .plecs file, optionally rename it and apply regex replacements.

    Validated by loading the result into PLECS afterwards (see the MCP tool).
    """
    src = Path(source).expanduser()
    if not src.is_file():
        raise FileNotFoundError(str(src))
    text = src.read_text(encoding="utf-8")

    applied: list[dict[str, Any]] = []
    if name:
        text, count = re.subn(r'(?m)^(\s*Name\s+")[^"]*(")', rf"\g<1>{name}\g<2>", text, count=1)
        applied.append({"pattern": "Name", "count": count, "value": name})

    for item in replacements or []:
        pattern = item.get("pattern")
        value = item.get("value", "")
        if not pattern:
            continue
        text, count = re.subn(pattern, value, text)
        applied.append({"pattern": pattern, "count": count, "value": value})

    destination = check_writable(target, overwrite=overwrite)
    destination.write_text(text, encoding="utf-8")
    return {
        "source": str(src),
        "path": str(destination),
        "bytes": destination.stat().st_size,
        "name": Path(destination).stem,
        "name_field": name,
        "applied": applied,
    }
