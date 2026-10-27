# PLECS-MCP

An MCP server that exposes the **complete Plexim PLECS Standalone JSON-RPC interface** as MCP tools, built on `fastmcp`.

Highlights:

- One MCP tool per RPC method (22/22 on PLECS 5.0.6), plus `plecs_rpc` and `plecs_batch` escape hatches
- `plecs_run_script` is verified: `[model, {"ScriptName": name}]`; script names are listed by `plecs_overview`
- `plecs_validate` now runs a static connection graph check: missing components, subsystem ports,
  C-Script terminal ranges, top-level Output indices and C-Script code indices
- Argument preflight and `plecs://docs/gotchas` return corrected shapes for common mistakes instead of
  leaving the agent to guess
- `plecs_connect` starts PLECS automatically (macOS / Windows / Linux) when the RPC port is closed
- Results are structured JSON; big arrays are auto-written to disk instead of flooding the context
- Read-only RPC calls run concurrently with a simulation; blocking/mutating calls are serialized
- Write guardrails: install dirs are refused, stray paths need `PLECS_MCP_ALLOWED_ROOTS`, overwrites need `overwrite=true`
- Irreversible operations (`protect`, `crash`) require `confirm=true`
- MCP **resources** ship the RPC/analysis/error references the agent needs
- `plecs_capture` / `plecs_plot` return **inline PNG images**; raw `plecs_webserver` bitmaps are saved to disk
- Async tasks (`submit`/`task`/`task_result`), acceptance checks, component-library search,
  file-level model cloning and local FFT/THD post-processing

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
| `PLECS_MCP_AUTO_START` | `always` | Default for `plecs_connect` (`always` / `never`) |
| `PLECS_EXECUTABLE` | auto-detect | PLECS binary/bundle used by auto-start (alias: `PLECS_APP_PATH`) |
| `PLECS_LIBRARY_PATH` | auto-detect | Explicit `Components.plecs` for offline library search |

## Auto-start

`plecs_connect(auto_start=True)` (default, configurable with `PLECS_MCP_AUTO_START=never` or
`--auto-start never`) probes `host:port`; if the port is closed it locates
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
| `plecs_scope` | `plecs.scope` | HoldTrace / RemoveTrace / ClearTraces / SaveTraces / LoadTraces (simulate before SaveTraces) |
| `plecs_webserver` | `plecs.webserver` | `getScopeCsv` / `getScopeBitmap` / `getCircuitBitmap` …; CSV slicing; images auto-saved (never inline) |
| `plecs_codegen` | `plecs.codegen` | Requires Coder; diagnostics are surfaced verbatim |
| `plecs_export_fmu` | `plecs.exportfmu` | Atomic subsystems only |
| `plecs_run_script` | `plecs.runScript` | **Verified**: `[model, {"ScriptName": name}]`; returns null, output goes to the PLECS console |
| `plecs_compare` | `plecs.compare` | Raw lines + parsed `entries` |
| `plecs_extract_execution_log_data` | `plecs.extractExecutionLogData` | Runtime counters |
| `plecs_set_cosim_server_enabled` | `plecs.setCoSimServerEnabled` | Global FMU co-simulation switch |
| `plecs_sign` | `plecs.sign` | Appends the demo signature (modifies the file) |
| `plecs_protect` | `plecs.protect` | Irreversible once saved; `confirm=true` |
| `plecs_crash` | `plecs.crash` | Terminates PLECS; `confirm=true` |
| `plecs_batch` | any | Several RPC calls in one tool call, per-call errors inline |
| `plecs_overview` | tree + get + statistics | One-call model briefing (solver, analyses, scopes, outports, scripts) |
| `plecs_validate` | tree + get + `.plecs` graph | Structural and connection pre-flight checks (errors/warnings/diagnostics) |
| `plecs_layout_check` | `webserver getCircuitBitmap` | Geometry: overlapping component boxes, diagonal wires, wires drawn across a device |
| `plecs_capture` | `webserver getScopeBitmap` | Scope screenshot as an **inline PNG** |
| `plecs_plot` | simulate / analyze | Waveform or Bode PNG — **PLECS bitmap by default**, matplotlib fallback |
| `plecs_submit` / `plecs_task` / `plecs_task_result` / `plecs_tasks` | simulate/analyze/codegen | Background tasks with polling |
| `plecs_check` | simulate + analyze | Pass/fail assertions (signal/time/analysis metrics) |
| `plecs_library_search` | `getModelTree(Components.plecs)` | Search the installed component library |
| `plecs_scan` | – | Regex-search a `.plecs` file without opening it |
| `plecs_model_clone` | – | Copy/rename/patch a model file, then load-validate |
| `plecs_model_edit` | – | Structural edits: add/remove component, set parameter, rotate/move, wire, add outport |
| `plecs_artifacts` | – | List codegen/FMU output files |
| `plecs_fmu_info` | – | Read `modelDescription.xml` from an FMU |
| `plecs_analyze_data` | – | Metrics + FFT/THD on a saved JSON result |
| `plecs_diagnose` | – | Explain a PLECS error string |
| `plecs_instances` | – | Known endpoints, active one flagged |
| `plecs_rpc` | any | Raw passthrough |

