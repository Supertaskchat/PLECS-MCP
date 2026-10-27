"""Decoders for the payloads PLECS smuggles through JSON-RPC as base64."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path
from typing import Any


class PlecsPayloadError(ValueError):
    """A base64 payload could not be decoded."""


def _b64(value: str, what: str) -> bytes:
    try:
        return base64.b64decode(value, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise PlecsPayloadError(f"{what} is not valid base64: {exc}") from exc


def base64_to_text(value: str, what: str = "payload") -> str:
    return _b64(value, what).decode("utf-8")


def base64_to_bytes(value: str, what: str = "payload") -> bytes:
    return _b64(value, what)


def decode_model_tree(raw: Any) -> dict[str, Any]:
    """``plecs.getModelTree`` returns base64-encoded JSON; decode it."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise PlecsPayloadError(f"unexpected model tree payload: {type(raw).__name__}")
    text = base64_to_text(raw, "model tree")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlecsPayloadError(f"model tree is not JSON: {exc}") from exc


def _children(node: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in node.get("children", []) if isinstance(c, dict)]


def _property(node: dict[str, Any], name: str) -> Any:
    for child in _children(node):
        if child.get("kind") == "property" and child.get("name") == name:
            return child.get("value")
    return None


def _walk(node: dict[str, Any], path: str, out: dict[str, Any]) -> None:
    for child in _children(node):
        kind = child.get("kind")
        name = child.get("name") or ""
        child_path = f"{path}/{name}" if path else name
        if kind:
            out["counts"][kind] = out["counts"].get(kind, 0) + 1
        if kind == "analysis":
            out["analyses"].append(
                {
                    "name": _property(child, "Name") or name,
                    "type": child.get("type"),
                    "path": child_path,
                }
            )
        elif kind == "subsystem":
            out["subsystems"].append({"name": name, "path": child_path})
        elif kind == "component":
            if (child.get("type") or "").endswith("Scope"):
                out["scopes"].append(child_path)
            out["components"].append({"name": name, "type": child.get("type"), "path": child_path})
        elif kind == "parameter":
            out["parameters"].append(name)
        _walk(child, child_path, out)


def summarize_tree(tree: dict[str, Any]) -> dict[str, Any]:
    """Condense a model tree into names/counts (size is dominated by connections)."""
    out: dict[str, Any] = {
        "name": tree.get("name"),
        "type": tree.get("type"),
        "counts": {},
        "analyses": [],
        "subsystems": [],
        "components": [],
        "scopes": [],
        "parameters": [],
    }
    _walk(tree, tree.get("name") or "", out)
    out["counts"].pop("connection", None)
    return out


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_bytes(path: str | Path, data: bytes, overwrite: bool = False) -> dict[str, Any]:
    from .paths import PathNotAllowed, check_writable

    try:
        target = check_writable(path, overwrite=overwrite)
    except PathNotAllowed as exc:
        raise PlecsPayloadError(str(exc)) from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"path": str(target), "bytes": len(data), "sha256": sha256_bytes(data)}


def outports_from_tree(tree: dict[str, Any]) -> list[dict[str, Any]]:
    """Top-level Signal Outport components (PLECS does not expose a port index)."""
    found: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        if _property(node, "Library type") == "Signal Outport":
            found.append({"name": _property(node, "Name"), "position": _property(node, "Position")})
        for child in _children(node):
            walk(child)

    walk(tree)
    return found


def parse_merged_items(lines: Any) -> list[dict[str, Any]]:
    """Turn ``plecs.compare`` output into structured entries.

    PLECS returns ONE string that already contains newlines, and component names may
    themselves contain newlines ("PID\nController"). Entries are therefore split on a
    newline that is followed by indentation + ``MergedItem(``, not on every newline.
    """
    import re

    if isinstance(lines, str):
        text = lines
    elif isinstance(lines, list):
        text = "\n".join(line for line in lines if isinstance(line, str))
    else:
        return []

    entries: list[dict[str, Any]] = []
    for part in re.split(r"\n(?=[ \t]*MergedItem\()", text):
        if not part.strip():
            continue
        indent = len(part) - len(part.lstrip(" \t"))
        body = part.strip()
        close = body.rfind(")")
        if not body.startswith("MergedItem(") or close < 0:
            continue
        fields = body[len("MergedItem(") : close].rsplit(", ", 3)
        if len(fields) != 4:
            continue
        left, right, change, kind = fields
        entries.append(
            {
                "depth": indent // 2,
                "left": left,
                "right": right,
                "change": change,
                "type": kind,
            }
        )
    return entries


def slice_csv(
    text: str,
    time_range: list[float] | tuple[float, float] | None = None,
    decimate: int | None = None,
) -> tuple[list[str], list[list[str]]]:
    """Apply a time window and decimation to a PLECS scope CSV (client-side only)."""
    import csv
    import io

    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader if row]
    if not rows:
        return [], []
    header, body = rows[0], rows[1:]

    if time_range:
        low, high = float(time_range[0]), float(time_range[1])
        filtered: list[list[str]] = []
        for row in body:
            try:
                t = float(row[0])
            except (ValueError, IndexError):
                continue
            if low <= t <= high:
                filtered.append(row)
        body = filtered

    if decimate and decimate > 1:
        body = [row for index, row in enumerate(body) if index % decimate == 0]

    return header, body
