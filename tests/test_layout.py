"""Tests for the geometric layout checks."""

from pathlib import Path

import pytest

from plecs_mcp import server
from plecs_mcp.layout import check_layout


def _model(extra: str = "") -> str:
    return f'''Plecs {{
  Name          "layout"
  Schematic {{
    Component {{
      Type          Resistor
      Name          "A"
      Position      [100, 100]
    }}
    Component {{
      Type          Resistor
      Name          "B"
      Position      [200, 100]
    }}
{extra}  }}
}}
'''


def _box(left: float, top: float, size: float = 10) -> dict:
    return {"dimensions": {"left": left, "top": top, "width": size, "height": size}}


def _codes(findings) -> set[str]:
    return {item["code"] for item in findings}


def test_clean_layout_has_no_findings():
    components = {"A": _box(95, 95), "B": _box(195, 95)}
    findings, info = check_layout(_model(), components)
    assert findings == []
    assert info["components"] == 2
    assert info["offset"] == [0.0, 0.0]


def test_overlapping_components_are_reported():
    components = {"A": _box(95, 95), "B": _box(100, 96)}
    findings, _ = check_layout(_model(), components)
    assert _codes(findings) == {"LAYOUT-001"}
    assert findings[0]["severity"] == "error"
    assert set(findings[0]["components"]) == {"A", "B"}


def test_diagonal_segment_is_reported():
    extra = '''    Connection {
      Type          Signal
      SrcComponent  "A"
      SrcTerminal   1
      DstComponent  "B"
      DstTerminal   1
      Points        [110, 100; 190, 120]
    }
'''
    components = {"A": _box(95, 95), "B": _box(195, 95)}
    findings, _ = check_layout(_model(extra), components)
    assert "LAYOUT-002" in _codes(findings)


def test_wire_crossing_a_component_is_reported():
    extra = '''    Component {
      Type          Resistor
      Name          "C"
      Position      [150, 100]
    }
    Connection {
      Type          Signal
      SrcComponent  "A"
      SrcTerminal   1
      DstComponent  "B"
      DstTerminal   1
      Points        [110, 100; 190, 100]
    }
'''
    components = {"A": _box(95, 95), "B": _box(195, 95), "C": _box(145, 95)}
    findings, _ = check_layout(_model(extra), components)
    crossing = [item for item in findings if item["code"] == "LAYOUT-003"]
    assert crossing and crossing[0]["component"] == "C"
    assert crossing[0]["severity"] == "info"


def test_wire_through_its_own_endpoints_is_not_flagged():
    extra = '''    Connection {
      Type          Signal
      SrcComponent  "A"
      SrcTerminal   1
      DstComponent  "B"
      DstTerminal   1
      Points        [100, 100; 200, 100]
    }
'''
    components = {"A": _box(95, 95), "B": _box(195, 95)}
    findings, _ = check_layout(_model(extra), components)
    assert findings == []


def test_missing_dimensions_are_skipped_not_guessed():
    components = {"A": _box(95, 95), "B": {}}
    findings, info = check_layout(_model(), components)
    assert findings == []
    assert info["skipped_components"] == ["B"]


def test_layout_check_tool_reports_findings(monkeypatch, tmp_path: Path):
    text = _model()
    path = tmp_path / "layout.plecs"
    path.write_text(text, encoding="utf-8")
    server.STATE.loaded("layout", str(path))

    def fake_scope(command, arguments):
        assert command == "getCircuitBitmap"
        return {"components": {"A": _box(95, 95), "B": _box(100, 96)}}, []

    monkeypatch.setattr(server, "_scope_call", fake_scope)
    try:
        result = server.plecs_layout_check("layout")
    finally:
        server.STATE.closed("layout")
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "LAYOUT-001"
    assert result["info"]["components"] == 2


def test_wire_starting_inside_a_third_component_is_reported():
    """Only the connection's own endpoints are exempt, not any box it touches."""
    extra = '''    Component {
      Type          Resistor
      Name          "C"
      Position      [150, 100]
    }
    Connection {
      Type          Signal
      SrcComponent  "A"
      SrcTerminal   1
      DstComponent  "B"
      DstTerminal   1
      Points        [150, 100; 190, 100]
    }
'''
    components = {"A": _box(95, 95), "B": _box(195, 95), "C": _box(145, 95)}
    findings, _ = check_layout(_model(extra), components)
    assert "LAYOUT-003" in _codes(findings)
    assert [item["component"] for item in findings if item["code"] == "LAYOUT-003"] == ["C"]


def test_nested_branch_points_follow_the_wire_path():
    """PLECS nests extra corners as Branch { Points }, not flat Points."""
    extra = '''    Component {
      Type          Resistor
      Name          "C"
      Position      [150, 100]
    }
    Connection {
      Type          Signal
      SrcComponent  "A"
      SrcTerminal   1
      Points        [110, 100]
      Branch {
        Points        [150, 100; 190, 100]
        DstComponent  "B"
        DstTerminal   1
      }
    }
'''
    components = {"A": _box(95, 95), "B": _box(195, 95), "C": _box(145, 95)}
    findings, _ = check_layout(_model(extra), components)
    crossing = [item for item in findings if item["code"] == "LAYOUT-003"]
    assert crossing and crossing[0]["component"] == "C"


def test_heat_sink_overlay_is_not_reported():
    extra = '''    Component {
      Type          HeatSink
      Name          "HS"
      Position      [150, 100]
    }
    Connection {
      Type          Signal
      SrcComponent  "A"
      SrcTerminal   1
      DstComponent  "B"
      DstTerminal   1
      Points        [110, 100; 190, 100]
    }
'''
    components = {"A": _box(95, 95), "B": _box(195, 95), "HS": _box(145, 95)}
    findings, _ = check_layout(_model(extra), components)
    assert findings == []
