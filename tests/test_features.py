import json
from pathlib import Path

import pytest
from fastmcp import Client

from plecs_mcp import server
from plecs_mcp.codec import parse_merged_items, slice_csv
from plecs_mcp.paths import PathNotAllowed, allowed_roots, check_writable
from plecs_mcp.session import STATE


@pytest.fixture(autouse=True)
def clean_session():
    saved = dict(STATE.models)
    STATE.models.clear()
    yield
    STATE.models.clear()
    STATE.models.update(saved)


# ---------------------------------------------------------------- paths

def test_write_guard_blocks_install_dirs():
    with pytest.raises(PathNotAllowed):
        check_writable("/Applications/PLECS 5.0.app/evil.plecs", overwrite=True)


def test_write_guard_blocks_outside_roots(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PLECS_MCP_ALLOWED_ROOTS", str(tmp_path))
    with pytest.raises(PathNotAllowed):
        check_writable("/tmp/outside.csv")


def test_write_guard_requires_overwrite(tmp_path: Path):
    target = tmp_path / "a.csv"
    target.write_text("x")
    with pytest.raises(PathNotAllowed):
        check_writable(target)
    assert check_writable(target, overwrite=True) == target


def test_default_roots_cover_home_and_temp():
    roots = [str(path) for path in allowed_roots()]
    assert any(root.startswith(str(Path.home())) for root in roots)


# ---------------------------------------------------------------- timeout / limits

def test_inject_timeout_keeps_user_value(monkeypatch):
    monkeypatch.setenv("PLECS_MCP_SIM_TIMEOUT", "42")
    assert server._inject_timeout({"SolverOpts": {"TimeSpan": 1e-3}}, None)["SolverOpts"]["Timeout"] == 42.0
    opts = server._inject_timeout({"SolverOpts": {"Timeout": 5}}, 99)
    assert opts["SolverOpts"]["Timeout"] == 5
    batch = server._inject_timeout([{}, {"ModelVars": {"a": 1}}], 7)
    assert [item["SolverOpts"]["Timeout"] for item in batch] == [7.0, 7.0]


def test_auto_limit_saves_large_results(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PLECS_MCP_OUTPUT_DIR", str(tmp_path))
    payload = {"Time": [0, 1, 2], "Values": [[1, 2, 3]]}
    result = server._auto_limit(payload, "mdl-simulation", summary=False, max_points=2)
    assert "summary" in result and result["summary"]["kind"] == "time-series"
    saved = Path(result["saved"]["path"])
    assert saved.is_file() and saved.parent == tmp_path.resolve()
    assert json.loads(saved.read_text())["Time"] == [0, 1, 2]


def test_auto_limit_respects_summary_flag(monkeypatch):
    monkeypatch.setenv("PLECS_MCP_OUTPUT_DIR", "/nonexistent")
    payload = {"Time": [0, 1], "Values": [[1, 2]]}
    result = server._auto_limit(payload, "x", summary=True, max_points=0)
    assert "saved" not in result
    assert result["summary"]["signals"][0]["max"] == 2


# ---------------------------------------------------------------- close guard

@pytest.mark.asyncio
async def test_close_refuses_session_dirty_model(monkeypatch):
    monkeypatch.setattr(server, "_call", lambda *a, **k: {"result": 0})
    STATE.loaded("mdl", "/tmp/mdl.plecs")
    STATE.mark_dirty("mdl/L1")
    async with Client(server.mcp) as client:
        refused = await client.call_tool("plecs_close", {"model_name": "mdl"}, raise_on_error=False)
        forced = await client.call_tool("plecs_close", {"model_name": "mdl", "force": True})
    assert refused.is_error
    assert "force=true" in refused.content[0].text
    assert forced.data["result"] == 0
    assert STATE.get("mdl") is None


# ---------------------------------------------------------------- batch / state space

@pytest.mark.asyncio
async def test_batch_runs_calls_and_reports_errors(monkeypatch):
    def fake_raw(method, params=None, timeout=None):
        if method == "boom":
            raise server.ToolError("nope")
        return {"method": method, "params": params}

    monkeypatch.setattr(server, "_raw", fake_raw)
    async with Client(server.mcp) as client:
        result = (await client.call_tool("plecs_batch", {"calls": [
            {"method": "plecs.get", "params": ["m/L1", "L"]},
            {"method": "boom"},
        ]})).data
    assert result["count"] == 2
    assert result["results"][0]["ok"] is True
    assert result["results"][1] == {"index": 1, "method": "boom", "ok": False, "error": "nope"}


@pytest.mark.asyncio
async def test_state_space_maps_switch_names(monkeypatch):
    calls = []

    def fake_raw(method, params=None, timeout=None):
        calls.append((method, params))
        if method == "plecs.get" and params[1] == "StateSpaceOrder":
            return {"Switches": ["mdl/FET", "mdl/D"]}
        if method == "plecs.get" and params[1] == "Topology":
            return {"A": [[1]]}
        return 0

    monkeypatch.setattr(server, "_raw", fake_raw)
    async with Client(server.mcp) as client:
        result = (await client.call_tool(
            "plecs_state_space", {"model_name": "mdl", "switches": {"FET": 1}}
        )).data
    assert result["switch_vector"] == [1, 0]
    assert result["topology"] == {"A": [[1]]}
    assert calls[1] == ("plecs.set", ["mdl", "SwitchVector", [1, 0]])


# ---------------------------------------------------------------- compare / csv

def test_parse_merged_items():
    lines = [
        "MergedItem(m, m2, Modification, Model File)",
        "  MergedItem(L1, L1, Modification, Inductor)",
        "  MergedItem(Name, Name, None, None)",
        "noise",
    ]
    entries = parse_merged_items(lines)
    assert len(entries) == 3
    assert entries[0]["change"] == "Modification"
    assert entries[1]["depth"] == 1 and entries[1]["type"] == "Inductor"


def test_slice_csv_applies_range_and_decimation():
    text = '"Time / s","sig"\n0,0\n1,1\n2,2\n3,3\n4,4\n'
    header, rows = slice_csv(text, time_range=[1, 3])
    assert header == ["Time / s", "sig"]
    assert rows == [["1", "1"], ["2", "2"], ["3", "3"]]

    _, decimated = slice_csv(text, decimate=2)
    assert decimated == [["0", "0"], ["2", "2"], ["4", "4"]]


def test_parse_merged_items_single_blob_with_newline_names():
    blob = (
        "MergedItem(m, m2, Modification, Model File)\n"
        "  MergedItem(PID\nController, PID\nController, None, Subsystem)\n"
        "  MergedItem(L1, L1, Modification, Inductor)\n"
    )
    entries = parse_merged_items([blob])
    assert [entry["type"] for entry in entries] == ["Model File", "Subsystem", "Inductor"]
    assert entries[1]["left"] == "PID\nController"
    assert entries[1]["depth"] == 1
