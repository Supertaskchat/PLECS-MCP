import pytest
from fastmcp import Client

from plecs_mcp.server import mcp

EXPECTED = {
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
