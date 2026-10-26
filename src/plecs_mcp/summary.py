"""Human-scale summaries for simulation and analysis results.

PLECS over JSON-RPC returns ``Values`` as **signals x time** and small-signal
results as ``{F, Gr, Gi}``; both are normalised here before summarising.
"""

from __future__ import annotations

import math
from typing import Any, Iterable


def _clean(value: Any) -> float | None:
    """JSON cannot carry inf/nan; degrade them to null."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _numbers(values: Iterable[Any]) -> list[float]:
    out: list[float] = []
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and math.isfinite(value):
            out.append(float(value))
    return out


def _channels(values: Any, points: int) -> list[list[float]]:
    """Return one list per signal, accepting both orientations."""
    if not isinstance(values, list) or not values:
        return []
    rows = [row for row in values if isinstance(row, list)]
    if len(rows) != len(values):
        return []
    if points and len(values) == points and rows and len(rows[0]) != points:
        # time x signals -> transpose
        return [[row[i] for row in rows if i < len(row)] for i in range(len(rows[0]))]
    return [list(row) for row in rows]


def _stats(samples: list[float]) -> dict[str, Any]:
    if not samples:
        return {"points": 0}
    total = sum(samples)
    mean = total / len(samples)
    rms = math.sqrt(sum(x * x for x in samples) / len(samples))
    return {
        "points": len(samples),
        "min": _clean(min(samples)),
        "max": _clean(max(samples)),
        "mean": _clean(mean),
        "p2p": _clean(max(samples) - min(samples)),
        "rms": _clean(rms),
        "first": _clean(samples[0]),
        "last": _clean(samples[-1]),
    }


def summarize_time_series(result: dict[str, Any]) -> dict[str, Any]:
    time = _numbers(result.get("Time") or [])
    channels = _channels(result.get("Values"), len(time))
    summary = {
        "kind": "time-series",
        "time": {
            "points": len(time),
            "start": time[0] if time else None,
            "stop": time[-1] if time else None,
        },
        "signals": [_stats(ch) for ch in channels],
    }
    if not channels:
        summary["note"] = (
            "no top-level outports: simulate returns no data; "
            "use plecs_webserver getScopeCsv or add an outport"
        )
    return summary


def _as_responses(gr: Any, gi: Any) -> list[tuple[list[float], list[float]]]:
    """Normalise Gr/Gi into a list of (real, imag) pairs."""
    if isinstance(gr, list) and gr and isinstance(gr[0], list):
        real_rows = [list(row) for row in gr if isinstance(row, list)]
        imag_rows = [list(row) for row in gi if isinstance(row, list)] if isinstance(gi, list) else []
        return [
            (real, imag_rows[i] if i < len(imag_rows) else [0.0] * len(real))
            for i, real in enumerate(real_rows)
        ]
    if isinstance(gr, list):
        return [(list(gr), list(gi) if isinstance(gi, list) else [0.0] * len(gr))]
    return []


def _interp_log(x0: float, x1: float, y0: float, y1: float, target: float) -> float:
    if y1 == y0:
        return x0
    ratio = (target - y0) / (y1 - y0)
    return 10 ** (math.log10(x0) + ratio * (math.log10(x1) - math.log10(x0)))


def _response_summary(freq: list[float], real: list[float], imag: list[float]) -> dict[str, Any]:
    points = min(len(freq), len(real), len(imag))
    mag_db: list[float] = []
    phase_deg: list[float] = []
    for i in range(points):
        magnitude = math.hypot(real[i], imag[i])
        mag_db.append(20 * math.log10(magnitude) if magnitude > 0 else float("-inf"))
        phase_deg.append(math.degrees(math.atan2(imag[i], real[i])))

    summary: dict[str, Any] = {
        "points": points,
        "magnitude_db": {"min": _clean(min(mag_db)), "max": _clean(max(mag_db))},
        "phase_deg": {"min": _clean(min(phase_deg)), "max": _clean(max(phase_deg))},
    }

    for i in range(points - 1):
        a, b = mag_db[i], mag_db[i + 1]
        if not (math.isfinite(a) and math.isfinite(b)) or a == b:
            continue
        if not ((a >= 0 > b) or (a > 0 >= b)):
            continue
        fc = _interp_log(freq[i], freq[i + 1], a, b, 0.0)
        if freq[i] > 0 and freq[i + 1] > 0 and freq[i + 1] != freq[i]:
            ratio = (math.log10(fc) - math.log10(freq[i])) / (math.log10(freq[i + 1]) - math.log10(freq[i]))
        else:
            ratio = (fc - freq[i]) / (freq[i + 1] - freq[i]) if freq[i + 1] != freq[i] else 0.0
        phase = phase_deg[i] + ratio * (phase_deg[i + 1] - phase_deg[i])
        summary["gain_crossover_hz"] = _clean(fc)
        summary["phase_margin_deg"] = _clean(180.0 + phase)
        summary["stable"] = summary["phase_margin_deg"] > 0
        break
    return summary


def summarize_frequency(result: dict[str, Any]) -> dict[str, Any]:
    freq = _numbers(result.get("F") or [])
    responses = _as_responses(result.get("Gr"), result.get("Gi"))
    return {
        "kind": "frequency-domain",
        "frequency": {
            "points": len(freq),
            "start_hz": freq[0] if freq else None,
            "stop_hz": freq[-1] if freq else None,
        },
        "responses": [
            {"index": i, **_response_summary(freq, real, imag)}
            for i, (real, imag) in enumerate(responses)
        ],
    }


def summarize_result(result: Any) -> Any:
    """Pick the right summary for a PLECS simulate/analyze payload."""
    if isinstance(result, list):
        return [summarize_result(item) for item in result]
    if not isinstance(result, dict):
        return result
    if "F" in result or "Gr" in result:
        return summarize_frequency(result)
    if "Time" in result or "Values" in result:
        return summarize_time_series(result)
    return result
