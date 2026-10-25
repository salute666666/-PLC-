"""ISPSoft IDE bridge.

ISPSoft 3.19 exposes **no** command-line or COM compile API on this
workstation: the install directory ships ``NewISPSoft.exe`` (Delphi GUI),
``CRproj.exe`` and ``*_ILToMachineProject.dll`` but no documented automation
entry point.  Compilation is therefore a GUI step.

This module locates the IDE and can open a project for the user.  Automatic
build/compile-error capture is the next milestone (UI automation); until it
lands, :func:`compile_project` returns ``BUILD_UNAVAILABLE`` with exact manual
steps so the agent can keep working instead of guessing.
"""

from __future__ import annotations

import glob
import os
import subprocess
from pathlib import Path

MANUAL_STEPS = [
    "ISPSoft 会打开导出的工程副本（不会动你的原工程）",
    "菜单：编译(C) → 编译（或按 F7）",
    "把输出窗口里的错误行复制回对话，我据此继续修改",
]

COMMON_PATTERNS = [
    r"C:\Program Files (x86)\Delta Industrial Automation\ISPSoft*\NewISPSoft.exe",
    r"C:\Program Files\Delta Industrial Automation\ISPSoft*\NewISPSoft.exe",
    r"D:\Program Files (x86)\Delta Industrial Automation\ISPSoft*\NewISPSoft.exe",
    r"D:\Program Files\Delta Industrial Automation\ISPSoft*\NewISPSoft.exe",
    r"D:\Delta Industrial Automation\ISPSoft*\NewISPSoft.exe",
    r"E:\Delta Industrial Automation\ISPSoft*\NewISPSoft.exe",
]


def find_executable() -> Path | None:
    override = os.environ.get("DELTA_ISPSOFT_EXE")
    if override and Path(override).is_file():
        return Path(override)
    for pattern in COMMON_PATTERNS:
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return Path(matches[0])
    return None


def open_project(path: str | Path) -> dict:
    target = Path(path)
    executable = find_executable()
    if executable is None:
        return {
            "status": "unavailable",
            "reason": "找不到 NewISPSoft.exe；设置环境变量 DELTA_ISPSOFT_EXE 指向它",
            "file": str(target),
        }
    subprocess.Popen([str(executable), str(target)], cwd=str(target.parent))
    return {
        "status": "opened",
        "exe": str(executable),
        "file": str(target),
        "note": "工程是工作区副本；原工程没有被修改",
    }


def compile_project(path: str | Path, timeout: int = 180) -> dict:
    target = Path(path)
    executable = find_executable()
    result = {
        "status": "manual_required",
        "file": str(target),
        "exe": str(executable) if executable else None,
        "reason": "ISPSoft 3.19 没有公开的命令行/COM 编译接口，编译需在 IDE 内完成",
        "instructions": MANUAL_STEPS,
        "automation": "pending",
    }
    if executable is None:
        result["status"] = "unavailable"
        result["reason"] = "找不到 NewISPSoft.exe"
    return result
