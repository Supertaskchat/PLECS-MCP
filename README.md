# PLECS-MCP

An MCP server that exposes the **complete Plexim PLECS Standalone JSON-RPC interface** as MCP tools, built on `fastmcp`.

Highlights:

- One MCP tool per RPC method (22/22 on PLECS 5.0.6), plus `plecs_rpc` and `plecs_batch` escape hatches
- `plecs_connect` starts PLECS automatically (macOS / Windows / Linux) when the RPC port is closed
- Results are structured JSON; big arrays are auto-written to disk instead of flooding the context
- Read-only RPC calls run concurrently with a simulation; blocking/mutating calls are serialized
- Write guardrails: install dirs are refused, stray paths need `PLECS_MCP_ALLOWED_ROOTS`, overwrites need `overwrite=true`
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
.venv/bin/python -m plecs_mcp                                   # stdio (local agents)
.venv/bin/python -m plecs_mcp --transport http --port 8765      # remote agents
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

Transports: `stdio` (default), `http`, `sse`, `streamable-http`.
Binding a non-loopback host is refused unless `PLECS_MCP_ALLOW_REMOTE=1` is set (there is no auth).

## Quickstart (3 minutes)

```bash
.venv/bin/python examples/quickstart.py --model /path/to/model.plecs
.venv/bin/python examples/quickstart.py --model /path/to/model.plecs \
    --analysis "Loop Gain (AC Sweep)"
```

Runs `connect → load → simulate (summary) → close`, prints per-signal `min/max/mean/rms` and,
for AC sweeps, gain crossover + phase margin. Without `--model` it uses `PLECS_EXAMPLE_MODEL`
or a bundled PLECS demo.

## Configuration

Resolution order: **environment variables → `config.yml` → defaults**.
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
| `PLECS_RPC_TIMEOUT` | `30` | Read timeout for non-simulation calls |
| `PLECS_MCP_SIM_TIMEOUT` | `600` | `SolverOpts.Timeout` injected into simulate/analyze |
| `PLECS_MCP_MAX_INLINE_POINTS` | `20000` | Above this, results are saved and summarised |
| `PLECS_MCP_MAX_CSV_ROWS` | `50000` | Above this, scope CSV is saved and summarised |
| `PLECS_MCP_OUTPUT_DIR` | `~/.plecs-mcp/out` | Destination for auto-saved results |
| `PLECS_MCP_ALLOWED_ROOTS` | `~`, `/tmp`, system temp | Write roots (`:`-separated) |
| `PLECS_MCP_LOG_LEVEL` | `INFO` | RPC timing/error logging on stderr |
| `PLECS_MCP_ALLOW_REMOTE` | – | Allow non-loopback HTTP bind |
| `PLECS_EXECUTABLE` | auto-detect | PLECS binary/bundle used by auto-start (alias: `PLECS_APP_PATH`) |

## Auto-start

`plecs_connect(auto_start=True)` (default) probes `host:port`; if the port is closed it locates
the newest install **for the host OS**, launches it, and polls the port for `startup_timeout`
(default 30 s):

| Host | Discovery | Command |
|---|---|---|
| macOS | `/Applications/PLECS*.app`, `~/Applications` | `open -a <bundle>` |
| Windows | `%ProgramFiles%\Plexim\*\plecs.exe`, `%LOCALAPPDATA%` | spawn `plecs.exe` |
| Linux | `plecs` on `PATH`, `/opt/plecs*/plecs`, `/usr/local` | spawn `plecs` |

Before launching it checks whether a PLECS process already exists (`pgrep` / `tasklist`); if so it
skips the launch and tells you to enable Preferences → RPC instead of waiting 30 s.
Overrides: the `app_path` argument, `PLECS_EXECUTABLE`, `PLECS_APP_PATH`.
PLECS RPC is localhost-only, so the MCP server and PLECS must run on the same machine.

## Tools

