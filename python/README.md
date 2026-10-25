# delta-isp-mcp (engine)

The Python engine bundled inside the `dsh-delta-isp` DSH plugin.

It only uses the Python standard library for the parts the plugin needs
(`bridge`, container codec, project model, ladder templates). The optional
`mcp` extra installs the official MCP SDK for running it as a standalone
stdio MCP server.

```powershell
# plugin usage: no install needed (the plugin sets PYTHONPATH)
python -m delta_isp_mcp bridge        # one JSON request on stdin

# standalone MCP server
pip install -e ".[mcp]"
python -m delta_isp_mcp serve --workspace .\plc-work --allow-read D:\projects

# CLI
python -m delta_isp_mcp inspect project.isp
python -m delta_isp_mcp unpack project.isp --out .\work
python -m delta_isp_mcp pack .\work --out repacked.isp
```

Layout:

```
src/delta_isp_mcp/
  isp/container.py   .isp container <-> project source text
  isp/project.py     pseudo-XML -> POU/TASK model, ST patch, new POU insertion
  isp/ladder.py      built-in ladder templates (self-lock)
  isp/symbols.py     global symbols / DUT
  lint/st_check.py   ST pre-flight checks
  service.py         workspace, diff, export, rollback
  cli.py             inspect / unpack / pack / serve / bridge
```

See `../docs/isp-format.md` for the container format notes.
