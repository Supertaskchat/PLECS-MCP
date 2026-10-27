"""Tests for the static .plecs connection graph and validator."""

from pathlib import Path

import pytest

from plecs_mcp import server
from plecs_mcp.model_graph import validate_model_file, validate_model_text


def _model(body: str, top_terminals: str = '  Terminal {\n    Type Output\n    Index "1"\n  }\n') -> str:
    return f'''Plecs {{
  Name          "test"
{top_terminals}  Schematic {{
{body}  }}
}}
'''


def _output(name: str = "Out", index: str = "1") -> str:
    return f'''    Component {{
      Type          Output
      Name          "{name}"
      Parameter {{
        Variable      "Index"
        Value         "{index}"
      }}
    }}
'''


def _resistor(name: str = "R1") -> str:
    return f'''    Component {{
      Type          Resistor
      Name          "{name}"
    }}
'''


def _cscript(name: str = "Calc", inputs: str = "[1 1]", outputs: str = "[2]") -> str:
    return f'''    Component {{
      Type          CScript
      Name          "{name}"
      Parameter {{
        Variable      "NumInputs"
        Value         "{inputs}"
      }}
      Parameter {{
        Variable      "NumOutputs"
        Value         "{outputs}"
      }}
      Parameter {{
        Variable      "DirectFeedthrough"
        Value         "[1 1]"
      }}
      Parameter {{
        Variable      "Parameters"
        Value         "a, b"
      }}
      Parameter {{
        Variable      "OutputFcn"
        Value         "OutputSignal(0,0)=InputSignal(0,0);"
      }}
    }}
'''


def _diag(text: str, include_code: bool = True):
    return validate_model_text("test", text, include_code=include_code)[1]


def _codes(diagnostics) -> set[str]:
    return {item.code for item in diagnostics}


def _errors(diagnostics) -> list:
    return [item for item in diagnostics if item.severity == "error"]


def test_valid_model_has_no_diagnostics():
    text = _model(_resistor() + _output() + '''    Connection {
      Type          Signal
      SrcComponent  "R1"
      SrcTerminal   1
      DstComponent  "Out"
      DstTerminal   1
    }
''')
    assert _diag(text) == []


def test_missing_component_is_an_error():
    text = _model(_output() + '''    Connection {
      Type          Signal
      SrcComponent  "Missing"
      SrcTerminal   1
      DstComponent  "Out"
      DstTerminal   1
    }
''')
    assert "CONN-001" in _codes(_diag(text))


def test_duplicate_component_name_is_an_error():
    text = _model(_resistor("R1") + _resistor("R1") + _output())
    assert "CONN-005" in _codes(_diag(text))


def test_cscript_terminal_range_and_direction():
    text = _model(
        _resistor()
        + _cscript()
        + _output()
        + '''    Connection {
      Type          Signal
      SrcComponent  "R1"
      SrcTerminal   1
      DstComponent  "Calc"
      DstTerminal   4
    }
'''
    )
    assert "CONN-007" in _codes(_diag(text))

    text = _model(
        _cscript()
        + _output()
        + '''    Connection {
      Type          Signal
      SrcComponent  "Calc"
      SrcTerminal   1
      DstComponent  "Out"
      DstTerminal   1
    }
'''
    )
    assert "CONN-011" in _codes(_diag(text))


def test_cscript_code_indices_are_warnings():
    text = _model(
        _cscript().replace("OutputSignal(0,0)", "OutputSignal(2,0)")
        + _output()
    )
    diagnostics = _diag(text)
    assert "CSCRIPT-008" in _codes(diagnostics)
    assert all(item.severity == "warning" for item in diagnostics if item.code == "CSCRIPT-008")


def test_subsystem_port_range_and_direction():
    subsystem = '''    Component {
      Type          Subsystem
      Name          "Sub"
      Terminal {
        Type Input
      }
      Terminal {
        Type Output
      }
      Schematic {
        Component {
          Type Input
          Name "in"
        }
        Component {
          Type Output
          Name "out"
        }
      }
    }
'''
    text = _model(subsystem + _output() + '''    Connection {
      Type          Signal
      SrcComponent  "Sub"
      SrcTerminal   3
      DstComponent  "Out"
      DstTerminal   1
    }
''')
    assert "CONN-006" in _codes(_diag(text))


def test_top_level_output_index_mismatch():
    text = _model(_output(index="2"))
    assert "CONN-006" in _codes(_diag(text))


def test_branch_fanout_is_valid_and_mixed_endpoint_warns():
    body = _resistor() + _output() + '''    Connection {
      Type          Signal
      SrcComponent  "R1"
      SrcTerminal   1
      Branch {
        DstComponent  "Out"
        DstTerminal   1
      }
    }
'''
    assert _diag(_model(body)) == []

    mixed = _resistor() + _output() + '''    Connection {
      Type          Signal
      SrcComponent  "R1"
      SrcTerminal   1
      DstComponent  "Out"
      DstTerminal   1
      Branch {
        DstComponent  "Out"
        DstTerminal   1
      }
    }
'''
    assert "CONN-009" in _codes(_diag(_model(mixed)))


def test_plecs_validate_includes_connection_diagnostics(monkeypatch, tmp_path: Path):
    text = _model(_output() + """    Connection {
      Type          Signal
      SrcComponent  "Missing"
      SrcTerminal   1
      DstComponent  "Out"
      DstTerminal   1
    }
""")
    path = tmp_path / "invalid.plecs"
    path.write_text(text, encoding="utf-8")
    server.STATE.loaded("invalid", str(path))

    def fake_raw(method, params=None, timeout=None):
        if method == "plecs.getModelTree":
            return {}
        if method == "plecs.get":
            return {"TimeSpan": "1e-3", "MaxStep": "1e-6", "Solver": "auto"}
        if method == "plecs.statistics":
            return {"models": []}
        return {}

    monkeypatch.setattr(server, "_raw", fake_raw)
    try:
        result = server.plecs_validate("invalid")
    finally:
        server.STATE.closed("invalid")
    assert result["ok"] is False
    assert any(item["code"] == "CONN-001" for item in result["diagnostics"])
    assert result["info"]["connections"]["connections"] == 1


