# Publishing

This repository **is** the DSH plugin package: the repository root contains
`package.json`, `index.js`, `cordis.patch.yml`, locales, icon and the bundled
Python engine.

## 1. Versioning

- `package.json` and `python/pyproject.toml` share the same version.
- Follow semver: behaviour changes to tools → minor; breaking tool names/schemas
  → major; fixes → patch.
- Update `CHANGELOG.md` in the same commit.

## 2. Pre-release checklist

```powershell
node --check index.js

# engine tests
python -m pip install -e "python[dev]"
python -m pytest python/tests -q

# plugin harness (mock ctx + real bridge)
$env:DELTA_ISP_TEST_PROJECT = "D:\path\to\project.isp"
node test/harness.mjs

# package contents
npm pack --dry-run
```

The pack list must **not** contain `__pycache__`, `test/.work`, `node_modules`,
or `.venv`. The plugin sets `PYTHONDONTWRITEBYTECODE=1` so running it does not
create caches.

## 3. Commit and tag

```powershell
git add -A
git commit -m "release: v0.1.0"
git tag v0.1.0
git push origin main --tags
```

## 4. GitHub release

1. Releases → Draft a new release → choose the tag.
2. Title: `v0.1.0`.
3. Notes: copy the `CHANGELOG.md` section.
4. Optional asset: `npm pack` output (`dsh-delta-isp-0.1.0.tgz`).
5. Publish.

## 5. Install verification (after publishing)

In a **new conversation**:

1. Install from the clone or the tgz.
2. Ask: `用 plc_environment 检查 PLC 插件环境` → expect Python + ISPSoft paths.
3. Open a real project → expect model, POU count, encoding.
4. Create a self-lock POU → export → open in ISPSoft → compile.
5. Roll back → `dirty=false`.

Record the result in the release notes.

## 6. Registry

The plugin is installable from a local directory or a git clone. Publishing to
the npm registry is optional; if you do, the package name `dsh-delta-isp` must be
available and `files` must ship `python/src/**`.

## 7. Compatibility

`package.json` declares:

```json
"dsh": { "compatibility": { "dsh": ">=0.2.0-rc.1 <0.3.0-0" } }
```

Re-test after a DSH minor upgrade: the `ctx.tools.register` contract is the only
Host API the plugin uses.
