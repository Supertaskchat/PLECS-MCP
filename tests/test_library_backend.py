from pathlib import Path

import pytest
from fastmcp import Client

from plecs_mcp import library_text, server

ITEMS = [
    {"type": "Resistor", "name": "R", "parameters": ["R"]},
    {"type": "Capacitor", "name": "C", "parameters": ["C"]},
]


def _text_ok(monkeypatch, items):
    monkeypatch.setattr(server.library_text_mod, "components_file", lambda *a, **k: Path("/x/Components.plecs"))
    monkeypatch.setattr(server.library_text_mod, "load_items", lambda *a, **k: items)


def _text_fails(monkeypatch, message="parse boom"):
    def boom(*args, **kwargs):
        raise library_text.LibraryParseError(message)

    monkeypatch.setattr(server.library_text_mod, "components_file", lambda *a, **k: Path("/x/Components.plecs"))
    monkeypatch.setattr(server.library_text_mod, "load_items", boom)


def _rpc_ok(monkeypatch, items=ITEMS):
    monkeypatch.setattr(server, "find_plecs_app", lambda *a, **k: Path("/Applications/PLECS 5.0.app"))
    monkeypatch.setattr(server.library_mod, "components_path", lambda app: Path("/x/Components.plecs"))
    monkeypatch.setattr(server.library_mod, "load_components", lambda path, fetch: items)


@pytest.mark.asyncio
async def test_text_backend_used_when_parse_succeeds(monkeypatch):
    _text_ok(monkeypatch, ITEMS)
    _rpc_ok(monkeypatch, items=[])  # must not be called
    async with Client(server.mcp) as client:
        result = (await client.call_tool("plecs_library_search", {"query": "resist"})).data
    assert result["backend"] == "text"
    assert result["count"] == 1
    assert "fallback_reason" not in result


@pytest.mark.asyncio
async def test_rpc_fallback_when_text_parse_fails(monkeypatch):
    _text_fails(monkeypatch, "parsed 0 components")
    _rpc_ok(monkeypatch)
    async with Client(server.mcp) as client:
        result = (await client.call_tool("plecs_library_search", {"query": "resist"})).data
    assert result["backend"] == "rpc"
    assert result["count"] == 1
    assert "parsed 0 components" in result["fallback_reason"]


@pytest.mark.asyncio
async def test_backend_rpc_skips_text(monkeypatch):
    _text_ok(monkeypatch, [])
    _rpc_ok(monkeypatch, items=ITEMS)
    async with Client(server.mcp) as client:
        result = (await client.call_tool("plecs_library_search", {"backend": "rpc"})).data
    assert result["backend"] == "rpc"
    assert result["total"] == 2


@pytest.mark.asyncio
async def test_backend_text_never_falls_back(monkeypatch):
    _text_fails(monkeypatch, "bad file")
    _rpc_ok(monkeypatch)
    async with Client(server.mcp) as client:
        result = await client.call_tool("plecs_library_search", {"backend": "text"}, raise_on_error=False)
    assert result.is_error
    assert "text library parse failed" in result.content[0].text


@pytest.mark.asyncio
async def test_both_backends_fail_reports_both(monkeypatch):
    _text_fails(monkeypatch, "text boom")

    def rpc_boom(*args, **kwargs):
        raise server.ToolError("rpc boom")

    monkeypatch.setattr(server, "find_plecs_app", lambda *a, **k: None)
    monkeypatch.setattr(server.library_mod, "components_path", lambda app: None)
    monkeypatch.setattr(server.library_mod, "load_components", rpc_boom)
    async with Client(server.mcp) as client:
        result = await client.call_tool("plecs_library_search", {}, raise_on_error=False)
    text = result.content[0].text
    assert result.is_error
    assert "text boom" in text and "rpc" in text


@pytest.mark.asyncio
async def test_rpc_fallback_starts_plecs_when_closed(monkeypatch):
    _text_fails(monkeypatch, "text boom")
    monkeypatch.setattr(server, "find_plecs_app", lambda *a, **k: Path("/Applications/PLECS 5.0.app"))
    monkeypatch.setattr(server.library_mod, "components_path", lambda app: Path("/x/Components.plecs"))
    monkeypatch.setattr(server.library_mod, "load_components", lambda path, fetch: ITEMS)

    calls = {"connect": 0}

    def fake_raw(method, params=None, timeout=None):
        raise server.ToolError("connection refused")

    def fake_connect(*args, **kwargs):
        calls["connect"] += 1
        return {"ok": True, "started": True}

    monkeypatch.setattr(server, "_raw", fake_raw)
    monkeypatch.setattr(server, "_connect_impl", fake_connect)

    async with Client(server.mcp) as client:
        result = (await client.call_tool("plecs_library_search", {})).data
    assert calls["connect"] == 1
    assert result["backend"] == "rpc"
    assert result["autostarted"] is True


@pytest.mark.asyncio
async def test_rpc_fallback_reports_when_pl_ecs_cannot_start(monkeypatch):
    _text_fails(monkeypatch, "text boom")
    monkeypatch.setattr(server, "_raw", lambda *a, **k: (_ for _ in ()).throw(server.ToolError("down")))
    monkeypatch.setattr(
        server, "_connect_impl", lambda *a, **k: {"ok": False, "error": "no PLECS installation was found"}
    )
    async with Client(server.mcp) as client:
        result = await client.call_tool("plecs_library_search", {}, raise_on_error=False)
    text = result.content[0].text
    assert result.is_error
    assert "text boom" in text
    assert "no PLECS installation was found" in text
