"""Filesystem guardrails for data that PLECS asks us to write."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

BLOCKED_PREFIXES = (
    "/Applications",
    "/System",
    "/Library",
    "/usr",
    "/bin",
    "/sbin",
    "/etc",
    "/private/etc",
)


class PathNotAllowed(ValueError):
    """The requested path is outside the allowed write roots."""


def output_dir() -> Path:
    return Path(os.getenv("PLECS_MCP_OUTPUT_DIR", "~/.plecs-mcp/out")).expanduser().resolve()


def allowed_roots() -> list[Path]:
    raw = os.getenv("PLECS_MCP_ALLOWED_ROOTS")
    if raw:
        roots = [Path(part).expanduser() for part in raw.split(os.pathsep) if part.strip()]
    else:
        roots = [Path.home(), Path("/tmp"), Path(tempfile.gettempdir())]
    return [root.resolve() for root in roots]


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def check_writable(path: str | Path, *, overwrite: bool = False) -> Path:
    """Resolve ``path`` and refuse install dirs, stray roots, and silent overwrites."""
    target = Path(path).expanduser().resolve()
    for blocked in BLOCKED_PREFIXES:
        if _is_under(target, Path(blocked).resolve()):
            raise PathNotAllowed(f"refusing to write inside {blocked}: {target}")
    roots = allowed_roots()
    if not any(_is_under(target, root) for root in roots):
        joined = os.pathsep.join(str(root) for root in roots)
        raise PathNotAllowed(f"{target} is outside PLECS_MCP_ALLOWED_ROOTS ({joined})")
    if target.exists() and not overwrite:
        raise PathNotAllowed(f"refusing to overwrite existing file: {target} (pass overwrite=true)")
    return target


def unique_output_path(directory: Path, stem: str, suffix: str) -> Path:
    """Timestamped path inside the MCP output directory (never overwrites)."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_") or "result"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = directory / f"{safe}-{stamp}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{safe}-{stamp}-{counter}{suffix}"
        counter += 1
    return candidate