| Tool | RPC method | Notes |
|---|---|---|
| `plecs_connect` | `plecs.statistics` | Handshake; auto-starts PLECS, returns version + `capabilities` |
| `plecs_list_methods` | `system.listMethods` | Capability discovery |
| `plecs_method_help` | `system.methodHelp` | PLECS help text |
| `plecs_statistics` | `plecs.statistics` | Licence hints, open models, run state |
| `plecs_load` | `plecs.load` | Returns `model_name` and records the path |
| `plecs_close` | `plecs.close` | Refuses when this session changed the model (`force=true` to discard) |
| `plecs_save` | `plecs.save` | `save_as` renames the model; existing target needs `overwrite=true` |
| `plecs_get_model_tree` | `plecs.getModelTree` | Base64 JSON → parsed; `summary=true` for names/counts |
| `plecs_get` | `plecs.get` | Parameter value (string) or all parameters |
| `plecs_set` | `plecs.set` | Expression string; marks the model dirty |
| `plecs_simulate` | `plecs.simulate` | optStruct or list; `summary`, `max_points`, `save_to` |
| `plecs_analyze` | `plecs.analyze` | Name property; `summary` adds dB/deg, fc, PM |
| `plecs_state_space` | `get StateSpaceOrder` + `set SwitchVector` + `get Topology` | Switch vector built from `{"FET": 1}` |
| `plecs_scope` | `plecs.scope` | HoldTrace / RemoveTrace / ClearTraces / SaveTraces / LoadTraces |
| `plecs_webserver` | `plecs.webserver` | `getScopeCsv` / `getScopeBitmap` / `getCircuitBitmap` …; CSV slicing |
| `plecs_codegen` | `plecs.codegen` | Requires Coder; diagnostics are surfaced verbatim |
| `plecs_export_fmu` | `plecs.exportfmu` | Atomic subsystems only |
| `plecs_run_script` | `plecs.runScript` | **Experimental**: wire shape unknown on 5.0.6 |
| `plecs_compare` | `plecs.compare` | Raw lines + parsed `entries` |
| `plecs_extract_execution_log_data` | `plecs.extractExecutionLogData` | Runtime counters |
| `plecs_set_cosim_server_enabled` | `plecs.setCoSimServerEnabled` | Global FMU co-simulation switch |
| `plecs_sign` | `plecs.sign` | Appends the demo signature (modifies the file) |
| `plecs_protect` | `plecs.protect` | Irreversible once saved; `confirm=true` |
| `plecs_crash` | `plecs.crash` | Terminates PLECS; `confirm=true` |
| `plecs_batch` | any | Several RPC calls in one tool call, per-call errors inline |
| `plecs_rpc` | any | Raw passthrough |

### Return shape

Every tool returns a JSON object (structured content):

- dict results as-is; scalars/arrays wrapped as `{"result": ...}`
- `plecs_list_methods` → `{"methods": [...]}`; `plecs_compare` → `{"diff": [...], "entries": [...]}`
- `plecs_connect` → `{"ok": true, "capabilities": {...}, ...}` or `{"ok": false, "hints": [...]}`
- `plecs_batch` → `{"count": n, "results": [{"ok": ..., "result"|"error": ...}]}`

## Data policy (large results)

| Situation | Behaviour |
|---|---|
| Simulation above `max_points` | Full JSON saved under `PLECS_MCP_OUTPUT_DIR`, response contains `summary` + `saved` + `note` |
| `summary=true` | Raw arrays replaced by `min/max/mean/p2p/rms`, plus `outports` names/positions |
| Scope CSV above `max_rows` | Full CSV saved, response has `columns`, `rows`, `saved`, 5-row `preview` |
| `time_range` / `decimate` | Applied client-side (PLECS ignores its own range options) |
| `OutputFormat=MatFile` | Base64 MAT decoded and written to `save_to` (or refused for unsafe paths) |
| PNG payloads | Written to `save_to`; never inlined |

Writes are refused inside `/Applications`, `/System`, `/Library`, `/usr`, `/bin`, `/sbin`, `/etc`,
and outside `PLECS_MCP_ALLOWED_ROOTS`. Existing files are never overwritten without `overwrite=true`.

## Concurrency

Measured on PLECS 5.0.6: `statistics` returns in **0.01 s while a 0.55 s simulation is running**,
and a second `simulate` still waits for the first. The client mirrors that:

- read-only calls share a read lock and run concurrently with a simulation
- `simulate/analyze/codegen/exportfmu/runScript` take a single "blocking" slot (PLECS allows one)
- `load/close/save/set/scope/protect` take the exclusive write lock, so state never changes mid-run

## Verified behaviour (PLECS 5.0.6)

1. `simulate` returns `Values` as **signals × time** over JSON-RPC; summaries normalise both orientations.
2. Models without top-level outports return `{"Time": [], "Values": []}` and a summary `note`.
3. Only nested `{"SolverOpts": {"TimeSpan": ...}}` is honoured; flat `{"StopTime": ...}` is silently ignored.
4. `SolverOpts.Timeout` works for **both** `simulate` and `analyze`; `AnalysisOpts.Timeout` is rejected.
5. `analyze` needs the analysis **Name property**; `plecs.scope` supports no `ExportCSV`/`GetCursorData`.
6. `plecs.webserver` ignores `TimeRange`/`Size`; slicing and decimation happen in this server.
7. `plecs.save(model, save_as)` **renames** the open model; the session registry follows the rename.
8. `plecs.protect(path)` takes one subsystem path, returns 0, is idempotent, and only becomes permanent on save.
9. `plecs.exportfmu(path)` accepts one path and requires an **atomic** subsystem.
10. `plecs.codegen(model)` runs and returns Coder diagnostics as an RPC error string.
11. `plecs.runScript` is listed by `system.listMethods` but every wire shape tried returns
    `server error: invalid method parameters` — kept as experimental with a `params` override.
