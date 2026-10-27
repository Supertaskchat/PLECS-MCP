"""Integration tests against a locally running PLECS (skipped when RPC is closed)."""

import os
import shutil
import socket
from pathlib import Path

import pytest
from fastmcp import Client

from plecs_mcp.client import PlecsClient
from plecs_mcp.launcher import find_plecs_app
from plecs_mcp.server import mcp
from plecs_mcp.session import STATE


def _demo_root() -> Path | None:
    app = find_plecs_app()
    if app is None:
        return None
    for root in (app / "Contents" / "demos", app / "demos", app.parent / "demos"):
        if root.is_dir():
            return root
    return None


DEMOS = _demo_root()
LOOP_GAIN = (DEMOS / "buck_converter_with_loop_gain_analysis/buck_converter_with_loop_gain_analysis.plecs"
             if DEMOS else Path("/nonexistent/loop.plecs"))
WITH_OUTPORT = (DEMOS / "buck_converter_with_parameter_sweep/buck_converter_with_parameter_sweep.plecs"
                if DEMOS else Path("/nonexistent/out.plecs"))
FREQUENCY_RESPONSE = (DEMOS / "frequency_response_of_passive_circuit/frequency_response_of_passive_circuit.plecs"
                      if DEMOS else Path("/nonexistent/frequency_response.plecs"))


def _rpc_open() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(os.getenv("PLECS_RPC_PORT", "1080"))), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _rpc_open() or not LOOP_GAIN.exists() or not WITH_OUTPORT.exists(),
    reason="PLECS RPC not reachable or demo models missing",
)


@pytest.fixture()
def models(tmp_path):
    """Load two temp copies: one with analyses/scopes, one with a top-level outport.

    Function-scoped because PLECS 5.0.6 closes other open models during scope commands.
    """
    loop = tmp_path / "live_loop.plecs"
    out = tmp_path / "live_out.plecs"
    shutil.copy2(LOOP_GAIN, loop)
    shutil.copy2(WITH_OUTPORT, out)

    client = PlecsClient()
    for path in (loop, out):
        client.call("plecs.load", [str(path)])
        STATE.loaded(path.stem, str(path))
    yield {"loop": loop, "out": out}
    for path in (loop, out):
        try:
            client.call("plecs.close", [path.stem])
        except Exception:
            pass
        STATE.closed(path.stem)
    client.close()


@pytest.mark.asyncio
async def test_connect_reports_handshake():
    async with Client(mcp) as client:
        result = (await client.call_tool("plecs_connect", {})).data
    assert result["ok"] is True
    assert result["version"]
    assert result["started"] is False  # PLECS is already running for these tests


@pytest.mark.asyncio
async def test_statistics_and_method_list():
    async with Client(mcp) as client:
        stats = (await client.call_tool("plecs_statistics", {})).data
        methods = (await client.call_tool("plecs_list_methods", {})).data["methods"]
    assert "hasServerLicense" in stats
    assert "plecs.simulate" in methods


