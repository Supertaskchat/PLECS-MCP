import json
from pathlib import Path

from plecs_mcp import library_text

LIB = '''Plecs {
  Name          "Components"
  Schematic {
    Component {
      Type          Resistor
      Name          "R1"
      Parameter {
        Variable      "R"
        Value         "1"
      }
    }
    Component {
      Type          Capacitor
      Name          "C1"
      Parameter {
        Variable      "C"
        Value         "1e-6"
      }
    }
  }
}
'''


def test_load_items_parses_and_caches(monkeypatch, tmp_path: Path):
    source = tmp_path / "Components.plecs"
    source.write_text(LIB, encoding="utf-8")
    monkeypatch.setenv("PLECS_LIBRARY_PATH", str(source))
    monkeypatch.setenv("PLECS_MCP_OUTPUT_DIR", str(tmp_path / "out"))

    items = library_text.load_items()
    assert [item["type"] for item in items] == ["Resistor", "Capacitor"]
    assert items[0]["parameters"] == {"R": "1"}

    cache = library_text.cache_file(source)
    assert cache.is_file()
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert len(payload) == 2

    # a second load must come from the cache, not from parsing the file again
    monkeypatch.setattr(
        library_text, "_items_from_text", lambda text: (_ for _ in ()).throw(AssertionError("cache miss"))
    )
    assert len(library_text.load_items(source)) == 2


def test_search_matches_type_name_and_parameter(tmp_path: Path):
    items = [
        {"type": "Resistor", "name": "R1", "parameters": {"R": "1"}},
        {"type": "Capacitor", "name": "C1", "parameters": {"C": "1e-6"}},
    ]
    assert [item["name"] for item in library_text.search(items, "resist")] == ["R1"]
    assert [item["name"] for item in library_text.search(items, "1e-6")] == ["C1"]
    assert library_text.search(items, "") == items


def test_templates_are_raw_blocks(monkeypatch, tmp_path: Path):
    source = tmp_path / "Components.plecs"
    source.write_text(LIB, encoding="utf-8")
    monkeypatch.setenv("PLECS_LIBRARY_PATH", str(source))
    templates = library_text.load_templates(refresh=True)
    assert set(templates) == {"Resistor", "Capacitor"}
    assert 'Type          Resistor' in templates["Resistor"]
