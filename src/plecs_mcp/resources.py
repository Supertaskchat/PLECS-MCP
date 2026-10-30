"""Static Markdown resources served over MCP (the "skills" counterpart)."""

from __future__ import annotations

DOCS: dict[str, tuple[str, str]] = {
    "quickstart": (
        "PLECS-MCP quickstart",
        """# PLECS-MCP quickstart

1. `plecs_connect()` — verifies the endpoint (and starts PLECS on this host if needed).
2. `plecs_get_model_tree(path, summary=True)` — learn model name, analyses, subsystems, scopes.
3. `plecs_simulate(model, {"SolverOpts": {"TimeSpan": 1e-3}}, summary=True)` — time-domain data.
4. `plecs_analyze(model, "<analysis Name property>", summary=True)` — Bode / margins.
5. `plecs_webserver("getScopeCsv", [f"{model}/Scope"])` — scope waveforms.
6. `plecs_close(model)` — refuses if this session changed parameters (`force=true` to discard).

Paths: a model is addressed by the name returned from `plecs_load`; components use
`model/Subsystem/Component` with `/` separators.
""",
    ),
    "rpc": (
        "PLECS RPC reference",
        """# PLECS RPC reference (verified on 5.0.6)

Transport: JSON-RPC 2.0 over HTTP on `127.0.0.1:1080` (localhost only).
`plecs_list_methods` shows what the running build supports.

| Method | Notes |
|---|---|
| `plecs.load(path)` | absolute path; returns 0 (the model name is the file stem) |
| `plecs.close(model)` | never saves |
| `plecs.save(model[, path])` | saving to a new path **renames** the open model |
| `plecs.get(path[, param])` | values are strings; `StateSpaceOrder` / `SystemState` / `Topology` are special params |
| `plecs.set(path, param, value)` | values are PLECS expressions ("48", "L*2") |
| `plecs.simulate(model, optStruct or list)` | only `SolverOpts` is honoured; `Values` is signals x time over JSON-RPC |
| `plecs.analyze(model, analysisName, optStruct)` | `analysisName` is the Name property; AC returns `{F, Gr, Gi}` |
| `plecs.scope(path, cmd, ...)` | HoldTrace / RemoveTrace / ClearTraces / SaveTraces / LoadTraces only |
| `plecs.webserver(cmd, ...)` | undocumented data channel: getScopeCsv / getScopeBitmap / getCircuitBitmap … |
| `plecs.compare(a, b)` | one multi-line string of `MergedItem(...)` entries |
| `plecs.extractExecutionLogData()` | solver/Jacobian counters for the last run |

`plecs.runScript(model, {"ScriptName": name})` runs a Simulation Script; success returns null.
""",
    ),
    "analysis": (
        "Simulation and analysis options",
        """# Simulation and analysis options

## SolverOpts (the only nesting PLECS reads)

```
{"SolverOpts": {"TimeSpan": 1e-3, "MaxStep": 1e-6, "Solver": "auto",
                "RelTol": 1e-4, "AbsTol": 1e-6, "Timeout": 600}}
```

A flat `{"StopTime": ...}` is **silently ignored** — the model then runs its configured TimeSpan.

## ModelVars

```
{"ModelVars": {"Vin": 48, "R_load": 10}}
```
Overrides are applied after initialization commands and before component parameters.

## Output

`{"OutputFormat": "Plain"}` (default) returns arrays; `"MatFile"` returns base64 MAT.
Only models with top-level **Signal Outport** blocks return data; otherwise use scope CSV.

## Analyses

AC Sweep / Impulse / Multitone / Frequency Response return `{F, Gr, Gi}` (complex transfer
functions). Steady-State returns `{Time, Values}`. `analysis_name` must equal the analysis'
**Name** property (e.g. `Loop Gain (AC Sweep)`).

Gain crossover and phase margin are only meaningful for loop-gain AC sweeps.
""",
    ),
    "errors": (
        "Troubleshooting PLECS errors",
        """# Troubleshooting

| Symptom | Cause | Next step |
|---|---|---|
| `Cannot find analysis named` | node label used instead of the Name property | `plecs_get_model_tree(..., summary=True)` |
| `Invalid scope command 'ExportCSV'` | RPC has no CSV export | `plecs_webserver("getScopeCsv", [scope])` |
| `Switch vector length mismatch` | wrong number of switch positions | `plecs_state_space(model)` lists the order |
| `Algebraic loop …` | loop cannot be broken | solver option / add delay / tolerance |
| `… exceeded maximum runtime` | `SolverOpts.Timeout` elapsed | raise timeout or shorten TimeSpan |
| `Cannot export FMU for non-atomic subsystem` | subsystem not atomic | enable "Treat as atomic unit" |
| `cannot reach PLECS` | RPC disabled or PLECS not running | `plecs_connect()` (auto-starts) |
| `refusing to overwrite` | file exists | pass `overwrite=true` |
| `outside PLECS_MCP_ALLOWED_ROOTS` | write guard | write under the output dir |

## Error payloads

MCP forwards the complete JSON-RPC `error.message` and any `error.data` verbatim; long and
multi-line messages are not truncated. If PLECS only puts a summary in the RPC payload, MCP
cannot reconstruct GUI-only details.

## Static connection checks

`plecs_validate(..., include_connections=True)` parses the `.plecs` text and reports structured
diagnostics such as `CONN-001` (missing component), `CONN-006` (subsystem/Output port),
`CONN-007` (C-Script terminal range), `CSCRIPT-007` (InputSignal index) and `SUB-005`
(subsystem schematic missing).

The checker only reports what the text can prove:

- C-Script ports declared as `-1` (inherited) or as expressions such as
  `"[1 num_channels]"` are skipped and listed in `info.connections.unchecked_cscript_ports`;
  `NumInputs "0"` means no input port.
- Encrypted subsystems are treated as opaque: no `SUB-005`.
- Library/masked component templates legitimately repeat variant names, so duplicate-name
  checks are skipped inside them.
- Top-level outport pairing (`CONN-006`/`CONN-008`) only runs when the root schematic has
  `Output` blocks; library files and RT Box data-logging models declare bare outport terminals.
- Connectors that only carry drawing `Points` are not endpoints.

Built-in component terminal counts are not present in `.plecs`, so those ranges stay unchecked;
geometric overlap still requires PLECS Diagnostics.

## C-Script compilation errors

The RPC error contains only the summary, for example:

```
Error(s) in component 'leg_test/PWM' during compilation of 'Code declarations'.
```

Full Clang diagnostics (file, line, column, message) are shown in the PLECS Diagnostics
dialog and are not returned over RPC. To continue without GUI access:

1. `plecs_get("<model>/<component>")` and inspect `Declarations`, `StartFcn`, `OutputFcn`,
   `UpdateFcn`, `DerivativeFcn`, `TerminateFcn`.
2. Check `#include` paths and header names, macros, port/state indices, sample time and
   direct feedthrough.
3. Optionally run `cc -fsyntax-only` as a pure C syntax pre-check (it cannot reproduce
   PLECS macros or solver semantics).
4. If the summary is insufficient, ask the user to paste the Diagnostics contents or a
   screenshot.
""",
    ),
    "gotchas": (
        "Common argument traps",
        """# Common argument traps

## PLECS process crashes

A few models make PLECS 5.0.6 segfault **inside its own model compiler**: the JSON-RPC
connection drops mid-call with no error payload. `plecs.simulate`, `plecs.analyze` and
`plecs.get(model, "Topology")` are the calls that can hit it; `plecs.load`, `plecs_get` on
parameters and official demos keep working, so the model - not the transport - is the trigger.

When MCP sees the connection drop during one of those calls it:

1. reports `[plecs-crash]` with the model path and the newest Crashpad `*.dmp` path;
2. restarts PLECS once (unless `PLECS_MCP_AUTO_START=never`);
3. quarantines that exact file version (path + mtime + size).

Further `plecs_simulate` / `plecs_analyze` / `plecs_state_space` calls on the unchanged file are
refused instead of killing PLECS again. Editing the file releases the quarantine.

When you hit this: go back to a copy that compiled, reintroduce the edits in small steps and run
`plecs_validate` after each one. `CONN-012` catches `From` blocks whose tag has no `Goto`
anywhere in the readable text, which is one of the mistakes PLECS reports as
"No matching Goto block found for tag ...".

## plecs_webserver

- `getScopeCsv` / `getScopeBitmap` / `getScopeSignals` / `getScopeInfo` / `getTraceNames`:
  `["scope_path"]`
- `getCursorData`: `["scope_path"]` or `["scope_path", {"Index": 0}]`.
  A bare integer (`["scope_path", 0]`) is rejected as invalid parameters.
- `getCircuitBitmap`: `["model_name"]` — **not** a `.plecs` file path. It also returns
  `components.<name>.dimensions` (`left`/`top`/`width`/`height`), which is the cheapest way to
  check spacing and overlap without eyeballing the PNG.

## Layout and orientation

- `plecs.set` **cannot** change `Direction`, `Flipped` or `Position`: PLECS reports
  `Unknown parameter`. Layout lives only in the `.plecs` text, so use `plecs_model_edit`
  (`direction`/`flipped` on `add_component`, or `set_orientation` / `set_position`) and reload.
- Place components with the direction they need: templates carry their own default (a
  `Resistor` is `up`), and an unrotated device forces wires to bend or overlap.
- Rotating a placed component invalidates explicit `Points` on its connections. There is no
  delete-connection or set-points operation: delete the `Points` lines in the text (or rewrite
  the corners) and reload. Re-`connect` does not help - it appends a second Connection and
  leaves the stale `Points` in place.
- `plecs_layout_check(model)` turns `getCircuitBitmap` boxes plus `Position`/`Points` into
  findings: `LAYOUT-001` (error) components overlap, `LAYOUT-002` (warning) a wire segment is
  diagonal, `LAYOUT-003` (info) a wire is drawn across a device. With
  `include_orientation=True` it adds `LAYOUT-004` (info), comparing each polar part against the
  placement convention measured in the bundled models: horizontal -> terminal 1 on the right,
  vertical passives/sources -> bottom, vertical diodes/thyristors -> top (`Direction`/`Flipped`
  to apply is included). Off by default because it is a house style. Crossings are cosmetic - PLECS
  connects only through explicit connections - and overlay blocks (`HeatSink`, `Goto`, `From`)
  are skipped. Wires are read through nested `Branch` nodes (one vertex per node), and the
  implicit corner-to-terminal hop is not checked.
- Base64 images are written to `save_to` or `PLECS_MCP_OUTPUT_DIR`; never inline.

## plecs_scope

- `SaveTraces`: `[scope, "SaveTraces", "/path/file.trace"]`.
  The scope must already contain **simulation data**; a scope that has never simulated
  writes a tiny `.trace` that `LoadTraces` rejects with "ended prematurely".
  Run a simulation first (clearing traces after a simulation is fine).
- `LoadTraces`: `[scope, "LoadTraces", "/path/existing.trace"]`; the file must be non-empty.
- `RemoveTrace`: requires a trace name. List traces with
  `plecs_webserver("getTraceNames", [scope])`.
- `ExportCSV` / `GetCursorData` are not scope commands; use the webserver equivalents.

## plecs_run_script

- `ScriptName` must exactly match a `Script { Name "..." }` block in the `.plecs` file.
- The RPC model tree does not expose script names. Use `plecs_overview(model)["scripts"]`
  or read the file; a wrong name returns the available script names in the error.
""",
    ),
    "limits": (
        "Data policy and limits",
        """# Data policy

- Simulations above `PLECS_MCP_MAX_INLINE_POINTS` (20000) are written as JSON to
  `PLECS_MCP_OUTPUT_DIR` and returned as a summary.
- Scope CSV above `PLECS_MCP_MAX_CSV_ROWS` (50000) is written to a file with a 5-row preview.
- `time_range` / `decimate` are applied client-side (PLECS ignores its own options).
- `summary=true` returns `min/max/mean/p2p/rms` per signal and Bode margins for AC sweeps.
- Base64 images are written to `save_to` (or `PLECS_MCP_OUTPUT_DIR`) and never inlined.
- Writes are refused inside `/Applications`, `/System`, `/Library`, `/usr`, `/bin`, `/etc`.
- `plecs_close` rejects models modified through `plecs_set` unless `force=true`.
""",
    ),
}
