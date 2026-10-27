# Changelog

All notable changes to this project are documented here.

## [0.3.1] - 2026-10-27

### Added

- `plecs_model_edit` now controls orientation: `add_component` accepts `direction`
  (`right|left|up|down`) and `flipped` (`on|off`), and two new operations rotate/move placed
  components (`set_orientation`, `set_position`). Templates carry their own default direction
  (a `Resistor` is `up`), so passing `direction` at placement time is what keeps a horizontal
  power path horizontal.

### Documented

- PLECS RPC cannot modify `Direction`, `Flipped` or `Position` (`plecs.set` returns
  `Unknown parameter` for each), so all layout is text-level through `plecs_model_edit` and
  needs a reload. Rotating a placed component invalidates explicit `Points`; drop that
  connection and re-`connect` so PLECS re-routes.

## [0.3.0] - 2026-10-27

### Added

- `plecs_validate(..., include_connections=True, include_code=True)` now builds a scope-aware
  graph from the native `.plecs` text and reports structured diagnostics: missing components,
  cross-schematic references, duplicate component names, subsystem port ranges/directions,
  C-Script terminal ranges/directions, top-level Output/Terminal indices, malformed branches,
  and C-Script code index warnings (`InputSignal`, `OutputSignal`, states, `ParamRealData`).
- `plecs_diagnose` recognises `Cannot create connection to terminal` and unconnected-terminal
  errors and points to `plecs_validate`.
- Docs/resources describe the static checker limits: built-in terminal counts and geometric
  overlap remain PLECS Diagnostics territory.

### Fixed

- Connection checks no longer guess: C-Script ports declared with `-1` or expressions
  (library templates) are skipped and listed in `info.connections.unchecked_cscript_ports`,
  while `NumInputs "0"` correctly means zero input ports.
- Encrypted subsystems no longer report `SUB-005`, points-only branch stubs no longer report
  `CONN-003`, duplicate-name checks are skipped inside masked library templates, and top-level
  outport pairing only runs when the model has `Output` blocks.
- `CSCRIPT-004` accepts both DirectFeedthrough conventions (one entry per port or per channel).

### Tests

- Added `tests/test_model_graph.py` plus diagnose/validate integration coverage (140 tests);
  all 239 bundled `.plecs` files (models, demos, component and target-support libraries) parse
  with zero connection diagnostics.

## [0.2.1] - 2026-10-27

### Added

- `plecs_diagnose` now recognises C-Script compilation failures (`during compilation of`) and
  returns concrete next steps: read the component code segments with `plecs_get`, check includes,
  macros, indices and sample time, and explain that full Clang details live in the GUI Diagnostics
  dialog.
- `plecs_get` documentation calls out the C-Script code fields (`Declarations`, `StartFcn`,
  `OutputFcn`, `UpdateFcn`, `DerivativeFcn`, `TerminateFcn`).
- `PlecsRpcError` now preserves JSON-RPC `error.data` as well as the full `error.message`;
  non-200/JSON HTTP error bodies are no longer truncated.
- `plecs://docs/errors` documents that all RPC error payloads are forwarded verbatim, and the
  RPC summary vs GUI Diagnostics boundary for C-Script.

### Tests

- 121 tests, including the C-Script compilation diagnose rule and full error-payload forwarding.

## [0.2.0] - 2026-10-27

### Added

- Argument preflight for `plecs_webserver`, `plecs_scope` and `plecs_run_script`, returning
  the exact corrected call instead of a bare `invalid method parameters`.
- `plecs://docs/gotchas` MCP resource with the command argument shapes and common traps.
- `plecs_overview(...).scripts` and `plecs_validate(...).info.scripts`: Simulation Script names
  are recovered from the `.plecs` text because the RPC model tree omits them.
- `plecs_run_script` error enrichment: a wrong `ScriptName` lists the available scripts.
- Cross-platform `Components.plecs` discovery for macOS bundles, Windows installs and Linux binaries.
- macOS CI job alongside Ubuntu; regression tests for argument shapes, image handling, task age,
  CRLF round trips and real PLECS integration paths.

### Fixed

- `plecs_run_script` now uses the verified signature
  `plecs.runScript(model, {"ScriptName": name})`; the previous bare-string argument was the reason
  every call returned `invalid method parameters`.
- `plecs_analyze_data` accepts parameter-sweep JSON lists and reports malformed JSON as a tool error.
- `plecs_webserver` externalises all `imageData` payloads (including nested `getScopeSignals` images)
  to disk instead of inlining base64.
- `plecs_model_edit` applies the write policy to in-place edits and uses collision-safe backups.
- `TaskRegistry` restores the newest tasks by creation time instead of random UUID filenames.
- `plecs_scope` preflights `SaveTraces` against actual simulation data (`getScopeSignals`), avoiding
  `.trace` files that `LoadTraces` rejects; `LoadTraces` and `RemoveTrace` validate their arguments.
- `plecs_webserver` reports `closed_models` when PLECS closes other open models during scope commands.

### Changed

- matplotlib and numpy are imported lazily; RPC-only sessions avoid the plotting startup cost.
- Model file reads/writes preserve CRLF line endings.
- README and MCP resources now document the verified `runScript` shape, script discovery, image
  policy, scope argument shapes and PLECS model-closing behaviour.

### Tests

- 118 tests, including live PLECS integration for connect, simulate/analyze, CSV, capture, plot,
  tasks, checks, compare, model editing, `runScript`, `getCursorData` and `getCircuitBitmap`.

## [0.1.0] - 2026-10-26

- Initial PLECS-MCP release: 22 RPC methods, auto-start, summaries, tasks, checks, plotting,
  library search, model editing and write guardrails.
