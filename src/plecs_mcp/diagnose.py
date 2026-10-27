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
        "invalid scope command",
        "scope-command",
        "The scope command is not available over RPC.",
        (
            "Use HoldTrace / RemoveTrace / ClearTraces / SaveTraces / LoadTraces.",
            "For waveform data use plecs_webserver('getScopeCsv', [scope]).",
        ),
    ),
    (
        "invalid webserver command",
        "webserver-command",
        "The webserver command is not available on this build.",
        ("Use getScopeInfo / getTraceNames / getScopeSignals / getScopeCsv / getCursorData / getScopeBitmap / getCircuitBitmap.",),
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
