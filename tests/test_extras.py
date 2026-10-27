import json
import time
import zipfile
from pathlib import Path

import pytest
from fastmcp import Client

from plecs_mcp import artifacts, checks, data, library, modelops, plotting, tasks
from plecs_mcp.diagnose import diagnose, with_hint
from plecs_mcp.server import mcp


# ---------------------------------------------------------------- plotting

def test_plotting_returns_png():
    png = plotting.time_series_png([0, 1, 2, 3], [[0, 1, 0, -1]], names=["vout"])
    assert png.startswith(b"\x89PNG")
    bode = plotting.frequency_png([10, 100, 1000], [([1, 0.5, 0.1], [0, -0.5, 0])])
    assert bode.startswith(b"\x89PNG")


def test_responses_from_result_handles_flat_and_nested():
    flat = plotting.responses_from_result({"Gr": [1, 2], "Gi": [0, 0]})
    assert flat == [([1, 2], [0, 0])]
    nested = plotting.responses_from_result({"Gr": [[1, 2]], "Gi": [[0, 0]]})
    assert nested == [([1, 2], [0, 0])]


# ---------------------------------------------------------------- checks

SIM = {"kind": "time-series", "time": {"points": 10, "start": 0, "stop": 0.001},
       "signals": [{"min": 0, "max": 12.5, "mean": 11.9, "rms": 12.0, "p2p": 12.5}]}
ANALYSIS = {"kind": "frequency-domain", "responses": [
    {"index": 0, "gain_crossover_hz": 5000, "phase_margin_deg": 47, "stable": True,
     "magnitude_db": {"min": -40, "max": 20}, "phase_deg": {"min": -180, "max": 0}},
]}


def test_checks_pass_and_fail():
    ok = checks.evaluate([
        {"type": "signal", "index": 0, "metric": "rms", "op": ">", "value": 10},
        {"type": "time", "metric": "stop", "op": ">=", "value": 1e-3},
        {"type": "analysis", "metric": "phase_margin_deg", "op": ">", "value": 45},
    ], SIM, ANALYSIS)
    assert ok["passed"] is True

    bad = checks.evaluate([{"type": "signal", "metric": "rms", "op": ">", "value": 100}], SIM, None)
    assert bad["passed"] is False
    assert bad["results"][0]["actual"] == 12.0


def test_checks_report_missing_inputs():
    result = checks.evaluate([{"type": "analysis", "metric": "phase_margin_deg", "op": ">", "value": 45}], SIM, None)
    assert result["passed"] is False
    assert "analysis results are required" in result["results"][0]["error"]


# ---------------------------------------------------------------- tasks

def test_task_registry_roundtrip(tmp_path: Path):
    registry = tasks.TaskRegistry(directory=tmp_path)
    record = registry.submit("demo", lambda: {"value": 42})
    deadline = time.time() + 5
    while time.time() < deadline and record.status == "running":
        time.sleep(0.01)
    assert record.status == "done"
    assert record.result == {"value": 42}
    assert registry.get(record.id) is not None


def test_task_registry_captures_errors(tmp_path: Path):
    registry = tasks.TaskRegistry(directory=tmp_path)
    record = registry.submit("boom", lambda: (_ for _ in ()).throw(RuntimeError("nope")))
    deadline = time.time() + 5
    while time.time() < deadline and record.status == "running":
        time.sleep(0.01)
    assert record.status == "error"
    assert record.error == "nope"


# ---------------------------------------------------------------- data / THD

def test_metrics_and_thd():
    import math

    t = [index / 10000 for index in range(10000)]
    signal = [math.sin(2 * math.pi * 50 * x) + 0.1 * math.sin(2 * math.pi * 150 * x) for x in t]
    metrics = data.metrics(signal)
    assert metrics["points"] == 10000
    assert abs(metrics["rms"] - 0.7071) < 0.05

    result = data.thd(t, signal, 50, harmonics=5)
    assert 8 < result["thd_percent"] < 12
    assert result["harmonics"][0]["order"] == 2


# ---------------------------------------------------------------- model ops

