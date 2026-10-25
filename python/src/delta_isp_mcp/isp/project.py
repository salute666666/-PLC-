"""Parse the ISPSoft project source text into POU / TASK / PROJECT models.

The payload is *not* XML: it is a line-oriented vendor format that happens to
use angle-bracket section markers.  Inside ``<POU>`` the fields are
``Key=Value`` lines, the POU comment is a ``(* ... *)`` block, and the body is
either ``<IL_ST_CODE>`` (ST) or a sequence of ``<NETWORK_START>`` blocks
(ladder).  Parsing therefore uses section regexes plus key/value scanning, and
editing only replaces the inner text of one section, leaving every other byte
untouched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

POU_RE = re.compile(r"<POU>(.*?)</POU>", re.S)
TASK_RE = re.compile(r"<TASK>(.*?)</TASK>", re.S)
TASK_BLOCK_RE = re.compile(r"\[TASK_S\](.*?)\[TASK_E\]", re.S)
PROJECT_RE = re.compile(r"<PROJECT>(.*?)</PROJECT>", re.S)
KV_RE = re.compile(r"(?m)^([A-Za-z_][A-Za-z0-9_]*)=([^\r\n]*?)\r?$")
NETWORK_RE = re.compile(r"<NETWORK_START>.*?<NETWORK_END>", re.S)

LANG_NAMES = {1: "LD", 4: "ST"}


class ProjectError(Exception):
    code = "PROJECT_ERROR"


class PouNotFound(ProjectError):
    code = "POU_NOT_FOUND"


class PouLangUnsupported(ProjectError):
    code = "POU_LANG_UNSUPPORTED"


@dataclass
class Pou:
    name: str
    ptype: int
    lang: int
    active: bool
    priority: int
    comment: str
    local_vars: str
    st_code: str | None
    networks: list[str]
    header: dict[str, str]
    raw: str
    span: tuple[int, int]

    @property
    def language(self) -> str:
        return LANG_NAMES.get(self.lang, f"LANG_{self.lang}")

    @property
    def is_ladder(self) -> bool:
        return self.lang == 1

    @property
    def is_st(self) -> bool:
        return self.lang == 4

    def summary(self) -> dict:
        return {
            "name": self.name,
            "type": "FB" if self.ptype == 1 else "PRG",
            "language": self.language,
            "active": self.active,
            "priority": self.priority,
            "comment": _one_line(self.comment),
            "local_vars_lines": len([ln for ln in self.local_vars.splitlines() if ln.strip()]),
            "code_lines": len(self.st_code.splitlines()) if self.st_code is not None else 0,
            "networks": len(self.networks),
        }


@dataclass
class Task:
    task_id: int
    active: bool
    cyc_time: str
    event_type: int
    pous: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "task_id": self.task_id,
            "active": self.active,
            "cycle_ms": self.cyc_time,
            "event_type": self.event_type,
            "pous": list(self.pous),
        }


@dataclass
class ProjectDoc:
    text: str
    info: dict[str, str]
    pous: list[Pou]
    tasks: list[Task]

    # ---- construction -------------------------------------------------
    @classmethod
    def parse(cls, text: str) -> "ProjectDoc":
        match = PROJECT_RE.search(text)
        if not match:
            raise ProjectError("工程文本缺少 <PROJECT> 段，格式不支持")
        info = {key: value for key, value in KV_RE.findall(match.group(1))}

        pous: list[Pou] = []
        for pou_match in POU_RE.finditer(text):
            pous.append(_parse_pou(pou_match))

        tasks: list[Task] = []
        task_match = TASK_RE.search(text)
        if task_match:
            for block in TASK_BLOCK_RE.findall(task_match.group(1)):
                tasks.append(_parse_task(block))

        return cls(text=text, info=info, pous=pous, tasks=tasks)

    # ---- lookups ------------------------------------------------------
    def get_pou(self, name: str) -> Pou:
        for pou in self.pous:
            if pou.name == name:
                return pou
        lowered = name.casefold()
        for pou in self.pous:
            if pou.name.casefold() == lowered:
                return pou
        raise PouNotFound(f"找不到 POU：{name}")

    def names(self) -> list[str]:
        return [pou.name for pou in self.pous]

    def used_in_tasks(self) -> dict[str, list[int]]:
        mapping: dict[str, list[int]] = {}
        for task in self.tasks:
            for pou_name in task.pous:
                mapping.setdefault(pou_name, []).append(task.task_id)
        return mapping

    # ---- editing ------------------------------------------------------
    def set_st_code(
        self,
        name: str,
        code: str,
        variables: str | None = None,
    ) -> str:
        """Return a new project text with one ST POU body (and vars) replaced."""

        pou = self.get_pou(name)
        if not pou.is_st:
            raise PouLangUnsupported(
                f"{pou.name} 是 {pou.language} 程序，不能直接改代码；"
                "请用 plc_pou_create_st 新建 ST 程序，或用 plc_create_selflock 新建自锁梯形图"
            )

        new_block = _replace_section(pou.raw, "IL_ST_CODE", code)
        if variables is not None:
            new_block = _replace_section(new_block, "LOCAL_VAR", variables)

        start, end = pou.span
        new_text = self.text[:start] + new_block + self.text[end:]

        # Re-parse and confirm the body landed where intended.
        check = ProjectDoc.parse(new_text)
        updated = check.get_pou(name)
        if _normalize(updated.st_code or "") != _normalize(code):
            raise ProjectError("写入后校验失败：POU 代码与输入不一致")
        return new_text


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _parse_pou(match: re.Match[str]) -> Pou:
    block = match.group(1)
    cut = block.find("<")
    header_text = block if cut < 0 else block[:cut]
    rest = "" if cut < 0 else block[cut:]

    header = {key: value for key, value in KV_RE.findall(header_text)}
    comment_match = re.search(r"\(\*(.*?)\*\)", header_text, re.S)
    comment = comment_match.group(1).strip() if comment_match else ""

    vars_match = re.search(r"<LOCAL_VAR>(.*?)</LOCAL_VAR>", rest, re.S)
    local_vars = vars_match.group(1) if vars_match else ""

    code_match = re.search(r"<IL_ST_CODE>(.*?)</IL_ST_CODE>", rest, re.S)
    st_code = code_match.group(1) if code_match else None

    name = header.get("P_Name", "").strip()
    if not name:
        raise ProjectError("POU 缺少 P_Name")

    return Pou(
        name=name,
        ptype=_int(header.get("P_type"), 0),
        lang=_int(header.get("P_Lang"), 0),
        active=header.get("P_Active", "").strip().upper() == "TRUE",
        priority=_int(header.get("P_Priority"), 9999),
        comment=comment,
        local_vars=local_vars,
        st_code=st_code,
        networks=NETWORK_RE.findall(rest),
        header=header,
        raw=block,
        span=match.span(1),
    )


def _parse_task(block: str) -> Task:
    fields = {key: value for key, value in KV_RE.findall(block)}
    pous = [
        name.strip()
        for name in re.findall(r"(?m)^T_PName=([^\r\n]*?)\r?$", block)
    ]
    return Task(
        task_id=_int(fields.get("T_ID"), -1),
        active=fields.get("T_ACT", "").strip().upper() == "TRUE",
        cyc_time=fields.get("T_CycTime", "").strip(),
        event_type=_int(fields.get("T_EventType"), 0),
        pous=pous,
    )


def _replace_section(block: str, tag: str, content: str) -> str:
    pattern = re.compile(rf"<{tag}>(.*?)</{tag}>", re.S)
    if not pattern.search(block):
        raise ProjectError(f"找不到 <{tag}> 段")

    newline = "\r\n" if "\r\n" in block else "\n"
    body = content.replace("\r\n", "\n")
    if body.endswith("\n"):
        body = body[:-1]
    if newline == "\r\n":
        body = body.replace("\n", "\r\n")
    replacement = f"<{tag}>{newline}{body}{newline}</{tag}>"
    return pattern.sub(lambda _m: replacement, block, count=1)


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").strip("\n")


def _int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _one_line(text: str, limit: int = 60) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


# ----------------------------------------------------------------------
# creating new ladder POUs from a known-good network template
# ----------------------------------------------------------------------
def add_ladder_pou(
    text: str,
    *,
    name: str,
    network: str,
    comment: str = "",
    task_id: int | None = None,
) -> str:
    """Append a new ladder POU and register it in the folder tree and a task.

    ``network`` must be a complete ``<NETWORK_START>...<NETWORK_END>`` block
    taken from an existing project (a known-good template).  The caller is
    responsible for adapting device names; this function only fixes
    ``NET_ACTIVE``, the comment, the POU header, the folder entry and the task
    assignment, then re-parses the result.
    """

    document = ProjectDoc.parse(text)
    if any(pou.name == name for pou in document.pous):
        raise ProjectError(f"POU 已存在：{name}")
    if "<ProgramFolder>" not in text:
        raise ProjectError("工程缺少 <ProgramFolder>，无法登记新 POU")

    newline = "\r\n"
    prepared = _prepare_network(network, comment, newline)
    pou_block = _build_ladder_pou(name, prepared, comment, newline)

    position = _pou_insert_position(text)
    text = text[:position] + newline + pou_block + text[position:]

    entry = (
        f"<FolderContent>{newline}ContentType=0{newline}ContentName={name}{newline}"
        f"ContentPath={newline}</FolderContent>{newline}"
    )
    text = text.replace("</ProgramFolder>", entry + "</ProgramFolder>", 1)

    if task_id is not None:
        text = _add_task_pou(text, task_id, name)

    check = ProjectDoc.parse(text)
    created = check.get_pou(name)
    if not created.is_ladder or len(created.networks) != 1:
        raise ProjectError("新建 POU 校验失败：语言或网络数量不符")
    if task_id is not None:
        task = next((item for item in check.tasks if item.task_id == task_id), None)
        if task is None or name not in task.pous:
            raise ProjectError("新建 POU 的任务挂载校验失败")
    return text


def _pou_insert_position(text: str) -> int:
    """Return the end of the last PRG block (before the first FB block).

    ISPSoft stores PRG blocks first and FB blocks after them.  A new PRG
    appended after an FB is silently ignored when the project is opened and
    dropped on save, so the insertion point must be the end of the PRG group.
    """

    last_prg_end: int | None = None
    for match in re.finditer(r"<POU>.*?</POU>", text, re.S):
        block = match.group(0)
        ptype = re.search(r"(?m)^P_type=(\d+)", block)
        if ptype is not None and ptype.group(1) == "0":
            last_prg_end = match.end()
    if last_prg_end is not None:
        return last_prg_end
    fallback = text.rfind("</POU>")
    if fallback < 0:
        raise ProjectError("工程里没有可参照的 POU")
    return fallback + len("</POU>")


def _prepare_network(network: str, comment: str, newline: str) -> str:
    network = network.strip("\r\n")
    if not network.startswith("<NETWORK_START>") or not network.endswith(
        "<NETWORK_END>"
    ):
        raise ProjectError("network 必须是完整的 <NETWORK_START>…<NETWORK_END> 段")
    network = re.sub(
        r"(?m)^(NET_ACTIVE=)[^\r\n]*", r"\1TRUE", network, count=1
    )
    if comment:
        network = re.sub(
            r"\(\*.*?\*\)",
            lambda _m: f"(*{newline}{comment}{newline}*)",
            network,
            count=1,
            flags=re.S,
        )
    return network


def _build_ladder_pou(
    name: str, network: str, comment: str, newline: str
) -> str:
    comment_block = (
        f"(*{newline}{comment}{newline}*)" if comment else f"(*{newline}{newline}*)"
    )
    lines = [
        "<POU>",
        f"P_Name={name}",
        "P_En_Eno=FALSE",
        "P_Last_Chg=",
        "P_type=0",
        "P_Rtn_Type=",
        "P_Lang=1",
        "P_Step=0",
        "P_Version=",
        "P_DeltaFB=FALSE",
        "P_Security=",
        "P_Active=TRUE",
        "P_Priority=9999",
        "P_DFBName=",
        comment_block,
        "<LOCAL_VAR>",
        "</LOCAL_VAR>",
        network,
        "</POU>",
    ]
    return newline.join(lines)


def _add_task_pou(text: str, task_id: int, name: str) -> str:
    pattern = re.compile(r"\[TASK_S\](.*?)\[TASK_E\]", re.S)
    for match in pattern.finditer(text):
        body = match.group(1)
        if re.search(rf"(?m)^T_ID={task_id}\r?$", body):
            new_body = body.rstrip("\r\n") + f"\r\nT_PName={name}\r\n"
            return text[: match.start(1)] + new_body + text[match.end(1) :]
    raise ProjectError(f"找不到任务 T_ID={task_id}")


def add_st_pou(
    text: str,
    *,
    name: str,
    code: str,
    variables: str = "",
    comment: str = "",
    task_id: int | None = None,
) -> str:
    """Append a new ST POU and register it in the folder tree and a task.

    Inserted at the end of the PRG group, before the first FB, for the same
    reason as :func:`add_ladder_pou`: ISPSoft drops a PRG that follows FB blocks
    when it saves the project.
    """

    document = ProjectDoc.parse(text)
    if any(pou.name == name for pou in document.pous):
        raise ProjectError(f"POU 已存在：{name}")
    if "<ProgramFolder>" not in text:
        raise ProjectError("工程缺少 <ProgramFolder>，无法登记新 POU")

    newline = "\r\n"
    pou_block = _build_st_pou(name, code, variables, comment, newline)

    position = _pou_insert_position(text)
    text = text[:position] + newline + pou_block + text[position:]

    entry = (
        f"<FolderContent>{newline}ContentType=0{newline}ContentName={name}{newline}"
        f"ContentPath={newline}</FolderContent>{newline}"
    )
    text = text.replace("</ProgramFolder>", entry + "</ProgramFolder>", 1)

    if task_id is not None:
        text = _add_task_pou(text, task_id, name)

    check = ProjectDoc.parse(text)
    created = check.get_pou(name)
    if not created.is_st:
        raise ProjectError("新建 ST POU 校验失败：语言不是 ST")
    if _normalize(created.st_code or "") != _normalize(code):
        raise ProjectError("新建 ST POU 校验失败：代码不一致")
    if task_id is not None:
        task = next((item for item in check.tasks if item.task_id == task_id), None)
        if task is None or name not in task.pous:
            raise ProjectError("新建 ST POU 的任务挂载校验失败")
    return text


def _build_st_pou(
    name: str, code: str, variables: str, comment: str, newline: str
) -> str:
    comment_block = (
        f"(*{newline}{comment}{newline}*)" if comment else f"(*{newline}{newline}*)"
    )
    code_body = code.replace("\r\n", "\n").strip("\n").replace("\n", newline)
    vars_body = variables.replace("\r\n", "\n").strip("\n").replace("\n", newline)
    lines = [
        "<POU>",
        f"P_Name={name}",
        "P_En_Eno=FALSE",
        "P_Last_Chg=",
        "P_type=0",
        "P_Rtn_Type=",
        "P_Lang=4",
        "P_Step=0",
        "P_Version=",
        "P_DeltaFB=FALSE",
        "P_Security=",
        "P_Active=TRUE",
        "P_Priority=9999",
        "P_DFBName=",
        comment_block,
        "<LOCAL_VAR>",
        vars_body,
        "</LOCAL_VAR>",
        "<BOOKMARK_MAP>",
        "</BOOKMARK_MAP>",
        "<IL_ST_CODE>",
        code_body,
        "</IL_ST_CODE>",
        "</POU>",
    ]
    return newline.join(lines)