### Return shape

Most tools return a JSON object (structured content). `plecs_capture` and `plecs_plot` return MCP
image content when `inline=true` (the default) and JSON metadata when `inline=false`:

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
| PNG payloads | Written to `save_to`; without it, auto-saved under `PLECS_MCP_OUTPUT_DIR`; never inlined |
| `getScopeSignals` images | Nested base64 bitmaps are saved as `<save_to>-1.png`, `-2.png`, … (or auto-saved) |

MCP-mediated writes are refused inside `/Applications`, `/System`, `/Library`, `/usr`, `/bin`,
`/sbin`, `/etc`, and outside `PLECS_MCP_ALLOWED_ROOTS`. Existing files are never overwritten
without `overwrite=true`. PLECS-side outputs (FMU export) follow the path configured in the model.

## MCP resources

The server exposes reference documents as MCP resources (no tool call needed):

| URI | Content |
|---|---|
| `plecs://docs/quickstart` | end-to-end workflow |
| `plecs://docs/rpc` | RPC method table and quirks |
| `plecs://docs/analysis` | SolverOpts/ModelVars/analysis result shapes |
| `plecs://docs/errors` | symptom → cause → next step |
| `plecs://docs/limits` | data policy and write guardrails |
| `plecs://docs/gotchas` | exact argument shapes and common traps |

## Images and plots

- `plecs_capture(model[, scope|analysis_name])` returns the PLECS scope/analysis bitmap as an MCP image.
- `plecs_plot(..., renderer="auto")` — **default: PLECS-rendered bitmap** (same styling as the GUI).
  `renderer="plecs"` forces it (error if no Scope/analysis plot exists);
  `renderer="matplotlib"` renders locally and is the only way to overlay several responses.
- Waveform: runs a short simulation (default TimeSpan 1e-3 s); `renderer="plecs"` captures the model Scope,
  `matplotlib` plots the top-level outports (requires at least one).
- Bode: runs `plecs.analyze` then captures `<model>/Analyses/<Name property>`; matplotlib uses `F/Gr/Gi`.
- Both accept `save_to` (write a PNG) and `inline=false` (metadata: `renderer`, `bytes`).

## Async tasks

`plecs_submit("plecs.simulate", [model, opts])` returns `{id, status}`; poll with
`plecs_task(id)` and fetch with `plecs_task_result(id)`. Only blocking methods are accepted, PLECS
still runs one at a time, and large results are stored as summary + file path.

Task records are persisted to `PLECS_MCP_TASK_DIR` (default `~/.plecs-mcp/tasks`). After a server
restart, finished tasks are still readable and anything that was running is reported as `lost`
instead of pretending to be in progress.

