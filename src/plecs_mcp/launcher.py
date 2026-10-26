"""Best-effort launch of the PLECS desktop app (macOS app bundles).

Only used by ``plecs_connect`` when the RPC endpoint is closed. PLECS has no
headless CLI that enables RPC, so starting the GUI is the only portable option.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

SEARCH_ROOTS = (Path("/Applications"), Path.home() / "Applications")


def _version_key(name: str) -> tuple[int, ...]:
    match = re.search(r"PLECS\s*([0-9][0-9.]*)", name, re.IGNORECASE)
    if not match:
        return (0,)
    return tuple(int(part) for part in match.group(1).split(".") if part.isdigit())


def find_plecs_app(explicit: str | None = None) -> Path | None:
    """Return the newest usable PLECS .app bundle (or ``PLECS_APP_PATH``)."""
    def usable(path: Path) -> bool:
        return path.is_dir() and (path / "Contents/MacOS/PLECS").is_file()

    # Explicit override wins, then PLECS_APP_PATH, then the newest bundle found.
    for override in (explicit, os.getenv("PLECS_APP_PATH")):
        if override:
            candidate = Path(override).expanduser()
            if usable(candidate):
                return candidate

    candidates: list[Path] = []
    for root in SEARCH_ROOTS:
        try:
            candidates.extend(root.glob("PLECS*.app"))
        except OSError:
            continue
    found = [path for path in candidates if usable(path)]
    if not found:
        return None
    return max(found, key=lambda path: (_version_key(path.name), str(path)))


def launch_plecs(app: Path) -> dict:
    """Start (or focus) PLECS. Returns ``{"ok", "app", "command", "error"}``."""
    command = ["open", "-a", str(app)]
    if sys.platform != "darwin":
        return {
            "ok": False,
            "app": str(app),
            "command": command,
            "error": f"automatic launch is only implemented for macOS (current platform: {sys.platform})",
        }
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        return {"ok": False, "app": str(app), "command": command, "error": detail.strip()}
    return {"ok": True, "app": str(app), "command": command, "error": None}


def wait_for_port(host: str, port: int, timeout: float, interval: float = 0.5) -> float | None:
    """Block until the RPC port accepts connections; return elapsed seconds or None."""
    deadline = time.monotonic() + max(timeout, 0.0)
    start = time.monotonic()
    while True:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return round(time.monotonic() - start, 2)
        except OSError:
            if time.monotonic() >= deadline:
                return None
            time.sleep(interval)
