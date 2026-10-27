"""MCP server exposing the complete Plexim PLECS JSON-RPC method set.

One tool per RPC method (plus ``plecs_rpc`` as a raw escape hatch). Payloads that
PLECS base64-encodes (model trees, CSV, MAT files) are decoded or written to disk.

Every tool returns a JSON object so MCP clients get structured content; scalar and
array results are wrapped as ``{"result": ...}``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# An MCP server is usually started by an agent: never hit PyPI at import time.
os.environ.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .client import PlecsClient, PlecsError, PlecsRpcError, PlecsUnreachable, get_client, set_client
from .config import load_config
from .launcher import find_plecs_app, launch_plecs, plecs_running, wait_for_port
from .codec import (
    PlecsPayloadError,
    base64_to_bytes,
    base64_to_text,
    decode_model_tree,
    outports_from_tree,
    parse_merged_items,
    slice_csv,
    summarize_tree,
    write_bytes,
)
from .paths import PathNotAllowed, check_writable, output_dir, unique_output_path
from .session import STATE
from .summary import classify_analysis, summarize_result

mcp = FastMCP(
    name="PLECS",
    instructions=(
        "Controls Plexim PLECS Standalone through its JSON-RPC server. "
        "PLECS must be running with the RPC interface enabled (Preferences > RPC, default port 1080). "
        "Every tool maps 1:1 to a PLECS RPC method; call plecs_list_methods to discover what this "
        "PLECS build actually supports. Blocking calls (simulate/analyze) are serialized."
    ),
)


def _raw(method: str, params: list[Any] | None = None, timeout: float | None = None) -> Any:
    try:
        return get_client().call(method, params, timeout=timeout)
    except (PlecsUnreachable, PlecsRpcError, PlecsError, PlecsPayloadError) as exc:
        raise ToolError(str(exc)) from exc


def _wrap(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {"result": value}


def _call(method: str, params: list[Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
    return _wrap(_raw(method, params, timeout=timeout))


def _require(method: str) -> None:
    """Fail fast (with the build's method list) when an optional RPC is missing."""
    try:
        supported = get_client().methods()
    except PlecsError:
        return
    if method not in supported:
        raise ToolError(
            f"{method} is not supported by this PLECS build; available: {', '.join(sorted(supported))}"
        )


def _maybe_save(result: Any, save_to: str | None, overwrite: bool) -> Any:
    """MatFile results arrive as a base64 string; persist them instead of inlining."""
    if not save_to or not isinstance(result, str):
        return result
    try:
        meta = write_bytes(save_to, base64_to_bytes(result, "binary result"), overwrite=overwrite)
    except PlecsPayloadError as exc:
        raise ToolError(str(exc)) from exc
    return {"saved": meta, "note": "PLECS returned binary data; written to disk instead of inline base64"}


def _with_summary(payload: Any, summary: bool) -> Any:
    """Summaries are opt-in; binary results saved to disk stay untouched."""
    if not summary:
        return payload
    if isinstance(payload, dict) and "saved" in payload:
        return payload
    if isinstance(payload, (dict, list)):
        return {"summary": summarize_result(payload)}
    return payload


MAX_INLINE_POINTS = 20000
MAX_CSV_ROWS = 50000
SIM_TIMEOUT = 600.0


def _limit(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _point_count(payload: Any) -> int:
    if isinstance(payload, list):
        return sum(_point_count(item) for item in payload)
    if not isinstance(payload, dict):
        return 0
    for key in ("Time", "F"):
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def _save_json(payload: Any, stem: str) -> dict[str, Any]:
    target = unique_output_path(output_dir(), stem, ".json")
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return {"path": str(target), "bytes": target.stat().st_size}


def _auto_limit(payload: Any, stem: str, summary: bool, max_points: int | None) -> Any:
    """Keep big results out of the model context unless the caller asks for raw data."""
    limit = max_points if max_points is not None else _limit("PLECS_MCP_MAX_INLINE_POINTS", MAX_INLINE_POINTS)
    if isinstance(payload, dict) and "saved" in payload:  # binary already persisted
        return payload
    if summary:
        return {"summary": summarize_result(payload)}
    if _point_count(payload) > limit:
        saved = _save_json(payload, stem)
        return {
            "summary": summarize_result(payload),
            "saved": saved,
            "note": (
                f"result exceeded {limit} points; full data written to {saved['path']} "
                "(pass max_points to force inline, or save_to for a custom path)"
            ),
        }
    return payload


def _attach_summary_meta(payload: Any, model_name: str, analysis_name: str | None = None) -> Any:
    summary = payload.get("summary") if isinstance(payload, dict) else None
    if isinstance(summary, dict):
        if analysis_name:
            summary["analysis"] = analysis_name
            kind = classify_analysis(analysis_name)
            if kind:
                summary["analysis_kind"] = kind
                if kind not in ("ac-sweep", "frequency-response"):
                    summary["note"] = (
                        "gain crossover / phase margin are only meaningful for loop-gain AC sweeps"
                    )
        if summary.get("kind") == "time-series":
            _attach_outports(summary, model_name)
    return payload


def _attach_outports(summary: dict[str, Any], model_name: str) -> None:
    model_path = STATE.path_for(model_name)
    if not model_path:
        return
    try:
        tree = decode_model_tree(_raw("plecs.getModelTree", [model_path]))
    except ToolError:
        return
    ports = outports_from_tree(tree)
    if ports:
        summary["outports"] = ports
        summary["channel_note"] = (
            "signals follow PLECS outport numbering; the RPC model tree exposes names/positions "
            "but no port index, so channel i is not auto-labelled"
        )


def _inject_timeout(options: Any, timeout: float | None) -> Any:
    """PLECS' own wall-clock guard lives in SolverOpts.Timeout (verified on 5.0.6)."""
    limit = float(timeout) if timeout else float(os.getenv("PLECS_MCP_SIM_TIMEOUT", SIM_TIMEOUT))
    if isinstance(options, list):
        return [_inject_timeout(item, limit) for item in options]
    opts = dict(options or {})
    solver = dict(opts.get("SolverOpts") or {})
    solver.setdefault("Timeout", limit)
    opts["SolverOpts"] = solver
    return opts


CONNECT_HINTS = (
    "Start PLECS Standalone and open (or create) a model.",
    "Enable Preferences -> RPC (remote control) and confirm the port matches.",
    "Check the port is really listening: lsof -nP -iTCP:{port} -sTCP:LISTEN",
    "PLECS only accepts localhost connections; keep host at 127.0.0.1.",
    "If the port differs, set PLECS_RPC_PORT or edit config.yml.",
)


# ---------------------------------------------------------------- system / model

def _safe_methods(client: PlecsClient) -> set[str]:
    try:
        return client.methods()
    except PlecsError:
        return set()


@mcp.tool(name="plecs_connect")
def plecs_connect(
    host: str = "",
    port: int = 0,
    auto_start: bool = True,
    startup_timeout: float = 30.0,
    app_path: str = "",
) -> dict[str, Any]:
    """Handshake/health check; starts PLECS automatically when the RPC port is closed.

    If the endpoint is unreachable and ``auto_start`` is true (default), the newest
    ``/Applications/PLECS*.app`` (or ``PLECS_APP_PATH``/``app_path``) is opened with
    ``open -a`` and the RPC port is polled for up to ``startup_timeout`` seconds.
    Set ``auto_start=false`` for a pure health check. Returns
    ``{"ok": true, "started": ..., ...}`` or ``{"ok": false, "launch": {...}, "hints": [...]}``.
    """
    cfg = load_config()
    target_host = host or cfg.host
    target_port = int(port or cfg.port)
    endpoint = f"{target_host}:{target_port}"
    client = PlecsClient(host=target_host, port=target_port)
    hints = [hint.format(port=target_port) for hint in CONNECT_HINTS]

    def failure(error: str, *, launch: dict[str, Any] | None = None, startup_seconds: float | None = None,
                extra_hints: tuple[str, ...] = ()) -> dict[str, Any]:
        client.close()
        return {
            "ok": False,
            "endpoint": endpoint,
            "error": error,
            "started": False,
            "launch": launch,
            "startup_seconds": startup_seconds,
            "hints": list(extra_hints) + hints,
        }

    try:
        stats = client.call("plecs.statistics")
        started = False
        launch: dict[str, Any] | None = None
        startup_seconds: float | None = None
    except PlecsError as exc:
        if not auto_start:
            return failure(str(exc))

        if plecs_running():
            return failure(
                "PLECS is running but its RPC port is closed",
                launch={"ok": False, "app": None, "error": "skipped: PLECS process already exists"},
                extra_hints=(
                    "PLECS is already running: enable Preferences -> RPC, then call plecs_connect again.",
                ),
            )

        app = find_plecs_app(app_path or None)
        if app is None:
            if sys.platform not in ("darwin", "win32") and not sys.platform.startswith("linux"):
                return failure(
                    f"PLECS is not reachable and auto-start is not implemented for {sys.platform}",
                    launch={"ok": False, "app": None, "error": "unsupported-platform"},
                    extra_hints=("Start PLECS manually, then call plecs_connect again.",),
                )
            return failure(
                "PLECS is not reachable and no PLECS installation was found",
                launch={
                    "ok": False,
                    "app": None,
                    "error": "set PLECS_EXECUTABLE (or PLECS_APP_PATH) to the PLECS binary/bundle",
                },
                extra_hints=("Install PLECS, or point PLECS_EXECUTABLE at the executable.",),
            )

        launch = launch_plecs(app)
        if not launch["ok"]:
            return failure(f"could not start PLECS: {launch['error']}", launch=launch)

        startup_seconds = wait_for_port(target_host, target_port, startup_timeout)
        if startup_seconds is None:
            return failure(
                f"started {app.name} but the RPC port did not open within {startup_timeout:g}s",
                launch=launch,
                extra_hints=(
                    "PLECS is running: enable Preferences -> RPC and confirm the port, then retry.",
                ),
            )

        try:
            stats = client.call("plecs.statistics")
        except PlecsError as exc2:
            return failure(str(exc2), launch=launch, startup_seconds=startup_seconds)
        started = True

    set_client(client)
    models = stats.get("models") or []
    raw_version = stats.get("version")
    if isinstance(raw_version, list):
        version = ".".join(str(part) for part in raw_version[:3])
        build = raw_version[3] if len(raw_version) > 3 else None
    else:
        version, build = raw_version, None
    return {
        "ok": True,
        "endpoint": endpoint,
        "started": started,
        "launch": launch,
        "startup_seconds": startup_seconds,
        "config_source": cfg.source,
        "version": version,
        "build": build,
        "uptime": stats.get("uptime"),
        "has_server_license": stats.get("hasServerLicense"),
        "open_models": [m.get("id") for m in models if not m.get("library")],
        "model_count": len(models),
        "capabilities": {
            name: method in _safe_methods(client)
            for name, method in (
                ("save", "plecs.save"),
                ("get_model_tree", "plecs.getModelTree"),
                ("compare", "plecs.compare"),
                ("run_script", "plecs.runScript"),
                ("webserver", "plecs.webserver"),
                ("export_fmu", "plecs.exportfmu"),
                ("protect", "plecs.protect"),
            )
        },
    }


@mcp.tool(name="plecs_list_methods")
def plecs_list_methods() -> dict[str, Any]:
    """List RPC methods supported by the running PLECS build (system.listMethods)."""
    return {"methods": _raw("system.listMethods")}


@mcp.tool(name="plecs_method_help")
def plecs_method_help(method: str) -> dict[str, Any]:
    """Return PLECS's own help text for an RPC method (system.methodHelp)."""
    return _call("system.methodHelp", [method])


@mcp.tool(name="plecs_statistics")
def plecs_statistics() -> dict[str, Any]:
    """PLECS usage statistics: licence hints plus every open model and its state."""
    return _wrap(_raw("plecs.statistics"))


@mcp.tool(name="plecs_load")
def plecs_load(model_path: str) -> dict[str, Any]:
    """Open a model file. ``model_path`` must be absolute. Returns ``{"result": 0}`` on success."""
    result = _call("plecs.load", [model_path])
    resolved = str(Path(model_path).expanduser())
    name = Path(model_path).stem
    STATE.loaded(name, resolved)
    return {**result, "model_name": name, "model_path": resolved}


@mcp.tool(name="plecs_save")
def plecs_save(model_name: str, save_as: str | None = None, overwrite: bool = False) -> dict[str, Any]:
    """Save a model. With ``save_as`` the open model is RENAMED to the new file (use the new name afterwards).

    ``save_as`` is checked against the write policy: install dirs are refused and an existing
    target requires ``overwrite=true``.
    """
    if save_as is None:
        result = _call("plecs.save", [model_name])
        STATE.saved(model_name)
        return result
    try:
        check_writable(save_as, overwrite=overwrite)
    except PathNotAllowed as exc:
        raise ToolError(str(exc)) from exc
    result = _call("plecs.save", [model_name, save_as])
    new_name = Path(save_as).stem
    STATE.renamed(model_name, new_name)
    return {**result, "model_name": new_name, "note": "open model was renamed; use the new name"}

@mcp.tool(name="plecs_close")
def plecs_close(model_name: str, force: bool = False) -> dict[str, Any]:
    """Close a model WITHOUT saving. Refuses when this session changed it via plecs_set.

    PLECS exposes no "dirty" flag, so the guard only knows about edits made through this
    MCP session; pass ``force=true`` to discard them.
    """
    state = STATE.get(model_name)
    if state is not None and state.dirty and not force:
        raise ToolError(
            f"{model_name} has unsaved changes made through plecs_set; "
            "call plecs_save first or pass force=true to discard them"
        )
    result = _call("plecs.close", [model_name])
    STATE.closed(model_name)
    return result


@mcp.tool(name="plecs_get_model_tree")
def plecs_get_model_tree(model_path: str, summary: bool = False, decode: bool = True) -> dict[str, Any]:
    """Return the model tree (needs an absolute path; PLECS returns base64 JSON).

    ``summary=True`` drops connections and returns counts plus analysis/subsystem/component names.
    ``decode=False`` returns ``{"result": "<base64>"}`` unchanged.
    """
    raw = _raw("plecs.getModelTree", [model_path])
    if not decode:
        return {"result": raw}
    try:
        tree = decode_model_tree(raw)
    except PlecsPayloadError as exc:
        raise ToolError(str(exc)) from exc
    return summarize_tree(tree) if summary else tree


# ---------------------------------------------------------------- parameters

@mcp.tool(name="plecs_get")
def plecs_get(path: str, parameter: str | None = None) -> dict[str, Any]:
    """Read a component/model parameter (model params too, e.g. "TimeSpan").

    Values come back as strings; without ``parameter`` a dict of all parameters is returned.
    """
    params: list[Any] = [path] if parameter is None else [path, parameter]
    return _call("plecs.get", params)


@mcp.tool(name="plecs_set")
def plecs_set(path: str, parameter: str, value: str | int | float) -> dict[str, Any]:
    """Set a parameter. ``value`` is a PLECS expression string (numbers are passed through)."""
    result = _call("plecs.set", [path, parameter, str(value)])
    STATE.mark_dirty(path)
    return result


@mcp.tool(name="plecs_state_space")
def plecs_state_space(
    model_name: str,
    switches: dict[str, int] | list[int] | None = None,
) -> dict[str, Any]:
    """Extract A/B/C/D/I for one switch combination.

    ``switches`` may be a list in ``StateSpaceOrder.Switches`` order, or a mapping keyed by
    component name ("FET") or full path ("model/FET"). Missing keys default to 0.
    Two RPC calls are made for you: ``set SwitchVector`` then ``get Topology``.
    """
    order = _raw("plecs.get", [model_name, "StateSpaceOrder"])
    names = order.get("Switches", []) if isinstance(order, dict) else []
    if not isinstance(names, list) or not names:
        raise ToolError(f"{model_name} has no switch order; is it a circuit model?")

    if switches is None:
        vector = [0] * len(names)
    elif isinstance(switches, list):
        vector = [int(item) for item in switches]
    else:
        vector = []
        for full_path in names:
            short = str(full_path).split("/")[-1]
            if short in switches:
                vector.append(int(switches[short]))
            elif full_path in switches:
                vector.append(int(switches[full_path]))
            else:
                vector.append(0)

    if len(vector) != len(names):
        raise ToolError(f"switch vector length {len(vector)} != {len(names)} ({names})")

    _raw("plecs.set", [model_name, "SwitchVector", vector])
    STATE.mark_dirty(model_name)
    topology = _raw("plecs.get", [model_name, "Topology"])
    return {"order": order, "switch_vector": vector, "topology": topology}


# ---------------------------------------------------------------- simulation / analysis

@mcp.tool(name="plecs_simulate")
def plecs_simulate(
    model_name: str,
    options: dict[str, Any] | list[dict[str, Any]] | None = None,
    save_to: str | None = None,
    overwrite: bool = False,
    timeout: float | None = None,
    summary: bool = False,
    max_points: int | None = None,
) -> dict[str, Any]:
    """Run a simulation (blocking).

    ``options`` is the PLECS optStruct (``ModelVars`` / ``SolverOpts`` / ``OutputFormat``);
    pass a LIST of optStructs to let PLECS parallelize parameter sweeps.
    Only models with top-level Outports return data (``{"Time": [...], "Values": [...]}``;
    over JSON-RPC, Values is signals x time). ``save_to`` writes a MatFile result to disk.
    ``summary=true`` replaces the raw arrays with per-signal min/max/mean/p2p/rms.
    Results above ``max_points`` (default 20000) are written to the MCP output dir and
    returned as a summary. ``SolverOpts.Timeout`` is injected (default 600 s) so PLECS
    aborts on its own even if the client gives up.
    """
    opts = _inject_timeout(options, timeout)
    payload = _maybe_save(_raw("plecs.simulate", [model_name, opts], timeout=timeout), save_to, overwrite)
    payload = _auto_limit(payload, f"{model_name}-simulation", summary, max_points)
    return _wrap(_attach_summary_meta(payload, model_name))


@mcp.tool(name="plecs_analyze")
def plecs_analyze(
    model_name: str,
    analysis_name: str,
    options: dict[str, Any] | list[dict[str, Any]] | None = None,
    save_to: str | None = None,
    overwrite: bool = False,
    timeout: float | None = None,
    summary: bool = False,
    max_points: int | None = None,
) -> dict[str, Any]:
    """Run an analysis (blocking).

    ``analysis_name`` is the analysis NAME property (e.g. "Loop Gain (AC Sweep)"), not the
    tree node label ("AC Sweep"). AC/Impulse/Multitone return ``{F, Gr, Gi}``;
    Steady-State returns ``{Time, Values}``. ``summary=true`` replaces raw arrays with
    magnitude/phase ranges plus gain crossover and phase margin.
    ``SolverOpts.Timeout`` is injected (verified: ``AnalysisOpts.Timeout`` is rejected).
    """
    opts = _inject_timeout(options, timeout)
    payload = _maybe_save(
        _raw("plecs.analyze", [model_name, analysis_name, opts], timeout=timeout), save_to, overwrite
    )
    payload = _auto_limit(payload, f"{model_name}-analysis", summary, max_points)
    return _wrap(_attach_summary_meta(payload, model_name, analysis_name))


# ---------------------------------------------------------------- scopes

@mcp.tool(name="plecs_scope")
def plecs_scope(scope_path: str, command: str, argument: Any = None) -> dict[str, Any]:
    """Send a command to a scope (HoldTrace / RemoveTrace / ClearTraces / SaveTraces / LoadTraces).

    ``scope_path`` is like "model/Scope". RPC does NOT support ExportCSV/GetCursorData;
    use plecs_webserver with getScopeCsv/getCursorData instead.
    """
    params: list[Any] = [scope_path, command]
    if argument is not None:
        params.append(argument)
    return _call("plecs.scope", params)


@mcp.tool(name="plecs_webserver")
def plecs_webserver(
    command: str,
    arguments: list[Any] | None = None,
    decode_csv: bool = True,
    save_to: str | None = None,
    overwrite: bool = False,
    time_range: list[float] | None = None,
    decimate: int | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Undocumented PLECS webserver channel (verified on PLECS 5.0.6).

    Commands: getScopeInfo, getTraceNames, getScopeSignals, getScopeCsv, getCursorData,
    getScopeBitmap, getCircuitBitmap. Pass the command's own arguments in ``arguments``.

    ``getScopeCsv`` is base64 CSV; PLECS ignores its own range/size options, so
    ``time_range=[t0,t1]`` and ``decimate=N`` are applied here. CSVs above ``max_rows``
    (default 50000) are written to the MCP output dir and only metadata is returned.
    ``getScopeBitmap``/``getScopeSignals`` contain base64 PNG: with ``save_to`` the image is
    written to that file and only metadata is returned.
    """
    result = _raw("plecs.webserver", [command, *(arguments or [])])
    if not isinstance(result, dict):
        return _wrap(result)

    try:
        if isinstance(result.get("csv"), str):
            if not decode_csv:
                return _wrap(result)
            text = base64_to_text(result["csv"], "scope CSV")
            header, rows = slice_csv(text, time_range, decimate)
            limit = max_rows if max_rows is not None else _limit("PLECS_MCP_MAX_CSV_ROWS", MAX_CSV_ROWS)
            if time_range or decimate:
                import csv
                import io

                buffer = io.StringIO()
                writer = csv.writer(buffer, lineterminator="\n")
                writer.writerow(header)
                writer.writerows(rows)
                rendered = buffer.getvalue().rstrip("\n")
            else:
                rendered = text  # keep PLECS' original quoting/formatting

            if save_to:
                meta = write_bytes(save_to, rendered.encode("utf-8"), overwrite=overwrite)
                return {"saved": meta, "rows": len(rows), "columns": header,
                        "filtered": bool(time_range or decimate)}
            if len(rows) > limit:
                target = unique_output_path(output_dir(), f"{command}-{arguments[0] if arguments else 'scope'}", ".csv")
                target.write_text(rendered, encoding="utf-8")
                return {
                    "columns": header,
                    "rows": len(rows),
                    "saved": {"path": str(target), "bytes": target.stat().st_size},
                    "preview": [header] + rows[:5],
                    "note": f"CSV exceeded {limit} rows; full data written to {target}",
                }
            return {**result, "csv": rendered, "columns": header, "rows": len(rows)}
        elif save_to and isinstance(result.get("imageData"), str):
            meta = write_bytes(save_to, base64_to_bytes(result["imageData"], "image"), overwrite=overwrite)
            rest = {k: v for k, v in result.items() if k != "imageData"}
            return {"saved": meta, **rest}
    except PlecsPayloadError as exc:
        raise ToolError(str(exc)) from exc

    return _wrap(result)


# ---------------------------------------------------------------- code generation / packaging

@mcp.tool(name="plecs_codegen")
def plecs_codegen(path: str, options: dict[str, Any] | None = None, output_dir: str | None = None) -> dict[str, Any]:
    """Generate code with PLECS Coder (requires a PLECS Coder licence).

    Verified on 5.0.6: ``plecs.codegen`` runs and streams Coder diagnostics back as an RPC
    error ("Code generation error: ..."), which is surfaced verbatim. A model with blocks that
    are ignored during code generation (e.g. Small Signal Response) fails instead of producing
    partial artifacts.
    """
    params: list[Any] = [path]
    if options is not None or output_dir is not None:
        params.append(options or {})
    if output_dir is not None:
        params.append(output_dir)
    return _call("plecs.codegen", params, timeout=3600)


@mcp.tool(name="plecs_export_fmu")
def plecs_export_fmu(subsystem_path: str) -> dict[str, Any]:
    """Export a subsystem as an FMU (uses the subsystem's saved FMU Export settings).

    Verified on 5.0.6: only an atomic subsystem can be exported; a normal subsystem returns
    "Cannot export FMU for non-atomic subsystem". The signature is a single subsystem path.
    """
    _require("plecs.exportfmu")
    return _call("plecs.exportfmu", [subsystem_path], timeout=3600)


@mcp.tool(name="plecs_run_script")
def plecs_run_script(model_name: str, script_name: str, params: list[Any] | None = None) -> dict[str, Any]:
    """Run a model Simulation Script by name.

    Verified on PLECS 5.0.6: the method is listed by ``system.listMethods`` but every
    positional/dict shape tried returns ``server error: invalid method parameters``.
    The tool therefore passes ``[model_name, script_name]`` by default and lets you
    override the wire payload with ``params`` once the shape is known for your build.
    """
    _require("plecs.runScript")
    return _call("plecs.runScript", params if params is not None else [model_name, script_name], timeout=600)


# ---------------------------------------------------------------- misc

@mcp.tool(name="plecs_compare")
def plecs_compare(before_path: str, after_path: str) -> dict[str, Any]:
    """Compare two model files with PLECS's diff engine.

    Returns the raw ``MergedItem(...)`` lines plus parsed ``entries``
    (depth/left/right/change/type) for direct use.
    """
    _require("plecs.compare")
    raw = _raw("plecs.compare", [before_path, after_path])
    return {"diff": raw, "entries": parse_merged_items(raw)}


@mcp.tool(name="plecs_batch")
def plecs_batch(calls: list[dict[str, Any]], stop_on_error: bool = False) -> dict[str, Any]:
    """Run several RPC calls in one tool call (still serialized by the client lock).

    Each item is ``{"method": "plecs.get", "params": ["mdl/L1", "L"], "timeout": 30}``.
    Per-call failures are reported inline as ``{"ok": false, "error": ...}`` instead of
    aborting the batch, which makes parameter sweeps and multi-model inspection cheap.
    """
    results: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        method = call.get("method")
        if not isinstance(method, str) or not method:
            results.append({"index": index, "ok": False, "error": "missing method"})
            if stop_on_error:
                break
            continue
        try:
            value = _raw(method, call.get("params") or [], timeout=call.get("timeout"))
            results.append({"index": index, "method": method, "ok": True, "result": value})
        except ToolError as exc:
            results.append({"index": index, "method": method, "ok": False, "error": str(exc)})
            if stop_on_error:
                break
    return {"count": len(results), "results": results}


@mcp.tool(name="plecs_extract_execution_log_data")
def plecs_extract_execution_log_data() -> dict[str, Any]:
    """Runtime execution-log counters (Jacobian/Newton/solver call counts) for the last run."""
    return _wrap(_raw("plecs.extractExecutionLogData"))


@mcp.tool(name="plecs_set_cosim_server_enabled")
def plecs_set_cosim_server_enabled(enabled: bool) -> dict[str, Any]:
    """Enable/disable the PLECS FMU Co-Simulation endpoint (global PLECS state)."""
    _require("plecs.setCoSimServerEnabled")
    return _call("plecs.setCoSimServerEnabled", [enabled])


@mcp.tool(name="plecs_sign")
def plecs_sign(file_path: str) -> dict[str, Any]:
    """Append the PLECS demo signature to a model file (modifies the file)."""
    _require("plecs.sign")
    return _call("plecs.sign", [file_path])


@mcp.tool(name="plecs_protect")
def plecs_protect(subsystem_path: str, confirm: bool = False) -> dict[str, Any]:
    """Make a subsystem non-viewable/non-modifiable. IRREVERSIBLE once saved; requires confirm=true.

    Verified on 5.0.6: the call takes a single subsystem path, returns 0, and is idempotent;
    it changes the open model only, so the protection becomes permanent when you save it.
    """
    if not confirm:
        raise ToolError("plecs_protect is irreversible; call again with confirm=true to proceed")
    _require("plecs.protect")
    return _call("plecs.protect", [subsystem_path])


@mcp.tool(name="plecs_crash")
def plecs_crash(confirm: bool = False) -> dict[str, Any]:
    """Crash the running PLECS process (debug helper). Requires confirm=true."""
    if not confirm:
        raise ToolError("plecs_crash terminates PLECS and may lose unsaved work; call again with confirm=true")
    _require("plecs.crash")
    return _call("plecs.crash")


@mcp.tool(name="plecs_rpc")
def plecs_rpc(method: str, params: list[Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
    """Raw escape hatch: call any PLECS RPC method verbatim.

    Dict results are returned as-is; scalars and arrays are wrapped as ``{"result": ...}``.
    """
    return _call(method, params, timeout=timeout)


def main() -> None:
    parser = argparse.ArgumentParser(prog="plecs-mcp", description="MCP server for Plexim PLECS")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse", "streamable-http"],
        default="stdio",
        help="stdio for local agents (default); http/sse for remote agents",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address for http/sse")
    parser.add_argument("--port", type=int, default=8765, help="bind port for http/sse")
    args = parser.parse_args()

    logging.basicConfig(
        level=os.getenv("PLECS_MCP_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    for noisy in ("httpx", "httpx2", "httpcore", "httpcore2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if (
        args.transport != "stdio"
        and args.host not in ("127.0.0.1", "localhost", "::1")
        and not os.getenv("PLECS_MCP_ALLOW_REMOTE")
    ):
        parser.error(
            f"refusing to bind {args.host} without authentication; "
            "set PLECS_MCP_ALLOW_REMOTE=1 to override"
        )

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
