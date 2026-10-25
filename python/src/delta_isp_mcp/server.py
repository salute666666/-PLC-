"""MCP (stdio) surface for the Delta ISPSoft service."""

import argparse
import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import __version__
from .ide.ispsoft import find_executable
from .safety import is_ispsoft_running
from .service import DeltaIspService

INSTRUCTIONS = """\
Delta ISPSoft PLC engineering service.

Workflow:
1. plc_project_open -> open a copy of an .isp project (the original is never modified).
2. plc_pou_list / plc_pou_read / plc_symbols / plc_tasks -> read before writing.
3. plc_pou_write -> replace one ST POU body (and optionally its local variables).
4. plc_lint -> cheap static checks; plc_build -> hand the project to ISPSoft.
5. plc_diff -> show exactly what changed; plc_export -> produce a new .isp.
6. plc_rollback -> discard the working copy changes.

Rules:
- Only ST POUs (P_Lang=4) can be rewritten in this phase; ladder POUs are read-only.
- Reuse existing global symbols and device addresses; never invent them.
- The project text is stored as GBK (cp936); avoid characters that cannot be encoded.
- Never download to a PLC without explicit human approval.
"""


def _ok(data):
    return {"ok": True, "data": data}


def _err(exc: Exception) -> dict:
    return {
        "ok": False,
        "error": {
            "code": getattr(exc, "code", "ERROR"),
            "message": str(exc),
        },
    }


