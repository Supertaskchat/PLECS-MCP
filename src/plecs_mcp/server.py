"""MCP server exposing the complete Plexim PLECS JSON-RPC method set.

One tool per RPC method (plus ``plecs_rpc`` as a raw escape hatch). Payloads that
PLECS base64-encodes (model trees, CSV, MAT files) are decoded or written to disk.

Every tool returns a JSON object so MCP clients get structured content; scalar and
array results are wrapped as ``{"result": ...}``.
"""

from __future__ import annotations

import argparse
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .client import PlecsClient, PlecsError, PlecsRpcError, PlecsUnreachable, get_client, set_client
from .config import load_config
from .codec import (
    PlecsPayloadError,
    base64_to_bytes,
    base64_to_text,
    decode_model_tree,
    summarize_tree,
    write_bytes,
)
from .summary import summarize_result

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


CONNECT_HINTS = (
    "Start PLECS Standalone and open (or create) a model.",
    "Enable Preferences -> RPC (remote control) and confirm the port matches.",
    "Check the port is really listening: lsof -nP -iTCP:{port} -sTCP:LISTEN",
    "PLECS only accepts localhost connections; keep host at 127.0.0.1.",
    "If the port differs, set PLECS_RPC_PORT or edit config.yml.",
)


# ---------------------------------------------------------------- system / model

@mcp.tool(name="plecs_connect")
def plecs_connect(host: str = "", port: int = 0) -> dict[str, Any]:
    """Handshake/health check with an explicit endpoint and troubleshooting hints.

    Optional: every other tool connects lazily. Use this when you want to verify the
    endpoint, pick a non-default host/port, or get an actionable error instead of a
    bare "connection refused". Returns ``{"ok": true, ...}`` or ``{"ok": false, "hints": [...]}``.
    """
    cfg = load_config()
    target_host = host or cfg.host
    target_port = int(port or cfg.port)
    endpoint = f"{target_host}:{target_port}"
    client = PlecsClient(host=target_host, port=target_port)

    try:
        stats = client.call("plecs.statistics")
    except PlecsError as exc:
        client.close()
        return {
            "ok": False,
            "endpoint": endpoint,
            "error": str(exc),
            "hints": [hint.format(port=target_port) for hint in CONNECT_HINTS],
        }

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
        "config_source": cfg.source,
        "version": version,
        "build": build,
        "uptime": stats.get("uptime"),
        "has_server_license": stats.get("hasServerLicense"),
        "open_models": [m.get("id") for m in models if not m.get("library")],
        "model_count": len(models),
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
    return _call("plecs.load", [model_path])


@mcp.tool(name="plecs_close")
def plecs_close(model_name: str) -> dict[str, Any]:
    """Close a model WITHOUT saving (PLECS offers no "dirty" flag; this always discards changes)."""
    return _call("plecs.close", [model_name])


@mcp.tool(name="plecs_save")
def plecs_save(model_name: str, save_as: str | None = None) -> dict[str, Any]:
    """Save a model. With ``save_as`` the open model is RENAMED to the new file (use the new name afterwards)."""
    params: list[Any] = [model_name] if save_as is None else [model_name, save_as]
    return _call("plecs.save", params)


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
    return _call("plecs.set", [path, parameter, str(value)])


# ---------------------------------------------------------------- simulation / analysis

@mcp.tool(name="plecs_simulate")
def plecs_simulate(
    model_name: str,
    options: dict[str, Any] | list[dict[str, Any]] | None = None,
    save_to: str | None = None,
    overwrite: bool = False,
    timeout: float | None = None,
    summary: bool = False,
) -> dict[str, Any]:
    """Run a simulation (blocking).

    ``options`` is the PLECS optStruct (``ModelVars`` / ``SolverOpts`` / ``OutputFormat``);
    pass a LIST of optStructs to let PLECS parallelize parameter sweeps.
    Only models with top-level Outports return data (``{"Time": [...], "Values": [...]}``;
    over JSON-RPC, Values is signals x time). ``save_to`` writes a MatFile result to disk.
    ``summary=true`` replaces the raw arrays with per-signal min/max/mean/p2p/rms.
    """
    params: list[Any] = [model_name] if options is None else [model_name, options]
    payload = _maybe_save(_raw("plecs.simulate", params, timeout=timeout), save_to, overwrite)
    return _wrap(_with_summary(payload, summary))