## Acceptance checks

`plecs_check(model, checks, options=..., analysis_name=...)` runs the needed simulation/analysis
and evaluates assertions:

```json
[{"type": "signal", "index": 0, "metric": "rms", "op": ">", "value": 10},
 {"type": "time",   "metric": "stop", "op": ">=", "value": 0.001},
 {"type": "analysis", "metric": "phase_margin_deg", "op": ">", "value": 45}]
```

The response contains `passed`, per-check `actual`/`pass`, and the summaries used.

## Discovery and file-level editing

- `plecs_library_search("resistor")` parses the installed `Components.plecs` **as text** (≈9.7k
  components, 0.6 s cold / 5 ms cached) — works without PLECS and without the 43 MB RPC tree.
  `Components.plecs` is located next to a macOS `.app` bundle or a Windows/Linux install binary
  (`PLECS_LIBRARY_PATH` overrides discovery).
  Cache lives next to the output dir; `refresh=true` rebuilds it.
  `backend="auto"` (default) keeps the RPC model tree as a **fallback**: if the file is missing,
  unreadable, corrupt, or yields 0 components, the call ensures a PLECS connection first —
  **starting PLECS automatically** when it is not running (same policy as `plecs_connect`) —
  then retries over RPC and reports `backend="rpc"`, `fallback_reason` and `autostarted`.
  If PLECS is not installed (or its RPC preference is off), the error says so.
  Use `backend="text"` or `"rpc"` to force one path.
- `plecs_scan(path, "TimeSpan")` greps model text without loading it.
- `plecs_model_edit(path, operations, confirm|output)` performs **structural** edits on a copy of a
  `.plecs` file: add/remove components, set parameters, wire terminals, add outports. Everything
  outside the edited span stays byte-identical (including CRLF line endings); the result is loaded
  in PLECS to verify. In-place edits obey the normal write policy and create a `.bak-<ms>` backup.
  This is the alternative to schematic editing, which the RPC does not expose.
- `plecs_model_clone(...)` remains for copy + regex-level rewrites.
- `plecs_artifacts(dir)` / `plecs_fmu_info(path)` inspect codegen output and FMU metadata.

## Local post-processing

`plecs_analyze_data(result_path, fundamental=50)` works on a saved JSON result (the ones written
by the inline-point limit): per-signal metrics plus FFT-based THD and harmonic amplitudes. Parameter
sweeps are saved as a JSON list and are summarised per entry. This covers the "arbitrary code
execution" gap without touching PLECS' console.

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
11. `plecs.runScript(model, {"ScriptName": name})` works; the second argument is an
    **optStruct**, not a bare string. A successful run returns `null` and the script's output
    goes to the PLECS console/Octave log. The script name is the `Name` of a `Script { ... }`
    block in the `.plecs` file (see demos such as `buck_converter_with_parameter_sweep`).
12. Business errors still return **HTTP 200**; the JSON `error` field becomes a tool error.
13. `trust_env=False`: macOS system proxies can hijack `127.0.0.1:1080` (HTTP 502), so PLECS is never
    reached through a proxy.

## Known limitations

- The RPC model tree exposes outport **names and positions but no port index**, so channel `i` is not
  auto-labelled; `summary.outports` is provided instead of guessing.
- `.trace` files (`scope SaveTraces`) use a private format and are not parsed.
- `plecs.runScript` returns `null`; the script's printed output goes to the PLECS console/Octave
  log and is not captured by the RPC response. Scripts that call `plecs('scope', ...)` internally
  can close other open models; `plecs_run_script` snapshots and reports them as `closed_models`.
- Script names are **not** exposed by `getModelTree`; read the `Script { Name "..." }` block in the
  `.plecs` file (or search it with `plecs_scan`) before calling `plecs_run_script`.
