# Changelog

All notable changes to this project are documented here.

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
