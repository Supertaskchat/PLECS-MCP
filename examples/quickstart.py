#!/usr/bin/env python3
"""End-to-end PLECS-MCP smoke test: connect -> load -> simulate -> close.

Run with the project's virtualenv, e.g.::

    .venv/bin/python examples/quickstart.py --model /path/to/model.plecs
    .venv/bin/python examples/quickstart.py --model model.plecs \
        --analysis "Loop Gain (AC Sweep)"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from plecs_mcp.launcher import find_plecs_app
from plecs_mcp.server import plecs_analyze, plecs_close, plecs_connect, plecs_load, plecs_simulate


def bundled_demo() -> Path | None:
    """Prefer a demo that has a top-level outport so simulate returns data."""
    app = find_plecs_app()
    if app is None:
        return None
    for root in (app / "Contents" / "demos", app / "demos", app.parent / "demos"):
        if not root.is_dir():
            continue
        preferred = root / "buck_converter_with_parameter_sweep" / "buck_converter_with_parameter_sweep.plecs"
        if preferred.is_file():
            return preferred
        candidates = sorted(root.rglob("*.plecs"))
        if candidates:
            return candidates[0]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="PLECS-MCP end-to-end smoke test")
    parser.add_argument("--model", default=os.getenv("PLECS_EXAMPLE_MODEL", ""), help="path to a .plecs file")
    parser.add_argument("--analysis", default="", help="analysis Name property (e.g. 'Loop Gain (AC Sweep)')")
    parser.add_argument("--time-span", type=float, default=1e-3, help="simulation TimeSpan in seconds")
    parser.add_argument("--no-auto-start", action="store_true", help="do not launch PLECS if the port is closed")
    args = parser.parse_args()

    status = plecs_connect(auto_start=not args.no_auto_start)
    if not status.get("ok"):
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {key: status.get(key) for key in ("endpoint", "version", "build", "started", "open_models")},
            indent=2,
            ensure_ascii=False,
        )
    )

    model_path = Path(args.model).expanduser() if args.model else bundled_demo()
    if model_path is None or not model_path.is_file():
        print("no model supplied and no bundled demo found; pass --model", file=sys.stderr)
        return 2
    model_path = model_path.resolve()

    loaded = plecs_load(str(model_path))
    name = loaded["model_name"]
    print(f"loaded {name} from {model_path}")
    try:
        simulation = plecs_simulate(name, {"SolverOpts": {"TimeSpan": args.time_span}}, summary=True)
        print(json.dumps(simulation, indent=2, ensure_ascii=False))
        if args.analysis:
            analysis = plecs_analyze(name, args.analysis, summary=True)
            print(json.dumps(analysis, indent=2, ensure_ascii=False))
    finally:
        try:
            plecs_close(name, force=True)
            print(f"closed {name}")
        except Exception as exc:  # keep the smoke test exit code meaningful
            print(f"close failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