- All JSON-RPC error messages are forwarded **verbatim** (including multi-line text and any
  `error.data`); MCP does not truncate them. C-Script compilation errors are special only because
  PLECS itself sends a **summary** (component + phase); full Clang details are only in the PLECS
  Diagnostics dialog. Use `plecs_get(model/component)` to inspect the code segments and
  `plecs_diagnose` for next steps, or ask the user for the Diagnostics contents.
- `plecs_validate` graph checks are static: they cover component references, subsystem ports,
  C-Script port/code indices and top-level Output indices. Built-in component terminal counts are
  not available in `.plecs`, so PLECS Diagnostics remains authoritative for those cases.
- `plecs_layout_check` uses the bounding box per component that `getCircuitBitmap` returns, plus
  `Position`/`Points` from the text. It reports `LAYOUT-001` (error: two component boxes
  intersect), `LAYOUT-002` (warning: diagonal wire segment) and `LAYOUT-003` (info: a wire drawn
  across a device). Crossings are cosmetic - PLECS connects only through explicit connections -
  and overlay blocks (`HeatSink`, `Goto`, `From`) are excluded because PLECS ships demos that
  draw them on top of devices. The implicit last hop from a corner to a terminal is not checked.
- `plecs_webserver` command arguments differ: `getScope*` take a scope path, `getCircuitBitmap`
  takes the **model name**, and `getCursorData` takes `[scope, {"Index": 0}]` (a bare integer is
  rejected). `plecs_scope("SaveTraces", ...)` requires simulation data in the scope; a scope that
  has never simulated writes a `.trace` file that `LoadTraces` rejects. Run a simulation first
  (`HoldTrace` alone does not create data). See `plecs://docs/gotchas`.
- PLECS 5.0.6 closes **other open models** while serving `getScopeCsv`/`getScopeBitmap`. The
  `plecs_webserver` / `plecs_capture` responses report `closed_models` with a warning (and the
  server logs it); models are not auto-reloaded because that could discard unsaved changes.
- `plecs_model_edit` handles structure (components/params/wires/outports) and orientation
  (`direction`/`flipped` when adding, `set_orientation`, `set_position`) but does **not** do
  automatic layout or route wires around obstacles; coordinates are caller-supplied.
  PLECS RPC cannot change `Direction`/`Flipped`/`Position` (`plecs.set` reports
  `Unknown parameter`), so layout is text-level and needs a reload. Rotating a placed component
  invalidates explicit `Points`; drop that connection and re-`connect`. In-place editing is
  subject to `PLECS_MCP_ALLOWED_ROOTS` and is refused inside install directories.
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

# Simulation Script by name (from the .plecs Script block)
plecs_run_script(model, "Parameter Sweep (Sequential)")

# scope export with client-side slicing
plecs_webserver("getScopeCsv", [f"{model}/Scope"], time_range=[0, 1e-3], decimate=10)

# state space at one switch combination
plecs_state_space(model, {"FET": 1, "D": 0})

# acceptance gate
plecs_check(model, [{"type": "signal", "index": 0, "metric": "rms", "op": ">", "value": 10},
                    {"type": "analysis", "metric": "phase_margin_deg", "op": ">", "value": 45}],
            analysis_name="Loop Gain (AC Sweep)")

# background run + poll
plecs_submit("plecs.simulate", [model, {"SolverOpts": {"TimeSpan": 0.5}}])
plecs_task("<id>"); plecs_task_result("<id>")

# figure (PLECS-rendered by default)
plecs_plot(model, kind="bode", analysis_name="Loop Gain (AC Sweep)")
plecs_plot(model, kind="waveform", renderer="matplotlib")   # only for overlays

# structural model edit
plecs_model_edit(path, confirm=True, operations=[
  {"op": "add_component", "type": "Resistor", "name": "R2",
   "position": [400, 200], "direction": "right", "flipped": "off",
   "parameters": {"R": "10"}},
  {"op": "set_orientation", "component": "R2", "direction": "up", "flipped": "on"},
  {"op": "set_position", "component": "R2", "position": [400, 240]},
  {"op": "connect", "source": "V_dc", "source_terminal": 1,
   "target": "R2", "target_terminal": 1},
  {"op": "add_outport", "name": "Vout", "position": [600, 200]}])

