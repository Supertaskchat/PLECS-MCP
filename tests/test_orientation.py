"""Tests for the placement-orientation rules."""

from pathlib import Path

import pytest

from plecs_mcp import orientation, plecsfile


def test_terminal_one_side_follows_direction_and_flip():
    assert orientation.term1_side("right", "off") == "left"
    assert orientation.term1_side("right", "on") == "right"
    assert orientation.term1_side("left", "off") == "right"
    assert orientation.term1_side("left", "on") == "left"
    assert orientation.term1_side("up", "off") == "bottom"
    assert orientation.term1_side("up", "on") == "top"
    assert orientation.term1_side("down", "off") == "top"
    assert orientation.term1_side("sideways", "off") is None


def test_orientation_for_is_the_inverse():
    for wanted in ("left", "right"):
        choice = orientation.orientation_for("horizontal", wanted)
        assert orientation.term1_side(choice["direction"], choice["flipped"]) == wanted
    for wanted in ("top", "bottom"):
        choice = orientation.orientation_for("vertical", wanted)
        assert orientation.term1_side(choice["direction"], choice["flipped"]) == wanted
    assert orientation.orientation_for("horizontal", "top") is None


def _chain(flip_l: bool = False, flip_brk: bool = False) -> str:
    def comp(kind, name, x, flip):
        return f'''    Component {{
      Type          {kind}
      Name          "{name}"
      Position      [{x}, 100]
      Direction     right
      Flipped       {"on" if flip else "off"}
    }}
'''
    def wire(src, dst):
        return f'''    Connection {{
      Type          Wire
      SrcComponent  "{src}"
      SrcTerminal   2
      DstComponent  "{dst}"
      DstTerminal   1
    }}
'''
    return (
        'Plecs {\n  Name          "m"\n  Schematic {\n'
        + comp("VoltageSource", "V", 100, False)
        + comp("Inductor", "L", 200, flip_l)
        + comp("Breaker", "B", 300, flip_brk)
        + wire("V", "L")
        + wire("L", "B")
        + "  }\n}\n"
    )


def test_reading_order_accepts_a_left_to_right_chain():
    assert orientation.check_orientation(text=_chain()) == []


def test_reading_order_flags_a_reversed_part(tmp_path: Path):
    findings = orientation.check_orientation(text=_chain(flip_l=True))
    assert [item["component"] for item in findings] == ["L"]
    assert findings[0]["code"] == "LAYOUT-004"
    assert findings[0]["severity"] == "info"
    assert findings[0]["actual"]["term1_side"] == "right"
    assert findings[0]["expected"] == {"direction": "right", "flipped": "off"}


def test_vertical_chain_expects_terminal_one_on_top():
    text = '''Plecs {
  Name          "m"
  Schematic {
    Component {
      Type          Inductor
      Name          "L"
      Position      [100, 100]
      Direction     up
      Flipped       off
    }
    Component {
      Type          Breaker
      Name          "B"
      Position      [100, 200]
      Direction     up
      Flipped       off
    }
    Connection {
      Type          Wire
      SrcComponent  "L"
      SrcTerminal   2
      DstComponent  "B"
      DstTerminal   1
    }
  }
}
'''
    findings = orientation.check_orientation(text=text)
    assert {item["component"] for item in findings} == {"L", "B"}
    inductor = next(item for item in findings if item["component"] == "L")
    assert inductor["actual"]["term1_side"] == "bottom"
    assert inductor["expected"] == {"direction": "up", "flipped": "on"}


def test_policy_override_replaces_reading_order():
    text = _chain()
    findings = orientation.check_orientation(text=text, policies={"Inductor": "right"})
    assert [item["component"] for item in findings] == ["L"]
    assert findings[0]["expected"]["flipped"] == "on"


def test_non_polar_parts_are_ignored():
    text = _chain().replace("Type          Inductor", "Type          Resistor")
    assert orientation.check_orientation(text=text) == []
