import struct
import zlib

import pytest

from delta_isp_mcp.isp.container import IspContainer
from delta_isp_mcp.service import DeltaIspService
from delta_isp_mcp.safety import SafetyError

PROJECT = (
    "<PROJECT>\r\n"
    "Prj_Name=Demo\r\n"
    "Prj_DT=AS320T\r\n"
    "Prj_ISPVer=3.19\r\n"
    "Prj_C_SourceCodeLocked=FALSE\r\n"
    "Active_CodePage=936\r\n"
    "</PROJECT>\r\n"
    "<TASK>\r\n[TASK_S]\r\nT_ID=0\r\nT_ACT=TRUE\r\nT_CycTime=20\r\nT_EventType=1\r\n"
    "T_PName=Main\r\n[TASK_E]\r\n</TASK>\r\n"
    "<POU>\r\nP_Name=Main\r\nP_type=0\r\nP_Lang=4\r\nP_Active=TRUE\r\nP_Priority=9999\r\n"
    "P_DFBName=\r\n(*\r\n\r\n*)\r\n<LOCAL_VAR>\r\n</LOCAL_VAR>\r\n"
    "<IL_ST_CODE>\r\nA:=1;\r\n</IL_ST_CODE>\r\n</POU>\r\n"
    "<GLOBAL_VAR>\r\nTableName=Global Variables\r\n{\r\nVAR\r\nA\r\nD0;INT;\r\n(*\r\n计数\r\n*)\r\n}\r\n</GLOBAL_VAR>\r\n"
)


def write_isp(path):
    source = PROJECT.encode("gbk")
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15, 9)
    payload = compressor.compress(source) + compressor.flush()
    header = bytearray(164)
    struct.pack_into("<I", header, 0x7C, len(source))
    trailer = b"\x08\x00" + struct.pack("<I", zlib.crc32(source) & 0xFFFFFFFF)
    path.write_bytes(bytes(header) + trailer + payload)
    return path


def test_open_write_diff_export_rollback(workdir):
    source = write_isp(workdir / "Demo.isp")
    service = DeltaIspService(workdir / "ws", allow_read=[workdir])

    summary = service.open_project(source)
    assert summary["pou_count"] == 1
    assert summary["plc_model"] == "AS320T"

    assert service.pou_read("Main")["code"].strip() == "A:=1;"
    symbol = service.symbols("A")["items"][0]
    assert symbol["device"] == "D0"

    service.pou_write("Main", "A := 2;\r\nIF A > 1 THEN\r\nA := 3;\r\nEND_IF;")
    diff = service.diff()
    assert diff["summary"]["changed_pous"] == ["Main"]

    exported = service.export()
    reopened = IspContainer.open(exported["output"])
    assert "A := 3;" in reopened.text
    assert reopened.checksum_ok

    service.rollback()
    assert service.summary()["dirty"] is False
    exported2 = service.export()
    assert IspContainer.open(exported2["output"]).text == PROJECT


def test_respects_allow_read(workdir):
    source = write_isp(workdir / "Demo.isp")
    other = workdir / "other"
    other.mkdir()
    service = DeltaIspService(workdir / "ws", allow_read=[other])
    with pytest.raises(SafetyError):
        service.open_project(source)


def test_resume_working_copy(workdir):
    source = write_isp(workdir / "Demo.isp")
    workspace = workdir / "ws"
    first = DeltaIspService(workspace, allow_read=[workdir])
    first.open_project(source)
    first.pou_write("Main", "A := 9;")
    first.export()

    second = DeltaIspService(workspace, allow_read=[workdir])
    assert second.summary()["dirty"] is True
    assert second.pou_read("Main")["code"].strip() == "A := 9;"
    # resuming reads working-source.txt with universal newlines; the diff must
    # still report only the edited POU, not every POU due to CRLF vs LF
    assert second.diff()["summary"]["changed_pous"] == ["Main"]