# cheap multi-read
plecs_batch([{"method": "plecs.get", "params": [f"{model}/L1", "L"]},
             {"method": "plecs.get", "params": [f"{model}/C1", "C"]}])
```

## Error table

| Symptom | Meaning | Next step |
|---|---|---|
| `cannot reach PLECS …` | RPC port closed | Run `plecs_connect` (auto-start) or enable Preferences → RPC |
| `-32601` | Method missing in this build | `plecs_list_methods` |
| `-32602` | Invalid parameters | Check the tool schema; `runScript` needs `[model, {"ScriptName": name}]` |
| `-32500 … Cannot find analysis named` | Wrong analysis name | Use the Name property from `plecs_get_model_tree` |
| `-32500 … Invalid scope command` | Unsupported scope command | Use `plecs_webserver getScopeCsv` |
| `HTTP 502` | A proxy intercepted localhost | Client already uses `trust_env=False`; check the environment |
| `refusing to overwrite` | File exists | Pass `overwrite=true` (and confirm it is safe) |
| `outside PLECS_MCP_ALLOWED_ROOTS` | Write blocked | Choose a path under `~`, temp, or `PLECS_MCP_OUTPUT_DIR` |

## Tests

```bash
.venv/bin/python -m pytest -q      # 153 tests
```

Current release: **0.4.0** — see [CHANGELOG.md](CHANGELOG.md).

- Unit: base64/model tree, summary maths, config precedence, paths, locks, app discovery/launch,
  plotting, checks, tasks, THD, model scan/clone, artifacts/FMU, library flattening, resources,
  sweep-result post-processing, image externalisation, task age ordering, CRLF round-trip
- Surface: all 45 tools registered/documented; destructive tools need confirmation; batch/limits/guards
- Integration: when `127.0.0.1:1080` is reachable, exercises connect/load/tree/get/simulate/analyze/
  summary/CSV/capture/plot/tasks/check/compare/model_edit on `/tmp` copies of the bundled demos
  (user models are never touched)

CI (`.github/workflows/ci.yml`) runs the unit/surface suite on Python 3.10 and 3.13 on Ubuntu and
macOS; integration tests skip automatically when PLECS is not installed.

## Layout

```
src/plecs_mcp/client.py    JSON-RPC client (RW lock, timeouts, logging, no proxy)
src/plecs_mcp/config.py    config.yml + environment resolution
src/plecs_mcp/paths.py     write guardrails and output directories
src/plecs_mcp/session.py   model registry (path, dirty flag, rename tracking)
src/plecs_mcp/codec.py     base64 decoding, tree/compare parsing, CSV slicing
src/plecs_mcp/summary.py   time-series statistics, Bode margins, analysis kinds
src/plecs_mcp/launcher.py  per-OS discovery/launch, port polling, process check
src/plecs_mcp/diagnose.py  error → cause → next steps
src/plecs_mcp/resources.py MCP reference documents
src/plecs_mcp/plotting.py  waveform/Bode PNG rendering
src/plecs_mcp/tasks.py     background task registry
src/plecs_mcp/checks.py    declarative acceptance checks
src/plecs_mcp/library.py   component-library browsing (RPC tree fallback)
src/plecs_mcp/library_text.py Components.plecs text parser + disk cache
src/plecs_mcp/plecsfile.py .plecs parser and structural editor
src/plecs_mcp/modelops.py  model scan/clone
src/plecs_mcp/artifacts.py codegen output + FMU metadata
src/plecs_mcp/data.py      local metrics/FFT/THD
src/plecs_mcp/server.py    45 MCP tools + 6 resources
examples/quickstart.py     end-to-end smoke test
tests/                     unit + surface + integration
```
