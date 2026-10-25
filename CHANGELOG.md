# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project uses [Semantic Versioning](https://semver.org/).

## [0.2.1] - 2026-10-25

### Security

- Removed real local paths, project names, and the maintainer email from all
  documentation and examples.
- Rewrote git history and tags so earlier commits with that data are no longer
  reachable from the repository.

### Added

- Optional system-prompt workflow section: the model now knows the
  `project_open → tasks → create_st/selflock → diff → export` sequence without
  the user naming tools.

## [0.2.0] - 2026-10-25

### Added

- `plc_pou_create_st`: create an arbitrary ST POU (`P_Lang=4`) with code,
  local variables, comment, and optional task assignment. Works on a blank
  ISPSoft project (`Prog0`-only) as well as existing projects.
- `plc_tasks`: list task IDs, cycle time and POU call order, so the model can
  choose `task_id` before creating a POU.
- Blank-project acceptance: `open → tasks → create_st_pou → export` verified on
  an empty AS320T project (POU order `Prog0`, `MainLogic`; task 0 contains both).

### Changed

- Writing to a ladder POU now returns a message pointing to
  `plc_pou_create_st` / `plc_create_selflock` instead of a generic "ST only".

## [0.1.0] - 2026-10-25

### Added

- DSH Host plugin `dsh-delta-isp` with 14 `plc_*` tools, zero npm dependencies.
- Bundled Python engine (`python/src/delta_isp_mcp`) using only the standard
  library for the plugin path.
- `.isp` container codec: locate the DEFLATE stream by content, preserve the
  header, patch source length / payload-block length / CRC32, re-parse before
  writing.
- Project model: POU (LD/ST), TASK, GLOBAL_VAR, DUT, local variables.
- ST POU rewrite with GBK checks and static lint (block pairing, full-width
  punctuation, `=` vs `:=`, missing semicolons).
- Ladder self-lock POU generation from a built-in network template, including
  `ProgramFolder` registration and task assignment.
- **PRG-before-FB insertion fix**: ISPSoft ignores a PRG placed after FB blocks
  and deletes it on save.
- Diff, rollback, export verification, evidence log (`evidence.jsonl`).
- Optional standalone MCP server (`python -m delta_isp_mcp serve`) with the
  `mcp` extra.
- Docs: architecture, install, usage, tools, container format, publishing.
- Local harness `test/harness.mjs` (mock `ctx.tools` + real bridge) and Python
  tests.

### Fixed

- `plc_diff` no longer reports every POU after a bridge resume; POU comparison
  now normalizes CRLF/LF (the working text is read with universal newlines).
- New PRGs are inserted at the end of the PRG group, before FB blocks; the first
  prototype appended after FBs and ISPSoft deleted it on save.

### Known limitations

- Compilation and error capture are manual; ISPSoft 3.19 has no public CLI.
- Ladder generation is template-based (self-lock only).
- No automatic PLC download.
