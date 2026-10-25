"""Global symbols and user data types from the project source text."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Symbol:
    table: str
    kind: str
    name: str
    device: str
    datatype: str
    initial: str
    comment: str

    @property
    def address_family(self) -> str:
        match = re.match(r"([A-Za-z]+)", self.device or "")
        return match.group(1).upper() if match else ""

    def summary(self) -> dict:
        return {
            "name": self.name,
            "device": self.device,
            "datatype": self.datatype,
            "initial": self.initial,
            "comment": " ".join(self.comment.split()),
            "kind": self.kind,
            "table": self.table,
        }


def parse_symbols(text: str) -> list[Symbol]:
    symbols: list[Symbol] = []
    for block in re.findall(r"<GLOBAL_VAR>(.*?)</GLOBAL_VAR>", text, re.S):
        table = _table_name(block)
        for entry in re.finditer(r"\{([^{}]*)\}", block, re.S):
            symbol = _parse_entry(table, entry.group(1))
            if symbol is not None:
                symbols.append(symbol)
    return symbols


def parse_dut_names(text: str) -> list[str]:
    return [
        name.strip()
        for name in re.findall(r"(?m)^DutName=([^\r\n]*?)\r?$", text)
        if name.strip()
    ]


def _table_name(block: str) -> str:
    match = re.search(r"(?m)^TableName=([^\r\n]*?)\r?$", block)
    return match.group(1).strip() if match else "Global Variables"


def _parse_entry(table: str, body: str) -> Symbol | None:
    lines = [line.strip() for line in body.splitlines()]
    lines = [line for line in lines if line]
    if len(lines) < 3:
        return None
    kind = lines[0]
    name = lines[1]
    spec = lines[2].split(";")
    device = spec[0].strip() if len(spec) > 0 else ""
    datatype = spec[1].strip() if len(spec) > 1 else ""
    initial = spec[2].strip() if len(spec) > 2 else ""
    comment_match = re.search(r"\(\*(.*?)\*\)", body, re.S)
    comment = comment_match.group(1).strip() if comment_match else ""
    return Symbol(
        table=table,
        kind=kind,
        name=name,
        device=device,
        datatype=datatype,
        initial=initial,
        comment=comment,
    )
