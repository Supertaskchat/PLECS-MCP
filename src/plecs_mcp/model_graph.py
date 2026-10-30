"""Static model graph and connection checks for ``.plecs`` files.

The RPC model tree does not expose built-in terminal counts.  This module builds a
scope-aware graph from the native text format and checks the items that can be
checked reliably: component references, subsystem ports, C-Script ports, top-level
outputs, and C-Script code indices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Iterable

from . import plecsfile

CSCRIPT_TYPES = {"CScript", "C-Script"}
OUTPUT_TYPES = {"Output", "Signal Outport"}
SUBSYSTEM_TYPE = "Subsystem"
CODE_FIELDS = (
    "Declarations",
    "StartFcn",
    "OutputFcn",
    "UpdateFcn",
    "DerivativeFcn",
    "TerminateFcn",
    "StoreCustomStateFcn",
    "RestoreCustomStateFcn",
)
INDEX_RE = re.compile(
    r"\b(InputSignal|OutputSignal|ContState|DiscState|ParamRealData)\s*\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\)"
)


@dataclass
class Port:
    index: int
    kind: str


@dataclass
class Endpoint:
    component: str
    terminal: int | None
    line: int
    role: str


@dataclass(eq=False)
class Component:
    name: str
    type: str
    line: int
    params: dict[str, str]
    ports: list[Port] = field(default_factory=list)
    input_widths: list[int] | None = None
    output_widths: list[int] | None = None
    ports_unknown: bool = False
    output_index: int | None = None
    subsystem: "Schematic | None" = None
    schematic: "Schematic | None" = None
    direction: str = ""
    flipped: str = ""
    position: tuple[int, int] | None = None
    opaque: bool = False


@dataclass(eq=False)
class Connection:
    schematic: "Schematic"
    line: int
    conn_type: str
    source: Endpoint | None
    destinations: list[Endpoint]
    has_branch: bool
    mixed_endpoint: bool


@dataclass(eq=False)
class Schematic:
    path: str
    node: plecsfile.Node
    components: dict[str, Component] = field(default_factory=dict)
    duplicates: set[str] = field(default_factory=set)
    connections: list[Connection] = field(default_factory=list)
    parent: "Schematic | None" = None
    # Library/masked component templates stack alternative variants on the same
    # positions, so repeated component names are expected there.
    template: bool = False


@dataclass
class Diagnostic:
    code: str
    severity: str
    message: str
    schematic: str = ""
    component: str | None = None
    line: int | None = None
    fix: str | None = None
    source: str = ".plecs"

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "schematic": self.schematic,
            "component": self.component,
            "line": self.line,
            "fix": self.fix,
            "source": self.source,
        }


@dataclass(eq=False)
class ModelGraph:
    model_name: str
    text: str
    root: Schematic
    schematics: list[Schematic]
    top_terminals: list[Port]

    def find_component(self, name: str) -> Component | None:
        for schematic in self.schematics:
            component = schematic.components.get(name)
            if component is not None:
                return component
        return None

    def unchecked_cscript_ports(self) -> list[str]:
        """C-Scripts whose port counts are dynamic and therefore not checked."""
        return sorted(
            component.name
            for schematic in self.schematics
            for component in schematic.components.values()
            if component.type in CSCRIPT_TYPES and component.ports_unknown
        )

    def unchecked_types(self) -> list[str]:
        return sorted(
            {
                component.type
                for schematic in self.schematics
                for component in schematic.components.values()
                if component.type not in CSCRIPT_TYPES
                and component.type not in OUTPUT_TYPES
                and component.type not in ("Input", SUBSYSTEM_TYPE)
                and not component.ports
            }
        )


def _line(text: str, node: plecsfile.Node) -> int:
    return text.count("\n", 0, node.start) + 1


def _strip(value: Any) -> str:
    return str(value or "").strip().strip('"')


def _ints(value: Any) -> list[int]:
    if value is None:
        return []
    return [int(item) for item in re.findall(r"-?\d+", str(value))]


LITERAL_INT_RE = re.compile(r"^-?\d+$")


def _widths(value: Any) -> list[int] | None:
    """Parse a NumInputs/NumOutputs spec.

    Returns ``None`` when the spec is not a literal (for example ``-1``, which
    means inherited, or an expression such as ``"[1 num_channels]"`` used by
    library component templates).  Callers must skip port-count checks in that
    case instead of guessing a count.
    """
    if value is None:
        return None
    text = str(value or "").strip().strip('"').strip()
    if not text:
        return None
    if text.startswith("[") and text.endswith("]"):
        tokens = [item for item in re.split(r"[\s,;]+", text[1:-1].strip()) if item]
        if not tokens or not all(LITERAL_INT_RE.match(item) for item in tokens):
            return None
        values = [int(item) for item in tokens]
        if any(item < 0 for item in values):
            return None
        # A vector lists the width of each port, e.g. "[4 8]" = two ports.
        # Zero-width entries are not ports.
        return [item for item in values if item > 0]
    if not LITERAL_INT_RE.match(text):
        return None
    count = int(text)
    if count < 0:
        return None
    # A scalar is one port with that width ("7" = one 7-wide input); "0"
    # means the block has no such port.
    return [count] if count > 0 else []


def _first_int(value: Any) -> int | None:
    values = _ints(value)
    return values[0] if values else None


def _params(node: plecsfile.Node) -> dict[str, str]:
    params: dict[str, str] = {}
    for child in node.children:
        if child.keyword != "Parameter":
            continue
        variable = _strip(child.get("Variable"))
        if variable:
            params[variable] = str(child.get("Value") or "")
    return params


def _component(node: plecsfile.Node, schematic: Schematic, text: str) -> Component:
    name = plecsfile.component_name(node) or ""
    kind = _strip(node.get("Type"))
    params = _params(node)
    ports = [
        Port(index=index, kind=_strip(child.get("Type")))
        for index, child in enumerate(
            (item for item in node.children if item.keyword == "Terminal"), start=1
        )
    ]
    input_widths = _widths(params.get("NumInputs"))
    output_widths = _widths(params.get("NumOutputs"))
    # Port checks only run when both specs are literal; library templates use
    # -1 (inherited) or expressions such as "[1 num_channels]".
    ports_unknown = input_widths is None or output_widths is None
    output_index = _first_int(params.get("Index")) if kind in OUTPUT_TYPES else None
    component = Component(
        name=name,
        type=kind,
        line=_line(text, node),
        params=params,
        ports=ports,
        input_widths=input_widths,
        output_widths=output_widths,
        ports_unknown=ports_unknown,
        output_index=output_index,
        schematic=schematic,
        direction=_strip(node.get("Direction")),
        flipped=_strip(node.get("Flipped")),
        position=tuple(_ints(node.get("Position"))[:2]) or None,
        # Encrypted subsystems carry an opaque blob instead of a schematic.
        opaque=bool(node.get("Encrypted")),
    )
    if kind == SUBSYSTEM_TYPE:
        sub_node = next((item for item in node.children if item.keyword == "Schematic"), None)
        if sub_node is not None:
            sub = Schematic(
                path=f"{schematic.path}/{name}" if schematic.path else name,
                node=sub_node,
                parent=schematic,
                template=bool(node.get("MaskType")),
            )
            component.subsystem = sub
            _populate(sub, sub_node, text)
    return component


def _walk_branch(
    branch: plecsfile.Node,
    text: str,
    destinations: list[Endpoint],
) -> None:
    component = _strip(branch.get("DstComponent"))
    terminal = _first_int(branch.get("DstTerminal"))
    children = [item for item in branch.children if item.keyword == "Branch"]
    if component or terminal is not None:
        destinations.append(Endpoint(component, terminal, _line(text, branch), "dst"))
    for child in children:
        _walk_branch(child, text, destinations)
    if not component and terminal is None and not children and not branch.get("Points"):
        destinations.append(Endpoint("", None, _line(text, branch), "dst"))


def _connection(node: plecsfile.Node, schematic: Schematic, text: str) -> Connection:
    direct_component = _strip(node.get("DstComponent"))
    direct_terminal = _first_int(node.get("DstTerminal"))
    destinations: list[Endpoint] = []
    if direct_component or direct_terminal is not None:
        destinations.append(
            Endpoint(direct_component, direct_terminal, _line(text, node), "dst")
        )
    branches = [item for item in node.children if item.keyword == "Branch"]
    for branch in branches:
        _walk_branch(branch, text, destinations)
    source_component = _strip(node.get("SrcComponent"))
    source_terminal = _first_int(node.get("SrcTerminal"))
    source = None
    if source_component or source_terminal is not None:
        source = Endpoint(source_component, source_terminal, _line(text, node), "src")
    return Connection(
        schematic=schematic,
        line=_line(text, node),
        conn_type=_strip(node.get("Type")),
        source=source,
        destinations=destinations,
        has_branch=bool(branches),
        mixed_endpoint=bool(destinations) and bool(branches) and (
            bool(direct_component) or direct_terminal is not None
        ),
    )


def _populate(schematic: Schematic, schematic_node: plecsfile.Node, text: str) -> None:
    for child in schematic_node.children:
        if child.keyword == "Component":
            component = _component(child, schematic, text)
            if component.name in schematic.components:
                schematic.duplicates.add(component.name)
            else:
                schematic.components[component.name] = component
        elif child.keyword == "Connection":
            schematic.connections.append(_connection(child, schematic, text))


def build_graph(model_name: str, text: str) -> ModelGraph:
    root_node = plecsfile.parse(text)
    plecs = next((item for item in root_node.children if item.keyword == "Plecs"), None)
    if plecs is None:
        return ModelGraph(model_name, text, Schematic(model_name, root_node), [], [])
    root = Schematic(path=model_name, node=plecs)
    top_terminals: list[Port] = []
    for index, child in enumerate(
        (item for item in plecs.children if item.keyword == "Terminal"), start=1
    ):
        top_terminals.append(
            Port(
                index=_first_int(child.get("Index")) or index,
                kind=_strip(child.get("Type")),
            )
        )
    schematic_node = next(
        (item for item in plecs.children if item.keyword == "Schematic"), None
    )
    if schematic_node is not None:
        _populate(root, schematic_node, text)

    schematics: list[Schematic] = []

    def collect(item: Schematic) -> None:
        schematics.append(item)
        for component in item.components.values():
            if component.subsystem is not None:
                collect(component.subsystem)

    collect(root)
    return ModelGraph(model_name, text, root, schematics, top_terminals)


def _add(
    diagnostics: list[Diagnostic],
    seen: set[tuple[str, str, str, int | None]],
    code: str,
    severity: str,
    message: str,
    *,
    schematic: str = "",
    component: str | None = None,
    line: int | None = None,
    fix: str | None = None,
) -> None:
    key = (code, schematic, component or "", line)
    if key in seen:
        return
    seen.add(key)
    diagnostics.append(
        Diagnostic(
            code=code,
            severity=severity,
            message=message,
            schematic=schematic,
            component=component,
            line=line,
            fix=fix,
        )
    )


def _check_cscript(
    component: Component,
    diagnostics: list[Diagnostic],
    seen: set[tuple[str, str, str, int | None]],
    include_code: bool,
) -> None:
    if component.ports_unknown:
        # Dynamic specs (-1 / expressions) cannot be resolved statically; the
        # caller reports these as unchecked instead of guessing a port count.
        if "NumInputs" not in component.params and "NumOutputs" not in component.params:
            _add(
                diagnostics,
                seen,
                "CSCRIPT-001",
                "warning",
                f"C-Script {component.name!r} declares neither NumInputs nor NumOutputs",
                schematic=component.schematic.path if component.schematic else "",
                component=component.name,
                line=component.line,
                fix="Open the C-Script Setup page and set explicit port counts.",
            )
        return

    direct = _ints(component.params.get("DirectFeedthrough"))
    ports_in = len(component.input_widths or [])
    channels = sum(component.input_widths or [])
    # PLECS accepts both one entry per input port and one entry per input
    # channel depending on how the block was authored; only flag a length that
    # matches neither convention.
    if direct and len(direct) > 1 and len(direct) not in (ports_in, channels):
        _add(
            diagnostics,
            seen,
            "CSCRIPT-004",
            "warning",
            f"C-Script {component.name!r} DirectFeedthrough has {len(direct)} entries, "
            f"which matches neither the {ports_in} input ports nor the {channels} input channels",
            schematic=component.schematic.path if component.schematic else "",
            component=component.name,
            line=component.line,
            fix="Match DirectFeedthrough to the input port count or the total input width.",
        )

    parameters = [
        item.strip()
        for item in str(component.params.get("Parameters") or "").split(",")
        if item.strip()
    ]
    cont_states = _first_int(component.params.get("NumContStates"))
    disc_states = _first_int(component.params.get("NumDiscStates"))
    if not include_code:
        return
    for field_name in CODE_FIELDS:
        code = str(component.params.get(field_name) or "")
        if not code or code.lstrip().lower().startswith("base64"):
            continue
        for match in INDEX_RE.finditer(code):
            kind, first, second = match.group(1), int(match.group(2)), match.group(3)
            column = int(second) if second is not None else 0
            if kind == "InputSignal" and component.input_widths is not None:
                if first >= len(component.input_widths):
                    _add(
                        diagnostics,
                        seen,
                        "CSCRIPT-007",
                        "warning",
                        f"{field_name} uses InputSignal({first}, ...), but NumInputs has "
                        f"{len(component.input_widths)} ports",
                        schematic=component.schematic.path if component.schematic else "",
                        component=component.name,
                        line=component.line,
                        fix="Check the C-Script port index (InputSignal is 0-based).",
                    )
                elif column >= component.input_widths[first]:
                    _add(
                        diagnostics,
                        seen,
                        "CSCRIPT-007",
                        "warning",
                        f"{field_name} uses InputSignal({first}, {column}), but input "
                        f"width is {component.input_widths[first]}",
                        schematic=component.schematic.path if component.schematic else "",
                        component=component.name,
                        line=component.line,
                        fix="Check the C-Script element index (0-based).",
                    )
            elif kind == "OutputSignal" and component.output_widths is not None:
                if first >= len(component.output_widths):
                    _add(
                        diagnostics,
                        seen,
                        "CSCRIPT-008",
                        "warning",
                        f"{field_name} uses OutputSignal({first}, ...), but NumOutputs has "
                        f"{len(component.output_widths)} ports",
                        schematic=component.schematic.path if component.schematic else "",
                        component=component.name,
                        line=component.line,
                        fix="Check the C-Script port index (OutputSignal is 0-based).",
                    )
                elif column >= component.output_widths[first]:
                    _add(
                        diagnostics,
                        seen,
                        "CSCRIPT-008",
                        "warning",
                        f"{field_name} uses OutputSignal({first}, {column}), but output "
                        f"width is {component.output_widths[first]}",
                        schematic=component.schematic.path if component.schematic else "",
                        component=component.name,
                        line=component.line,
                        fix="Check the C-Script element index (0-based).",
                    )
            elif kind in ("ContState", "DiscState"):
                limit = cont_states if kind == "ContState" else disc_states
                if limit is not None and first >= limit:
                    _add(
                        diagnostics,
                        seen,
                        "CSCRIPT-009",
                        "warning",
                        f"{field_name} uses {kind}({first}), but the configured count is {limit}",
                        schematic=component.schematic.path if component.schematic else "",
                        component=component.name,
                        line=component.line,
                        fix="Check the state count and the 0-based state index.",
                    )
            elif kind == "ParamRealData" and parameters and first >= len(parameters):
                _add(
                    diagnostics,
                    seen,
                    "CSCRIPT-006",
                    "warning",
                    f"{field_name} uses ParamRealData({first}, ...), but Parameters has "
                    f"{len(parameters)} entries",
                    schematic=component.schematic.path if component.schematic else "",
                    component=component.name,
                    line=component.line,
                    fix="Check the Parameters order and the 0-based parameter index.",
                )


def _check_endpoint(
    graph: ModelGraph,
    connection: Connection,
    endpoint: Endpoint | None,
    diagnostics: list[Diagnostic],
    seen: set[tuple[str, str, str, int | None]],
) -> None:
    if endpoint is None:
        _add(
            diagnostics,
            seen,
            "CONN-003",
            "error",
            f"Connection at line {connection.line} has no {endpoint.role if endpoint else 'source'} endpoint",
            schematic=connection.schematic.path,
            line=connection.line,
            fix="Add the missing component/terminal fields.",
        )
        return
    if not endpoint.component:
        _add(
            diagnostics,
            seen,
            "CONN-003",
            "error",
            f"Connection at line {endpoint.line} has an empty {endpoint.role} component",
            schematic=connection.schematic.path,
            line=endpoint.line,
            fix="Set SrcComponent/DstComponent to an existing component name.",
        )
        return
    component = connection.schematic.components.get(endpoint.component)
    if component is None:
        other = graph.find_component(endpoint.component)
        if other is not None:
            _add(
                diagnostics,
                seen,
                "CONN-002",
                "error",
                f"Connection at line {endpoint.line} references {endpoint.component!r}, "
                f"which is in {other.schematic.path if other.schematic else 'another schematic'} "
                f"but not in {connection.schematic.path}",
                schematic=connection.schematic.path,
                component=endpoint.component,
                line=endpoint.line,
                fix="Move the connection into the component's schematic or use a subsystem port.",
            )
        else:
            _add(
                diagnostics,
                seen,
                "CONN-001",
                "error",
                f"Connection at line {endpoint.line} references missing component {endpoint.component!r}",
                schematic=connection.schematic.path,
                component=endpoint.component,
                line=endpoint.line,
                fix="Create/rename the component or fix the connection text.",
            )
        return
    if endpoint.terminal is None:
        _add(
            diagnostics,
            seen,
            "CONN-003",
            "error",
            f"Connection at line {endpoint.line} for {endpoint.component!r} has no terminal index",
            schematic=connection.schematic.path,
            component=endpoint.component,
            line=endpoint.line,
            fix="Set SrcTerminal/DstTerminal to a positive integer.",
        )
        return
    if endpoint.terminal <= 0:
        _add(
            diagnostics,
            seen,
            "CONN-004",
            "error",
            f"Connection at line {endpoint.line} uses invalid terminal {endpoint.terminal} "
            f"for {endpoint.component!r}",
            schematic=connection.schematic.path,
            component=endpoint.component,
            line=endpoint.line,
            fix="Terminal indices are 1-based and must be positive.",
        )
        return

    if component.type == SUBSYSTEM_TYPE:
        limit = len(component.ports)
        if endpoint.terminal > limit:
            _add(
                diagnostics,
                seen,
                "CONN-006",
                "error",
                f"Connection at line {endpoint.line} uses terminal {endpoint.terminal} of "
                f"subsystem {endpoint.component!r}, but it has {limit} ports",
                schematic=connection.schematic.path,
                component=endpoint.component,
                line=endpoint.line,
                fix="Use a terminal from 1..port count or add the subsystem port.",
            )
        else:
            port = component.ports[endpoint.terminal - 1]
            if endpoint.role == "src" and port.kind == "Input":
                _add(
                    diagnostics,
                    seen,
                    "CONN-011",
                    "error",
                    f"Connection at line {endpoint.line} takes a source from input port "
                    f"{endpoint.terminal} of subsystem {endpoint.component!r}",
                    schematic=connection.schematic.path,
                    component=endpoint.component,
                    line=endpoint.line,
                    fix="Use an output/port terminal as the source.",
                )
            elif endpoint.role == "dst" and port.kind == "Output":
                _add(
                    diagnostics,
                    seen,
                    "CONN-011",
                    "error",
                    f"Connection at line {endpoint.line} drives output port "
                    f"{endpoint.terminal} of subsystem {endpoint.component!r}",
                    schematic=connection.schematic.path,
                    component=endpoint.component,
                    line=endpoint.line,
                    fix="Use an input/port terminal as the destination.",
                )
    elif component.type in CSCRIPT_TYPES:
        if component.input_widths is None or component.output_widths is None:
            return
        inputs = len(component.input_widths)
        total = inputs + len(component.output_widths)
        if endpoint.terminal > total:
            _add(
                diagnostics,
                seen,
                "CONN-007",
                "error",
                f"Connection at line {endpoint.line} uses terminal {endpoint.terminal} of "
                f"C-Script {endpoint.component!r}, but it has {total} terminals "
                f"({inputs} input + {total - inputs} output)",
                schematic=connection.schematic.path,
                component=endpoint.component,
                line=endpoint.line,
                fix="Update the terminal index or the C-Script NumInputs/NumOutputs.",
            )
        elif endpoint.role == "src" and endpoint.terminal <= inputs:
            _add(
                diagnostics,
                seen,
                "CONN-011",
                "error",
                f"Connection at line {endpoint.line} takes a source from input terminal "
                f"{endpoint.terminal} of C-Script {endpoint.component!r}",
                schematic=connection.schematic.path,
                component=endpoint.component,
                line=endpoint.line,
                fix="C-Script inputs are destinations; outputs come after the inputs.",
            )
        elif endpoint.role == "dst" and endpoint.terminal > inputs:
            _add(
                diagnostics,
                seen,
                "CONN-011",
                "error",
                f"Connection at line {endpoint.line} drives output terminal "
                f"{endpoint.terminal} of C-Script {endpoint.component!r}",
                schematic=connection.schematic.path,
                component=endpoint.component,
                line=endpoint.line,
                fix="C-Script outputs are sources; inputs come before the outputs.",
            )
    elif component.type in OUTPUT_TYPES:
        if endpoint.terminal != 1:
            _add(
                diagnostics,
                seen,
                "CONN-006",
                "error",
                f"Connection at line {endpoint.line} uses terminal {endpoint.terminal} of "
                f"Output {endpoint.component!r}; the only terminal is 1",
                schematic=connection.schematic.path,
                component=endpoint.component,
                line=endpoint.line,
                fix="Use terminal 1 for a Signal Outport.",
            )
        if endpoint.role == "src":
            _add(
                diagnostics,
                seen,
                "CONN-011",
                "error",
                f"Connection at line {endpoint.line} uses Output {endpoint.component!r} as a source",
                schematic=connection.schematic.path,
                component=endpoint.component,
                line=endpoint.line,
                fix="Output/Signal Outport is a destination.",
            )
    elif component.type == "Input":
        if endpoint.terminal != 1:
            _add(
                diagnostics,
                seen,
                "CONN-006",
                "error",
                f"Connection at line {endpoint.line} uses terminal {endpoint.terminal} of "
                f"Input {endpoint.component!r}; the only terminal is 1",
                schematic=connection.schematic.path,
                component=endpoint.component,
                line=endpoint.line,
                fix="Use terminal 1 for an Input block.",
            )
        if endpoint.role == "dst":
            _add(
                diagnostics,
                seen,
                "CONN-011",
                "error",
                f"Connection at line {endpoint.line} uses Input {endpoint.component!r} as a destination",
                schematic=connection.schematic.path,
                component=endpoint.component,
                line=endpoint.line,
                fix="Input is a source; use an Output or a component input.",
            )


def validate_graph(graph: ModelGraph, include_code: bool = True) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    seen: set[tuple[str, str, str, int | None]] = set()

    for schematic in graph.schematics:
        for name in sorted(schematic.duplicates):
            if schematic.template:
                continue
            _add(
                diagnostics,
                seen,
                "CONN-005",
                "error",
                f"Component name {name!r} is defined more than once in {schematic.path}",
                schematic=schematic.path,
                component=name,
                fix="Give every component in a schematic a unique Name.",
            )
        for component in schematic.components.values():
            if component.type in CSCRIPT_TYPES:
                _check_cscript(component, diagnostics, seen, include_code)
            elif (
                component.type == SUBSYSTEM_TYPE
                and component.subsystem is None
                and not component.opaque
            ):
                _add(
                    diagnostics,
                    seen,
                    "SUB-005",
                    "error",
                    f"Subsystem {component.name!r} has no Schematic block",
                    schematic=schematic.path,
                    component=component.name,
                    line=component.line,
                    fix="Add the subsystem schematic or convert it to a normal component.",
                )
        for connection in schematic.connections:
            _check_endpoint(graph, connection, connection.source, diagnostics, seen)
            for endpoint in connection.destinations:
                _check_endpoint(graph, connection, endpoint, diagnostics, seen)
            if connection.mixed_endpoint:
                _add(
                    diagnostics,
                    seen,
                    "CONN-009",
                    "warning",
                    f"Connection at line {connection.line} has both a direct destination and Branch destinations",
                    schematic=schematic.path,
                    line=connection.line,
                    fix="Use either direct Dst fields or Branch destinations, not both.",
                )
            if not connection.destinations:
                _add(
                    diagnostics,
                    seen,
                    "CONN-009",
                    "error",
                    f"Connection at line {connection.line} has no destination endpoint",
                    schematic=schematic.path,
                    line=connection.line,
                    fix="Add DstComponent/DstTerminal or a Branch destination.",
                )

    outputs = [
        component
        for component in graph.root.components.values()
        if component.type in OUTPUT_TYPES
    ]
    _check_goto_from(graph, diagnostics, seen)

    # Library definition files and RT Box data-logging models declare bare
    # outport terminals without Output blocks; only cross-check when the model
    # actually routes signals to top-level Output components.
    if not outputs:
        return diagnostics
    output_indices: dict[int, Component] = {}
    for component in outputs:
        if component.output_index is None:
            _add(
                diagnostics,
                seen,
                "CONN-006",
                "warning",
                f"Output component {component.name!r} has no Index parameter",
                schematic=graph.root.path,
                component=component.name,
                line=component.line,
                fix="Set the Output Index to a positive integer.",
            )
            continue
        if component.output_index in output_indices:
            _add(
                diagnostics,
                seen,
                "CONN-008",
                "error",
                f"Output Index {component.output_index} is used by "
                f"{output_indices[component.output_index].name!r} and {component.name!r}",
                schematic=graph.root.path,
                component=component.name,
                line=component.line,
                fix="Use a unique Index for each top-level Output.",
            )
        else:
            output_indices[component.output_index] = component

    terminal_indices: dict[int, Port] = {}
    for terminal in graph.top_terminals:
        if terminal.kind != "Output":
            continue
        if terminal.index in terminal_indices:
            _add(
                diagnostics,
                seen,
                "CONN-008",
                "error",
                f"Top-level Output terminal index {terminal.index} is defined more than once",
                schematic=graph.root.path,
                fix="Remove the duplicate Plecs Terminal or change its Index.",
            )
        else:
            terminal_indices[terminal.index] = terminal

    for index, component in output_indices.items():
        if index not in terminal_indices:
            _add(
                diagnostics,
                seen,
                "CONN-006",
                "error",
                f"Output component {component.name!r} uses Index {index}, "
                f"but there is no top-level Terminal Output with that Index",
                schematic=graph.root.path,
                component=component.name,
                line=component.line,
                fix="Add the matching Plecs Terminal or change the Output Index.",
            )
    for index in terminal_indices:
        if index not in output_indices:
            _add(
                diagnostics,
                seen,
                "CONN-006",
                "error",
                f"Top-level Terminal Output {index} has no Output component",
                schematic=graph.root.path,
                fix="Add the matching Output component or remove the terminal.",
            )
    return diagnostics


def _check_goto_from(
    graph: ModelGraph,
    diagnostics: list[Diagnostic],
    seen: set[tuple[str, str, str, int | None]],
) -> None:
    """Signal routing tags are model-wide; a From without any Goto cannot resolve."""
    gotos: set[str] = set()
    froms: list[tuple[str, str, int]] = []
    for schematic in graph.schematics:
        for component in schematic.components.values():
            tag = (component.params.get("Tag") or "").strip().strip('"')
            if not tag:
                continue
            if component.type == "Goto":
                gotos.add(tag)
            elif component.type == "From":
                froms.append((component.name, tag, component.line))
    for name, tag, line in froms:
        if tag in gotos:
            continue
        _add(
            diagnostics,
            seen,
            "CONN-012",
            "warning",
            f"From block {name!r} reads tag {tag!r}, but no Goto declares it in the readable "
            f"text (a masked or encrypted subsystem may supply it)",
            component=name,
            line=line,
            fix="Add the matching Goto, fix the tag spelling, or ignore if a masked block provides it.",
        )


def validate_model_text(
    model_name: str,
    text: str,
    *,
    include_code: bool = True,
) -> tuple[ModelGraph, list[Diagnostic]]:
    graph = build_graph(model_name, text)
    return graph, validate_graph(graph, include_code=include_code)


def validate_model_file(
    model_name: str,
    path: str | Path,
    *,
    include_code: bool = True,
) -> tuple[ModelGraph, list[Diagnostic]]:
    return validate_model_text(
        model_name,
        plecsfile.read_text(path),
        include_code=include_code,
    )


def component_types(model_path: str | Path) -> dict[str, str]:
    """Map ``model/Sub/Name`` -> the *English* library type from the ``.plecs`` text.

    ``plecs.getModelTree`` returns localized type names (``Scope`` -> ``示波器``) and no
    longer carries a ``Library type`` property, so the file is the only stable source.
    """
    text = plecsfile.read_text(model_path)
    root = plecsfile.parse(text)
    model_name = Path(str(model_path)).stem
    types: dict[str, str] = {}
    for node in plecsfile.components(root):
        name = plecsfile.component_name(node)
        if not name:
            continue
        kind = (node.get("Type") or "").strip().strip('"')
        if kind:
            types[name] = kind
    graph = build_graph(model_name, text)
    paths: dict[str, str] = {}
    for schematic in graph.schematics:
        for component in schematic.components.values():
            paths[f"{schematic.path}/{component.name}"] = component.type
    return {**types, **paths}
