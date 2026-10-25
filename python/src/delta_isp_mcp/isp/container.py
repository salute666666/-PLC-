"""Read and rebuild Delta ISPSoft ``.isp`` containers.

Verified on ISPSoft 3.19 / AS320T projects in this workstation:

* the project source is a raw DEFLATE stream (``zlib`` with ``wbits=-15``);
* the stream does **not** start at a fixed offset.  Three real projects
  started at ``0xAA`` (1.3 KB project), ``0xCEE`` (12.9 KB) and ``0x10FC``
  (16.7 KB).  The header grows with the project, so the stream must be
  located by scanning, not by a hard-coded offset;
* the uncompressed size is also stored as a little-endian ``uint32`` at
  ``0x7C`` in the header, which is patched when the source changes;
* the decompressed payload is a pseudo-XML text with ``<PROJECT>`` as its
  first tag and ``Active_CodePage=936`` for Chinese projects;
* the header itself is preserved byte for byte.  Only the DEFLATE payload
  and the known length fields are rewritten, which keeps unknown header
  sections (devices, screens, locks) intact.

The module never trusts an offset blindly: every candidate is decompressed
and must contain ``<PROJECT>`` ... ``</PROJECT>``.  On write the new
container is parsed again and must round-trip to the same text.
"""

from __future__ import annotations

import os
import re
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

MAX_CONTAINER = 32 * 1024 * 1024
MAX_SOURCE = 16 * 1024 * 1024
SCAN_LIMIT = 256 * 1024

# Offsets that are worth probing first (fixed-header variants).
HEADER_HINTS = (0xAA, 0xAC, 0xA4)

# Fields that may carry a length.  Each value is probed as-is and with the
# small constants observed in ISPSoft headers (the 6-byte gap before the
# DEFLATE payload).
LEN_FIELD_HINTS = (0x7C, 0x94, 0x98, 0x9C)

# Known source-length field.
SOURCE_LEN_OFFSET = 0x7C


class IspError(Exception):
    """Base class; ``code`` is returned to MCP clients."""

    code = "ISP_ERROR"


class IspFormatError(IspError):
    code = "ISP_FORMAT_UNSUPPORTED"


class IspProtectedError(IspError):
    code = "ISP_PROTECTED"


class IspLockedError(IspError):
    code = "ISP_LOCKED"


class IspRoundTripError(IspError):
    code = "ISP_ROUNDTRIP_FAILED"


def detect_encoding(source: bytes) -> str:
    """Return the Python codec named by ``Active_CodePage``."""

    match = re.search(rb"Active_CodePage=(\d+)", source[:16384])
    if not match:
        return "utf-8"
    codepage = int(match.group(1))
    if codepage in (0, 65001):
        return "utf-8"
    return f"cp{codepage}"


def _probe_source(data: bytes, offset: int) -> bytes | None:
    """Return the decompressed source if ``offset`` points at a valid stream."""

    if offset < 0 or offset >= len(data):
        return None
    # BTYPE=11b is reserved; a real DEFLATE stream never starts with it.
    if (data[offset] >> 1) & 3 == 3:
        return None

    try:
        decoder = zlib.decompressobj(-15)
        head = decoder.decompress(data[offset : offset + 8192])
    except zlib.error:
        return None

    if b"<PROJECT>" not in head:
        return None

    try:
        rest = decoder.decompress(data[offset + 8192 :])
        rest += decoder.flush()
    except zlib.error:
        return None

    source = head + rest
    if len(source) > MAX_SOURCE or b"</PROJECT>" not in source:
        return None
    return source


def locate_source(data: bytes) -> tuple[int, bytes]:
    """Find the project source inside a container and return ``(offset, bytes)``.

    Raises :class:`IspFormatError` when no valid stream is present (protected
    project, encrypted POU source, or an unknown future container variant).
    """

    if len(data) < 0x100:
        raise IspFormatError("文件太小，不是有效的 ISPSoft 工程")

    candidates: list[int] = list(HEADER_HINTS)
    for base in LEN_FIELD_HINTS:
        if len(data) >= base + 4:
            value = struct.unpack_from("<I", data, base)[0]
            candidates.extend((value, value + 4, value + 6, value - 6))

    seen: set[int] = set()
    for offset in candidates:
        if offset in seen:
            continue
        seen.add(offset)
        source = _probe_source(data, offset)
        if source is not None:
            return offset, source

    limit = min(len(data), SCAN_LIMIT)
    for offset in range(0x20, limit):
        if offset in seen:
            continue
        source = _probe_source(data, offset)
        if source is not None:
            return offset, source

    raise IspFormatError(
        "未找到可解压的工程源码。可能是带密码/源码锁的工程，或 ISPSoft 新版本容器格式。"
    )