12. Business errors still return **HTTP 200**; the JSON `error` field becomes a tool error.
13. `trust_env=False`: macOS system proxies can hijack `127.0.0.1:1080` (HTTP 502), so PLECS is never
    reached through a proxy.

## Known limitations

- The RPC model tree exposes outport **names and positions but no port index**, so channel `i` is not
  auto-labelled; `summary.outports` is provided instead of guessing.
- `.trace` files (`scope SaveTraces`) use a private format and are not parsed.
- Gain crossover/phase margin only make sense for loop-gain AC sweeps; other analysis kinds are labelled.
- Auto-start picks the newest install for the **host** OS: macOS `/Applications/PLECS*.app`,
  Windows `%ProgramFiles%\Plexim\*\plecs.exe`, Linux `plecs` on `PATH` or `/opt/plecs*/plecs`.
  Other platforms return `unsupported-platform` and require a manual start.
- One MCP server instance manages one PLECS instance (localhost).

## Example workflows

```text
# parameter sweep (PLECS-native parallel)
plecs_simulate(model, options=[{"ModelVars": {"R": 10}}, {"ModelVars": {"R": 47}}], summary=True)

# Bode / loop gain
plecs_analyze(model, "Loop Gain (AC Sweep)", summary=True)
# → responses[0].gain_crossover_hz / phase_margin_deg / stable

# scope export with client-side slicing
plecs_webserver("getScopeCsv", [f"{model}/Scope"], time_range=[0, 1e-3], decimate=10)

# state space at one switch combination
plecs_state_space(model, {"FET": 1, "D": 0})

# cheap multi-read
plecs_batch([{"method": "plecs.get", "params": [f"{model}/L1", "L"]},
             {"method": "plecs.get", "params": [f"{model}/C1", "C"]}])
```

## Error table

| Symptom | Meaning | Next step |
|---|---|---|
| `cannot reach PLECS …` | RPC port closed | Run `plecs_connect` (auto-start) or enable Preferences → RPC |
| `-32601` | Method missing in this build | `plecs_list_methods` |
| `-32602` | Invalid parameters | Check the tool schema; for `runScript` pass `params` |
| `-32500 … Cannot find analysis named` | Wrong analysis name | Use the Name property from `plecs_get_model_tree` |
| `-32500 … Invalid scope command` | Unsupported scope command | Use `plecs_webserver getScopeCsv` |
| `HTTP 502` | A proxy intercepted localhost | Client already uses `trust_env=False`; check the environment |
| `refusing to overwrite` | File exists | Pass `overwrite=true` (and confirm it is safe) |
| `outside PLECS_MCP_ALLOWED_ROOTS` | Write blocked | Choose a path under `~`, temp, or `PLECS_MCP_OUTPUT_DIR` |

## Tests

```bash
.venv/bin/python -m pytest -q      # 50 tests
```

- Unit: base64/model tree, summary maths, config precedence, paths, locks, app discovery/launch
- Surface: all 26 tools registered/documented; destructive tools need confirmation; batch/limits/guards
- Integration: when `127.0.0.1:1080` is reachable, exercises connect/load/tree/get/simulate/summary/CSV
  on `/tmp` copies of the bundled demos (user models are never touched)

CI (`.github/workflows/ci.yml`) runs the unit/surface suite on Python 3.10 and 3.13; integration tests
skip automatically when PLECS is not installed.

## Layout

```
src/plecs_mcp/client.py    JSON-RPC client (RW lock, timeouts, logging, no proxy)
src/plecs_mcp/config.py    config.yml + environment resolution
src/plecs_mcp/paths.py     write guardrails and output directories
src/plecs_mcp/session.py   model registry (path, dirty flag, rename tracking)
src/plecs_mcp/codec.py     base64 decoding, tree/compare parsing, CSV slicing
src/plecs_mcp/summary.py   time-series statistics, Bode margins, analysis kinds
src/plecs_mcp/launcher.py  per-OS discovery/launch, port polling, process check
src/plecs_mcp/server.py    26 MCP tools
examples/quickstart.py     end-to-end smoke test
tests/                     unit + surface + integration
```
