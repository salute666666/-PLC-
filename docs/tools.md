# Tools reference

All tools return a JSON string. Failures are thrown as `Error("<code>: <message>")`
and appear as a failed tool call, never as a fake success.

Common result envelope from the engine:

```json
{ "ok": true, "data": { } }
```

## `plc_environment`

Parameters: none.

Returns engine/plugin info: version, workspace, `allow_read`, ISPSoft exe,
ISPSoft running, active project, detected Python, Node version, package dir.

## `plc_project_open`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | absolute `.isp` path |

Copies the project into the workspace and returns:

```json
{
  "plc_model": "AS320T",
  "isp_version": "3.19 ,2024/1/30,2024",
  "encoding": "cp936",
  "pou_count": 24,
  "task_count": 4,
  "symbol_count": 54,
  "checksum_ok": true,
  "workspace": "...",
  "source_path": "..."
}
```

## `plc_project_status`

No parameters. Same fields as `project_open`, plus `dirty` and
`ispsoft_running`.

## `plc_pou_list`

No parameters. Returns an array:

```json
[
  {
    "name": "test",
    "type": "PRG",
    "language": "ST",
    "active": false,
    "priority": 9999,
    "comment": "流量计计算",
    "local_vars_lines": 0,
    "code_lines": 9,
    "networks": 0,
    "tasks": [0]
  }
]
```

## `plc_pou_read`

| Parameter | Type | Required |
|---|---|---|
| `name` | string | yes |

Returns `name`, `type`, `language`, `active`, `comment`, `variables`, `code`
(for ST), `networks` (for LD), `tasks`.

## `plc_symbols`

| Parameter | Type | Required | Default |
|---|---|---|---|
| `query` | string | no | — |
| `limit` | integer | no | 200 |

Returns:

```json
{
  "total": 54,
  "items": [
    {
      "name": "PluseFlag1",
      "device": "X0.0",
      "datatype": "BOOL",
      "initial": "",
      "comment": "流量计1的上升沿标志位",
      "kind": "VAR",
      "table": "Global Variables"
    }
  ],
  "duts": ["AOStruct", "AIStruct", "DOStruct"]
}
```

## `plc_tasks`

No parameters. Returns:

```json
[
  { "task_id": 0, "active": true, "cycle_ms": "20", "event_type": 1,
    "pous": ["Prog0", "MainLogic"] }
]
```

Use it before creating a POU to choose `task_id`.

## `plc_pou_create_st`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | new POU name |
| `code` | string | yes | full ST body (GBK encodable) |
| `variables` | string | no | local-variable declarations |
| `task_id` | integer | no | task to call the POU |
| `comment` | string | no | POU comment |

Creates `P_Lang=4`, inserts it at the end of the PRG group, registers it in
`ProgramFolder`, and optionally adds `T_PName`. Returns `name`, `language`
(`ST`), `task`, `code_lines`, `variables_lines`, `issues`, `dirty`.

Works on a blank project (`Prog0`-only): result is `Prog0`, `MainLogic`, task 0
contains both.

## `plc_pou_write`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | existing ST POU |
| `code` | string | yes | full body |
| `variables` | string | no | full local-variable section |

Returns `name`, `language`, `dirty`, `issues`, `diff` summary.

Errors: `POU_NOT_FOUND`, `POU_LANG_UNSUPPORTED` (ladder), static-check errors.

## `plc_create_selflock`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | new POU name |
| `start` | string | yes | start NO contact, e.g. `M0` |
| `stop` | string | yes | stop NC contact, e.g. `M1` |
| `coil` | string | yes | output + seal contact, e.g. `Y0.1` |
| `indicator` | string | no | run lamp coil, e.g. `M2` |
| `task_id` | integer | no | task to call the POU |
| `comment` | string | no | POU/network comment |

Returns `name`, `language` (`LD`), `networks` (1), `task`, `devices`, `dirty`.

## `plc_lint`

| Parameter | Type | Required |
|---|---|---|
| `pou` | string | one of `pou`/`code` |
| `code` | string | one of `pou`/`code` |

Checks: `IF/CASE/FOR/WHILE` pairing, `REPEAT/UNTIL`, parentheses, full-width
punctuation, `=` vs `:=`, missing semicolons, GBK encodability.

## `plc_diff`

No parameters. Returns:

```json
{
  "summary": { "changed_pous": ["test"], "added_lines": 3, "removed_lines": 0 },
  "diff": "--- baseline\n+++ working\n...",
  "truncated": false
}
```

## `plc_export`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `output` | string | no | absolute path; must be inside workspace or `allowRead` |

Returns `output`, `output_size`, `output_sha256`, `patched_offsets`, `dirty`.
The written file is parsed again and its text compared before returning.

## `plc_rollback`

No parameters. Returns `{ "dirty": false, "restored_from": "..." }`.

## `plc_open_in_ispsoft`

No parameters. Exports first, then launches `NewISPSoft.exe <file>`.
Returns `status` (`opened` / `unavailable`), `exe`, `file`.

## `plc_build`

| Parameter | Type | Required | Default |
|---|---|---|---|
| `timeout` | integer | no | 180 |

Returns `status: "manual_required"` with the file path and exact compile steps.
Automatic compile/error capture is the next milestone.