@dataclass
class IspContainer:
    """An in-memory ``.isp`` file."""

    raw: bytes
    data_offset: int
    source: bytes
    encoding: str
    path: Path | None = None
    patched_offsets: list[int] = field(default_factory=list)
    stored_method: int | None = None
    stored_crc: int | None = None

    # ---- construction -------------------------------------------------
    @classmethod
    def from_bytes(cls, data: bytes, path: Path | None = None) -> "IspContainer":
        if len(data) > MAX_CONTAINER:
            raise IspFormatError(
                f"工程文件超过 {MAX_CONTAINER // (1024 * 1024)} MB 上限"
            )
        offset, source = locate_source(data)
        method = (
            struct.unpack_from("<H", data, offset - 6)[0] if offset >= 6 else None
        )
        crc = struct.unpack_from("<I", data, offset - 4)[0] if offset >= 4 else None
        return cls(
            raw=data,
            data_offset=offset,
            source=source,
            encoding=detect_encoding(source),
            path=path,
            stored_method=method,
            stored_crc=crc,
        )

    @classmethod
    def open(cls, path: str | Path) -> "IspContainer":
        file_path = Path(path)
        data = file_path.read_bytes()
        return cls.from_bytes(data, path=file_path)

    # ---- inspection ---------------------------------------------------
    @property
    def text(self) -> str:
        return self.source.decode(self.encoding)

    @property
    def header(self) -> bytes:
        return self.raw[: self.data_offset]

    @property
    def compressed_length(self) -> int:
        return len(self.raw) - self.data_offset

    @property
    def newline(self) -> str:
        return "\r\n" if b"\r\n" in self.source[:4096] else "\n"

    @property
    def checksum_ok(self) -> bool:
        return self.stored_crc == (zlib.crc32(self.source) & 0xFFFFFFFF)

    def summary(self) -> dict:
        text = self.text
        project = dict(
            re.findall(
                r"(?m)^([A-Za-z_][A-Za-z0-9_]*)=([^\r\n]*?)\r?$", _project_block(text)
            )
        )
        return {
            "file": str(self.path) if self.path else None,
            "file_size": len(self.raw),
            "data_offset": self.data_offset,
            "header_size": self.data_offset - 6,
            "source_size": len(self.source),
            "compressed_size": self.compressed_length,
            "encoding": self.encoding,
            "newline": "CRLF" if self.newline == "\r\n" else "LF",
            "project_name": project.get("Prj_Name", ""),
            "plc_model": project.get("Prj_DT", ""),
            "isp_version": project.get("Prj_ISPVer", ""),
            "source_locked": project.get("Prj_C_SourceCodeLocked", ""),
            "pou_count": text.count("<POU>"),
            "compression_method": self.stored_method,
            "checksum_ok": self.checksum_ok,
        }

    # ---- writing ------------------------------------------------------
    def rebuild(self, new_text: str, *, verify: bool = True) -> bytes:
        """Return new container bytes for ``new_text``.

        The original header is preserved; the source-length field is patched
        when present.  The result is parsed back before it is returned.
        """

        try:
            new_source = new_text.encode(self.encoding)
        except UnicodeEncodeError as exc:
            bad = new_text[exc.start : exc.end]
            raise IspFormatError(
                f"文本包含 {self.encoding} 无法表示的字符 {bad!r}；"
                "PLC 工程只能写 GBK 可编码的内容"
            ) from exc

        if len(new_source) > MAX_SOURCE:
            raise IspFormatError("工程源码超过 16 MB 上限")

        compressor = zlib.compressobj(9, zlib.DEFLATED, -15, 9)
        payload = compressor.compress(new_source) + compressor.flush()

        header = bytearray(self.raw[: self.data_offset])
        old_source_len = len(self.source)
        old_block_len = len(self.raw) - self.data_offset + 6  # trailer + payload

        matches: list[tuple[int, int]] = []
        for offset in range(0, len(header) - 3):
            value = struct.unpack_from("<I", header, offset)[0]
            if value == old_source_len:
                matches.append((offset, len(new_source)))
            elif value == old_block_len:
                matches.append((offset, len(payload) + 6))

        if len(matches) > 6:
            # Implausible coincidence count; keep only the known source field.
            matches = [item for item in matches if item[0] == SOURCE_LEN_OFFSET]

        for offset, value in matches:
            struct.pack_into("<I", header, offset, value)

        # The six bytes directly before the payload are the vendor trailer:
        # 2-byte compression method (8 = DEFLATE) + 4-byte CRC32 of the
        # *uncompressed* source.  ISPSoft verifies the CRC, so it must follow
        # the new text.
        if len(header) >= 6:
            struct.pack_into("<H", header, len(header) - 6, 8)
            struct.pack_into(
                "<I", header, len(header) - 4, zlib.crc32(new_source) & 0xFFFFFFFF
            )

        new_raw = bytes(header) + payload
        if verify:
            try:
                check = IspContainer.from_bytes(new_raw)
            except IspError as exc:  # pragma: no cover - defensive
                raise IspRoundTripError(f"重新打包后无法解析：{exc}") from exc
            if check.text != new_text:
                raise IspRoundTripError("重新打包后源码与输入不一致")
            if not check.checksum_ok:
                raise IspRoundTripError("重新打包后 CRC32 校验不一致")

        self.patched_offsets = [offset for offset, _value in matches]
        return new_raw

    def write(self, path: str | Path, new_text: str) -> dict:
        """Rebuild and write atomically.  Returns evidence for the caller."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = self.rebuild(new_text)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        return {
            "output": str(target),
            "output_size": len(data),
            "output_sha256": sha256_bytes(data),
            "patched_offsets": self.patched_offsets,
        }


def _project_block(text: str) -> str:
    match = re.search(r"<PROJECT>(.*?)</PROJECT>", text, re.S)
    return match.group(1) if match else ""


def sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()
