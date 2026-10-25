# Security

## Supported versions

| Version | Supported |
|---|---|
| 0.2.x | yes |

## Reporting

Open a GitHub issue with the label `security` for non-sensitive reports. For a
sensitive issue (path traversal, arbitrary code execution, credential leak),
open a private security advisory:
<https://github.com/salute666666/-PLC-/security/advisories/new>.

Please include the DSH version, plugin version, Python version, and a minimal
reproduction. Do not attach password-protected projects.

## Design boundaries

- The plugin runs in the DSH Host process and spawns only the bundled Python
  engine with a fixed argv (`python -m delta_isp_mcp bridge`). Tool arguments are
  passed as JSON on stdin, never interpolated into a shell command.
- The engine performs no network access. The only external process it may start
  is `NewISPSoft.exe <file>` when you explicitly call `plc_open_in_ispsoft`.
- Project files are copied into the workspace; the original is opened read-only.
- `allowRead` (when non-empty) restricts which project paths can be opened;
  export paths are restricted to the workspace or `allowRead`.
- Password-protected / source-locked projects are rejected. The project does not
  attempt to bypass vendor protection.

## Industrial safety

This tool writes PLC source code. Model-generated logic can damage equipment or
injure people.

- Review every diff before compiling, and compile before downloading.
- Never download without simulation and a dry run on the machine.
- Emergency stop, light curtains, safety gates, over-pressure and over-
  temperature protection must be hard-wired or use a certified safety relay.
  PLC software logic is not a safety function.
- The self-lock template can drive an existing output symbol (for example
  `Y0.1`). Treat generated ladder as a demo until wiring and interlocks are
  verified.

## Known security limitations

- The engine trusts the `.isp` file contents within the documented limits
  (source <=16 MiB, container <=32 MiB). Crafted files are not a supported
  threat model; use projects from trusted sources.
- The DSH Host process can read files the user can read; `allowRead` is a
  convenience guard, not a sandbox.
- Automatic compile/download is not implemented, which keeps a human in the
  loop by design.
