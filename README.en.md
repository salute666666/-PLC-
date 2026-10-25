# dsh-delta-isp

> Read and edit Delta **ISPSoft** PLC projects from DeepSeek Harness: inspect
> POUs and symbols, patch ST, generate a ladder self-lock POU, export a verified
> `.isp`.

A DSH Host plugin plus a bundled Python engine. The plugin registers 14 PLC
tools; the engine reads and writes the vendor container. The original project is
never modified — every change happens in a workspace copy.

## Features

- Inspect POU list, ST bodies, ladder networks, local variables, global symbols,
  DUTs, task order.
- Patch ST POUs with GBK and static checks.
- Create a start/stop self-hold ladder POU from a built-in template, register it
  in the program tree and a task.
- Diff, rollback, export with CRC/length verification.
- Zero npm dependencies; Python engine uses only the standard library for the
  plugin path.

## Requirements

- DeepSeek Harness `>= 0.2.0-rc.1 < 0.3.0`
- Node.js `>= 20`
- Python `>= 3.10` (auto-detected: `py -3.x`, PATH, DSH runtime, local installs)
- Delta ISPSoft 3.19 (only to open/compile/download)

## Install

```powershell
git clone https://github.com/salute666666/-PLC-.git C:\tools\dsh-delta-isp
```

Then ask the agent to install the local plugin directory, or use Settings →
Plugins. Start a **new conversation** after installation.

Configuration (optional): `~/.dsh-delta-isp/config.json`

```json
{
  "python": "C:\\Python312\\python.exe",
  "workspace": "D:\\plc-work",
  "allowRead": ["D:\\work"]
}
```

## Verify

> Use `plc_environment` to check the PLC plugin.

Expected: Python path, ISPSoft path, workspace, no active project.

## Quick start

Create/save a blank project in ISPSoft first (File → New, choose the model).
Then:

```text
Open D:\work\Demo.isp, list the tasks, create an ST POU MainLogic on task 0 with
M10 := M0 AND NOT M1;, then export.
```

```text
Create a ladder POU named 自锁: M0 start, M1 stop, Y0.1 motor, M2 run lamp, task 1.
```

```text
Export the project and open it in ISPSoft.
```

## Tools

`plc_environment`, `plc_project_open`, `plc_project_status`, `plc_pou_list`,
`plc_pou_read`, `plc_symbols`, `plc_tasks`, `plc_pou_write`,
`plc_pou_create_st`, `plc_create_selflock`, `plc_lint`, `plc_diff`,
`plc_export`, `plc_rollback`, `plc_open_in_ispsoft`, `plc_build`.

## How it works

```
DSH Host plugin (Node, no deps)
  → spawn python -m delta_isp_mcp bridge
  → JSON request / response
  → workspace copy, re-parse, verify CRC and lengths
```

The `.isp` file is a variable-length header followed by a raw DEFLATE stream of a
pseudo-XML project text. The engine locates the stream by content, preserves the
header, patches the source-length/payload-length/CRC fields, and re-parses the
result before writing.

**Important:** ISPSoft stores all PRG blocks before all FB blocks. A new PRG
appended after an FB is ignored on open and dropped on save. The engine inserts
new PRGs at the end of the PRG group.

## Limitations

- Compilation/error capture is manual (no public CLI in ISPSoft 3.19).
- Ladder support is template-based (self-lock); arbitrary rungs need a node/API
  mapping table.
- GBK only; characters the project code page cannot encode are rejected.
- No automatic PLC download.

## Safety

Never download generated logic without review and a dry run. Emergency stop,
light curtains and safety gates must be hard-wired or use a safety relay.

## License

MIT © 2026 dsh-delta-isp contributors

---

中文完整文档：[README.md](README.md)
