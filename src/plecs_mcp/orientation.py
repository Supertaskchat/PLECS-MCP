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

The recommended convention is *terminal 1 faces upstream* (towards the source),
because PLECS uses terminal 1 as the reference terminal for v/i.  The polar
marker (dot, X, anode, +, ...) then lands wherever the symbol defines it: for an
inductor/breaker/diode that is terminal 1, for a voltage source the ``+`` is
terminal 2, so a source points its ``+`` downstream - which is what we want.
"""

from __future__ import annotations

from typing import Any

from . import plecsfile
from .model_graph import CSCRIPT_TYPES, ModelGraph, build_graph

SIDES = ("left", "right", "top", "bottom")
OPPOSITE = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}
TERM1_SIDE = {"right": "left", "left": "right", "up": "bottom", "down": "top"}

# Two-terminal types whose symbol carries a polarity/reference marker.
POLAR_TYPES = {
    "Inductor",
    "Breaker",
    "Diode",
    "ZenerDiode",
    "DCVoltageSource",
    "ACVoltageSource",
    "VoltageSource",
    "CurrentSource",
    "ACCurrentSource",
    "Thyristor",
    "IdealSwitch",
    # library variants that keep the same terminal geometry
    "MosfetWithDiode",
}

# Which terminal the visible marker is drawn on (default 1).  A DC/AC voltage
# source draws "+" on terminal 2, which is why its arrow points downstream.
MARKER_TERMINAL = {"DCVoltageSource": 2, "ACVoltageSource": 2, "VoltageSource": 2}

# Three-terminal devices need per-topology judgement (gate/D/S geometry differs
# between library variants), so they are reported but never auto-chosen.
MANUAL_TYPES = {"MosfetWithDiode", "IgbtWithDiode", "MOSFET", "IGBT", "Thyristor"}

SOURCE_TYPES = {
    "VoltageSource",
    "DCVoltageSource",
    "ACVoltageSource",
    "CurrentSource",
    "ACCurrentSource",
    "Input",
}


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


def _axis_for(first: tuple[float, float], second: tuple[float, float]) -> str | None:
    dx = abs(second[0] - first[0])
    dy = abs(second[1] - first[1])
    if dx == 0 and dy == 0:
        return None
    return "horizontal" if dx >= dy else "vertical"


def _neighbour_side(own: tuple[float, float], other: tuple[float, float]) -> str:
    dx, dy = other[0] - own[0], other[1] - own[1]
    if abs(dx) >= abs(dy):
        return "left" if dx < 0 else "right"
    return "top" if dy < 0 else "bottom"


def _positions(text: str) -> dict[str, tuple[float, float]]:
    root = plecsfile.parse(text)
    positions: dict[str, tuple[float, float]] = {}
    for node in plecsfile.components(root):
        name = plecsfile.component_name(node)
        raw = plecsfile._numbers(node.get("Position")) if hasattr(plecsfile, "_numbers") else None
        if raw is None:
            values = [
                float(item)
                for item in __import__("re").findall(r"-?\d+(?:\.\d+)?", node.get("Position") or "")
            ]
        else:
            values = raw
        if name and len(values) >= 2:
            positions[name] = (values[0], values[1])
    return positions


def _neighbours(graph: ModelGraph) -> dict[tuple[str, int], list[tuple[str, int]]]:
    """(component, terminal) -> directly wired (component, terminal) nodes."""
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


def _side_of(own: tuple[float, float], other: tuple[float, float]) -> str:
    dx, dy = other[0] - own[0], other[1] - own[1]
    if abs(dx) >= abs(dy):
        return "left" if dx < 0 else "right"
    return "top" if dy < 0 else "bottom"


def _reading_side(
    component: Any,
    links: dict[tuple[str, int], list[tuple[str, int]]],
    positions: dict[str, tuple[float, float]],
) -> str | None:
    """Side that reading order wants terminal 1 on: left for horizontal, top for vertical.

    Topology cannot answer this: an AC voltage source has two terminals that are
    both "the start".  Reading order is the stable convention, and it matches the
    direction a left-to-right schematic is drawn in.
    """
    own = positions.get(component.name)
    if own is None:
        return None
    sides: list[str] = []
    for terminal in (1, 2):
        for neighbour, _ in links.get((component.name, terminal), ()):
            other = positions.get(neighbour)
            if other is None or neighbour == component.name:
                continue
            sides.append(_side_of(own, other))
    if not sides:
        return None
    horizontal = [s for s in sides if s in ("left", "right")]
    vertical = [s for s in sides if s in ("top", "bottom")]
    if horizontal and vertical:
        return None  # corner: the axis is not determined by the neighbours
    if horizontal:
        return "left"
    return "top"


def check_orientation(
    model_path: str | None = None,
    text: str | None = None,
    policies: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Report polar two-terminal parts whose terminal 1 is not on the reading side.

    ``policies`` may override the wanted side per component type
    (``{"Breaker": "right"}``), which is how a caller expresses a house style.
    """
    if text is None:
        if model_path is None:
            return []
        text = plecsfile.read_text(model_path)
    graph = build_graph("model", text)
    links = _neighbours(graph)
    positions = _positions(text)
    policies = policies or {}

    findings: list[dict[str, Any]] = []
    for schematic in graph.schematics:
        for component in schematic.components.values():
            if component.type not in POLAR_TYPES:
                continue
            wanted = policies.get(component.type)
            if wanted is None:
                wanted = _reading_side(component, links, positions)
            if wanted is None:
                continue
            actual = term1_side(component.direction, component.flipped)
            if actual is None or actual == wanted:
                continue
            axis = "horizontal" if wanted in ("left", "right") else "vertical"
            expected = orientation_for(axis, wanted)
            manual = component.type in MANUAL_TYPES
            findings.append(
                {
                    "code": "LAYOUT-004",
                    "severity": "info",
                    "message": (
                        f"{component.type} {component.name!r} has terminal 1 on the {actual} side, "
                        f"but reading order wants it on the {wanted} side"
                        + (" (three-terminal symbol: review by hand)" if manual else "")
                    ),
                    "component": component.name,
                    "actual": {
                        "direction": component.direction,
                        "flipped": component.flipped,
                        "term1_side": actual,
                    },
                    "expected": expected,
                    "auto_fixable": not manual,
                    "source": ".plecs",
                }
            )
    return findings
