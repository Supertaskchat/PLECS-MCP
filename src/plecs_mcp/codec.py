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


def write_bytes(path: str, data: bytes, overwrite: bool = False) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if target.exists() and not overwrite:
        raise PlecsPayloadError(f"refusing to overwrite existing file: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"path": str(target), "bytes": len(data), "sha256": sha256_bytes(data)}
