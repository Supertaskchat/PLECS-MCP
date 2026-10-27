"""Recognise PLECS process crashes and keep the same file from re-crashing us.

PLECS 5.0.6 can segfault *inside its own model compiler* for some models: the
JSON-RPC connection drops mid-call with no error payload.  Nothing in the MCP
server can prevent that, but it can avoid the crash loop that follows - the
client retries the same call, PLECS dies again, and again.

This module provides three pieces:

* ``is_disconnect`` - did the call die because the peer vanished?
* ``latest_dump`` - Crashpad writes ``<uuid>.dmp`` into the temp directory.
* ``fingerprint`` - the (mtime, size) of the model file, so a quarantine is
  released as soon as the caller edits the model.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time

DISCONNECT_MARKERS = (
    "server disconnected without sending a response",
    "connection refused",
    "cannot reach plecs",
    "connection reset",
    "broken pipe",
)

# RPC calls that make PLECS build a netlist. Only these can hit the compiler crash.
COMPILE_METHODS = frozenset(
    {
        "plecs.simulate",
        "plecs.analyze",
        "plecs.codegen",
        "plecs.exportfmu",
        "plecs.runScript",
        "plecs.get",  # narrowed to Topology / StateSpaceOrder by is_compile_call
    }
)


def is_disconnect(message: str) -> bool:
    text = (message or "").lower()
    return any(marker in text for marker in DISCONNECT_MARKERS)


def fingerprint(path: str | None) -> str | None:
    if not path:
        return None
    try:
        stat = Path(path).expanduser().stat()
    except OSError:
        return None
    return f"{Path(path).expanduser()}::{stat.st_mtime_ns}::{stat.st_size}"


def latest_dump(since_seconds: float = 180.0) -> str | None:
    """Newest Crashpad dump in the temp dir, if it is fresh enough."""
    directory = Path(tempfile.gettempdir())
    newest: tuple[float, Path] | None = None
    now = time.time()
    try:
        entries = list(directory.glob("*.dmp"))
    except OSError:
        return None
    for entry in entries:
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if now - mtime > since_seconds:
            continue
        if newest is None or mtime > newest[0]:
            newest = (mtime, entry)
    return str(newest[1]) if newest else None


def is_compile_call(method: str, params: list | None) -> bool:
    if method not in COMPILE_METHODS:
        return False
    if method == "plecs.get":
        target = str((params or ["", ""])[1] if len(params or []) > 1 else "")
        return target in {"Topology", "StateSpaceOrder"}
    return True