def build_server(service: DeltaIspService) -> FastMCP:
    mcp = FastMCP(name="delta-isp-mcp", instructions=INSTRUCTIONS)

    # ---- read-only ----------------------------------------------------
    @mcp.tool()
    def plc_environment() -> dict:
        """查看服务版本、工作区、允许读取的目录，以及 ISPSoft 是否在运行。"""
        try:
            return _ok(
                {
                    "version": __version__,
                    "workspace": str(service.workspace),
                    "allow_read": [str(item) for item in service.allow_read],
                    "ispsoft_exe": str(find_executable() or ""),
                    "ispsoft_running": is_ispsoft_running(),
                    "python": sys.version.split()[0],
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            return _err(exc)

    @mcp.tool()
    def plc_project_open(path: str) -> dict:
        """打开 .isp 工程。会把工程复制到工作区，原文件不会被修改。"""
        try:
            return _ok(service.open_project(path))
        except Exception as exc:
            return _err(exc)

    @mcp.tool()
    def plc_project_status() -> dict:
        """当前工程的型号、版本、POU/任务数量、是否有未导出的改动。"""
        try:
            return _ok(service.summary())
        except Exception as exc:
            return _err(exc)

    @mcp.tool()
    def plc_pou_list() -> dict:
        """列出全部 POU：名称、类型、语言（LD/ST）、是否启用、所属任务。"""
        try:
            return _ok(service.pou_list())
        except Exception as exc:
            return _err(exc)

    @mcp.tool()
    def plc_pou_read(name: str) -> dict:
        """读取一个 POU：ST 代码或梯形图网络、局部变量、注释。"""
        try:
            return _ok(service.pou_read(name))
        except Exception as exc:
            return _err(exc)

    @mcp.tool()
    def plc_symbols(query: str | None = None, limit: int = 200) -> dict:
        """查询全局符号（变量名、设备地址、数据类型、注释）和 DUT 名称。"""
        try:
            return _ok(service.symbols(query, limit))
        except Exception as exc:
            return _err(exc)

    @mcp.tool()
    def plc_tasks() -> dict:
        """列出任务及其 POU 调用顺序。"""
        try:
            return _ok(service.tasks())
        except Exception as exc:
            return _err(exc)

    @mcp.tool()
    def plc_search(query: str, limit: int = 50) -> dict:
        """在整个工程文本里搜索（变量、地址、注释、指令），返回所在 POU 和行号。"""
        try:
            return _ok(service.search(query, limit))
        except Exception as exc:
            return _err(exc)

    # ---- write --------------------------------------------------------
    @mcp.tool()
    def plc_pou_write(name: str, code: str, variables: str | None = None) -> dict:
        """改写一个 ST POU 的程序体（可选同时改局部变量）。只写工作区副本。"""
        try:
            return _ok(service.pou_write(name, code, variables))
        except Exception as exc:
            return _err(exc)

    @mcp.tool()
    def plc_lint(pou: str | None = None, code: str | None = None) -> dict:
        """对 ST 代码做静态检查：块配对、全角字符、赋值符、GBK 可编码性。"""
        try:
            return _ok(service.lint(pou, code))
        except Exception as exc:
            return _err(exc)

    @mcp.tool()
    def plc_diff(full: bool = False) -> dict:
        """显示工作区相对基线的差异；默认只给摘要，full=True 给 unified diff。"""
        try:
            result = service.diff()
            if not full:
                result["diff"] = ""
            return _ok(result)
        except Exception as exc:
            return _err(exc)

    @mcp.tool()
    def plc_export(output: str | None = None) -> dict:
        """把工作区内容重新打包成 .isp，并校验能再次解析。"""
        try:
            return _ok(service.export(output))
        except Exception as exc:
            return _err(exc)

    @mcp.tool()
    def plc_build(timeout: int = 180) -> dict:
        """导出并请求 ISPSoft 编译；当前返回手动编译步骤与结构化占位。"""
        try:
            return _ok(service.build(timeout))
        except Exception as exc:
            return _err(exc)

    @mcp.tool()
    def plc_open_in_ispsoft() -> dict:
        """导出后在本机 ISPSoft 中打开工作区副本，供人工检查。"""
        try:
            return _ok(service.open_in_ispsoft())
        except Exception as exc:
            return _err(exc)

    @mcp.tool()
    def plc_rollback() -> dict:
        """放弃工作区改动，恢复到打开工程时的基线。"""
        try:
            return _ok(service.rollback())
        except Exception as exc:
            return _err(exc)

    # ---- resources / prompts -----------------------------------------
    @mcp.resource("plc://conventions", name="PLC 编程规范", mime_type="text/markdown")
    def conventions() -> str:
        return service.conventions()

    @mcp.resource(
        "plc://project/current",
        name="当前工程概览",
        mime_type="application/json",
    )
    def current_project() -> str:
        try:
            return json.dumps(service.summary(), ensure_ascii=False, indent=2)
        except Exception as exc:
            return json.dumps(_err(exc), ensure_ascii=False)

    @mcp.prompt(name="generate_st_pou")
    def generate_st_pou(requirement: str, pou: str = "") -> str:
        target = pou or "目标 POU"
        return (
            f"你是台达 AS 系列 PLC 工程师。请为 {target} 编写 ST 程序。\n"
            "先调用 plc_symbols 和 plc_pou_read 了解现有变量与风格，"
            "只使用工程里已存在的变量/地址；完成后调用 plc_lint 自检，"
            "再调用 plc_pou_write 写入。\n\n需求："
            + requirement
        )

    @mcp.prompt(name="review_plc_code")
    def review_plc_code(pou: str, code: str) -> str:
        return (
            f"请审查 {pou} 的 ST 代码，重点检查：输出是否有唯一驱动、"
            "急停/联锁是否依赖软件逻辑、扫描周期是否有无界循环、"
            "变量地址是否与工程一致、边界条件与复位逻辑。\n\n" + code
        )

    return mcp


def run_server(workspace: str, allow_read: list[str]) -> None:
    service = DeltaIspService(workspace, allow_read)
    mcp = build_server(service)
    mcp.run(transport="stdio")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="delta-isp-mcp")
    parser.add_argument("--workspace", default=str(Path.cwd() / "plc-work"))
    parser.add_argument("--allow-read", action="append", default=[])
    args = parser.parse_args(argv)
    run_server(args.workspace, args.allow_read)
    return 0
