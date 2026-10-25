"""Cheap pre-flight checks for Delta ST code.

This is deliberately *not* a full IEC 61131-3 parser.  The real compiler is
ISPSoft; the goal here is to catch the mistakes that would otherwise cost a
full IDE round-trip: unbalanced blocks, full-width punctuation, ``=`` instead
of ``:=`` and characters the GBK project code page cannot store.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

FULLWIDTH = {
    "；": ";",
    "（": "(",
    "）": ")",
    "＝": "=",
    "，": ",",
    "：": ":",
}

WORD_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")

OPENERS = {"IF", "CASE", "FOR", "WHILE"}
CLOSERS = {
    "END_IF": "IF",
    "END_CASE": "CASE",
    "END_FOR": "FOR",
    "END_WHILE": "WHILE",
}

STATEMENT_END_WORDS = (
    "THEN",
    "DO",
    "ELSE",
    "ELSIF",
    "CASE",
    "OF",
    "END_IF",
    "END_CASE",
    "END_FOR",
    "END_WHILE",
    "REPEAT",
    "UNTIL",
    "STRUCT",
    "END_STRUCT",
    "VAR",
    "END_VAR",
)


@dataclass
class Issue:
    severity: str
    line: int
    code: str
    message: str

    def as_dict(self) -> dict:
        return {
            "severity": self.severity,
            "line": self.line,
            "code": self.code,
            "message": self.message,
        }


def check_st(code: str) -> list[Issue]:
    issues: list[Issue] = []
    raw_lines = code.splitlines()
    code_lines = strip_comments(code).splitlines()

    for number, line in enumerate(code_lines, start=1):
        for char, replacement in FULLWIDTH.items():
            if char in line:
                issues.append(
                    Issue(
                        "error",
                        number,
                        "FULLWIDTH",
                        f"全角字符 {char!r} 应改为半角 {replacement!r}",
                    )
                )
        if re.match(r"^\s*[A-Za-z_][\w.\[\]]*\s*=[^=]", line):
            issues.append(
                Issue("warning", number, "ASSIGN_EQ", "ST 赋值应使用 := 而不是 =")
            )
        text = line.strip()
        if (
            text
            and not text.endswith(";")
            and not text.endswith("(*")
            and not re.search(r"\b(" + "|".join(STATEMENT_END_WORDS) + r")\b", text, re.I)
        ):
            issues.append(
                Issue("warning", number, "NO_SEMICOLON", "语句可能缺少结尾分号")
            )

    issues.extend(_check_blocks(code_lines))
    issues.extend(_check_parens(code_lines))

    try:
        code.encode("cp936")
    except UnicodeEncodeError as exc:
        line = code[: exc.start].count("\n") + 1
        bad = code[exc.start : exc.end]
        issues.append(
            Issue("error", line, "NON_GBK", f"字符 {bad!r} 无法用 GBK 保存")
        )

    if not raw_lines or not "".join(raw_lines).strip():
        issues.append(Issue("warning", 1, "EMPTY", "POU 代码为空"))

    return issues


def strip_comments(code: str) -> str:
    """Remove ``(* ... *)`` (possibly multi-line) and ``//`` comments."""

    out: list[str] = []
    in_comment = False
    for line in code.splitlines():
        buffer: list[str] = []
        index = 0
        while index < len(line):
            if in_comment:
                end = line.find("*)", index)
                if end == -1:
                    index = len(line)
                else:
                    in_comment = False
                    index = end + 2
            else:
                start = line.find("(*", index)
                if start == -1:
                    buffer.append(line[index:])
                    break
                buffer.append(line[index:start])
                in_comment = True
                index = start + 2
        text = "".join(buffer)
        if "//" in text:
            text = text.split("//", 1)[0]
        out.append(text)
    return "\n".join(out)


def _check_blocks(lines: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    stack: list[tuple[str, int]] = []
    repeat_line = 0

    for number, line in enumerate(lines, start=1):
        for word in WORD_RE.findall(line):
            upper = word.upper()
            if upper in OPENERS:
                stack.append((upper, number))
            elif upper in CLOSERS:
                _pop(stack, CLOSERS[upper], number, issues)
            elif upper == "REPEAT":
                repeat_line = number
            elif upper == "UNTIL":
                if repeat_line == 0:
                    issues.append(
                        Issue("error", number, "UNBALANCED", "UNTIL 没有对应的 REPEAT")
                    )
                else:
                    repeat_line = 0

    for start, number in stack:
        issues.append(
            Issue("error", number, "UNBALANCED", f"{start} 缺少对应的 END_{start}")
        )
    if repeat_line:
        issues.append(Issue("error", repeat_line, "UNBALANCED", "REPEAT 缺少 UNTIL"))
    return issues


def _pop(
    stack: list[tuple[str, int]], expected: str, number: int, issues: list[Issue]
) -> None:
    if not stack:
        issues.append(
            Issue("error", number, "UNBALANCED", f"END_{expected} 没有对应的 {expected}")
        )
        return
    start, line = stack[-1]
    if start != expected:
        issues.append(
            Issue(
                "error",
                number,
                "UNBALANCED",
                f"END_{expected} 与第 {line} 行的 {start} 不匹配",
            )
        )
        return
    stack.pop()


def _check_parens(lines: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    depth = 0
    for number, line in enumerate(lines, start=1):
        depth += line.count("(") - line.count(")")
        if depth < 0:
            issues.append(Issue("error", number, "UNBALANCED", "右括号多于左括号"))
            depth = 0
    if depth:
        issues.append(Issue("error", len(lines), "UNBALANCED", "左括号未闭合"))
    return issues
