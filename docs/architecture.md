# Architecture

## 1. Design constraints

| Constraint | Consequence |
|---|---|
| ISPSoft 3.19 exposes no CLI / COM / script API | Compilation stays a GUI step; the plugin does file-level edits |
| `.isp` is a vendor container with a variable-length header | Never hard-code offsets; locate the DEFLATE stream by content and preserve the header |
| Project source is GBK text | All writes are encoded with the project's `Active_CodePage`; other characters are rejected |
| POU blocks are grouped PRG first, FB second | A new PRG must be inserted at the end of the PRG group or ISPSoft drops it on save |
| The model should not see raw container bytes | The plugin exposes a small, typed tool surface over a JSON bridge |

## 2. Components

```
DSH Host process
┌─────────────────────────────────────────────────────────────┐
│ dsh-delta-isp/index.js                                      │
│  ├─ loadSettings()   config.json + patch config             │
│  ├─ detectPython()   py -3.x / PATH / DSH runtime / Python3 │
│  ├─ runBridge()      spawn + JSON stdin/stdout + timeout    │
│  └─ 16 tool definitions registered on ctx.tools             │
└───────────────────────────┬─────────────────────────────────┘
                            │ child_process.spawn
                            │ PYTHONPATH=<pkg>/python/src
                            ▼
python/src/delta_isp_mcp
  cli.py      bridge (one JSON request)
  service.py  workspace / active project / diff / export / rollback
  isp/container.py  .isp ⇄ text
  isp/project.py    text ⇄ POU/TASK; ST patch; new POU insertion
  isp/ladder.py     built-in ladder templates
  isp/symbols.py    global symbols / DUT
  lint/st_check.py  ST checks
  safety.py         hashes, atomic writes, process check
```

The plugin deliberately does **not** import `@deepseek-ai/dsh-tools` or any other
Host package. It registers plain objects through `ctx.tools.register`, so the
package has zero npm dependencies and no build step.

## 3. Host plugin contract

`index.js` exports:

```js
export const inject = ['tools']

export function apply(ctx, config) {
  const disposers = TOOL_SPECS.map((spec) =>
    ctx.tools.register(makeToolDefinition(spec, runtime)),
  )
  return () => disposers.forEach((dispose) => dispose())
}
```

Each registered definition follows the Host `ToolDefinition` shape:

```js
{
  name: 'plc_pou_read',
  description: '...',
  parameters: {           // raw JSON Schema subset
    type: 'object',
    properties: { name: { type: 'string', description: '...' } },
    required: ['name'],
    additionalProperties: false,
  },
  output: {
    schema: { type: 'string' },
    render: (_args, value) => [{ type: 'text', text: String(value) }],
  },
  timeoutMs: 210000,
  async execute(args, exec) {
    const data = await runtime.call('pou_read', args, exec.signal)
    return JSON.stringify(data, null, 2)
  },
}
```

- `inject: ['tools']` makes the plugin inactive in profiles without the tool
  registry instead of throwing.
- The returned cleanup is called on plugin unload/HMR.
- `timeoutMs` is 210 s (bridge timeout 180 s + margin), because a large project
  export can take a few seconds and Python startup adds ~100 ms.

## 4. Bridge protocol

One request per process; state lives in the workspace, not in memory.

**stdin**

```json
{
  "op": "pou_write",
  "args": { "name": "test", "code": "D555 := 0;" },
  "workspace": "C:\\Users\\me\\.dsh-delta-isp\\plc-work",
  "allow_read": ["D:\\projects"]
}
```

**stdout — success**

```json
{ "ok": true, "data": { "name": "test", "language": "ST", "dirty": true } }
```

**stdout — failure**

```json
{ "ok": false, "error": { "code": "POU_NOT_FOUND", "message": "找不到 POU：foo" } }
```

| op | args | service method |
|---|---|---|
| `environment` | — | plugin/engine info |
| `project_open` | `path` | `open_project` |
| `project_status` | — | `summary` |
| `pou_list` | — | `pou_list` |
| `pou_read` | `name` | `pou_read` |
| `symbols` | `query?`, `limit?` | `symbols` |
| `tasks` | — | `tasks` |
| `search` | `query`, `limit?` | `search` |
| `pou_write` | `name`, `code`, `variables?` | `pou_write` |
| `create_st_pou` | `name`, `code`, `variables?`, `task_id?`, `comment?` | `create_st_pou` |
| `create_selflock` | `name`, `start`, `stop`, `coil`, `indicator?`, `task_id?`, `comment?` | `create_selflock` |
| `lint` | `pou?`, `code?` | `lint` |
| `diff` | — | `diff` |
| `export` | `output?` | `export` |
| `build` | `timeout?` | `build` |
| `open_in_ispsoft` | — | `open_in_ispsoft` |
| `rollback` | — | `rollback` |

