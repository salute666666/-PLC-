"""Command line entry points (also usable without an MCP client)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .isp.container import IspContainer
from .isp.project import ProjectDoc
from .isp.symbols import parse_symbols
from .safety import atomic_write_text, write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="delta-isp",
        description="Delta ISPSoft .isp toolkit: inspect, unpack, pack, serve MCP.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="查看容器与 POU 概览")
    p_inspect.add_argument("isp")

    p_pous = sub.add_parser("pous", help="列出 POU")
    p_pous.add_argument("isp")

    p_symbols = sub.add_parser("symbols", help="列出全局符号")
    p_symbols.add_argument("isp")

    p_unpack = sub.add_parser("unpack", help="解包为可编辑文本")
    p_unpack.add_argument("isp")
    p_unpack.add_argument("--out", default=None)

    p_pack = sub.add_parser("pack", help="从解包目录重新打包")
    p_pack.add_argument("dir")
    p_pack.add_argument("--out", default=None)

    p_serve = sub.add_parser("serve", help="启动 MCP stdio 服务")
    p_serve.add_argument("--workspace", default=str(Path.cwd() / "plc-work"))
    p_serve.add_argument("--allow-read", action="append", default=[])

    sub.add_parser("bridge", help="单次 JSON 请求（供 DSH 插件调用）")

    args = parser.parse_args(argv)

    if args.command == "inspect":
        container = IspContainer.open(args.isp)
        doc = ProjectDoc.parse(container.text)
        payload = container.summary()
        payload["pous"] = [pou.summary() for pou in doc.pous]
        payload["tasks"] = [task.summary() for task in doc.tasks]
        _print_json(payload)
        return 0

    if args.command == "pous":
        doc = ProjectDoc.parse(IspContainer.open(args.isp).text)
        _print_json([pou.summary() for pou in doc.pous])
        return 0

    if args.command == "symbols":
        doc = ProjectDoc.parse(IspContainer.open(args.isp).text)
        _print_json([symbol.summary() for symbol in parse_symbols(doc.text)])
        return 0

    if args.command == "unpack":
        container = IspContainer.open(args.isp)
        out = Path(args.out) if args.out else Path(args.isp).with_suffix("")
        out.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out / "project-source.txt", container.text)
        (out / "baseline.isp").write_bytes(container.raw)
        container.path = out / "baseline.isp"
        write_json(
            out / "meta.json",
            {
                "source": str(Path(args.isp).resolve()),
                "container": container.summary(),
            },
        )
        print(f"unpacked -> {out}", file=sys.stderr)
        return 0

    if args.command == "pack":
        workdir = Path(args.dir)
        container = IspContainer.open(workdir / "baseline.isp")
        text = (workdir / "project-source.txt").read_text(encoding="utf-8")
        out = Path(args.out) if args.out else workdir / "repacked.isp"
        evidence = container.write(out, text)
        _print_json(evidence)
        return 0

    if args.command == "serve":
        from .server import run_server

        run_server(args.workspace, args.allow_read)
        return 0

    if args.command == "bridge":
        return _bridge()

    return 1


def _bridge() -> int:
    """One JSON request on stdin, one JSON response on stdout.

    The DSH plugin spawns this once per tool call.  State survives because the
    service resumes the active project from ``workspace/active-project.json``.
    """

    from . import __version__
    from .ide.ispsoft import find_executable
    from .safety import is_ispsoft_running
    from .service import DeltaIspService

    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    payload = json.loads(sys.stdin.read() or "{}")
    workspace = payload.get("workspace") or str(Path.cwd() / "plc-work")
    allow_read = payload.get("allow_read") or []
    service = DeltaIspService(workspace, allow_read)

    op = payload.get("op", "")
    args = payload.get("args") or {}

    handlers = {
        "environment": lambda: {
            "version": __version__,
            "workspace": str(service.workspace),
            "allow_read": [str(item) for item in service.allow_read],
            "ispsoft_exe": str(find_executable() or ""),
            "ispsoft_running": is_ispsoft_running(),
            "active_project": service.summary()["source_path"] if service._ctx else None,
        },
        "project_open": lambda: service.open_project(args["path"]),
        "project_status": service.summary,
        "pou_list": service.pou_list,
        "pou_read": lambda: service.pou_read(args["name"]),
        "symbols": lambda: service.symbols(args.get("query"), int(args.get("limit", 200))),
        "tasks": service.tasks,
        "search": lambda: service.search(args["query"], int(args.get("limit", 50))),
        "pou_write": lambda: service.pou_write(
            args["name"], args["code"], args.get("variables")
        ),
        "create_selflock": lambda: service.create_selflock(
            name=args["name"],
            start=args["start"],
            stop=args["stop"],
            coil=args["coil"],
            indicator=args.get("indicator", ""),
            task_id=args.get("task_id"),
            comment=args.get("comment", ""),
        ),
        "create_st_pou": lambda: service.create_st_pou(
            name=args["name"],
            code=args["code"],
            variables=args.get("variables", ""),
            task_id=args.get("task_id"),
            comment=args.get("comment", ""),
        ),
        "lint": lambda: service.lint(args.get("pou"), args.get("code")),
        "diff": service.diff,
        "export": lambda: service.export(args.get("output")),
        "build": lambda: service.build(int(args.get("timeout", 180))),
        "open_in_ispsoft": service.open_in_ispsoft,
        "rollback": service.rollback,
    }

    if op not in handlers:
        result = {
            "ok": False,
            "error": {"code": "UNKNOWN_OP", "message": f"未知操作：{op}"},
        }
    else:
        try:
            result = {"ok": True, "data": handlers[op]()}
        except Exception as exc:  # noqa: BLE001 - errors are protocol data
            result = {
                "ok": False,
                "error": {
                    "code": getattr(exc, "code", "ERROR"),
                    "message": str(exc),
                },
            }

    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.flush()
    return 0


def _print_json(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
