"""Local post-processing for simulation data (FFT / THD / metrics)."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np


def metrics(values: Sequence[float]) -> dict[str, Any]:
    samples = np.asarray([value for value in values if isinstance(value, (int, float))], dtype=float)
    if samples.size == 0:
        return {"points": 0}
    return {
        "points": int(samples.size),
        "min": float(samples.min()),
        "max": float(samples.max()),
        "mean": float(samples.mean()),
        "rms": float(np.sqrt(np.mean(samples**2))),
        "p2p": float(samples.max() - samples.min()),
    }


def thd(time: Sequence[float], values: Sequence[float], fundamental: float, harmonics: int = 10) -> dict[str, Any]:
    """THD of a uniformly sampled signal (DC removed) at the given fundamental."""
    t = np.asarray(time, dtype=float)
    y = np.asarray(values, dtype=float)
    if t.size < 8 or y.size != t.size:
        raise ValueError("time and signal must have the same length and enough samples")
    dt = float(np.median(np.diff(t)))
    if not np.isfinite(dt) or dt <= 0:
        raise ValueError("non-uniform or empty time vector")

    y = y - y.mean()
    spectrum = np.fft.rfft(y)
    frequencies = np.fft.rfftfreq(y.size, d=dt)
    magnitude = np.abs(spectrum) / (y.size / 2)

    def amplitude_at(freq: float) -> float:
        index = int(np.argmin(np.abs(frequencies - freq)))
        return float(magnitude[index])

    base = amplitude_at(fundamental)
    entries = []
    squares = 0.0
    nyquist = frequencies[-1]
    for order in range(2, harmonics + 1):
        freq = fundamental * order
        if freq >= nyquist:
            break
        amp = amplitude_at(freq)
        squares += amp**2
        entries.append({"order": order, "hz": freq, "amplitude": amp,
                        "percent": (amp / base * 100) if base else None})
    return {
        "fundamental_hz": fundamental,
        "fundamental_amplitude": base,
        "thd_percent": (float(np.sqrt(squares) / base * 100) if base else None),
        "harmonics": entries,
    }
