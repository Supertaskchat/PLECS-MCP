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


def test_sign_and_codegen_refuse_install_dirs(monkeypatch):
    monkeypatch.setattr(server, "_require", lambda method: None)
    with pytest.raises(ToolError, match="refusing to write inside"):
        server.plecs_sign("/Applications/PLECS 5.0.app/model.plecs")
    with pytest.raises(ToolError, match="refusing to write inside"):
        server.plecs_codegen("m", output_dir="/Applications/PLECS 5.0.app/out")
