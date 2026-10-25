# Usage tutorial

All examples assume the plugin is installed and a **new conversation** is open.
The original `.isp` is never modified; every operation happens on a copy under
`~/.dsh-delta-isp/plc-work`.

## 0. Before you start

- ISPSoft may stay open; the plugin only reads the `.isp` file to copy it.
- Compilation and download remain manual. The plugin produces a verified
  `.isp`; you open it in ISPSoft and press compile.
- Use a project without a source password. Locked projects are rejected.
- A brand-new project must be created and saved **once in ISPSoft** (File → New,
  choose the PLC model), because the model, hardware configuration and sidecar
  files are vendor-generated. After that, AI can create POUs and write code.

## 0.5 Start from a blank project (the path for new users)

1. In ISPSoft: **File → New**, choose the PLC model (for example `AS320T`), save
   as `Demo.isp`.
2. In DSH:

   > 打开 `D:\work\Demo.isp`，列出任务。新建 ST 程序 `MainLogic`，挂到任务 0，
   > 代码：`M10 := M0 AND NOT M1;`，然后导出。

3. Tools used: `plc_project_open` → `plc_tasks` → `plc_pou_create_st` → `plc_export`.
4. Expected: the blank project has one LD `Prog0` and task 0; the new
   `MainLogic` is inserted after `Prog0`, registered in `ProgramFolder`, and
   task 0 becomes `["Prog0", "MainLogic"]`.
5. Open the exported `.isp` in ISPSoft and compile.

`plc_pou_create_st` is the general "write a new program" tool; `plc_pou_write`
only edits an existing ST POU, and the default `Prog0` is ladder (read-only).

## 1. Read a project

> 打开 `D:\work\Demo.isp`，
> 列出所有 ST 程序，并告诉我 `test` 在哪个任务、用了哪些变量。

Tools used: `plc_project_open` → `plc_pou_list` → `plc_pou_read` → `plc_symbols`.

Expected output shape:

```
型号: AS320T   版本: 3.19   编码: cp936
POU: 24（ST 14 / LD 10）  任务: 4
test: PRG, ST, 任务 0, 9 行
符号: 54（示例 PluseFlag1 -> X0.0）
```

Useful follow-ups:

- “`Main` 在第几个任务？” → `plc_pou_read` / `plc_pou_list`
- “哪些 POU 里用到了 `D555`？” → `plc_symbols` + `plc_pou_read`
- “列出所有未启用的 POU” → `plc_pou_list` 的 `active` 字段

## 2. Edit an ST POU

> 把 `test` 改成：`D555` 每扫描周期加一，加到 100 清零；先自检，再给我 diff。

Tool flow: `plc_pou_read` → `plc_pou_write` → `plc_lint` → `plc_diff`.

Example code the model writes:

```st
D555 := D555 + 1;
IF D555 >= 100 THEN
    D555 := 0;
END_IF;
```

Expected diff:

```
changed=['test'] +3/-0
```

Rules enforced by the engine:

- `P_Lang=4` only; ladder POUs are read-only.
- Code must be encodable in the project code page (GBK). Emoji/full-width
  punctuation are rejected or flagged.
- The POU must exist and its name must resolve (case-insensitive fallback).

## 3. Create a ladder self-lock POU

> 新建梯形图子程序 `自锁`：M0 启动、M1 停止、Y0.1 电机输出、M2 运行指示，挂到任务 1。

Tool: `plc_create_selflock`

Parameters:

| Parameter | Example | Meaning |
|---|---|---|
| `name` | `自锁` | new POU name |
| `start` | `M0` | start pushbutton (NO) |
| `stop` | `M1` | stop pushbutton (NC) |
| `coil` | `Y0.1` | motor output + self-hold contact |
| `indicator` | `M2` | optional run lamp |
| `task_id` | `1` | task that calls the POU |
| `comment` | `电机自锁` | POU/network comment |

Generated ladder:

```
        M0              M1
|-------[ ]------+-----[/]-----+-----( Y0.1 )
|                |             |
|      Y0.1      |             +-----( M2 )
|-------[ ]------+
```

Behavior: press `M0` → `Y0.1` energizes and seals through its own contact;
release `M0` → stays on; press `M1` → seal breaks, motor stops.

Choosing `task_id`: call `plc_pou_list` or ask “列出任务”; each POU shows its
tasks. `T_ID=1` in the demo project is the main cyclic task (`Main`, `Sub_AD`,
`Sub_IOlog`, `Sub_DA`).

> The engine inserts the new PRG **before the first FB**; otherwise ISPSoft
> ignores it on open and deletes it on save. See `docs/isp-format.md`.

## 4. Export, open, compile

> 导出工程并用 ISPSoft 打开。

Tools: `plc_export` → `plc_open_in_ispsoft`.

Expected:

```
output: ~/.dsh-delta-isp/plc-work/projects/Demo-xxxx/exports/Demo-modified.isp
size: 16xxx bytes   crc: ok
```

Then in ISPSoft:

1. The project tree should show the new POU after the last PRG (`test`) and
   before the FB folder.
2. Open the POU and check the ladder visually.
3. Press **Compile**. Report the error count back to the AI.

If the POU is missing: **do not save**. ISPSoft would drop it again and destroy
the evidence. Report the screenshot instead.

## 5. Roll back

> 回滚所有改动。

Tool: `plc_rollback` → `dirty=false`. The working text returns to
`baseline.isp`; the original source was never touched.

## 6. Address conventions (Delta AS series)

| Prefix | Meaning | Notes |
|---|---|---|
| `X0.0` … | digital input | bit address with dot |
| `Y0.1` … | digital output | dot address |
| `M0` … | internal relay | HMI/watchable |
| `D0`, `W5000` … | data register | 16-bit; `D`/`W` both appear |
| `T0`, `C0` … | timer / counter | |

Use existing symbols when possible (`plc_symbols`). For demos, prefer `M`
devices so no physical output is energized by accident.

## 7. Prompt library

Copy-paste prompts live in [`examples/prompts.md`](../examples/prompts.md).

## 8. Safety

- Never download generated logic to a machine without review, simulation and a
  dry run.
- Emergency stop, light curtains, safety gates and over-pressure protection must
  be hard-wired or use a safety relay; PLC software logic is not a substitute.
- `Y` outputs may be wired to real actuators. The self-lock tool can drive an
  existing output symbol such as `Y0.1` (`HydraulicMotor`); treat it as a demo
  until you verify the wiring and interlocks.
