"""Parser and surgical editor for the plain-text ``.plecs`` model format.

The file is a nested block language::

    Plecs {
      Terminal { Type Output Index "1" }
      Schematic {
        Component { Type DCVoltageSource Name "V_dc" ... Parameter { ... } }
        Connection { Type Wire SrcComponent "V_dc" SrcTerminal 1
                     Branch { DstComponent "R1" DstTerminal 1 } }
      }
    }

Edits are applied as text splices on node spans, so everything outside the edited
region stays byte-identical (verified by round-trip tests).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

OPEN_RE = re.compile(r"^(\s*)([A-Za-z_][\w]*)\s*\{\s*$")
CLOSE_RE = re.compile(r"^(\s*)\}\s*$")
ENTRY_RE = re.compile(r"^(\s*)([A-Za-z_][\w]*)\s+(.*?)\s*$")


@dataclass
class Node:
    keyword: str
    indent: str = ""
    entries: list[tuple[str, str]] = field(default_factory=list)
    children: list["Node"] = field(default_factory=list)
    start: int = 0
    close_start: int = 0
    end: int = 0

    def get(self, key: str) -> str | None:
        for name, value in self.entries:
            if name == key:
                return value
        return None

    def set(self, key: str, value: str) -> None:
        for index, (name, _) in enumerate(self.entries):
            if name == key:
                self.entries[index] = (key, value)
                return
        self.entries.append((key, value))


def read_text(path: str | Path) -> str:
    """Read without newline translation so CRLF files survive a round trip."""
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def write_text(path: str | Path, text: str) -> None:
    """Write without newline translation (the inverse of :func:`read_text`)."""
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _quotes_open(line: str) -> bool:
    count = 0
    escaped = False
    for char in line:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == '"':
            count += 1
    return count % 2 == 1


def parse(text: str) -> Node:
    root = Node("__root__")
    stack = [root]
    offset = 0
    in_string = False
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        if in_string:
            in_string = _quotes_open(stripped)
            offset += len(line)
            continue

        open_match = OPEN_RE.match(stripped)
        close_match = CLOSE_RE.match(stripped)
        if open_match:
            node = Node(open_match.group(2), open_match.group(1), start=offset)
            node.close_start = offset
            stack[-1].children.append(node)
            stack.append(node)
        elif close_match and len(stack) > 1:
            node = stack.pop()
            node.close_start = offset
            node.end = offset + len(line)
        else:
            entry = ENTRY_RE.match(stripped)
            if entry:
                stack[-1].entries.append((entry.group(2), entry.group(3)))
                if _quotes_open(stripped):
                    in_string = True
        offset += len(line)
    while len(stack) > 1:
        node = stack.pop()
        node.end = len(text)
    root.end = len(text)
    return root


def walk(node: Node):
    yield node
    for child in node.children:
        yield from walk(child)


def find(node: Node, keyword: str) -> list[Node]:
    return [item for item in walk(node) if item.keyword == keyword]


def top_schematic(root: Node) -> Node | None:
    plecs = next((item for item in root.children if item.keyword == "Plecs"), None)
    if plecs is None:
        return None
    return next((child for child in plecs.children if child.keyword == "Schematic"), None)


def components(root: Node) -> list[Node]:
    """Every Component node, including those inside subsystem Schematics."""
    return [item for item in walk(root) if item.keyword == "Component"]


def component_name(node: Node) -> str | None:
    value = node.get("Name")
    return value.strip('"') if value else None


def find_component(root: Node, name: str) -> Node | None:
    for node in components(root):
        if component_name(node) == name:
            return node
    return None


def component_position(root: Node, name: str) -> list[int] | None:
    node = find_component(root, name)
    raw = node.get("Position") if node else None
    if not raw:
        return None
    numbers = re.findall(r"-?\d+", raw)
    return [int(value) for value in numbers[:2]] if len(numbers) >= 2 else None


def _insert(text: str, offset: int, fragment: str) -> str:
    return text[:offset] + fragment + text[offset:]


def _block_lines(node: Node, text: str) -> list[str]:
    return text[node.start : node.end].splitlines()


def _dedent(lines: list[str]) -> list[str]:
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return lines
    prefix = len(non_empty[0]) - len(non_empty[0].lstrip())
    return [line[prefix:] if line.strip() else "" for line in lines]


def _indent_lines(lines: list[str], indent: str) -> str:
    return "\n".join((indent + line) if line.strip() else "" for line in lines)


def _set_entry(block: str, key: str, value: str) -> str:
    pattern = re.compile(rf'^(\s*{key}\s+).*$', re.MULTILINE)
    if pattern.search(block):
        return pattern.sub(rf"\g<1>{value}", block, count=1)
    return block


def _set_parameter(block: str, variable: str, value: str) -> tuple[str, bool]:
    pattern = re.compile(
        rf'(Parameter\s*\{{[^{{}}]*?Variable\s+"{re.escape(variable)}"[^{{}}]*?Value\s+)"[^"]*"',
        re.DOTALL,
    )
    new_block, count = pattern.subn(rf'\g<1>"{value}"', block, count=1)
    return new_block, count > 0


def render_from_template(
    template: str,
    name: str,
    position: list[int] | None,
    parameters: dict[str, str] | None,
    indent: str,
) -> str:
    lines = _dedent(template.splitlines())
    block = _indent_lines(lines, indent)
    block = _set_entry(block, "Name", f'"{name}"')
    if position:
        block = _set_entry(block, "Position", f"[{position[0]}, {position[1]}]")
    for variable, value in (parameters or {}).items():
        block, _ = _set_parameter(block, variable, str(value))
    return block


def _component_insert_offset(schematic: Node) -> int:
    """PLECS keeps all Components before Connections/Annotations; insert at that boundary."""
    for child in schematic.children:
        if child.keyword != "Component":
            return child.start
    return schematic.close_start


def add_component(
    text: str,
    root: Node,
    template: str,
    name: str,
    position: list[int] | None,
    parameters: dict[str, str] | None = None,
) -> str:
    schematic = top_schematic(root)
    if schematic is None:
        raise ValueError("model has no top-level Schematic")
    if find_component(root, name) is not None:
        raise ValueError(f"component {name!r} already exists")
    indent = schematic.indent + "  "
    block = render_from_template(template, name, position, parameters, indent)
    fragment = "\n" + block + "\n"
    return _insert(text, _component_insert_offset(schematic), fragment)


def set_parameter(text: str, root: Node, component: str, variable: str, value: str) -> str:
    node = find_component(root, component)
    if node is None:
        raise ValueError(f"component {component!r} not found")
    span = text[node.start : node.end]
    updated, found = _set_parameter(span, variable, value)
    if not found:
        raise ValueError(f"component {component!r} has no parameter {variable!r}")
    return text[: node.start] + updated + text[node.end :]


def remove_component(text: str, root: Node, name: str) -> str:
    node = find_component(root, name)
    if node is None:
        raise ValueError(f"component {name!r} not found")
    # drop the component block plus the trailing newline
    end = node.end
    start = node.start
    return text[:start] + text[end:]


def _wire_block(
    src: str,
    src_terminal: int,
    dst: str,
    dst_terminal: int,
    points: list[list[int]] | None,
    indent: str,
) -> str:
    lines = [
        f"{indent}Connection {{",
        f"{indent}  Type          Wire",
        f'{indent}  SrcComponent  "{src}"',
        f"{indent}  SrcTerminal   {int(src_terminal)}",
    ]
    if points:
        lines.append(f"{indent}  Points        [{points[0][0]}, {points[0][1]}]")
    inner = indent + "  "
    for corner in (points or [])[1:-1]:
        lines.append(f"{inner}Branch {{")
        lines.append(f"{inner}  Points        [{corner[0]}, {corner[1]}]")
        inner += "  "
    lines.append(f"{inner}Branch {{")
    lines.append(f'{inner}  DstComponent  "{dst}"')
    lines.append(f"{inner}  DstTerminal   {int(dst_terminal)}")
    lines.append(f"{inner}}}")
    for _ in (points or [])[1:-1]:
        inner = inner[:-2]
        lines.append(f"{inner}}}")
    lines.append(f"{indent}}}")
    return "\n".join(lines)


def add_connection(
    text: str,
    root: Node,
    src: str,
    src_terminal: int,
    dst: str,
    dst_terminal: int,
    points: list[list[int]] | None = None,
) -> str:
    for name in (src, dst):
        if find_component(root, name) is None:
            raise ValueError(f"component {name!r} not found")
    schematic = top_schematic(root)
    if schematic is None:
        raise ValueError("model has no top-level Schematic")

    if not points:
        start = component_position(root, src)
        points = [start] if start else None

    block = _wire_block(src, src_terminal, dst, dst_terminal, points, schematic.indent + "  ")
    fragment = "\n" + block + "\n"
    return _insert(text, schematic.close_start, fragment)


OUTPUT_TEMPLATE = """Component {{
  Type          Output
  Name          "{name}"
  Show          on
  Position      [{x}, {y}]
  Direction     right
  Flipped       off
  LabelPosition south
  Parameter {{
    Variable      "Index"
    Value         "{index}"
    Show          on
  }}
  Parameter {{
    Variable      "Width"
    Value         "-1"
    Show          off
  }}
}}"""


def next_output_index(root: Node) -> int:
    best = 0
    for node in components(root):
        if node.get("Type") == "Output":
            raw = node.get("Index")
            match = re.search(r'"?(\d+)"?', raw or "")
            if match:
                best = max(best, int(match.group(1)))
    for plecs in (item for item in root.children if item.keyword == "Plecs"):
        for child in plecs.children:
            if child.keyword != "Terminal" or child.get("Type") != "Output":
                continue
            match = re.search(r'"?(\d+)"?', child.get("Index") or "")
            if match:
                best = max(best, int(match.group(1)))
    return best + 1


def add_outport(text: str, root: Node, name: str, position: list[int], index: int | None = None) -> str:
    schematic = top_schematic(root)
    if schematic is None:
        raise ValueError("model has no top-level Schematic")
    if find_component(root, name) is not None:
        raise ValueError(f"component {name!r} already exists")
    index = index or next_output_index(root)
    indent = schematic.indent + "  "
    block = OUTPUT_TEMPLATE.format(name=name, x=position[0], y=position[1], index=index)
    block = _indent_lines(block.splitlines(), indent)
    text = _insert(text, _component_insert_offset(schematic), "\n" + block + "\n")

    # model-level port declaration must live before Schematic
    plecs = schematic_start = None
    for item in root.children:
        if item.keyword == "Plecs":
            plecs = item
            break
    for child in (plecs.children if plecs else []):
        if child.keyword == "Schematic":
            schematic_start = child.start
            break
    if schematic_start is not None:
        terminal = f'{plecs.indent}  Terminal {{\n{plecs.indent}    Type          Output\n{plecs.indent}    Index         "{index}"\n{plecs.indent}  }}\n'
        text = _insert(text, schematic_start, terminal)
    return text


def component_names(root: Node) -> list[str]:
    return [name for name in (component_name(node) for node in components(root)) if name]


def script_names(path: str | Path) -> list[str]:
    """Simulation Script names from a .plecs file (the RPC model tree omits them)."""
    try:
        root = parse(read_text(path))
    except (OSError, ValueError):
        return []
    names: list[str] = []
    for node in find(root, "Script"):
        value = node.get("Name")
        if not value:
            continue
        name = value.strip('"')
        if name and name not in names:
            names.append(name)
    return names


def library_templates(text: str) -> dict[str, str]:
    """Map component Type -> raw block text (first occurrence) for use as a template."""
    root = parse(text)
    templates: dict[str, str] = {}
    for node in components(root):
        kind = (node.get("Type") or "").strip('"')
        if kind and kind not in templates:
            templates[kind] = text[node.start : node.end]
    return templates
