# Install, configure, verify

## 1. Requirements

| Item | Requirement | Notes |
|---|---|---|
| DeepSeek Harness | `>= 0.2.0-rc.1 < 0.3.0` | plugin row uses `@deepseek-ai/dsh-tools` contract |
| Node.js | `>= 20` | DSH's bundled Node is fine |
| Python | `>= 3.10` | engine uses only the standard library |
| Delta ISPSoft | 3.19 recommended | only for opening/compiling/downloading |

No `npm install` and no `pip install` are required for the plugin path: the
Python source ships inside the package and the plugin sets `PYTHONPATH`.

## 2. Install from a local directory (recommended)

1. Get the package:

   ```powershell
   git clone https://github.com/salute666666/-PLC-.git C:\tools\dsh-delta-isp
   ```

   (or unzip a release tarball)

2. In DSH, install the directory. Either:

   - ask the agent: **"安装本地插件 `C:\tools\dsh-delta-isp`"** — it calls
     `plugin_manager install_bundle` with the absolute directory; or
   - open Settings → Plugins / Plugin Manager and choose the local directory.

3. Start a **new conversation**. Tool registration happens when the agent's tool
   set is assembled; an already-running turn may not see the new tools.

## 3. Install from GitHub

The repository root is the plugin package, so a clone is directly installable:

```powershell
git clone https://github.com/salute666666/-PLC-.git
```

Then install the cloned directory as in section 2.

## 4. Package a tarball

```powershell
cd dsh-delta-isp
npm pack
# dsh-delta-isp-0.1.0.tgz
```

The tarball contains `index.js`, `cordis.patch.yml`, locales, icon, `python/src`,
and docs. It must not contain `__pycache__`, `test/.work`, or `node_modules`.

## 5. Configuration

Optional file: `~/.dsh-delta-isp/config.json`

```json
{
  "python": "C:\\Python312\\python.exe",
  "workspace": "D:\\plc-work",
  "allowRead": ["D:\\work"]
}
```

| Field | Default | Meaning |
|---|---|---|
| `python` | auto-detect | absolute path to Python 3.10+ |
| `workspace` | `~/.dsh-delta-isp/plc-work` | copies, exports, evidence |
| `allowRead` | `[]` | directories the engine may open; empty = unrestricted |

The same keys can be placed in the bundle row config in
`~/.dsh/profiles/<profile>/cordis.patch.yml`; that takes precedence over the JSON
file. Editing the row reloads the plugin in place.

### Python detection

Order:

1. config `python`
2. `DELTA_ISP_PYTHON` environment variable
3. Windows: `py -3.13`, `py -3.12`, `py -3.11`, `py -3.10`
4. `python3`, `python`
5. `~/.dsh/dsh-runtimes/*/dependencies/python/python.exe` (DSH runtime)
6. `%LOCALAPPDATA%\Programs\Python\Python3*\python.exe`

Each candidate is executed once with
`import sys; print("PYVER=%d.%d" % sys.version_info[:2])` and must report 3.10+.
A wrapper that prints extra text (e.g. Amesim's `python.bat`) is skipped.

## 6. Verify

In a new conversation:

> 用 plc_environment 检查 PLC 插件环境

Expected fields:

```json
{
  "version": "0.1.0",
  "workspace": "C:\\Users\\<you>\\.dsh-delta-isp\\plc-work",
  "ispsoft_exe": "C:\\Program Files (x86)\\Delta Industrial Automation\\ISPSoft 3.19\\NewISPSoft.exe",
  "ispsoft_running": false,
  "plugin": {
    "python": { "command": "...python.exe", "args": [] },
    "node": "v24.x",
    "packageDir": "...\\dsh-delta-isp"
  }
}
```

Then a real project check:

> 打开 `D:\work\Demo.isp`，告诉我型号和 POU 数量

Expected: `AS320T`, `24 POU`, `4 tasks`, `cp936`.

## 7. Update

- Local clone: `git pull`, then reinstall the directory (plugin manager may offer
  an update), start a new conversation.
- Tarball: install the new tgz; a changed JavaScript module generation needs a
  restart.

## 8. Uninstall

Use Plugin Manager / `plugin_manager remove_bundle` with the package name
`dsh-delta-isp`. The workspace under `~/.dsh-delta-isp` is user data and is not
removed automatically; delete it manually if desired.

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| No `plc_*` tools | plugin not enabled, or old turn | check Plugin Manager; start a new conversation |
| `未找到 Python 3.10+` | only old Python on PATH | set `python` in config.json |
| `PLC 引擎退出码 1` | Python import error | run the engine manually (below) |
| `ISP_FORMAT_UNSUPPORTED` | password/locked project or new format | unlock the project; report a sample |
| `文件损坏` when ISPSoft opens | length/CRC fields inconsistent | see `docs/isp-format.md` |
| New POU missing after save | inserted after FB blocks | upgrade; insertion now targets end of PRG group |
| `SAFETY_BLOCKED` | path outside `allowRead` | widen `allowRead` deliberately |
| Tool timeout | dialog open in ISPSoft / huge project | close dialogs; retry |

Manual engine check:

```powershell
$env:PYTHONPATH = "C:\tools\dsh-delta-isp\python\src"
'{"op":"environment","workspace":"E:\tmp\plc-work"}' |
  & "C:\Users\<you>\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" -m delta_isp_mcp bridge
```

Expected: `{"ok": true, "data": {...}}`.