@mcp.tool(name="plecs_analyze")
def plecs_analyze(
    model_name: str,
    analysis_name: str,
    options: dict[str, Any] | list[dict[str, Any]] | None = None,
    save_to: str | None = None,
    overwrite: bool = False,
    timeout: float | None = None,
    summary: bool = False,
) -> dict[str, Any]:
    """Run an analysis (blocking).

    ``analysis_name`` is the analysis NAME property (e.g. "Loop Gain (AC Sweep)"), not the
    tree node label ("AC Sweep"). AC/Impulse/Multitone return ``{F, Gr, Gi}``;
    Steady-State returns ``{Time, Values}``. ``summary=true`` replaces raw arrays with
    magnitude/phase ranges plus gain crossover and phase margin (AC sweeps).
    """
    params: list[Any] = [model_name, analysis_name] if options is None else [model_name, analysis_name, options]
    payload = _maybe_save(_raw("plecs.analyze", params, timeout=timeout), save_to, overwrite)
    return _wrap(_with_summary(payload, summary))


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
) -> dict[str, Any]:
    """Undocumented PLECS webserver channel (verified on PLECS 5.0.6).

    Commands: getScopeInfo, getTraceNames, getScopeSignals, getScopeCsv, getCursorData,
    getScopeBitmap, getCircuitBitmap. Pass the command's own arguments in ``arguments``.
    ``getScopeCsv`` is base64 CSV and is decoded to text; ``getScopeBitmap``/``getScopeSignals``
    contain base64 PNG. With ``save_to`` the payload is written to that file (CSV or PNG)
    and only metadata is returned.
    """
    result = _raw("plecs.webserver", [command, *(arguments or [])])
    if not isinstance(result, dict):
        return _wrap(result)

    try:
        if isinstance(result.get("csv"), str):
            text = base64_to_text(result["csv"], "scope CSV") if decode_csv else None
            if text is not None:
                if save_to:
                    meta = write_bytes(save_to, text.encode("utf-8"), overwrite=overwrite)
                    lines = text.splitlines()
                    return {"saved": meta, "rows": max(len(lines) - 1, 0), "header": lines[0] if lines else ""}
                result = {**result, "csv": text}
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
    """Generate code with PLECS Coder (requires a PLECS Coder licence)."""
    params: list[Any] = [path]
    if options is not None or output_dir is not None:
        params.append(options or {})
    if output_dir is not None:
        params.append(output_dir)
    return _call("plecs.codegen", params, timeout=3600)


@mcp.tool(name="plecs_export_fmu")
def plecs_export_fmu(subsystem_path: str) -> dict[str, Any]:
    """Export a subsystem as an FMU (uses the subsystem's saved FMU Export settings)."""
    return _call("plecs.exportfmu", [subsystem_path], timeout=3600)


@mcp.tool(name="plecs_run_script")
def plecs_run_script(model_name: str, script_name: str, params: list[Any] | None = None) -> dict[str, Any]:
    """Run a model Simulation Script by name.

    The exact RPC parameter shape is unverified on 5.0.6; pass ``params`` to override the
    ``[model_name, script_name]`` default if your build expects something else.
    """
    return _call("plecs.runScript", params if params is not None else [model_name, script_name])


# ---------------------------------------------------------------- misc

@mcp.tool(name="plecs_compare")
def plecs_compare(before_path: str, after_path: str) -> dict[str, Any]:
    """Compare two model files with PLECS's diff engine (returns "MergedItem(...)" lines)."""
    return {"diff": _raw("plecs.compare", [before_path, after_path])}


@mcp.tool(name="plecs_extract_execution_log_data")
def plecs_extract_execution_log_data() -> dict[str, Any]:
    """Runtime execution-log counters (Jacobian/Newton/solver call counts) for the last run."""
    return _wrap(_raw("plecs.extractExecutionLogData"))


@mcp.tool(name="plecs_set_cosim_server_enabled")
def plecs_set_cosim_server_enabled(enabled: bool) -> dict[str, Any]:
    """Enable/disable the PLECS FMU Co-Simulation endpoint (global PLECS state)."""
    return _call("plecs.setCoSimServerEnabled", [enabled])


@mcp.tool(name="plecs_sign")
def plecs_sign(file_path: str) -> dict[str, Any]:
    """Append the PLECS demo signature to a model file (modifies the file)."""
    return _call("plecs.sign", [file_path])


@mcp.tool(name="plecs_protect")
def plecs_protect(subsystem_path: str, confirm: bool = False) -> dict[str, Any]:
    """Make a subsystem non-viewable/non-modifiable. IRREVERSIBLE once saved; requires confirm=true."""
    if not confirm:
        raise ToolError("plecs_protect is irreversible; call again with confirm=true to proceed")
    return _call("plecs.protect", [subsystem_path])


@mcp.tool(name="plecs_crash")
def plecs_crash(confirm: bool = False) -> dict[str, Any]:
    """Crash the running PLECS process (debug helper). Requires confirm=true."""
    if not confirm:
        raise ToolError("plecs_crash terminates PLECS and may lose unsaved work; call again with confirm=true")
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

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
