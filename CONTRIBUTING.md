# Contributing

Thanks for improving `dsh-delta-isp`.

## Development setup

```powershell
git clone https://github.com/salute666666/-PLC-.git
cd -PLC-   # or the local directory name

node --check index.js

python -m pip install -e "python[dev]"
python -m pytest python/tests -q
```

Plugin harness (mock `ctx.tools`, real Python bridge):

```powershell
$env:DELTA_ISP_TEST_PROJECT = "D:\path\to\project.isp"
node test/harness.mjs
```

## Adding a tool

1. Add a spec to `TOOL_SPECS` in `index.js`: `name`, `description`, JSON-Schema
   `parameters`, `op`.
2. Add the `op` to `_bridge()` in `python/src/delta_isp_mcp/cli.py`.
3. Implement the service method with validation and an evidence record.
4. Add a harness step and a `docs/tools.md` row.
5. Keep tool names `plc_*`; keep the description in Chinese with enough English
   keywords for retrieval.

## Changing container or ladder logic

- Read `docs/isp-format.md` first.
- Never write to a user's original `.isp`; use a workspace copy.
- If you add header fields, patch them by value and keep
  `payload_block_len + header_len == file_len`.
- Add a fixture-based test; avoid tying tests to one machine's project path.

## Style

- JavaScript: ESM, Node built-ins only in `index.js` (no npm dependencies).
- Python: standard library only for the engine; `mcp`/`pydantic` stay optional.
- Comments explain **why** (format quirks, ISPSoft behavior), not what.
- User-facing strings: Chinese, concise.

## Pull request checklist

- [ ] `node --check index.js`
- [ ] `python -m pytest python/tests -q`
- [ ] `node test/harness.mjs` (with a project if the change touches engine I/O)
- [ ] `npm pack --dry-run` contains no caches
- [ ] Docs updated (`README`, `docs/tools.md`, `CHANGELOG.md`)
- [ ] No secrets, no machine-specific paths committed

## Reporting format bugs

Attach:

- ISPSoft version and PLC model
- the `.isp` header size / data offset if known
- the exact dialog text (e.g. 文件损坏)
- whether ISPSoft saved over the file (check `.bak` timestamp)

Do not attach password-protected projects.
