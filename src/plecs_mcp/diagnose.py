"""Map PLECS RPC errors to a cause and concrete next steps."""

from __future__ import annotations

RULES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "algebraic loop",
        "algebraic-loop",
        "The model contains an algebraic loop that the solver cannot break.",
        (
            "Set SolverOpts.AlgebraicLoopMethod or enable 'Minimize algebraic loops' in the circuit settings.",
            "Insert a small delay/state in the loop, or use the algebraic-loop tolerance parameter.",
        ),
    ),
    (
        "stiff",
        "stiffness",
        "The system is stiff for the selected solver/step size.",
        ("Try Solver=radau or Solver=auto.", "Reduce MaxStep or tighten RelTol/AbsTol."),
    ),
    (
        "singular matrix",
        "singular-matrix",
        "The state-space/topology matrix is singular for this switch combination.",
        (
            "Check for floating nodes, shorted sources, or missing references.",
            "Verify the SwitchVector matches the number of switches reported by StateSpaceOrder.",
        ),
    ),
    (
        "switch vector length mismatch",
        "switch-vector",
        "The switch vector length does not match the circuit's switch count.",
        ("Call plecs_state_space(model) without switches to see the expected order.",),
    ),
    (
        "nan",
        "numeric",
        "The simulation produced NaN/Inf before finishing.",
        (
            "Look for division by zero, negative inductance/capacitance, or an unstable controller.",
            "Start from zero initial conditions and check the execution log counters.",
        ),
    ),
    (
        "exceeded maximum runtime",
        "timeout",
        "PLECS stopped the run because SolverOpts.Timeout elapsed.",
        (
            "Increase the timeout or shorten TimeSpan.",
            "Reduce MaxStep/Refine or simplify the model before retrying.",
        ),
    ),
    (
        "cannot find analysis named",
        "analysis-name",
        "The analysis name passed is not the Name property of any analysis.",
        ("Read the Name properties from plecs_get_model_tree(model_path, summary=True).",),
    ),
    (
        "invalid scope path",
        "scope-path",
        "The scope path does not exist in the open model.",
        (
            "Read the exact scope paths from plecs_overview(model)['scopes'] or getModelTree summary.",
            "Scope paths look like 'model/Scope' or 'model/Subsystem/Scope'.",
        ),
    ),
    (
        "cannot find scope",
        "scope-path",
        "The scope path does not exist in the open model.",
        (
            "Read the exact scope paths from plecs_overview(model)['scopes'] or getModelTree summary.",
            "Scope paths look like 'model/Scope' or 'model/Subsystem/Scope'.",
        ),
    ),
    (
        "invalid scope command",
        "scope-command",
        "The scope command is not available over RPC.",
        (
            "Use HoldTrace / RemoveTrace / ClearTraces / SaveTraces / LoadTraces.",
            "ExportCSV/GetCursorData are not scope commands; use plecs_webserver getScopeCsv/getCursorData.",
        ),
    ),
    (
        "invalid webserver command",
        "webserver-command",
        "The webserver command is not available on this build.",
        (
            "Use getScopeInfo / getTraceNames / getScopeSignals / getScopeCsv / getCursorData / getScopeBitmap / getCircuitBitmap.",
            "getScope* take [scope]; getCircuitBitmap takes [model_name]; getCursorData takes [scope] or [scope, {\"Index\": 0}].",
        ),
    ),
    (
        "trace '' not found",
        "trace-name",
        "HoldTrace/RemoveTrace needs a non-empty trace name.",
        ("Call plecs_webserver('getTraceNames', [scope]) to list the available traces.",),
    ),
    (
        "trace file ended prematurely",
        "trace-file",
        "The .trace file is incomplete; this usually means SaveTraces ran on a scope with no simulation data.",
        (
            "Run a simulation before SaveTraces.",
            "Pass a non-empty .trace written by SaveTraces to LoadTraces.",
        ),
    ),
    (
        "could not find script with name",
        "script-name",
        "ScriptName is not the exact Name of a Script block in the model file.",
        (
            "Read the Script { Name \"...\" } block in the .plecs file, or use plecs_overview(model)['scripts'].",
            "The RPC model tree does not expose script names.",
        ),
    ),
    (
        "invalid subsystem path",
        "path",
        "The subsystem path does not exist (names may contain line breaks, e.g. 'PID\\nController').",
        ("Get exact names from plecs_get_model_tree(model_path, summary=True).",),
    ),
    (
        "non-atomic subsystem",
        "fmu",
        "Only atomic subsystems can be exported as FMUs.",
        ("Enable 'Treat as atomic unit' on the subsystem, then export again.",),
    ),
    (
        "cannot reach plecs",
        "connection",
        "The RPC endpoint is not reachable.",
        (
            "Call plecs_connect (it can start PLECS on this host).",
            "Enable Preferences -> RPC and confirm the port.",
        ),
    ),
    (
        "invalid path",
        "path-kind",
        "The value is not the kind of path this method expects.",
        (
            "getCircuitBitmap expects a model name, not a .plecs file path.",
            "exportfmu expects a subsystem path inside the open model.",
        ),
    ),
    (
        "named parameters are not supported",
        "positional-params",
        "PLECS JSON-RPC accepts positional parameters only.",
        ("Pass a JSON array of positional params; see plecs://docs/gotchas.",),
    ),
    (
        "invalid method parameters",
        "parameters",
        "The positional parameter shape does not match the method.",
        (
            "Check the tool docstring or plecs://docs/gotchas.",
            "For runScript use [model, {\"ScriptName\": name}].",
        ),
    ),
    (
        "permission denied",
        "permission",
        "A file or folder could not be written.",
        ("Write under PLECS_MCP_OUTPUT_DIR, or set PLECS_MCP_ALLOWED_ROOTS.",),
    ),
)


def diagnose(message: str) -> dict[str, object] | None:
    lowered = (message or "").lower()
    for needle, kind, cause, steps in RULES:
        if needle in lowered:
            return {"kind": kind, "cause": cause, "next_steps": list(steps)}
    return None


def with_hint(message: str) -> str:
    """Append a compact diagnosis to an error string (used before raising ToolError)."""
    found = diagnose(message)
    if not found:
        return message
    steps = " | ".join(found["next_steps"])  # type: ignore[index]
    return f"{message}\n\n[{found['kind']}] {found['cause']} Next: {steps}"