@pytest.mark.asyncio
async def test_ignores_system_proxies(monkeypatch):
    """macOS system proxies must not swallow localhost RPC calls."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    async with Client(mcp) as client:
        stats = (await client.call_tool("plecs_statistics", {})).data
    assert "hasServerLicense" in stats


@pytest.mark.asyncio
async def test_model_tree_and_params(models):
    loop = models["loop"]
    async with Client(mcp) as client:
        summary = (await client.call_tool("plecs_get_model_tree", {"model_path": str(loop), "summary": True})).data
        span = (await client.call_tool("plecs_get", {"path": loop.stem, "parameter": "TimeSpan"})).data
        tree = (await client.call_tool("plecs_get_model_tree", {"model_path": str(loop)})).data
    assert summary["analyses"], "expected analyses in the demo model"
    assert float(span["result"]) > 0
    assert tree["name"] == loop.stem


@pytest.mark.asyncio
async def test_simulate_returns_aligned_values(models):
    name = models["out"].stem
    async with Client(mcp) as client:
        sim = (await client.call_tool(
            "plecs_simulate", {"model_name": name, "options": {"SolverOpts": {"TimeSpan": 5e-4}}}
        )).data
    assert sim["Time"], "expected simulation data from a model with a top-level outport"
    assert all(len(signal) == len(sim["Time"]) for signal in sim["Values"])


@pytest.mark.asyncio
async def test_simulate_summary(models):
    name = models["out"].stem
    async with Client(mcp) as client:
        summary = (await client.call_tool(
            "plecs_simulate",
            {"model_name": name, "options": {"SolverOpts": {"TimeSpan": 5e-4}}, "summary": True},
        )).data["summary"]
    assert summary["kind"] == "time-series"
    assert summary["time"]["points"] > 0
    assert summary["signals"] and summary["signals"][0]["rms"] is not None


@pytest.mark.asyncio
async def test_scope_csv_export(models):
    name = models["loop"].stem
    async with Client(mcp) as client:
        await client.call_tool("plecs_simulate", {"model_name": name, "options": {"SolverOpts": {"TimeSpan": 1e-3}}})
        csv = (await client.call_tool(
            "plecs_webserver", {"command": "getScopeCsv", "arguments": [f"{name}/Scope"]}
        )).data["csv"]
    lines = csv.splitlines()
    assert lines[0].startswith('"Time / s"')
    assert len(lines) > 1


@pytest.mark.asyncio
async def test_run_script_with_real_demo(tmp_path):
    if not FREQUENCY_RESPONSE.is_file():
        pytest.skip("frequency_response demo missing")
    target = tmp_path / "run_script_demo.plecs"
    shutil.copy2(FREQUENCY_RESPONSE, target)
    name = target.stem
    async with Client(mcp) as client:
        loaded = await client.call_tool("plecs_load", {"model_path": str(target)})
        assert not loaded.is_error
        try:
            result = await client.call_tool(
                "plecs_run_script",
                {"model_name": name,
                 "script_name": "Sweep filter configuration with small-signal analysis"},
            )
            assert result.data["script_name"] == "Sweep filter configuration with small-signal analysis"
            assert result.data["result"] is None
        finally:
            await client.call_tool("plecs_close", {"model_name": name, "force": True})


@pytest.mark.asyncio
async def test_overview_and_validate(models):
    name = models["loop"].stem
    async with Client(mcp) as client:
        overview = (await client.call_tool("plecs_overview", {"model_name": name})).data
        validation = (await client.call_tool("plecs_validate", {"model_name": name})).data
    assert overview["path"].endswith(".plecs")
    assert overview["counts"]["component"] > 0
    assert validation["ok"] is True


@pytest.mark.asyncio
async def test_analyze_summary(models):
    name = models["loop"].stem
    async with Client(mcp) as client:
        analysis = (await client.call_tool(
            "plecs_analyze", {"model_name": name, "analysis_name": "Loop Gain (AC Sweep)", "summary": True}
        )).data["summary"]
    assert analysis["kind"] == "frequency-domain"
    assert analysis["responses"] and "magnitude_db" in analysis["responses"][0]


@pytest.mark.asyncio
async def test_capture_and_plot(models):
    name = models["loop"].stem
    async with Client(mcp) as client:
        capture = (await client.call_tool("plecs_capture", {"model_name": name, "inline": False})).data
        waveform = (await client.call_tool(
            "plecs_plot", {"model_name": name, "kind": "waveform", "inline": False}
        )).data
        bode = (await client.call_tool(
            "plecs_plot",
            {"model_name": name, "kind": "bode", "analysis_name": "Loop Gain (AC Sweep)", "inline": False},
        )).data
    assert capture["bytes"] > 1000
    assert waveform["renderer"] in ("plecs", "matplotlib") and waveform["bytes"] > 1000
    assert bode["renderer"] in ("plecs", "matplotlib") and bode["bytes"] > 1000


@pytest.mark.asyncio
async def test_webserver_bitmap_is_saved_not_inlined(monkeypatch, tmp_path, models):
    monkeypatch.setenv("PLECS_MCP_OUTPUT_DIR", str(tmp_path))
    name = models["loop"].stem
    async with Client(mcp) as client:
        await client.call_tool(
            "plecs_simulate", {"model_name": name, "options": {"SolverOpts": {"TimeSpan": 1e-3}}}
        )
        bitmap = (await client.call_tool(
            "plecs_webserver", {"command": "getScopeBitmap", "arguments": [f"{name}/Scope"]}
        )).data
    assert "iVBOR" not in str(bitmap)
    saved = Path(bitmap["saved"]["path"])
    assert saved.is_file() and saved.stat().st_size > 1000


@pytest.mark.asyncio
async def test_parameter_sweep_saves_list_and_analyze_data_reads_it(monkeypatch, tmp_path, models):
    monkeypatch.setenv("PLECS_MCP_OUTPUT_DIR", str(tmp_path))
    name = models["out"].stem
    async with Client(mcp) as client:
        sweep = (await client.call_tool(
            "plecs_simulate",
            {
                "model_name": name,
                "options": [
                    {"SolverOpts": {"TimeSpan": 2e-4}},
                    {"SolverOpts": {"TimeSpan": 3e-4}},
                ],
                "max_points": 1,
            },
        )).data
        analysed = (await client.call_tool("plecs_analyze_data", {"result_path": sweep["saved"]["path"]})).data
    assert analysed["kind"] == "parameter-sweep"
    assert analysed["count"] == 2


@pytest.mark.asyncio
async def test_check_passes_on_real_simulation(models):
    name = models["out"].stem
    async with Client(mcp) as client:
        result = (await client.call_tool(
            "plecs_check",
            {"model_name": name, "checks": [{"type": "time", "metric": "points", "op": ">", "value": 0}]},
        )).data
    assert result["passed"] is True


@pytest.mark.asyncio
async def test_compare_and_model_edit(tmp_path):
    first = tmp_path / "first.plecs"
    second = tmp_path / "second.plecs"
    shutil.copy2(WITH_OUTPORT, first)
    shutil.copy2(WITH_OUTPORT, second)
    edited = tmp_path / "edited.plecs"
    async with Client(mcp) as client:
        diff = (await client.call_tool("plecs_compare", {"before_path": str(first), "after_path": str(second)})).data
        edit = (await client.call_tool(
            "plecs_model_edit",
            {
                "path": str(first),
                "output": str(edited),
                "operations": [
                    {"op": "add_component", "type": "Resistor", "name": "R_probe",
                     "position": [900, 500], "parameters": {"R": "10"}}
                ],
                "validate": True,
            },
        )).data
    assert isinstance(diff["entries"], list)
    assert edit["validation"]["ok"] is True
    assert '"R_probe"' in edited.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_scope_save_traces_requires_simulation_data(models, tmp_path):
    name = models["loop"].stem
    async with Client(mcp) as client:
        result = await client.call_tool(
            "plecs_scope",
            {"scope_path": f"{name}/Scope", "command": "SaveTraces",
             "argument": str(tmp_path / "empty.trace")},
            raise_on_error=False,
        )
    assert result.is_error
    assert "no simulation data" in result.content[0].text


@pytest.mark.asyncio
async def test_webserver_cursor_and_circuit_bitmap(monkeypatch, tmp_path, models):
    monkeypatch.setenv("PLECS_MCP_OUTPUT_DIR", str(tmp_path))
    name = models["loop"].stem
    async with Client(mcp) as client:
        await client.call_tool(
            "plecs_simulate", {"model_name": name, "options": {"SolverOpts": {"TimeSpan": 1e-3}}}
        )
        circuit = (await client.call_tool(
            "plecs_webserver", {"command": "getCircuitBitmap", "arguments": [name]}
        )).data
        cursor = (await client.call_tool(
            "plecs_webserver", {"command": "getCursorData",
                                "arguments": [f"{name}/Scope", {"Index": 0}]}
        )).data
    assert "iVBOR" not in str(circuit)
    assert Path(circuit["saved"]["path"]).is_file()
    assert "cursorData" in cursor and "time" in cursor


@pytest.mark.asyncio
async def test_overview_includes_scripts(tmp_path):
    if not FREQUENCY_RESPONSE.is_file():
        pytest.skip("frequency_response demo missing")
    target = tmp_path / "overview_script.plecs"
    shutil.copy2(FREQUENCY_RESPONSE, target)
    name = target.stem
    async with Client(mcp) as client:
        loaded = await client.call_tool("plecs_load", {"model_path": str(target)})
        assert not loaded.is_error
        try:
            overview = (await client.call_tool("plecs_overview", {"model_name": name})).data
        finally:
            await client.call_tool("plecs_close", {"model_name": name, "force": True})
    assert "Sweep filter configuration with small-signal analysis" in overview["scripts"]
