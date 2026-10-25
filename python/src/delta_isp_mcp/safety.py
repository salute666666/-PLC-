"""Workspace, hash, process and file helpers shared by the service layer."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

ISP_PROCESS_NAMES = ("NewISPSoft.exe", "ISPSoft.exe")


class SafetyError(Exception):
    code = "SAFETY_BLOCKED"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_ispsoft_running() -> bool:
    """Return True when an ISPSoft process holds project files open."""

    try:
        result = subprocess.run(
            ["tasklist", "/NH"],
            capture_output=True,
            text=True,
            errors="ignore",
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    output = result.stdout.lower()
    return any(name.lower() in output for name in ISP_PROCESS_NAMES)


def ensure_within(path: Path, roots: list[Path]) -> Path:
    """Resolve ``path`` and require it to live under one of ``roots``."""

    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return resolved
        except ValueError:
            continue
    raise SafetyError(f"路径不在允许范围内：{resolved}")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write(path, text.encode("utf-8"))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def append_evidence(path: Path, record: dict) -> None:
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **record}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
