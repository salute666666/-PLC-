import struct
import zlib

import pytest

from delta_isp_mcp.isp.container import (
    IspContainer,
    IspFormatError,
)

SOURCE_TEXT = (
    "<PROJECT>\r\n"
    "Prj_Name=Demo\r\n"
    "Prj_DT=AS320T\r\n"
    "Prj_ISPVer=3.19 ,2024/1/30,2024\r\n"
    "Prj_C_SourceCodeLocked=FALSE\r\n"
    "Active_CodePage=936\r\n"
    "</PROJECT>\r\n"
    + "(* filler *)\r\n" * 40
)


def make_container(text: str = SOURCE_TEXT, header_size: int = 164) -> bytes:
    source = text.encode("gbk")
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15, 9)
    payload = compressor.compress(source) + compressor.flush()
    header = bytearray(header_size)
    struct.pack_into("<I", header, 0x7C, len(source))
    struct.pack_into("<I", header, 0xA0, 0xAAAA)
    trailer = b"\x08\x00" + struct.pack("<I", zlib.crc32(source) & 0xFFFFFFFF)
    return bytes(header) + trailer + payload


def test_reads_source_and_trailer():
    container = IspContainer.from_bytes(make_container())
    assert container.text == SOURCE_TEXT
    assert container.encoding == "cp936"
    assert container.stored_method == 8
    assert container.checksum_ok


def test_rebuild_roundtrip_updates_sizes():
    container = IspContainer.from_bytes(make_container())
    changed = SOURCE_TEXT.replace("filler", "changed")
    raw = container.rebuild(changed)
    again = IspContainer.from_bytes(raw)
    assert again.text == changed
    assert again.checksum_ok
    # the source length field was found and patched
    assert 0x7C in container.patched_offsets


def test_scans_for_offset_when_header_is_large():
    raw = make_container(header_size=3000)
    container = IspContainer.from_bytes(raw)
    assert container.data_offset == 3006
    assert container.text == SOURCE_TEXT


def test_rejects_non_container_bytes():
    with pytest.raises(IspFormatError):
        IspContainer.from_bytes(b"\x00" * 5000)


def test_rejects_unencodable_text():
    container = IspContainer.from_bytes(make_container())
    with pytest.raises(IspFormatError):
        container.rebuild(SOURCE_TEXT + "😀")


def test_real_project_if_available():
    import os
    from pathlib import Path

    sample = os.environ.get("DELTA_ISP_SAMPLE")
    if not sample:
        pytest.skip("DELTA_ISP_SAMPLE not set")
    container = IspContainer.open(Path(sample))
    assert container.checksum_ok
    assert "<PROJECT>" in container.text
    raw = container.rebuild(container.text)
    assert IspContainer.from_bytes(raw).text == container.text
