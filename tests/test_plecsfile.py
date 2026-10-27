from plecs_mcp import plecsfile

MODEL = '''Plecs {
  Name          "demo"
  Terminal {
    Type          Output
    Index         "1"
  }
  Schematic {
    Component {
      Type          Resistor
      Name          "R1"
      Show          on
      Position      [100, 100]
      Parameter {
        Variable      "R"
        Value         "1"
        Show          off
      }
    }
    Connection {
      Type          Wire
      SrcComponent  "R1"
      SrcTerminal   1
      Branch {
        DstComponent  "Out"
        DstTerminal   1
      }
    }
  }
  Analysis {
    Type          SteadyStateAnalysis
    Name          "Steady State Analysis"
  }
}
'''

TEMPLATE = '''Component {
  Type          Resistor
  Name          "R"
  Show          on
  Position      [0, 0]
  Parameter {
    Variable      "R"
    Value         "1"
    Show          off
  }
}'''


def test_parse_and_find_components():
    root = plecsfile.parse(MODEL)
    assert plecsfile.component_names(root) == ["R1"]
    assert plecsfile.component_position(root, "R1") == [100, 100]
    assert plecsfile.find_component(root, "nope") is None


def test_set_parameter_only_touches_the_value():
    root = plecsfile.parse(MODEL)
    updated = plecsfile.set_parameter(MODEL, root, "R1", "R", "22")
    assert '"Value         "22""' not in updated  # sanity on replacement syntax
    assert updated.count('"R"') == 1
    assert updated.replace('"22"', '"1"') == MODEL


def test_add_component_inserts_before_connections():
    root = plecsfile.parse(MODEL)
    updated = plecsfile.add_component(MODEL, root, TEMPLATE, "R2", [200, 100], {"R": "5"})
    assert 'Name          "R2"' in updated
    assert updated.index('"R2"') < updated.index("Connection {")
    reparsed = plecsfile.parse(updated)
    assert plecsfile.component_names(reparsed) == ["R1", "R2"]
    assert plecsfile.find_component(reparsed, "R2").get("Position") == "[200, 100]"


def test_add_component_rejects_duplicates():
    root = plecsfile.parse(MODEL)
    try:
        plecsfile.add_component(MODEL, root, TEMPLATE, "R1", [0, 0])
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_add_connection_is_brace_balanced():
    root = plecsfile.parse(MODEL)
    updated = plecsfile.add_connection(MODEL, root, "R1", 1, "R1", 2, [[120, 100], [160, 100]])
    assert updated.count("{") == updated.count("}")  # the inserted wire must be balanced
    assert updated.count("Connection {") == 2
    assert "DstTerminal   2" in updated


def test_add_outport_adds_terminal_and_component():
    root = plecsfile.parse(MODEL)
    updated = plecsfile.add_outport(MODEL, root, "Vout", [300, 100])
    assert 'Name          "Vout"' in updated
    assert updated.count("Terminal {") == 2
    assert 'Index         "2"' in updated


def test_library_templates_extracts_types():
    lib = TEMPLATE + '\nComponent {\n  Type          Inductor\n  Name          "L"\n}\n'
    templates = plecsfile.library_templates(lib)
    assert set(templates) == {"Resistor", "Inductor"}
    assert 'Type          Resistor' in templates["Resistor"]
