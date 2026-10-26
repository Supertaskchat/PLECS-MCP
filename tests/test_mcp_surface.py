import pytest
from fastmcp import Client

from plecs_mcp.server import mcp

EXPECTED = {
    "plecs_connect",
    "plecs_list_methods",
    "plecs_method_help",
    "plecs_statistics",
    "plecs_load",
    "plecs_close",
    "plecs_save",
    "plecs_get_model_tree",
    "plecs_get",
    "plecs_set",
    "plecs_simulate",
    "plecs_analyze",
    "plecs_scope",
    "plecs_webserver",
    "plecs_codegen",
    "plecs_export_fmu",
    "plecs_run_script",
    "plecs_compare",
    "plecs_extract_execution_log_data",
    "plecs_set_cosim_server_enabled",
    "plecs_sign",
    "plecs_protect",
    "plecs_crash",
    "plecs_rpc",
}


@pytest.mark.asyncio
async def test_all_rpc_methods_are_exposed():
    async with Client(mcp) as client:
        tools = await client.list_tools()
    names = {t.name for t in tools}
    assert names == EXPECTED


@pytest.mark.asyncio
async def test_tools_are_documented_and_typed():
    async with Client(mcp) as client:
        tools = await client.list_tools()
    for tool in tools:
        assert tool.description, f"{tool.name} has no description"
        schema = getattr(tool, "input_schema", None) or tool.inputSchema
        assert schema.get("type") == "object"


@pytest.mark.asyncio
async def test_destructive_tools_require_confirm():
    async with Client(mcp) as client:
        for name in ("plecs_protect", "plecs_crash"):
            result = await client.call_tool(name, {"subsystem_path": "x"} if name == "plecs_protect" else {}, raise_on_error=False)
            assert result.is_error
            assert "confirm=true" in result.content[0].text


@pytest.mark.asyncio
async def test_connect_returns_hints_when_unreachable(monkeypatch):
    from plecs_mcp.client import PlecsUnreachable

    class _StubClient:
        def __init__(self, *args, **kwargs):
            pass

        def call(self, *args, **kwargs):
            raise PlecsUnreachable("connection refused")

        def close(self):
            pass

    monkeypatch.setattr("plecs_mcp.server.PlecsClient", _StubClient)
    async with Client(mcp) as client:
        result = await client.call_tool("plecs_connect", {"auto_start": False})
    assert result.data["ok"] is False
    assert len(result.data["hints"]) >= 3


@pytest.mark.asyncio
async def test_connect_starts_plecs_when_unreachable(monkeypatch):
    from plecs_mcp import client as client_module
    from plecs_mcp.client import PlecsUnreachable

    class _FlakyClient:
        instances = []

        def __init__(self, *args, **kwargs):
            self.calls = 0
            _FlakyClient.instances.append(self)

        def call(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise PlecsUnreachable("connection refused")
            return {"version": [5, 0, 6, "build"], "models": [], "hasServerLicense": True}

        def close(self):
            pass

    saved = client_module._client
    monkeypatch.setattr("plecs_mcp.server.PlecsClient", _FlakyClient)
    monkeypatch.setattr("plecs_mcp.server.find_plecs_app", lambda *_a, **_k: __import__("pathlib").Path("/Applications/PLECS 5.0.app"))
    monkeypatch.setattr("plecs_mcp.server.launch_plecs", lambda app: {"ok": True, "app": str(app), "error": None})
    monkeypatch.setattr("plecs_mcp.server.wait_for_port", lambda *_a, **_k: 1.5)
    try:
        async with Client(mcp) as client:
            result = await client.call_tool("plecs_connect", {})
        assert result.data["ok"] is True
        assert result.data["started"] is True
        assert result.data["startup_seconds"] == 1.5
        assert result.data["version"] == "5.0.6"
        assert _FlakyClient.instances[0].calls == 2
    finally:
        client_module._client = saved


@pytest.mark.asyncio
async def test_connect_reports_missing_bundle(monkeypatch):
    from plecs_mcp import client as client_module
    from plecs_mcp.client import PlecsUnreachable

    class _StubClient:
        def __init__(self, *args, **kwargs):
            pass

        def call(self, *args, **kwargs):
            raise PlecsUnreachable("connection refused")

        def close(self):
            pass

    saved = client_module._client
    monkeypatch.setattr("plecs_mcp.server.PlecsClient", _StubClient)
    monkeypatch.setattr("plecs_mcp.server.find_plecs_app", lambda *_a, **_k: None)
    try:
        async with Client(mcp) as client:
            result = await client.call_tool("plecs_connect", {})
        assert result.data["ok"] is False
        assert result.data["launch"]["ok"] is False
        assert "PLECS_APP_PATH" in result.data["launch"]["error"]
    finally:
        client_module._client = saved
