"""PNG rendering for waveforms and Bode plots (matplotlib, Agg backend).

matplotlib is imported lazily: RPC-only sessions should not pay its startup cost.
"""

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path
from typing import Any, Sequence

from .summary import frequency_responses


def _mpl_cache() -> str:
    preferred = Path.home() / ".plecs-mcp" / "matplotlib"
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        probe = preferred / ".writable"
        probe.touch()
        probe.unlink()
        return str(preferred)
    except OSError:
        return os.path.join(tempfile.gettempdir(), "plecs-mcp-matplotlib")


_PYPLOT: Any = None
_NUMPY: Any = None


def _plt() -> Any:
    global _PYPLOT
    if _PYPLOT is None:
        os.environ.setdefault("MPLCONFIGDIR", _mpl_cache())
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        _PYPLOT = plt
    return _PYPLOT


def _np() -> Any:
    global _NUMPY
    if _NUMPY is None:
        import numpy as np

        _NUMPY = np
    return _NUMPY


def _downsample(x: Sequence[float], y: Sequence[float], limit: int) -> tuple[Any, Any]:
    np = _np()
    xa, ya = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if limit and xa.size > limit:
        step = int(np.ceil(xa.size / limit))
        xa, ya = xa[::step], ya[::step]
    return xa, ya


def time_series_png(
    time: Sequence[float],
    signals: Sequence[Sequence[float]],
    names: Sequence[str] | None = None,
    title: str | None = None,
    max_points: int = 5000,
) -> bytes:
    plt = _plt()
    t, _ = _downsample(time, time, max_points)
    figure, axes = plt.subplots(len(signals) or 1, 1, figsize=(9, 2.4 * max(len(signals), 1)), squeeze=False)
    for index, signal in enumerate(signals):
        _, values = _downsample(time, signal, max_points)
        label = names[index] if names and index < len(names) else f"signal {index + 1}"
        axes[index][0].plot(t[: values.size], values, linewidth=1.0, label=label)
        axes[index][0].set_ylabel(label)
        axes[index][0].grid(True, alpha=0.3)
        axes[index][0].legend(loc="upper right", fontsize=8)
    axes[-1][0].set_xlabel("time / s")
    if title:
        figure.suptitle(title)
    figure.tight_layout()
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=120)
    plt.close(figure)
    return buffer.getvalue()


def frequency_png(
    freq: Sequence[float],
    responses: Sequence[tuple[Sequence[float], Sequence[float]]],
    names: Sequence[str] | None = None,
    title: str | None = None,
) -> bytes:
    plt = _plt()
    np = _np()
    responses = list(responses)[:4]
    figure, axes = plt.subplots(len(responses), 2, figsize=(11, 2.6 * max(len(responses), 1)), squeeze=False)
    for index, (real, imag) in enumerate(responses):
        f = np.asarray(freq, dtype=float)
        magnitude = 20 * np.log10(np.maximum(np.hypot(np.asarray(real, float), np.asarray(imag, float)), 1e-30))
        phase = np.degrees(np.arctan2(np.asarray(imag, float), np.asarray(real, float)))
        label = names[index] if names and index < len(names) else f"response {index + 1}"
        axes[index][0].semilogx(f, magnitude, linewidth=1.0, color="tab:blue")
        axes[index][0].axhline(0, color="grey", linewidth=0.6, linestyle="--")
        axes[index][0].set_ylabel(f"{label}\n|H| / dB")
        axes[index][0].grid(True, which="both", alpha=0.3)
        axes[index][1].semilogx(f, phase, linewidth=1.0, color="tab:orange")
        axes[index][1].set_ylabel("phase / deg")
        axes[index][1].grid(True, which="both", alpha=0.3)
    axes[-1][0].set_xlabel("frequency / Hz")
    axes[-1][1].set_xlabel("frequency / Hz")
    if title:
        figure.suptitle(title)
    figure.tight_layout()
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=120)
    plt.close(figure)
    return buffer.getvalue()


def responses_from_result(result: dict[str, Any]) -> list[tuple[list[float], list[float]]]:
    return frequency_responses(result)