def test_validate_model_file_matches_text_validation(tmp_path: Path):
    text = _model(_resistor() + _output())
    path = tmp_path / "model.plecs"
    path.write_text(text, encoding="utf-8")
    file_graph, file_diagnostics = validate_model_file("model", path)
    text_graph, text_diagnostics = validate_model_text("model", text)
    assert [item.as_dict() for item in file_diagnostics] == [
        item.as_dict() for item in text_diagnostics
    ]
    assert len(file_graph.schematics) == len(text_graph.schematics)


def test_dynamic_cscript_port_specs_are_not_checked():
    """Library templates use -1 (inherited) or expressions; never guess a count."""
    inherited = _cscript(inputs="-1", outputs="-1")
    expression = _cscript(inputs="[1 num_channels]", outputs="[(3+1)*num_channels]")
    for spec in (inherited, expression):
        text = _model(
            _resistor()
            + spec
            + _output()
            + '''    Connection {
      Type          Signal
      SrcComponent  "Calc"
      SrcTerminal   9
      DstComponent  "Out"
      DstTerminal   1
    }
'''
        )
        diagnostics = _diag(text)
        assert diagnostics == [], [item.as_dict() for item in diagnostics]

    graph, _ = validate_model_text("test", _model(inherited))
    assert graph.unchecked_cscript_ports() == ["Calc"]


def test_cscript_without_port_parameters_warns():
    body = '''    Component {
      Type          CScript
      Name          "Calc"
    }
'''
    diagnostics = _diag(_model(body + _output()))
    assert "CSCRIPT-001" in _codes(diagnostics)
    assert all(item.severity == "warning" for item in diagnostics)


def test_points_only_branch_is_ignored():
    """A Branch with only Points is drawing geometry, not an endpoint."""
    body = _resistor() + _output() + '''    Connection {
      Type          Wire
      SrcComponent  "R1"
      SrcTerminal   1
      Branch {
        Points        [280, 220]
      }
      Branch {
        DstComponent  "Out"
        DstTerminal   1
      }
    }
'''
    assert _diag(_model(body)) == []


def test_encrypted_subsystem_is_not_missing_a_schematic():
    body = '''    Component {
      Type          Subsystem
      Name          "Sealed"
      Encrypted     "QUJD"
    }
''' + _output()
    assert "SUB-005" not in _codes(_diag(_model(body)))


def test_library_template_variants_may_repeat_names():
    body = '''    Component {
      Type          Subsystem
      Name          "Switches"
      MaskType      "Switches"
      Terminal {
        Type Input
      }
      Schematic {
        Component {
          Type          Switch
          Name          "S1"
        }
        Component {
          Type          ManualSwitch
          Name          "S1"
        }
      }
    }
'''
    assert "CONN-005" not in _codes(_diag(_model(body)))

    duplicate = _model(_resistor("R1") + _resistor("R1") + _output())
    assert "CONN-005" in _codes(_diag(duplicate))


def test_directfeedthrough_matches_ports_or_channels():
    """PLECS accepts one entry per port and one entry per channel."""
    per_channel = _cscript(inputs="7", outputs="2").replace(
        'Value         "[1 1]"', 'Value         "[1 1 1 0 0 1 1]"'
    )
    assert "CSCRIPT-004" not in _codes(_diag(_model(per_channel + _output())))

    per_port = _cscript(inputs="[8 1 3]", outputs="[3 1]").replace(
        'Value         "[1 1]"', 'Value         "[8 1 3]"'
    )
    assert "CSCRIPT-004" not in _codes(_diag(_model(per_port + _output())))


def test_missing_ports_without_outputs_skip_root_outport_pairing():
    """Library files and RT Box models declare bare outport terminals."""
    text = _model(_resistor(), top_terminals='  Terminal {\n    Type Output\n    Index "1"\n  }\n')
    assert "CONN-006" not in _codes(_diag(text))


def test_scalar_zero_port_count_means_no_ports():
    body = _cscript(inputs="0", outputs="[5]") + _output() + '''    Connection {
      Type          Signal
      SrcComponent  "Calc"
      SrcTerminal   2
      DstComponent  "Out"
      DstTerminal   1
    }
'''
    diagnostics = _diag(_model(body))
    assert "CONN-007" in _codes(diagnostics)
    graph, _ = validate_model_text("test", _model(body))
    calc = graph.find_component("Calc")
    assert calc.input_widths == []
    assert calc.output_widths == [5]


def test_from_without_goto_is_a_warning():
    body = '''    Component {
      Type          From
      Name          "F1"
      Parameter {
        Variable      "Tag"
        Value         "IslandCmd"
      }
    }
'''
    diagnostics = _diag(_model(body + _output()))
    assert "CONN-012" in _codes(diagnostics)
    assert all(item.severity == "warning" for item in diagnostics if item.code == "CONN-012")


def test_from_with_matching_goto_is_clean():
    body = '''    Component {
      Type          Goto
      Name          "G1"
      Parameter {
        Variable      "Tag"
        Value         "IslandCmd"
      }
    }
    Component {
      Type          From
      Name          "F1"
      Parameter {
        Variable      "Tag"
        Value         "IslandCmd"
      }
    }
'''
    assert "CONN-012" not in _codes(_diag(_model(body + _output())))
