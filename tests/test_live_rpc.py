"""Integration tests against a locally running PLECS (skipped when RPC is closed)."""

import os
import shutil
import socket
from pathlib import Path

import pytest
from fastmcp import Client

from plecs_mcp.client import PlecsClient
from plecs_mcp.server import mcp

DEMOS = Path("/Applications/PLECS 5.0.app/Contents/demos")
LOOP_GAIN = DEMOS / "buck_converter_with_loop_gain_analysis/buck_converter_with_loop_gain_analysis.plecs"
WITH_OUTPORT = DEMOS / "buck_converter_with_parameter_sweep/buck_converter_with_parameter_sweep.plecs"


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


@pytest.fixture(scope="module")
def models(tmp_path_factory):
    """Load two temp copies: one with analyses/scopes, one with a top-level outport."""
    root = tmp_path_factory.mktemp("models")
    loop = root / "live_loop.plecs"
    out = root / "live_out.plecs"
    shutil.copy2(LOOP_GAIN, loop)
    shutil.copy2(WITH_OUTPORT, out)

    client = PlecsClient()
    for path in (loop, out):
        client.call("plecs.load", [str(path)])
    yield {"loop": loop, "out": out}
    for path in (loop, out):
        try:
            client.call("plecs.close", [path.stem])
        except Exception:
            pass
    client.close()


@pytest.mark.asyncio
async def test_connect_reports_handshake():
    async with Client(mcp) as client:
        result = (await client.call_tool("plecs_connect", {})).data
    assert result["ok"] is True
    assert result["version"]


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
