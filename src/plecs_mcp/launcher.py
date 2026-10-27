"""Best-effort launch of the PLECS desktop GUI (macOS / Windows / Linux).

Only used by ``plecs_connect`` when the RPC endpoint is closed. PLECS exposes no
headless switch that enables RPC, so starting the GUI is the only portable option.
Discovery and the launch command are chosen from the **host** platform where this
MCP server runs (PLECS RPC is localhost-only, so host == PLECS machine).
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

MAC_ROOTS = (Path("/Applications"), Path.home() / "Applications")
LINUX_ROOTS = (Path("/opt"), Path("/usr/local"), Path.home())


def _version_key(name: str) -> tuple[int, ...]:
    match = re.search(r"PLECS[ _-]*([0-9][0-9.]*)", name, re.IGNORECASE)
    if not match:
        return (0,)
    return tuple(int(part) for part in match.group(1).split(".") if part.isdigit())


def _is_launchable(path: Path) -> bool:
    if path.is_dir():
        return (path / "Contents/MacOS/PLECS").is_file()
    return path.is_file()


def _mac_candidates() -> list[Path]:
    found: list[Path] = []
    for root in MAC_ROOTS:
        try:
            found.extend(root.glob("PLECS*.app"))
        except OSError:
            continue
    return found


def windows_roots() -> list[Path]:
    roots: list[Path] = []
    for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        value = os.getenv(key)
        if value:
            roots.append(Path(value))
    roots.append(Path.home() / "AppData/Local")
    return roots


def _windows_candidates() -> list[Path]:
    found: list[Path] = []
    for root in windows_roots():
        for pattern in ("Plexim/*/plecs.exe", "Plexim/*/bin/plecs.exe", "*/PLECS*/plecs.exe"):
            try:
                found.extend(root.glob(pattern))
            except OSError:
                continue
    return found


def _linux_candidates() -> list[Path]:
    found: list[Path] = []
    which = shutil.which("plecs")
    if which:
        found.append(Path(which))
    for root in LINUX_ROOTS:
        for pattern in ("plecs*/plecs", "Plexim/*/plecs", "*/PLECS*/plecs"):
            try:
                found.extend(root.glob(pattern))
            except OSError:
                continue
    return found


def _candidates() -> list[Path]:
    if sys.platform == "darwin":
        return _mac_candidates()
    if sys.platform == "win32":
        return _windows_candidates()
    if sys.platform.startswith("linux"):
        return _linux_candidates()
    return []


def find_plecs_app(explicit: str | None = None) -> Path | None:
    """Newest usable PLECS install for this host, or an explicit override.

    Overrides (in order): ``explicit``, ``PLECS_EXECUTABLE``, ``PLECS_APP_PATH``.
    macOS targets are ``*.app`` bundles, Windows/Linux targets are the ``plecs`` binary.
    """
    for override in (explicit, os.getenv("PLECS_EXECUTABLE"), os.getenv("PLECS_APP_PATH")):
        if override:
            candidate = Path(override).expanduser()
            if _is_launchable(candidate):
                return candidate

    found = [path for path in _candidates() if _is_launchable(path)]
    if not found:
        return None
    return max(found, key=lambda path: (_version_key(path.name), str(path)))


def launch_plecs(app: Path) -> dict:
    """Start PLECS with the host-appropriate command.

    macOS: ``open -a <bundle>``; Windows/Linux: spawn the executable directly.
    Returns ``{"ok", "app", "command", "error"}``.
    """
    if sys.platform == "darwin":
        command = ["open", "-a", str(app)]
    elif sys.platform == "win32":
        command = [str(app)]
    elif sys.platform.startswith("linux"):
        command = [str(app)]
    else:
        return {
            "ok": False,
            "app": str(app),
            "command": [],
            "error": f"automatic launch is not implemented for platform {sys.platform!r}",
        }

    try:
        if sys.platform == "darwin":
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        else:
            subprocess.Popen(command, close_fds=True, start_new_session=True)
    except (OSError, subprocess.SubprocessError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        return {"ok": False, "app": str(app), "command": command, "error": str(detail).strip()}
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


def plecs_running() -> bool:
    """Best-effort check whether the PLECS GUI process exists on this host."""
    if sys.platform == "win32":
        commands = [["tasklist", "/FI", "IMAGENAME eq plecs.exe", "/NH"]]
    else:
        commands = [["pgrep", "-x", "PLECS"], ["pgrep", "-f", r"PLECS\.app/Contents/MacOS/PLECS"]]

    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0 and "plecs" in result.stdout.lower():
            return True
    return False
