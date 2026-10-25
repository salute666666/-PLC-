from delta_isp_mcp.isp.project import (
    ProjectDoc,
    PouLangUnsupported,
    add_ladder_pou,
    add_st_pou,
)

PROJECT = (
    "<PROJECT>\r\n"
    "Prj_Name=Demo\r\n"
    "Prj_DT=AS320T\r\n"
    "Prj_ISPVer=3.19\r\n"
    "Prj_C_SourceCodeLocked=FALSE\r\n"
    "Active_CodePage=936\r\n"
    "</PROJECT>\r\n"
    "<TASK>\r\n"
    "[TASK_S]\r\n"
    "T_ID=0\r\n"
    "T_ACT=TRUE\r\n"
    "T_CycTime=20\r\n"
    "T_EventType=1\r\n"
    "T_PName=Main\r\n"
    "T_PName=Blink\r\n"
    "[TASK_E]\r\n"
    "</TASK>\r\n"
    "<POU>\r\n"
    "P_Name=Main\r\n"
    "P_type=0\r\n"
    "P_Lang=4\r\n"
    "P_Active=TRUE\r\n"
    "P_Priority=9999\r\n"
    "P_DFBName=\r\n"
    "(*\r\n主程序\r\n*)\r\n"
    "<LOCAL_VAR>\r\n"
    "</LOCAL_VAR>\r\n"
    "<IL_ST_CODE>\r\n"
    "A:=1;\r\n"
    "</IL_ST_CODE>\r\n"
    "</POU>\r\n"
    "<POU>\r\n"
    "P_Name=Blink\r\n"
    "P_type=1\r\n"
    "P_Lang=1\r\n"
    "P_Active=TRUE\r\n"
    "P_Priority=9999\r\n"
    "P_DFBName=\r\n"
    "(*\r\n\r\n*)\r\n"
    "<LOCAL_VAR>\r\n"
    "</LOCAL_VAR>\r\n"
    "<NETWORK_START>\r\n"
    "<ROOTLINK_START>\r\n"
    "[LD_NODE]\r\n"
    "TYPE=3\r\n"
    "DEV_NAME=M0\r\n"
    "[END_LD_NODE]\r\n"
    "<ROOTLINK_END>\r\n"
    "<OUTLINK_START>\r\n"
    "[LD_NODE]\r\n"
    "TYPE=9\r\n"
    "SYMB=OUT\r\n"
    "API_NUM=1\r\n"
    "[END_LD_NODE]\r\n"
    "<OUTLINK_END>\r\n"
    "<NETWORK_END>\r\n"
    "</POU>\r\n"
)


def test_parse_project_and_tasks():
    doc = ProjectDoc.parse(PROJECT)
    assert doc.info["Prj_DT"] == "AS320T"
    assert [p.name for p in doc.pous] == ["Main", "Blink"]
    assert doc.pous[0].language == "ST"
    assert doc.pous[1].language == "LD"
    assert doc.pous[1].is_ladder and len(doc.pous[1].networks) == 1
    assert doc.tasks[0].pous == ["Main", "Blink"]
    assert doc.used_in_tasks()["Main"] == [0]


def test_replace_st_body_keeps_everything_else():
    doc = ProjectDoc.parse(PROJECT)
    new_text = doc.set_st_code("Main", "A := 2;\r\nIF A > 1 THEN\r\nB := TRUE;\r\nEND_IF;")
    again = ProjectDoc.parse(new_text)
    assert "A := 2;" in again.get_pou("Main").st_code
    assert "B := TRUE;" in again.get_pou("Main").st_code
    # the ladder POU is untouched
    assert again.get_pou("Blink").networks == doc.get_pou("Blink").networks
    assert again.tasks[0].pous == ["Main", "Blink"]


def test_replace_local_vars():
    doc = ProjectDoc.parse(PROJECT)
    new_text = doc.set_st_code("Main", "A:=1;", variables="A : INT;\r\nB : BOOL;")
    again = ProjectDoc.parse(new_text)
    assert "A : INT;" in again.get_pou("Main").local_vars


def test_ladder_pou_is_read_only():
    doc = ProjectDoc.parse(PROJECT)
    try:
        doc.set_st_code("Blink", "A:=1;")
    except PouLangUnsupported:
        pass
    else:  # pragma: no cover
        raise AssertionError("ladder POU should not be writable")


NETWORK = (
    "<NETWORK_START>\r\n"
    "<PROPERTIES_START>\r\n"
    "NET_ID=1\r\nNET_LABEL=\r\nNET_ACTIVE=FALSE\r\nNET_BOOKMARK=FALSE\r\n"
    "NET_MODIFY=FALSE\r\nNET_FOLD=FALSE\r\n(*\r\nold\r\n*)\r\n<PROPERTIES_END>\r\n"
    "<ROOTLINK_START>\r\n[LD_NODE]\r\nTYPE=1\r\nDEV_NAME=M0\r\n[END_LD_NODE]\r\n"
    "<ROOTLINK_END>\r\n"
    "<OUTLINK_START>\r\n[LD_NODE]\r\nTYPE=13\r\nDEV_NAME=Y0.1\r\n[END_LD_NODE]\r\n"
    "<OUTLINK_END>\r\n"
    "<NETWORK_END>"
)


def test_add_ladder_pou_registers_folder_and_task():
    text = PROJECT.replace(
        "<POU>",
        "<ProgramFolder>\r\n<FolderContent>\r\nContentType=0\r\nContentName=Main\r\n"
        "ContentPath=\r\n</FolderContent>\r\n</ProgramFolder>\r\n<POU>",
        1,
    )
    new_text = add_ladder_pou(
        text, name="自锁", network=NETWORK, comment="电机自锁", task_id=0
    )
    doc = ProjectDoc.parse(new_text)
    created = doc.get_pou("自锁")
    assert created.is_ladder and len(created.networks) == 1
    assert "NET_ACTIVE=TRUE" in created.networks[0]
    assert "电机自锁" in created.networks[0]
    assert "ContentName=自锁" in new_text
    assert "自锁" in doc.tasks[0].pous
    # existing POUs and tasks are preserved; the new PRG sits before the FB
    names = [p.name for p in doc.pous]
    assert names[:3] == ["Main", "自锁", "Blink"]
    assert doc.tasks[0].pous[:2] == ["Main", "Blink"]


def test_add_st_pou_registers_code_folder_and_task():
    text = PROJECT.replace(
        "<POU>",
        "<ProgramFolder>\r\n<FolderContent>\r\nContentType=0\r\nContentName=Main\r\n"
        "ContentPath=\r\n</FolderContent>\r\n</ProgramFolder>\r\n<POU>",
        1,
    )
    new_text = add_st_pou(
        text,
        name="Logic",
        code="A := 1;\r\nB := 2;",
        variables="A : INT;\r\nB : INT;",
        comment="test",
        task_id=0,
    )
    doc = ProjectDoc.parse(new_text)
    pou = doc.get_pou("Logic")
    assert pou.is_st and not pou.is_ladder
    assert "A := 1;" in pou.st_code and "B := 2;" in pou.st_code
    assert "A : INT;" in pou.local_vars
    assert "ContentName=Logic" in new_text
    assert "Logic" in doc.tasks[0].pous
    # Main (PRG), Logic (PRG), Blink (FB)
    assert [p.name for p in doc.pous] == ["Main", "Logic", "Blink"]