def test_scan_and_clone(tmp_path: Path):
    source = tmp_path / "m.plecs"
    source.write_text('Plecs {\n  Name          "old"\n  TimeSpan      "1e-2"\n}\n', encoding="utf-8")

    hits = modelops.scan_text(source, r"TimeSpan", ignore_case=False)
    assert hits["hits"][0]["line"] == 3

    target = tmp_path / "copy.plecs"
    meta = modelops.clone_model(
        source, target, name="new",
        replacements=[{"pattern": r'"1e-2"', "value": '"5e-3"'}],
    )
    assert meta["path"] == str(target.resolve())
    text = target.read_text(encoding="utf-8")
    assert '"new"' in text and '"5e-3"' in text


# ---------------------------------------------------------------- artifacts

def test_artifacts_listing(tmp_path: Path):
    (tmp_path / "a.c").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.h").write_text("y")
    listing = artifacts.list_artifacts(tmp_path)
    assert listing["count"] == 2
    assert listing["bytes"] == 2


def test_fmu_info_from_zip(tmp_path: Path):
    xml = """<?xml version="1.0"?>
    <fmiModelDescription fmiVersion="3.0" modelName="buck" guid="abc">
      <CoSimulation modelIdentifier="buck"/>
      <ModelVariables>
        <ScalarVariable name="u" valueReference="1"/>
        <ScalarVariable name="y" valueReference="2"/>
      </ModelVariables>
    </fmiModelDescription>"""
    fmu = tmp_path / "buck.fmu"
    with zipfile.ZipFile(fmu, "w") as archive:
        archive.writestr("modelDescription.xml", xml)
    info = artifacts.fmu_info(fmu)
    assert info["fmi_version"] == "3.0"
    assert info["model_name"] == "buck"
    assert info["interfaces"] == ["CoSimulation"]
    assert info["variable_count"] == 2


# ---------------------------------------------------------------- library

def test_library_flatten_and_search():
    tree = {
        "name": "Components", "kind": "circuit", "children": [
            {"kind": "subsystem", "name": "Electrical", "type": "Subsystem", "children": [
                {"kind": "component", "name": "Resistor", "type": "Resistor",
                 "children": [{"kind": "parameter", "name": "R"}, {"kind": "parameter", "name": "R_init"}]},
            ]},
            {"kind": "component", "name": "Scope", "type": "Scope", "children": []},
        ],
    }
    items = []
    library._flatten(tree, items)
    assert any(item["name"] == "Resistor" and "R" in item["parameters"] for item in items)
    assert [item["name"] for item in library.search(items, "resist")] == ["Resistor"]
    assert len(library.search(items, "")) == 3  # subsystem + component + scope


# ---------------------------------------------------------------- diagnose / resources

def test_diagnose_known_and_unknown():
    found = diagnose("Cannot find analysis named 'AC Sweep'.")
    assert found and found["kind"] == "analysis-name"
    assert diagnose("totally unrelated") is None
    assert "[analysis-name]" in with_hint("Cannot find analysis named 'x'")


def test_diagnose_connection_errors():
    found = diagnose("Cannot create connection to terminal 2 of 'model/Ctrl'.")
    assert found and found["kind"] == "connection-terminal"
    found = diagnose("Unconnected terminals overlapped by other elements were found.")
    assert found and found["kind"] == "unconnected-terminals"


def test_diagnose_cscript_compilation():
    message = "Error(s) in component 'leg_test/PWM' during compilation of 'Code declarations'."
    found = diagnose(message)
    assert found and found["kind"] == "cscript-compile"
    steps = " ".join(found["next_steps"])
    assert "plecs_get" in steps
    assert "Diagnostics" in steps
    assert "[cscript-compile]" in with_hint(message)


@pytest.mark.asyncio
async def test_docs_resources_are_served():
    async with Client(mcp) as client:
        resources = await client.list_resources()
        uris = {str(item.uri) for item in resources}
        assert "plecs://docs/rpc" in uris
        assert "plecs://docs/gotchas" in uris
        content = await client.read_resource("plecs://docs/rpc")
        gotchas = await client.read_resource("plecs://docs/gotchas")
        errors = await client.read_resource("plecs://docs/errors")
    text = content[0].text if hasattr(content[0], "text") else str(content[0])
    trap_text = gotchas[0].text if hasattr(gotchas[0], "text") else str(gotchas[0])
    error_text = errors[0].text if hasattr(errors[0], "text") else str(errors[0])
    assert "plecs.simulate" in text
    assert "getCursorData" in trap_text
    assert "C-Script compilation errors" in error_text
    assert "getCircuitBitmap" in trap_text
    assert "SaveTraces" in trap_text
    assert "ScriptName" in trap_text
