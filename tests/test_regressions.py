"""Regression tests for issues found during the project review."""

import base64
import json
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from plecs_mcp import library, modelops, server, tasks

PNG = b"\x89PNG\r\n\x1a\n" + b"payload"


def _model_text() -> str:
    return '''Plecs {
  Schematic {
    Component {
      Type          Resistor
      Name          "R1"
      Parameter {
        Variable      "R"
        Value         "1"
      }
    }
  }
}
'''


def test_analyze_data_handles_parameter_sweep_list(tmp_path: Path):
    path = tmp_path / "sweep.json"
    path.write_text(json.dumps([{"Time": [0, 1], "Values": [[1, 2]]}, {"Time": [0, 1], "Values": [[3, 4]]}]))
    result = server.plecs_analyze_data(str(path))
    assert result["kind"] == "parameter-sweep"
    assert result["count"] == 2
    assert result["results"][0]["kind"] == "time-series"


def test_analyze_data_rejects_invalid_json(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    with pytest.raises(ToolError, match="not valid JSON"):
        server.plecs_analyze_data(str(path))


def test_point_count_handles_values_only_payloads():
    assert server._point_count({"Values": [[1, 2, 3], [4, 5, 6]]}) == 3
    assert server._point_count({"Values": [1, 2, 3]}) == 3


def test_webserver_externalizes_bitmap_without_save_to(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PLECS_MCP_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(
        server,
        "_raw",
        lambda *args, **kwargs: {"imageData": base64.b64encode(PNG).decode(), "componentType": "Scope"},
    )
    result = server.plecs_webserver("getScopeBitmap", ["m/Scope"])
    assert result["imageData"]["saved"]["bytes"] == len(PNG)
    assert result["saved"]["bytes"] == len(PNG)
    assert Path(result["saved"]["path"]).read_bytes() == PNG
    assert "iVBOR" not in json.dumps(result)


def test_webserver_externalizes_nested_signals(monkeypatch, tmp_path: Path):
    encoded = base64.b64encode(PNG).decode()
    monkeypatch.setattr(
        server,
        "_raw",
        lambda *args, **kwargs: [{"signal": [{"name": "v", "imageData": [encoded, encoded]}]}],
    )
    target = tmp_path / "signals.png"
    result = server.plecs_webserver("getScopeSignals", ["m/Scope"], save_to=str(target))
    assert len(result["images"]) == 2
    assert (tmp_path / "signals-1.png").read_bytes() == PNG
    assert (tmp_path / "signals-2.png").read_bytes() == PNG


def test_model_edit_in_place_obeys_allowed_roots(monkeypatch, tmp_path: Path):
    models = tmp_path / "models"
    models.mkdir()
    source = models / "m.plecs"
    source.write_text(_model_text(), encoding="utf-8")
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("PLECS_MCP_ALLOWED_ROOTS", str(allowed))

    with pytest.raises(ToolError, match="outside PLECS_MCP_ALLOWED_ROOTS"):
        server.plecs_model_edit(
            str(source),
            [{"op": "set_parameter", "component": "R1", "variable": "R", "value": "2"}],
            confirm=True,
            validate=False,
        )

    monkeypatch.setenv("PLECS_MCP_ALLOWED_ROOTS", str(tmp_path))
    result = server.plecs_model_edit(
        str(source),
        [{"op": "set_parameter", "component": "R1", "variable": "R", "value": "2"}],
        confirm=True,
        validate=False,
    )
    assert result["backup"] and ".bak-" in result["backup"]
    assert '"2"' in source.read_text(encoding="utf-8")


def test_task_load_keeps_newest_by_created(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(tasks, "MAX_TASKS", 2)
    for index, created in enumerate([1.0, 2.0, 3.0]):
        record = tasks.TaskRecord(id=f"t{index}", method="demo", status="done", created=created)
        (tmp_path / f"t{index}.json").write_text(json.dumps(record.to_json()), encoding="utf-8")
    registry = tasks.TaskRegistry(directory=tmp_path)
    assert set(registry._tasks) == {"t1", "t2"}


def test_components_path_supports_all_layouts(tmp_path: Path):
    mac = tmp_path / "PLECS.app"
    (mac / "Contents").mkdir(parents=True)
    (mac / "Contents" / "Components.plecs").write_text("x")
    assert library.components_path(mac) == mac / "Contents" / "Components.plecs"

    linux = tmp_path / "opt" / "plecs"
    linux.mkdir(parents=True)
    (linux / "Components.plecs").write_text("x")
    assert library.components_path(linux / "plecs") == linux / "Components.plecs"

    windows = tmp_path / "Program Files" / "Plexim" / "PLECS 5.0"
    windows.mkdir(parents=True)
    (windows / "Components.plecs").write_text("x")
    assert library.components_path(windows / "plecs.exe") == windows / "Components.plecs"


def test_clone_preserves_crlf(tmp_path: Path):
    source = tmp_path / "m.plecs"
    original = 'Plecs {\r\n  Name          "old"\r\n}\r\n'
    source.write_bytes(original.encode("utf-8"))
    target = tmp_path / "copy.plecs"
    modelops.clone_model(source, target)
    assert target.read_bytes() == original.encode("utf-8")


def test_webserver_rejects_bare_cursor_index():
    with pytest.raises(ToolError, match="Index"):
        server.plecs_webserver("getCursorData", ["m/Scope", 0])


def test_webserver_rejects_circuit_bitmap_path():
    with pytest.raises(ToolError, match="model name"):
        server.plecs_webserver("getCircuitBitmap", ["/tmp/model.plecs"])


def test_scope_remove_trace_requires_name():
    with pytest.raises(ToolError, match="RemoveTrace requires"):
        server.plecs_scope("m/Scope", "RemoveTrace")


def test_scope_load_traces_requires_existing_file(tmp_path: Path):
    with pytest.raises(ToolError, match="non-empty .trace"):
        server.plecs_scope("m/Scope", "LoadTraces", str(tmp_path / "missing.trace"))


def test_scope_save_traces_requires_simulation_data(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(server, "_scope_call", lambda *args, **kwargs: ([{"signal": []}], []))
    with pytest.raises(ToolError, match="no simulation data"):
        server.plecs_scope("m/Scope", "SaveTraces", str(tmp_path / "empty.trace"))


def test_scope_save_traces_with_data_passes(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(server, "_scope_call", lambda *args, **kwargs: ([{"signal": [1]}], []))
    monkeypatch.setattr(
        server, "_call", lambda method, params=None, timeout=None: calls.append((method, params)) or {"result": 0}
    )
    target = str(tmp_path / "ok.trace")
    result = server.plecs_scope("m/Scope", "SaveTraces", target)
    assert result == {"result": 0}
    assert calls == [("plecs.scope", ["m/Scope", "SaveTraces", target])]


def test_run_script_lists_available_scripts(monkeypatch, tmp_path: Path):
    model = tmp_path / "script_model.plecs"
    model.write_text(
        """Plecs {
  Script {
    Name          "First"
    Script        "x"
  }
  Script {
    Name          "Second"
    Script        "y"
  }
}
""",
        encoding="utf-8",
    )
    server.STATE.loaded("script_model", str(model))
    monkeypatch.setattr(server, "_require", lambda method: None)
    monkeypatch.setattr(server, "_scope_snapshot", lambda: {})

    def fail(*args, **kwargs):
        raise ToolError("plecs.runScript failed [-32500]: Could not find script with name Nope.")

    monkeypatch.setattr(server, "_call", fail)
    try:
        with pytest.raises(ToolError) as excinfo:
            server.plecs_run_script("script_model", "Nope")
    finally:
        server.STATE.closed("script_model")
    message = str(excinfo.value)
    assert "Available scripts" in message
    assert "First" in message and "Second" in message
    assert "does not expose scripts" in message


def test_run_script_uses_scriptname_optstruct(monkeypatch):
    calls = []

    def fake_raw(method, params=None, timeout=None):
        calls.append((method, params, timeout))
        return None

    monkeypatch.setattr(server, "_require", lambda method: None)
    monkeypatch.setattr(server, "_raw", fake_raw)
    result = server.plecs_run_script("mdl", "My Script")
    assert calls[-1] == ("plecs.runScript", ["mdl", {"ScriptName": "My Script"}], 600)
    assert result["script_name"] == "My Script"
    assert result["result"] is None


def test_sign_and_codegen_refuse_install_dirs(monkeypatch):
    monkeypatch.setattr(server, "_require", lambda method: None)
    with pytest.raises(ToolError, match="refusing to write inside"):
        server.plecs_sign("/Applications/PLECS 5.0.app/model.plecs")
    with pytest.raises(ToolError, match="refusing to write inside"):
        server.plecs_codegen("m", output_dir="/Applications/PLECS 5.0.app/out")
