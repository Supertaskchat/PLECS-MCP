"""Placement orientation rules for schematic components.

PLECS expresses placement with ``Direction`` (right/left/up/down, a 90 degree
step) and ``Flipped`` (a mirror inside that axis).  Measured on 5.0.7 for the
two-terminal power components: terminal 1 sits at the side **opposite** the
direction vector, and ``Flipped`` swaps it, so

    right/off -> term 1 left     left/off  -> term 1 right
    right/on  -> term 1 right    left/on   -> term 1 left
    up/off    -> term 1 bottom   down/off  -> term 1 top

which means ``left`` and ``Flipped on`` are the same 180 degree turn and there
are only two visual states per axis.

The conventions below are **measured from the 239 models shipped with PLECS
5.0.7**, not invented: for each (type, axis) the dominant placement is the one
that at least 70% of at least 10 real instances use. Highlights:

* horizontal two-terminal power parts (inductor 78% of 359, breaker 100% of 18)
  put terminal 1 on the **right** -> ``Direction left``;
* vertical passives and sources (capacitor 100% of 270, DC voltage source 100% of
  181) put terminal 1 at the **bottom**;
* vertical diodes and thyristors (96% of 219, 77% of 30) put terminal 1 at the
  **top**, i.e. the valve points down.

Entries with weak support are deliberately absent: the checker stays silent when
the corpus does not agree, instead of imposing a taste.
"""

from __future__ import annotations

from typing import Any

from . import plecsfile
from .model_graph import ModelGraph, build_graph

SIDES = ("left", "right", "top", "bottom")
OPPOSITE = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}
TERM1_SIDE = {"right": "left", "left": "right", "up": "bottom", "down": "top"}

# Two-terminal types whose symbol carries a polarity/reference marker.

# Which terminal the visible marker is drawn on (default 1).  A DC/AC voltage
# source draws "+" on terminal 2, which is why its arrow points downstream.

# Three-terminal devices need per-topology judgement (gate/D/S geometry differs
# between library variants), so they are reported but never auto-chosen.



TERM1_SIDE_EXPECTED: dict[tuple[str, str], dict[str, Any]] = {
    # type, axis -> dominant placement (support in the bundled corpus)
    ("Inductor", "H"): {"side": "right", "direction": "left", "flipped": "off", "n": 359, "share": 78},
    ("Breaker", "H"): {"side": "right", "direction": "left", "flipped": "off", "n": 18, "share": 100},
    ("Diode", "H"): {"side": "right", "direction": "right", "flipped": "on", "n": 52, "share": 73},
    ("VoltageSource", "H"): {"side": "right", "direction": "right", "flipped": "on", "n": 26, "share": 100},
    ("Capacitor", "V"): {"side": "bottom", "direction": "down", "flipped": "on", "n": 270, "share": 100},
    ("DCVoltageSource", "V"): {"side": "bottom", "direction": "up", "flipped": "off", "n": 181, "share": 100},
    ("VoltageSource", "V"): {"side": "bottom", "direction": "down", "flipped": "on", "n": 66, "share": 100},
    ("ACVoltageSource", "V"): {"side": "bottom", "direction": "down", "flipped": "on", "n": 35, "share": 100},
    ("Diode", "V"): {"side": "top", "direction": "down", "flipped": "off", "n": 219, "share": 96},
    ("Thyristor", "V"): {"side": "top", "direction": "down", "flipped": "off", "n": 30, "share": 77},
}


def expected_for(component_type: str, direction: str) -> dict[str, Any] | None:
    """Dominant placement for a type on the axis implied by its own direction."""
    axis = "H" if (direction or "").strip().lower() in ("right", "left") else "V"
    return TERM1_SIDE_EXPECTED.get((component_type, axis))


def term1_side(direction: str, flipped: str) -> str | None:
    """Which screen side terminal 1 is on for a 2-terminal component."""
    base = TERM1_SIDE.get((direction or "").strip().lower())
    if base is None:
        return None
    on = str(flipped or "off").strip().lower() == "on"
    return OPPOSITE[base] if on else base


def orientation_for(axis: str, wanted: str) -> dict[str, str] | None:
    """Canonical (direction, flipped) that puts terminal 1 on ``wanted``."""
    if axis == "horizontal":
        if wanted == "left":
            return {"direction": "right", "flipped": "off"}
        if wanted == "right":
            return {"direction": "right", "flipped": "on"}
    elif axis == "vertical":
        if wanted == "bottom":
            return {"direction": "up", "flipped": "off"}
        if wanted == "top":
            return {"direction": "up", "flipped": "on"}
    return None


def _neighbours(graph: ModelGraph) -> dict[tuple[str, int], list[tuple[str, int]]]:
    links: dict[tuple[str, int], list[tuple[str, int]]] = {}
    for schematic in graph.schematics:
        for connection in schematic.connections:
            if connection.source is None or not connection.source.component:
                continue
            src = (connection.source.component, int(connection.source.terminal or 0))
            for endpoint in connection.destinations:
                if not endpoint.component:
                    continue
                dst = (endpoint.component, int(endpoint.terminal or 0))
                links.setdefault(src, []).append(dst)
                links.setdefault(dst, []).append(src)
    return links


def check_orientation(
    model_path: str | None = None,
    text: str | None = None,
    policies: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Report polar parts that deviate from the convention measured in the corpus.

    Only (type, axis) pairs with at least 10 samples and 70% agreement are checked,
    so a report always means "the shipped models do it the other way", never a
    personal preference. ``policies`` overrides the wanted terminal-1 side per type
    (``{"Inductor": "left"}``) for a project that wants its own style.
    """
    if text is None:
        if model_path is None:
            return []
        text = plecsfile.read_text(model_path)
    graph = build_graph("model", text)
    policies = policies or {}

    findings: list[dict[str, Any]] = []
    for schematic in graph.schematics:
        for component in schematic.components.values():
            direction = component.direction
            if not direction:
                continue
            actual = term1_side(direction, component.flipped)
            if actual is None:
                continue
            override = policies.get(component.type)
            if override is not None:
                wanted, expected, n, share = override, None, 0, 0
            else:
                convention = expected_for(component.type, direction)
                if convention is None:
                    continue
                wanted = convention["side"]
                expected = {
                    "direction": convention["direction"],
                    "flipped": convention["flipped"],
                }
                n, share = convention["n"], convention["share"]
            if actual == wanted:
                continue
            axis = "horizontal" if wanted in ("left", "right") else "vertical"
            if expected is None:
                expected = orientation_for(axis, wanted)
            findings.append(
                {
                    "code": "LAYOUT-004",
                    "severity": "info",
                    "message": (
                        f"{component.type} {component.name!r} has terminal 1 on the {actual} side; "
                        f"{share}% of {n} bundled instances put it on the {wanted} side"
                        if n
                        else f"{component.type} {component.name!r} has terminal 1 on the {actual} "
                        f"side; project policy wants it on the {wanted} side"
                    ),
                    "component": component.name,
                    "actual": {
                        "direction": direction,
                        "flipped": component.flipped,
                        "term1_side": actual,
                    },
                    "expected": expected,
                    "convention": {"n": n, "share": share},
                    "auto_fixable": True,
                    "source": ".plecs",
                }
            )
    return findings
