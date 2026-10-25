# `.isp` container and project text format

Everything below was measured on real Delta ISPSoft 3.19 / AS320T projects.
It is not copied from vendor documentation.

## 1. Container layout

```
+-------------------------------+ 0x0000
| header (variable length)      |
+-------------------------------+ data_offset - 6
| uint16 method = 8 (DEFLATE)   |
+-------------------------------+ data_offset - 4
| uint32 CRC32(uncompressed)    |  little-endian
+-------------------------------+ data_offset
| raw DEFLATE stream (wbits=-15)|
+-------------------------------+ EOF
```

Samples:

| Project | file | header | data_offset | source | compressed |
|---|---:|---:|---:|---:|---:|
| Demo (set 2) | 16727 | 4342 | 4348 (0x10FC) | 95839 | 12379 |
| Demo (set 1) | 12956 | 3304 | 3310 (0x0CEE) | 72612 | 9646 |
| Untitled0 | 1378 | 164 | 170 (0x00AA) | 3085 | 1208 |

Consequences:

1. **Never hard-code 0xAA.** The header grows with the project; the stream must
   be located by scanning and validating the decompressed text (`<PROJECT>` …
   `</PROJECT>`).
2. **Preserve the header byte for byte.** It contains device, screen and config
   sections that cannot be regenerated.
3. A fixed-0xAA decoder (some open-source codecs) fails on real 3.19 projects.

## 2. Header fields to patch when rewriting

| Offset | Meaning | Action |
|---|---|---|
| `data_offset - 4` | CRC32 of the uncompressed source | recompute |
| `data_offset - 6` | compression method `8` | write `8` |
| `0x7C` | uncompressed source length | new length |
| `0x94` | payload-block length = compressed length + 6 | new compressed length + 6 |
| `0x98` | header length (164 + extended) | unchanged |
| `0x9C` | extended-header length (header − 164) | unchanged |
| `0x90` | unknown per-project value | unchanged |

Measured values:

| Project | 0x94 | 0x98 | 0x9C |
|---|---:|---:|---:|
| set 2 | 12385 | 4342 | 4178 |
| set 1 | 9652 | 3304 | 3140 |
| Untitled0 | 1214 | 164 | 0 |

Invariant: `0x94 + 0x98 == file length`. If it does not hold, ISPSoft reports
**文件损坏** ("file corrupted"). The engine patches fields **by value** (old
source length, old payload + 6) rather than by fixed offset, because header
lengths differ between projects.

## 3. Project source text

```
<PROJECT>
VERSION_CONTROL=ISPSoft_Version_1
Active_CodePage=936
Prj_ISPVer=3.19 ,2024/1/30,2024
Prj_Name=Demo
Prj_DT=AS320T
Prj_C_SourceCodeLocked=FALSE
</PROJECT>
<TASK>
[TASK_S]
T_ID=0
T_CycTime=20
T_PName=Systeminit
T_PName=HMI
[TASK_E]
</TASK>
<GroupPOUFolder>
<ProgramFolder>
<FolderContent>ContentType=0 / ContentName=Main / ContentPath=</FolderContent>
...
</ProgramFolder>
<FBFolder>
<FolderContent>ContentType=1 / ContentName=Slove_Flow / ...</FolderContent>
</FBFolder>
</GroupPOUFolder>
<GLOBAL_VAR> ... </GLOBAL_VAR>
<DUT_INFO> ... </DUT_INFO>
<POU> ... </POU>
<FBInstVAR> ... </FBInstVAR>
<Compiler_Option> ... </Compiler_Option>
```

- Encoding is the code page in `Active_CodePage` (cp936/GBK for Chinese
  projects), line endings CRLF. The engine preserves both.
- POU fields: `P_Name`, `P_type` (0 = PRG, 1 = FB), `P_Lang` (1 = LD, 4 = ST),
  `P_Active`, `P_Priority`, comment `(* ... *)`.
- ST bodies live in `<IL_ST_CODE>`; ladder bodies are networks of `[LD_NODE]`.
- Task call order is the repeated `T_PName=` list.
- Global symbols: `{ VAR name address;type;initial (* comment *) }` inside
  `<GLOBAL_VAR>`.

## 4. POU ordering — the trap

ISPSoft stores **all PRG blocks first, then all FB blocks**:

```
... HMI (PRG), 485_servomotor4 (PRG), test (PRG),
    Slove_Flow (FB), FreConv_PIDCAL (FB) ...
```

A new PRG appended after an FB is:

- not shown in the project tree on open;
- **deleted** when ISPSoft saves the project (the file shrinks and a `.bak` is
  written).

Insertion rule used by `add_ladder_pou()`:

1. find the last `P_type=0` block;
2. insert the new `<POU>` right after it, before the first `P_type=1`;
3. append a `<FolderContent>` row to `ProgramFolder` (not `FBFolder`);
4. append `T_PName=<name>` to the requested task;
5. re-parse and assert name, language, network count, folder row and task row.

## 5. Ladder node format

A network is a sequence of nodes:

```
<NETWORK_START>
<PROPERTIES_START>
NET_ID=1
NET_ACTIVE=TRUE
(* comment *)
<PROPERTIES_END>
<ROOTLINK_START> ... <ROOTLINK_END>
<OUTLINK_START>  ... <OUTLINK_END>
<NETWORK_END>
```

Observed node types:

| TYPE | Meaning | Key fields |
|---:|---|---|
| 1 | NO contact | `DEV_NAME` |
| 2 | NC contact | `DEV_NAME` |
| 3 | rising-edge contact | `DEV_NAME` |
| 4 | falling-edge contact | `DEV_NAME` |
| 6 | branch open | `LNK_C`, `LNK_L` |
| 13 | coil (OUT) | `DEV_NAME` |
| 29 | branch close | `LNK_C`, `LNK_L` |
| 9 | instruction box | `SYMB`, `API_NUM` |
| 11 | instruction operands | `VAR_NAME` list |
| 15/16 | contact variants used as EN/condition | `DEV_NAME` |
| 20 | horizontal connector | — |
| 7/12 | box terminator / rail nodes | — |

The bundled self-lock template only uses 1, 2, 6, 13, 29, so it does not need
the instruction/API mapping.

## 6. Sidecar files

`Demo.hwc`, `.dlhw`, `.ex`, `.tag`, `.eiptag`, `.opcuatag`, `.ecam`,
`.pnt` and `.ini` live next to the `.isp`. They hold hardware and communication
configuration. The plugin only rewrites the `.isp`; when testing a copy, keep
the sidecars with the same base name so ISPSoft loads them.

`.ex` is XML (Modbus/COM configuration). `.tag` is INI-style I/O mapping.

## 7. Verification matrix

| Check | Status |
|---|---|
| Parse 24 POUs / 4 tasks / AS320T / cp936 | verified |
| Round-trip unchanged text (CRC, lengths) | verified |
| CRC + `0x94 + 0x98 == size` after rewrite | verified |
| ISPSoft 3.19 opens a rewritten project | verified (project tree loaded) |
| New PRG at end of PRG group | verified in file; pending compile |
| ISPSoft drops a PRG placed after FBs | reproduced (file + `.bak` evidence) |
| Compile error capture | not implemented |

## 8. Open questions

- `0x90` changes per project; purpose unknown, preserved as-is.
- Whether ISPSoft validates anything beyond the CRC and lengths is not proven;
  the current build passes the observed checks.
- `API_NUM` values for arbitrary instructions require a mapping table; only the
  built-in template avoids them.
