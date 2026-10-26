"""Configuration loading: ``config.yml`` first, environment variables win."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULTS = {"host": "127.0.0.1", "port": 1080, "timeout": 30.0}
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class PlecsConfig:
    host: str
    port: int
    timeout: float
    source: str


def _candidate_paths() -> list[Path]:
    paths: list[Path] = []
    explicit = os.getenv("PLECS_MCP_CONFIG")
    if explicit:
        paths.append(Path(explicit).expanduser())
    paths.append(Path.cwd() / "config.yml")
    paths.append(PROJECT_ROOT / "config.yml")
    return paths


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    section = data.get("plecs") if isinstance(data, dict) else None
    return section if isinstance(section, dict) else {}


def _env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return None


def load_config() -> PlecsConfig:
    """Resolve host/port/timeout from config.yml, then override with the environment."""
    values = dict(DEFAULTS)
    source = "defaults"

    for path in _candidate_paths():
        if path.is_file():
            file_values = _read_yaml(path)
            for key in DEFAULTS:
                if key in file_values and file_values[key] is not None:
                    values[key] = file_values[key]
            source = str(path)
            break

    host = _env("PLECS_RPC_HOST", "PLECS_HOST")
    port = _env("PLECS_RPC_PORT", "PLECS_PORT")
    timeout = _env("PLECS_RPC_TIMEOUT", "PLECS_TIMEOUT")
    if host:
        values["host"], source = host, "environment"
    if port:
        values["port"], source = port, "environment"
    if timeout:
        values["timeout"], source = timeout, "environment"

    return PlecsConfig(host=str(values["host"]), port=int(values["port"]), timeout=float(values["timeout"]), source=source)
