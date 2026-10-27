"""Geometry checks for the schematic that PLECS currently renders.

``plecs.webserver getCircuitBitmap`` returns a bounding box per component, which is
the only geometry PLECS exposes over RPC.  Combined with the ``Position`` and
``Points`` written in the ``.plecs`` text, it is enough to report two things that are
certain: component boxes that intersect, and wire polylines that run through a
component that is not one of their own endpoints.

Renderer coordinates are schematic units up to a constant offset (measured on PLECS
5.0.6: scale 1, offset within +/-2 px), so the offset is estimated from the median
``bbox centre - Position`` and the comparison keeps a margin for that rounding.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import statistics
from typing import Any

from . import plecsfile

DEFAULT_MARGIN = 3.0

# Overlay/annotation blocks are drawn on top of devices in the shipped demos
# (a Heat Sink sits on its switch, Goto/From labels sit on wires), so an
# intersecting bounding box is not a defect there.
OVERLAY_TYPES = {"HeatSink", "Goto", "From", "Annotation", "Comment", "Note"}

# Subsystem boxes include port stubs and name labels, so touching corners are
# normal; only a substantial intersection is reported.
MIN_OVERLAP_RATIO = 0.15
MIN_OVERLAP_AREA = 25.0


@dataclass
class Box:
    name: str
    left: float
    top: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top + self.height

    @property
    def centre(self) -> tuple[float, float]:
        return (self.left + self.width / 2, self.top + self.height / 2)

    def eroded(self, margin: float) -> "Box | None":
        left, top = self.left + margin, self.top + margin
        width, height = self.width - 2 * margin, self.height - 2 * margin
        if width <= 0 or height <= 0:
            return None
        return Box(self.name, left, top, width, height)

    def contains(self, point: tuple[float, float], margin: float = 0.0) -> bool:
        x, y = point
        return (
            self.left - margin <= x <= self.right + margin
            and self.top - margin <= y <= self.bottom + margin
        )

    def overlap(self, other: "Box") -> tuple[float, float]:
        dx = min(self.right, other.right) - max(self.left, other.left)
        dy = min(self.bottom, other.bottom) - max(self.top, other.top)
        return (dx, dy) if dx > 0 and dy > 0 else (0.0, 0.0)


def _numbers(raw: str | None) -> list[float]:
    return [float(item) for item in re.findall(r"-?\d+(?:\.\d+)?", raw or "")]


def polyline(raw: str | None) -> list[tuple[float, float]]:
    values = _numbers(raw)
    return list(zip(values[0::2], values[1::2]))


def _segment_hits_box(a: tuple[float, float], b: tuple[float, float], box: Box) -> bool:
    """Liang-Barsky clipping: does the segment cross the interior of ``box``?"""
    x0, y0 = a
    dx, dy = b[0] - x0, b[1] - y0
    t0, t1 = 0.0, 1.0
    for p, q in (
        (-dx, x0 - box.left),
        (dx, box.right - x0),
        (-dy, y0 - box.top),
        (dy, box.bottom - y0),
    ):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return t1 - t0 > 1e-9


def _finding(code: str, severity: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, **extra}


def _paths(
    node: plecsfile.Node, prefix: list[tuple[float, float]] | None = None
) -> list[list[tuple[float, float]]]:
    """Vertex paths of a connection.

    PLECS stores one ``Points`` entry per node and nests further corners as
    ``Branch`` children, so a wire is a path through the tree: every branch
    continues from the vertices collected so far. Sibling branches are
    alternatives that start from the same trunk point.
    """
    path = list(prefix or []) + polyline(node.get("Points"))
    children = [child for child in node.children if child.keyword == "Branch"]
    if not children:
        return [path]
    paths: list[list[tuple[float, float]]] = []
    for child in children:
        paths.extend(_paths(child, path))
    return paths


def _segments(node: plecsfile.Node) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """All straight segments of a connection, including nested Branch corners."""
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for path in _paths(node):
        segments.extend(zip(path, path[1:]))
    return segments


def _endpoints(node: plecsfile.Node) -> set[str]:
    names: set[str] = set()
    for key in ("SrcComponent", "DstComponent"):
        value = (node.get(key) or "").strip().strip('"')
        if value:
            names.add(value)
    for child in node.children:
        if child.keyword == "Branch":
            names |= _endpoints(child)
    return names


def _boxes(components: dict[str, Any]) -> tuple[dict[str, Box], list[str], dict[str, str]]:
    boxes: dict[str, Box] = {}
    skipped: list[str] = []
    kinds: dict[str, str] = {}
    for name, payload in (components or {}).items():
        dims = (payload or {}).get("dimensions") or {}
        # The renderer reports masked blocks as "Subsystem"; the .plecs text keeps
        # the real type (e.g. HeatSink), which is what the overlay rules need.
        kinds[name] = str((payload or {}).get("type") or "")
        try:
            box = Box(
                name,
                float(dims["left"]),
                float(dims["top"]),
                float(dims["width"]),
                float(dims["height"]),
            )
        except (KeyError, TypeError, ValueError):
            skipped.append(name)
            continue
        boxes[name] = box
    return boxes, skipped, kinds


def _offset(root: plecsfile.Node, boxes: dict[str, Box]) -> tuple[float, float]:
    dx: list[float] = []
    dy: list[float] = []
    for name, box in boxes.items():
        position = plecsfile.component_position(root, name)
        if not position:
            continue
        centre = box.centre
        dx.append(centre[0] - position[0])
        dy.append(centre[1] - position[1])
    return (
        statistics.median(dx) if dx else 0.0,
        statistics.median(dy) if dy else 0.0,
    )


def check_layout(
    text: str,
    components: dict[str, Any],
    *,
    include_wires: bool = True,
    margin: float = DEFAULT_MARGIN,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = plecsfile.parse(text)
    schematic = plecsfile.top_schematic(root)
    boxes, skipped, kinds = _boxes(components)
    findings: list[dict[str, Any]] = []
    if schematic is None or not boxes:
        return findings, {
            "components": len(boxes),
            "connections": 0,
            "skipped_components": skipped,
            "offset": [0.0, 0.0],
        }

    for component in plecsfile.components(root):
        name = plecsfile.component_name(component)
        if name in kinds and component.get("Type"):
            kinds[name] = str(component.get("Type")).strip().strip('"')

    eroded = {name: box.eroded(margin) for name, box in boxes.items()}

    names = sorted(boxes)
    for index, first in enumerate(names):
        for second in names[index + 1:]:
            if kinds.get(first) in OVERLAY_TYPES or kinds.get(second) in OVERLAY_TYPES:
                continue
            dx, dy = boxes[first].overlap(boxes[second])
            if dx <= 0 or dy <= 0:
                continue
            smaller = min(
                boxes[first].width * boxes[first].height,
                boxes[second].width * boxes[second].height,
            )
            if dx * dy < max(MIN_OVERLAP_RATIO * smaller, MIN_OVERLAP_AREA):
                continue
            findings.append(
                _finding(
                    "LAYOUT-001",
                    "error",
                    f"components {first!r} and {second!r} overlap by "
                    f"{dx:.0f}x{dy:.0f} schematic units",
                    components=[first, second],
                    overlap=[round(dx, 1), round(dy, 1)],
                )
            )

    connections = 0
    if include_wires:
        offset_x, offset_y = _offset(root, boxes)
        for node in schematic.children:
            if node.keyword != "Connection":
                continue
            connections += 1
            source = (node.get("SrcComponent") or "").strip().strip('"')
            own = _endpoints(node)
            label = f"{source or '?'} -> "
            for a, b in _segments(node):
                if a[0] != b[0] and a[1] != b[1]:
                    findings.append(
                        _finding(
                            "LAYOUT-002",
                            "warning",
                            f"connection {label} has a diagonal segment "
                            f"{list(a)} -> {list(b)}",
                            connection=label,
                            points=[list(a), list(b)],
                        )
                    )
                start = (a[0] + offset_x, a[1] + offset_y)
                end = (b[0] + offset_x, b[1] + offset_y)
                for name, box in eroded.items():
                    if box is None or name in own or kinds.get(name) in OVERLAY_TYPES:
                        # A wire is drawn from terminal to terminal, so it may only
                        # touch the two components this connection belongs to.
                        continue
                    if _segment_hits_box(start, end, box):
                        findings.append(
                            _finding(
                                "LAYOUT-003",
                                "info",
                                f"connection {label} is drawn across component {name!r} "
                                f"between {list(a)} and {list(b)} (cosmetic)",
                                connection=label,
                                component=name,
                                points=[list(a), list(b)],
                            )
                        )
    info = {
        "components": len(boxes),
        "connections": connections,
        "skipped_components": skipped,
        "offset": [round(value, 2) for value in _offset(root, boxes)],
    }
    return findings, info
