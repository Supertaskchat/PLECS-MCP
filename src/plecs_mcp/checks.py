"""Declarative acceptance checks over simulation/analysis summaries."""

from __future__ import annotations

import operator
from typing import Any

OPERATORS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
}

TIME_METRICS = {"start", "stop", "points"}
SIGNAL_METRICS = {"min", "max", "mean", "p2p", "rms", "first", "last"}
ANALYSIS_METRICS = {"gain_crossover_hz", "phase_margin_deg", "stable", "magnitude_max", "phase_min"}


def _actual(check: dict[str, Any], sim: dict[str, Any] | None, analysis: dict[str, Any] | None) -> Any:
    kind = check.get("type", "signal")
    if kind == "time":
        metric = check.get("metric", "stop")
        if metric not in TIME_METRICS or not sim:
            raise ValueError(f"unsupported time metric {metric!r}")
        return sim.get("time", {}).get(metric)
    if kind == "analysis":
        response_index = int(check.get("response", 0))
        if not analysis or not analysis.get("responses"):
            raise ValueError("analysis results are required for analysis checks")
        responses = analysis["responses"]
        if response_index >= len(responses):
            raise ValueError(f"response {response_index} not present")
        response = responses[response_index]
        metric = check.get("metric", "phase_margin_deg")
        if metric == "magnitude_max":
            return (response.get("magnitude_db") or {}).get("max")
        if metric == "phase_min":
            return (response.get("phase_deg") or {}).get("min")
        if metric not in ANALYSIS_METRICS:
            raise ValueError(f"unsupported analysis metric {metric!r}")
        return response.get(metric)
    metric = check.get("metric", "rms")
    if metric not in SIGNAL_METRICS or not sim:
        raise ValueError(f"unsupported signal metric {metric!r}")
    index = int(check.get("index", 0))
    signals = sim.get("signals") or []
    if index >= len(signals):
        raise ValueError(f"signal {index} not present")
    return signals[index].get(metric)


def evaluate(
    checks: list[dict[str, Any]],
    sim: dict[str, Any] | None = None,
    analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for check in checks:
        entry: dict[str, Any] = {"check": check}
        try:
            actual = _actual(check, sim, analysis)
            op = OPERATORS[check.get("op", ">")]
            expected = check.get("value")
            passed = actual is not None and op(actual, expected)
            entry.update({"actual": actual, "expected": expected, "pass": bool(passed)})
        except (KeyError, TypeError, ValueError) as exc:
            entry.update({"actual": None, "pass": False, "error": str(exc)})
        results.append(entry)
    return {"passed": all(item.get("pass") for item in results), "results": results}
