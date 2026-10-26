# PLECS-MCP

An MCP server that exposes the **complete Plexim PLECS Standalone JSON-RPC interface** as MCP tools, built on `fastmcp`.

- One MCP tool per RPC method, plus `plecs_rpc` as a raw escape hatch
- Blocking calls (simulate/analyze) are serialized globally, matching the PLECS "one blocking command" rule
- Handles PLECS base64 payloads automatically: model tree → JSON, scope CSV → text, bitmaps/MatFile → files
- Optional `summary=true` turns raw arrays into per-signal statistics or Bode margins
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
.venv/bin/python -m plecs_mcp                 # stdio (default, for local agents)
.venv/bin/python -m plecs_mcp --transport http --port 8765   # remote agents
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

Supported transports: `stdio` (default), `http`, `sse`, `streamable-http`.

## Quickstart (3 minutes)

With PLECS running and RPC enabled:

```bash
.venv/bin/python examples/quickstart.py --model /path/to/model.plecs
# include a small-signal analysis (uses the analysis Name property)
.venv/bin/python examples/quickstart.py --model /path/to/model.plecs \
    --analysis "Loop Gain (AC Sweep)"
```

The script performs `plecs_connect → plecs_load → plecs_simulate (summary) → plecs_close`
and prints per-signal `min/max/mean/rms` plus gain crossover and phase margin.
Without `--model` it falls back to `PLECS_EXAMPLE_MODEL` or a bundled PLECS demo.

## Configuration

Settings resolve in this order: **environment variables → `config.yml` → defaults**.
`config.yml` is looked up at `$PLECS_MCP_CONFIG`, then `./config.yml`, then the repo root.

```yaml
plecs:
  host: "127.0.0.1"
  port: 1080
  timeout: 30
```

| Variable | Default | Description |
|---|---|---|
| `PLECS_MCP_CONFIG` | – | Explicit path to `config.yml` |
| `PLECS_RPC_HOST` (or `PLECS_HOST`) | `127.0.0.1` | Localhost only (PLECS restriction) |
| `PLECS_RPC_PORT` (or `PLECS_PORT`) | `1080` | Must match the PLECS preference |
| `PLECS_RPC_TIMEOUT` | `30` | Read timeout in seconds for non-simulation calls |

## Tools

| Tool | RPC method | Notes |
|---|---|---|
| `plecs_connect` | `plecs.statistics` | Optional handshake: endpoint, version, open models, actionable hints |
| `plecs_list_methods` | `system.listMethods` | Capability discovery for the running build |
| `plecs_method_help` | `system.methodHelp` | PLECS's own help text |
| `plecs_statistics` | `plecs.statistics` | Licence hints, open models, run state |
| `plecs_load` | `plecs.load` | Absolute model path |
| `plecs_close` | `plecs.close` | Closes **without saving** |
| `plecs_save` | `plecs.save` | `save_as` renames the open model |
| `plecs_get_model_tree` | `plecs.getModelTree` | Decodes base64 JSON; `summary=true` returns names/counts only |
| `plecs_get` | `plecs.get` | Parameter value (string) or all parameters as a dict |
| `plecs_set` | `plecs.set` | Value is a PLECS expression string |
| `plecs_simulate` | `plecs.simulate` | One optStruct or a list (PLECS-native parallel); `summary=true` adds statistics |
| `plecs_analyze` | `plecs.analyze` | `analysis_name` is the Name property; `summary=true` adds fc/PM |
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

Every tool returns a JSON object, so MCP clients get structured content:

- dict results are returned as-is; scalars and arrays are wrapped as `{"result": ...}`
- `plecs_list_methods` → `{"methods": [...]}`, `plecs_compare` → `{"diff": [...]}`
- `plecs_connect` → `{"ok": true, ...}` or `{"ok": false, "hints": [...]}` (never raises)
- `plecs_simulate/plecs_analyze` with `summary=true` → `{"summary": {...}}`, e.g.:

```json
{"summary": {"kind": "time-series",
             "time": {"points": 418, "start": 0.0, "stop": 0.001},
             "signals": [{"min": 0, "max": 23.09, "mean": 4.14, "rms": 6.57, "p2p": 23.09}]}}
```

```json
{"summary": {"kind": "frequency-domain",
             "responses": [{"index": 0, "gain_crossover_hz": 5144.6,
                            "phase_margin_deg": 47.5, "stable": true}]}}
```

## Verified behaviour (PLECS 5.0.6)

1. `simulate` returns `Values` as **signals × time** over JSON-RPC (the manual's `m × n` wording is misleading); `summary=true` normalises both orientations.
2. A model without top-level outports returns `{"Time": [], "Values": []}` — not an error.
3. Only **nested** `{"SolverOpts": {"TimeSpan": ...}}` is honoured; a flat `{"StopTime": ...}` is silently ignored.
4. `analyze` needs the analysis **Name property**, not the tree node label (`AC Sweep` fails).
5. `plecs.scope` does **not** support `ExportCSV` / `GetCursorData` over RPC. Use `plecs_webserver` → `getScopeCsv`; this is an unofficial channel, so fall back to a top-level outport or a ToFile block if it ever breaks.
6. `plecs_webserver` ignores `TimeRange` / `Size` arguments — do range clipping client-side.
7. `plecs.save(model, save_as)` **renames** the open model; later calls must use the new name.
8. Business errors still return **HTTP 200**; the error lives in the JSON `error` field and is translated into a tool error.
9. The client uses `trust_env=False`: macOS system proxies can hijack `127.0.0.1:1080` and return HTTP 502, so PLECS is **never** reached through a proxy.

## Tests

```bash
.venv/bin/python -m pytest -q
```

- Unit: base64/model tree/file writing, summary maths, config precedence
- Surface: all 24 tools registered with descriptions; destructive tools require confirmation; `plecs_connect` degrades to hints
- Integration: when `127.0.0.1:1080` is reachable, runs `connect → load → tree → get → simulate (raw + summary) → scope CSV` on `/tmp` copies of the bundled demos (user models are never touched)

## Layout

```
src/plecs_mcp/client.py   JSON-RPC client (serialized calls, timeouts, error mapping, no proxy)
src/plecs_mcp/config.py   config.yml + environment resolution
src/plecs_mcp/codec.py    base64 decoding, model-tree summary, file output
src/plecs_mcp/summary.py  time-series statistics and Bode margins
src/plecs_mcp/server.py   24 MCP tools
examples/quickstart.py    end-to-end smoke test
tests/                    unit + surface + integration
```