Error codes: `ISP_FORMAT_UNSUPPORTED`, `ISP_PROTECTED`, `ISP_ROUNDTRIP_FAILED`,
`POU_NOT_FOUND`, `POU_LANG_UNSUPPORTED`, `NO_PROJECT`, `SAFETY_BLOCKED`,
`UNKNOWN_OP`.

The plugin turns `ok:false` into a thrown `Error("<code>: <message>")`, which
the tool pipeline records as a visible tool failure.

## 5. Workspace

```
<workspace>/
  active-project.json
  projects/<stem>-<sha8>/
    baseline.isp            byte-for-byte copy; never written
    baseline-source.txt     UTF-8 for diff/readability
    working-source.txt      editable text (UTF-8)
    exports/                generated .isp
    evidence.jsonl          one record per operation
```

`active-project.json` makes every bridge call stateless: constructing
`DeltaIspService` resumes the active project, so `pou_write` in call N and
`export` in call N+1 see the same working text.

`project_open` hashes the source, derives `<stem>-<sha8>`, and reuses an
existing workspace when the hash matches. The original `.isp` is copied, never
modified.

## 6. Container writing

```
header (preserved) | 08 00 | CRC32(source) | new DEFLATE payload
```

`IspContainer.rebuild()`:

1. Encode the new text with the project codec (`cp936` for Chinese projects).
2. Patch every `uint32` in the header equal to the old source length, plus the
   field equal to `old_payload + 6` (the payload-block length).
3. Rewrite the 6-byte trailer: method `8`, CRC32 of the new source.
4. Compress with raw DEFLATE (`wbits=-15`).
5. Re-parse the result, compare the text, verify the CRC, and only then write
   atomically.

The caller (`service.export`) opens the written file again and compares the text
once more. A mismatch is a hard error, never a silent success.

## 7. New POU insertion

`add_ladder_pou()` and `add_st_pou()` do four things:

1. Insert the `<POU>` block at the **end of the PRG group** (before the first
   `P_type=1` block). Ladder POUs use `P_Lang=1` plus a network; ST POUs use
   `P_Lang=4` plus `<LOCAL_VAR>` / `<BOOKMARK_MAP>` / `<IL_ST_CODE>`.
2. Add a `<FolderContent>` row to `<ProgramFolder>`.
3. Optionally add `T_PName=<name>` to the requested task.
4. Re-parse and assert the new POU has the expected language, network count or
   code, the folder entry exists, and the task contains it.

A blank ISPSoft project (only `Prog0`, task 0) is supported: the new POU is
inserted after `Prog0` and registered in the same task.

Why PRG-before-FB matters: ISPSoft parses the POU region as two consecutive
groups. A PRG placed after an FB is ignored on open and **dropped on save**,
which is exactly what happened during the first prototype.

## 8. Ladder template

`templates/selflock.network` is a proven start/stop rung with placeholders:

```
        {{START}}          {{STOP}}
|-------[ ]------+--------[/]--------+-----( {{COIL}} )
|                |                   |
|      {{COIL}}  |                   +-----( {{INDICATOR}} )
|-------[ ]------+
```

Node types:

| Type | Meaning |
|---:|---|
| 1 | normally-open contact |
| 2 | normally-closed contact |
| 6 | branch open (`LNK_C`/`LNK_L` grid coordinates) |
| 13 | coil (OUT) |
| 29 | branch close |

`indicator` is optional; when empty the second coil node is removed.

## 9. Security and trust boundary

- The plugin runs in the Host process and can spawn Python. It only spawns the
  bundled engine with a fixed argv; tool arguments never become shell commands.
- Project paths are validated against `allowRead` by the Python service when the
  list is non-empty.
- Export paths must stay inside the workspace or `allowRead`.
- The engine refuses password/source-locked projects.
- PLC download is out of scope; `plc_build` returns manual steps.

## 10. Testing strategy

| Layer | Test | Needs DSH? | Needs ISPSoft? |
|---|---|---|---|
| Container / model | `python/tests` (pytest) | no | no |
| Bridge + tools | `node test/harness.mjs` | no (mock ctx) | no |
| Plugin activation | `plugin_manager install_bundle` | yes | no |
| Compile acceptance | manual open + compile | yes | yes |

The harness runs the **real** Python bridge and a real project copy, so it
covers the same code path the model uses minus DSH's registration wrapper.

## 11. Extension points

- Add ladder templates: drop a `.network` file and a helper in `isp/ladder.py`,
  then a tool spec in `index.js`.
- Add ST templates: generate code from a skeleton and call `pou_write`.
- Compile automation: implement UI automation in `ide/ispsoft.py` and change
  `compile_project` to return structured diagnostics; the tool surface stays the
  same.
- Online verification: add a Modbus/OPC UA tool that reads a tag after download.
