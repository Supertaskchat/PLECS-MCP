# PLECS-MCP

An MCP server that exposes the **complete Plexim PLECS Standalone JSON-RPC interface** as MCP tools, built on `fastmcp`.

- One MCP tool per RPC method, plus `plecs_rpc` as a raw escape hatch
- Blocking calls (simulate/analyze) are serialized globally, matching the PLECS "one blocking command" rule
- Handles PLECS base64 payloads automatically: model tree → JSON, scope CSV → text, bitmaps/MatFile → files
- Irreversible operations (`protect`, `crash`) require `confirm=true`

## Requirements

- PLECS Standalone running locally
- RPC enabled in **Preferences → RPC** (default port `1080`)
- Python 3.10+ (tested with 3.13)

## Install

```bash
cd "/Users/guohuawei/Workspace/AI Usecase/PLECS-MCP"
uv venv --python 3.13 .venv
uv pip install -e . --python .venv/bin/python
```

## Run

```bash
.venv/bin/python -m plecs_mcp        # stdio transport
# or
.venv/bin/plecs-mcp
```

Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.plecs]
command = "/Users/guohuawei/Workspace/AI Usecase/PLECS-MCP/.venv/bin/python"
args = ["-m", "plecs_mcp"]
```

Claude Desktop / Cursor (`mcpServers` JSON):

```json
{
  "mcpServers": {
    "plecs": {
      "command": "/Users/guohuawei/Workspace/AI Usecase/PLECS-MCP/.venv/bin/python",
      "args": ["-m", "plecs_mcp"]
    }
  }
}
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `PLECS_RPC_HOST` | `127.0.0.1` | Localhost only (PLECS restriction) |
| `PLECS_RPC_PORT` | `1080` | Must match the PLECS preference |
| `PLECS_RPC_TIMEOUT` | `30` | Read timeout in seconds for non-simulation calls |

## Tools

| Tool | RPC method | Notes |
|---|---|---|
| `plecs_list_methods` | `system.listMethods` | Capability discovery for the running build |
| `plecs_method_help` | `system.methodHelp` | PLECS's own help text |
| `plecs_statistics` | `plecs.statistics` | Licence hints, open models, run state |
| `plecs_load` | `plecs.load` | Absolute model path |
| `plecs_close` | `plecs.close` | Closes **without saving** |
| `plecs_save` | `plecs.save` | `save_as` renames the open model |
| `plecs_get_model_tree` | `plecs.getModelTree` | Decodes base64 JSON; `summary=true` returns names/counts only |
| `plecs_get` | `plecs.get` | Parameter value (string) or all parameters as a dict |
| `plecs_set` | `plecs.set` | Value is a PLECS expression string |
| `plecs_simulate` | `plecs.simulate` | Accepts one optStruct or a list (PLECS-native parallel sweep) |
| `plecs_analyze` | `plecs.analyze` | `analysis_name` is the Name property, e.g. `Loop Gain (AC Sweep)` |
| `plecs_scope` | `plecs.scope` | HoldTrace / RemoveTrace / ClearTraces / SaveTraces / LoadTraces |
| `plecs_webserver` | `plecs.webserver` | Undocumented channel: `getScopeCsv`, `getScopeBitmap`, `getCircuitBitmap`, … |
| `plecs_codegen` | `plecs.codegen` | Requires a PLECS Coder licence |
| `plecs_export_fmu` | `plecs.exportfmu` | Exports a subsystem as an FMU |
| `plecs_run_script` | `plecs.runScript` | Parameter shape unverified; override with `params` |
| `plecs_compare` | `plecs.compare` | Diff of two model files |
| `plecs_extract_execution_log_data` | `plecs.extractExecutionLogData` | Runtime counters (Jacobian/Newton/solver calls) |
| `plecs_set_cosim_server_enabled` | `plecs.setCoSimServerEnabled` | Global FMU co-simulation switch |
| `plecs_sign` | `plecs.sign` | Appends the demo signature (modifies the file) |
| `plecs_protect` | `plecs.protect` | Irreversible; requires `confirm=true` |
| `plecs_crash` | `plecs.crash` | Terminates PLECS; requires `confirm=true` |
| `plecs_rpc` | any | Raw passthrough |

### Return shape

Every tool returns a JSON object, so MCP clients get structured content. Dict results are returned as-is; scalars and arrays are wrapped as `{"result": ...}`. `plecs_list_methods` returns `{"methods": [...]}` and `plecs_compare` returns `{"diff": [...]}`.

## Verified behaviour (PLECS 5.0.6)

1. `simulate` returns `Values` as **signals × time** over JSON-RPC (the manual's `m × n` wording is misleading).
2. A model without top-level outports returns `{"Time": [], "Values": []}` — not an error.
3. `analyze` needs the analysis **Name property**, not the tree node label (`AC Sweep` fails).
4. `plecs.scope` does **not** support `ExportCSV` / `GetCursorData` over RPC. Use `plecs_webserver` → `getScopeCsv`; this is an unofficial channel, so fall back to a top-level outport or a ToFile block if it ever breaks.
5. `plecs_webserver` ignores `TimeRange` / `Size` arguments — do range clipping client-side.
6. `plecs.save(model, save_as)` **renames** the open model; later calls must use the new name.
7. Business errors still return **HTTP 200**; the error lives in the JSON `error` field and is translated into a tool error.
8. The client uses `trust_env=False`: macOS system proxies can hijack `127.0.0.1:1080` and return HTTP 502, so PLECS is **never** reached through a proxy.

## Tests

```bash
.venv/bin/python -m pytest -q
```

- Unit: base64/model tree/file writing
- Surface: all 23 tools registered with descriptions; destructive tools require confirmation
- Integration: when `127.0.0.1:1080` is reachable, runs `load → tree → get → simulate → scope CSV` on `/tmp` copies of the bundled demos (user models are never touched)

## Layout

```
src/plecs_mcp/client.py   JSON-RPC client (serialized calls, timeouts, error mapping, no proxy)
src/plecs_mcp/codec.py    base64 decoding, model-tree summary, file output
src/plecs_mcp/server.py   23 MCP tools
tests/                    unit + surface + integration
```
