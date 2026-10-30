"""Tests for the corpus-measured placement conventions."""

import pytest

from plecs_mcp import orientation


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


def test_conventions_come_from_the_corpus():
    horizontal = orientation.expected_for("Inductor", "right")
    assert horizontal["side"] == "right"
    assert horizontal["n"] >= 300 and horizontal["share"] >= 70
    vertical = orientation.expected_for("Diode", "up")
    assert vertical["side"] == "top"
    assert orientation.expected_for("Resistor", "right") is None
    assert orientation.expected_for("MosfetWithDiode", "right") is None


def _inductor(direction: str, flipped: str) -> str:
    return f'''Plecs {{
  Name          "m"
  Schematic {{
    Component {{
      Type          Inductor
      Name          "L"
      Position      [100, 100]
      Direction     {direction}
      Flipped       {flipped}
    }}
    Component {{
      Type          Breaker
      Name          "B"
      Position      [200, 100]
      Direction     left
      Flipped       off
    }}
    Connection {{
      Type          Wire
      SrcComponent  "L"
      SrcTerminal   2
      DstComponent  "B"
      DstTerminal   1
    }}
  }}
}}
'''


def test_horizontal_inductor_matching_the_corpus_is_clean():
    assert orientation.check_orientation(text=_inductor("left", "off")) == []


def test_horizontal_inductor_with_terminal_one_on_the_left_is_reported():
    findings = orientation.check_orientation(text=_inductor("right", "off"))
    assert [item["component"] for item in findings] == ["L"]
    assert findings[0]["code"] == "LAYOUT-004"
    assert findings[0]["severity"] == "info"
    assert findings[0]["actual"]["term1_side"] == "left"
    assert findings[0]["expected"] == {"direction": "left", "flipped": "off"}
    assert findings[0]["convention"]["n"] > 0


def test_vertical_diode_points_down_in_the_corpus():
    text = '''Plecs {
  Name          "m"
  Schematic {
    Component {
      Type          Diode
      Name          "D"
      Position      [100, 100]
      Direction     down
      Flipped       off
    }
  }
}
'''
    assert orientation.check_orientation(text=text) == []
    flipped = text.replace("Direction     down", "Direction     up")
    findings = orientation.check_orientation(text=flipped)
    assert [item["component"] for item in findings] == ["D"]
    assert findings[0]["expected"] == {"direction": "down", "flipped": "off"}


def test_project_policy_overrides_the_corpus():
    findings = orientation.check_orientation(
        text=_inductor("left", "off"), policies={"Inductor": "left"}
    )
    assert [item["component"] for item in findings] == ["L"]
    assert findings[0]["expected"] == {"direction": "right", "flipped": "off"}
    assert findings[0]["convention"]["n"] == 0


def test_types_without_a_convention_are_silent():
    text = _inductor("right", "off").replace("Type          Inductor", "Type          Resistor")
    assert orientation.check_orientation(text=text) == []
