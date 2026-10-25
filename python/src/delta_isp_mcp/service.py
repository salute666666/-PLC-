"""Stateful operations behind the MCP tools and the CLI.

A *workspace* is created per project revision.  The original ``.isp`` is
copied once as ``baseline.isp``; the editable project source lives in
``working-source.txt`` (UTF-8 on disk, GBK inside the container).  Nothing in
this module ever writes back to the user's source project.
"""

from __future__ import annotations

import difflib
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from . import __version__
from .isp.container import IspContainer, IspError
from .isp.ladder import selflock_network
from .isp.project import ProjectDoc, add_ladder_pou, add_st_pou
from .isp.symbols import parse_dut_names, parse_symbols
from .lint.st_check import check_st
from .safety import (
    append_evidence,
    atomic_write_text,
    ensure_within,
    is_ispsoft_running,
    sha256_file,
    write_json,
)


class ServiceError(Exception):
    code = "SERVICE_ERROR"


class NoProject(ServiceError):
    code = "NO_PROJECT"


@dataclass
class ProjectContext:
    workdir: Path
    source_path: Path
    baseline_isp: Path
    baseline_source: Path
    working_source: Path
    evidence_path: Path
    container: IspContainer
    baseline_text: str
    text: str
    doc: ProjectDoc
    dirty: bool = False
    meta: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return Path(self.source_path).stem

    def save_working(self) -> None:
        atomic_write_text(self.working_source, self.text)

    def evidence(self, action: str, **fields) -> None:
        append_evidence(
            self.evidence_path,
            {
                "action": action,
                "project": self.name,
                "dirty": self.dirty,
                **fields,
            },
        )


class DeltaIspService:
    def __init__(
        self,
        workspace: str | Path,
        allow_read: Sequence[str | Path] | None = None,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.allow_read = [Path(item).expanduser().resolve() for item in (allow_read or [])]
        self._active_file = self.workspace / "active-project.json"
        self._ctx: ProjectContext | None = None
        self._resume()

    # ---- session ------------------------------------------------------
    def _resume(self) -> None:
        if not self._active_file.exists():
            return
        try:
            payload = json.loads(self._active_file.read_text(encoding="utf-8"))
            workdir = Path(payload["workdir"])
            if workdir.exists():
                self._load(workdir, Path(payload["source_path"]))
        except Exception:  # pragma: no cover - corrupt session file
            self._ctx = None

    def _load(self, workdir: Path, source_path: Path) -> ProjectContext:
        baseline_isp = workdir / "baseline.isp"
        baseline_source = workdir / "baseline-source.txt"
        working_source = workdir / "working-source.txt"
        container = IspContainer.open(baseline_isp)
        baseline_text = container.text
        if not baseline_source.exists():
            atomic_write_text(baseline_source, baseline_text)
        text = working_source.read_text(encoding="utf-8") if working_source.exists() else baseline_text
        doc = ProjectDoc.parse(text)
        ctx = ProjectContext(
            workdir=workdir,
            source_path=source_path,
            baseline_isp=baseline_isp,
            baseline_source=baseline_source,
            working_source=working_source,
            evidence_path=workdir / "evidence.jsonl",
            container=container,
            baseline_text=baseline_text,
            text=text,
            doc=doc,
            dirty=text != baseline_text,
            meta={},
        )
        self._ctx = ctx
        try:
            write_json(
                self._active_file,
                {"workdir": str(workdir), "source_path": str(source_path)},
            )
        except OSError:
            # A read-only workspace must not prevent resuming this process.
            pass
        return ctx

    def require(self) -> ProjectContext:
        if self._ctx is None:
            raise NoProject("还没有打开工程；先调用 plc_project_open")
        return self._ctx

    # ---- opening ------------------------------------------------------
    def open_project(self, path: str | Path, *, force: bool = False) -> dict:
        source = Path(path).expanduser()
        if source.suffix.lower() != ".isp":
            raise ServiceError("只支持 .isp 工程文件")
        if not source.exists():
            raise ServiceError(f"文件不存在：{source}")
        source = source.resolve()

        if self.allow_read:
            ensure_within(source, self.allow_read)
        if source.stat().st_size > 32 * 1024 * 1024:
            raise ServiceError("工程文件超过 32 MB")

        sha = sha256_file(source)
        slug = re.sub(r"[^\w\-]+", "_", source.stem)[:40] + "-" + sha[:8]
        workdir = self.workspace / "projects" / slug
        baseline_isp = workdir / "baseline.isp"

        if not baseline_isp.exists():
            workdir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, baseline_isp)
            atomic_write_text(workdir / "source-path.txt", str(source) + "\n")
            write_json(workdir / "meta.json", {"source": str(source), "sha256": sha})

        ctx = self._load(workdir, source)
        ctx.meta = {"source_sha256": sha, "locked_warning": is_ispsoft_running()}
        ctx.evidence("open", source_sha256=sha)
        return self.summary()

    # ---- read ---------------------------------------------------------
    def summary(self) -> dict:
        ctx = self.require()
        languages: dict[str, int] = {}
        for pou in ctx.doc.pous:
            languages[pou.language] = languages.get(pou.language, 0) + 1
        info = ctx.container.summary()
        info.update(
            {
                "workspace": str(ctx.workdir),
                "source_path": str(ctx.source_path),
                "dirty": ctx.dirty,
                "languages": languages,
                "task_count": len(ctx.doc.tasks),
                "symbol_count": len(parse_symbols(ctx.text)),
                "ispsoft_running": is_ispsoft_running(),
            }
        )
        return info

    def pou_list(self) -> list[dict]:
        ctx = self.require()
        in_tasks = {
            name: ids for name, ids in ctx.doc.used_in_tasks().items()
        }
        result = []
        for pou in ctx.doc.pous:
            item = pou.summary()
            item["tasks"] = in_tasks.get(pou.name, [])
            result.append(item)
        return result

    def pou_read(self, name: str) -> dict:
        ctx = self.require()
        pou = ctx.doc.get_pou(name)
        return {
            "name": pou.name,
            "type": "FB" if pou.ptype == 1 else "PRG",
            "language": pou.language,
            "active": pou.active,
            "comment": pou.comment,
            "variables": pou.local_vars,
            "code": pou.st_code,
            "networks": pou.networks,
            "tasks": ctx.doc.used_in_tasks().get(pou.name, []),
        }

    def symbols(self, query: str | None = None, limit: int = 200) -> dict:
        ctx = self.require()
        items = [symbol.summary() for symbol in parse_symbols(ctx.text)]
        if query:
            needle = query.casefold()
            items = [
                item
                for item in items
                if needle in item["name"].casefold()
                or needle in item["device"].casefold()
                or needle in item["comment"].casefold()
            ]
        return {
            "total": len(items),
            "items": items[: max(1, min(limit, 2000))],
            "duts": parse_dut_names(ctx.text),
        }

    def tasks(self) -> list[dict]:
        ctx = self.require()
        return [task.summary() for task in ctx.doc.tasks]

    def search(self, query: str, limit: int = 50) -> list[dict]:
        ctx = self.require()
        if not query:
            raise ServiceError("搜索关键字不能为空")
        needle = query.casefold()
        hits: list[dict] = []
        spans = [(pou.name, pou.span) for pou in ctx.doc.pous]
        offset = 0
        for number, raw_line in enumerate(ctx.text.splitlines(keepends=True), start=1):
            line = raw_line.rstrip("\r\n")
            current = offset
            offset += len(raw_line)
            if needle not in line.casefold():
                continue
            owner = next(
                (name for name, (start, end) in spans if start <= current < end),
                "<project>",
            )
            hits.append(
                {
                    "line": number,
                    "pou": owner,
                    "text": line.strip()[:200],
                }
            )
            if len(hits) >= limit:
                break
        return hits

    # ---- write --------------------------------------------------------
    def pou_write(
        self, name: str, code: str, variables: str | None = None
    ) -> dict:
        ctx = self.require()
        issues = check_st(code)
        errors = [issue.as_dict() for issue in issues if issue.severity == "error"]
        if errors:
            raise ServiceError(
                "ST 静态检查未通过：" + "；".join(f"第{e['line']}行 {e['message']}" for e in errors[:5])
            )

        new_text = ctx.doc.set_st_code(name, code, variables)
        ctx.doc = ProjectDoc.parse(new_text)
        ctx.text = new_text
        ctx.dirty = ctx.text != ctx.baseline_text
        ctx.save_working()

        pou = ctx.doc.get_pou(name)
        ctx.evidence(
            "pou_write",
            pou=pou.name,
            code_lines=len((pou.st_code or "").splitlines()),
        )
        return {
            "name": pou.name,
            "language": pou.language,
            "dirty": ctx.dirty,
            "issues": [issue.as_dict() for issue in issues],
            "diff": self.diff(changed_only=True)["summary"],
        }

    def create_selflock(
        self,
        name: str,
        start: str,
        stop: str,
        coil: str,
        indicator: str = "",
        task_id: int | None = None,
        comment: str = "",
    ) -> dict:
        """Create a new ladder POU with a start/stop self-hold rung."""

        ctx = self.require()
        if not (start and stop and coil):
            raise ServiceError("start / stop / coil 不能为空")
        network = selflock_network(start, stop, coil, indicator, comment)
        new_text = add_ladder_pou(
            ctx.text,
            name=name,
            network=network,
            comment=comment or f"电机自锁：{start} 启动，{stop} 停止",
            task_id=task_id,
        )
        ctx.doc = ProjectDoc.parse(new_text)
        ctx.text = new_text
        ctx.dirty = ctx.text != ctx.baseline_text
        ctx.save_working()
        pou = ctx.doc.get_pou(name)
        ctx.evidence("pou_create_selflock", pou=pou.name, task=task_id)
        return {
            "name": pou.name,
            "language": pou.language,
            "networks": len(pou.networks),
            "task": task_id,
            "devices": {
                "start": start,
                "stop": stop,
                "coil": coil,
                "indicator": indicator,
            },
            "dirty": ctx.dirty,
        }

    def create_st_pou(
        self,
        name: str,
        code: str,
        variables: str = "",
        task_id: int | None = None,
        comment: str = "",
    ) -> dict:
        """Create a new ST POU and optionally attach it to a task."""

        ctx = self.require()
        if not name.strip():
            raise ServiceError("POU 名称不能为空")
        issues = check_st(code)
        errors = [issue.as_dict() for issue in issues if issue.severity == "error"]
        if errors:
            raise ServiceError(
                "ST 静态检查未通过："
                + "；".join(
                    f"第{e['line']}行 {e['message']}" for e in errors[:5]
                )
            )
        new_text = add_st_pou(
            ctx.text,
            name=name,
            code=code,
            variables=variables,
            comment=comment,
            task_id=task_id,
        )
        ctx.doc = ProjectDoc.parse(new_text)
        ctx.text = new_text
        ctx.dirty = ctx.text != ctx.baseline_text
        ctx.save_working()
        pou = ctx.doc.get_pou(name)
        ctx.evidence("pou_create_st", pou=pou.name, task=task_id)
        return {
            "name": pou.name,
            "language": pou.language,
            "task": task_id,
            "code_lines": len((pou.st_code or "").splitlines()),
            "variables_lines": len(
                [line for line in pou.local_vars.splitlines() if line.strip()]
            ),
            "issues": [issue.as_dict() for issue in issues],
            "dirty": ctx.dirty,
        }

    def lint(self, name: str | None = None, code: str | None = None) -> dict:
        ctx = self.require()
        if code is None:
            if not name:
                raise ServiceError("lint 需要 pou 或 code")
            code = ctx.doc.get_pou(name).st_code or ""
        issues = check_st(code)
        return {
            "pou": name,
            "issues": [issue.as_dict() for issue in issues],
            "errors": sum(1 for issue in issues if issue.severity == "error"),
            "warnings": sum(1 for issue in issues if issue.severity == "warning"),
        }

    def rollback(self) -> dict:
        ctx = self.require()
        ctx.text = ctx.baseline_text
        ctx.doc = ProjectDoc.parse(ctx.text)
        ctx.dirty = False
        ctx.save_working()
        ctx.evidence("rollback")
        return {"dirty": False, "restored_from": str(ctx.baseline_isp)}

    # ---- diff / export ------------------------------------------------
    def diff(self, changed_only: bool = False) -> dict:
        ctx = self.require()
        old = ctx.baseline_text.splitlines()
        new = ctx.text.splitlines()
        lines = list(
            difflib.unified_diff(old, new, fromfile="baseline", tofile="working", lineterm="", n=2)
        )
        changed: list[str] = []
        base = {pou.name: pou for pou in ProjectDoc.parse(ctx.baseline_text).pous}
        work = {pou.name: pou for pou in ctx.doc.pous}
        for name in sorted(set(base) | set(work)):
            if name not in base:
                changed.append(f"+{name}")
            elif name not in work:
                changed.append(f"-{name}")
            elif (
                _normalize_newlines(base[name].st_code or "")
                != _normalize_newlines(work[name].st_code or "")
                or _normalize_newlines(base[name].local_vars)
                != _normalize_newlines(work[name].local_vars)
            ):
                changed.append(name)
        summary = {
            "changed_pous": changed,
            "added_lines": sum(1 for line in lines if line.startswith("+") and not line.startswith("+++")),
            "removed_lines": sum(1 for line in lines if line.startswith("-") and not line.startswith("---")),
        }
        text = "\n".join(lines)
        truncated = len(lines) > 600
        if truncated:
            text = "\n".join(lines[:600]) + "\n... (截断)"
        return {
            "summary": summary,
            "diff": "" if changed_only else text,
            "truncated": truncated,
        }

    def export(self, output: str | Path | None = None) -> dict:
        ctx = self.require()
        if output is None:
            target = ctx.workdir / "exports" / f"{ctx.source_path.stem}-modified.isp"
        else:
            target = Path(output).expanduser().resolve()
            if self.allow_read and not any(
                _is_relative_to(target, root) for root in [self.workspace, *self.allow_read]
            ):
                raise ServiceError("导出路径不在允许范围内")
        evidence = ctx.container.write(target, ctx.text)
        check = IspContainer.open(target)
        if check.text != ctx.text:
            raise IspError("导出后源码校验失败")
        ctx.evidence("export", **evidence)
        return {"dirty": ctx.dirty, **evidence}

    def open_in_ispsoft(self) -> dict:
        ctx = self.require()
        exported = self.export()
        from .ide import ispsoft

        return ispsoft.open_project(Path(exported["output"]))

    def build(self, timeout: int = 180) -> dict:
        ctx = self.require()
        exported = self.export()
        from .ide import ispsoft

        result = ispsoft.compile_project(Path(exported["output"]), timeout=timeout)
        ctx.evidence("build", status=result.get("status"), output=exported["output"])
        return {"file": exported["output"], **result}

    # ---- meta ---------------------------------------------------------
    def conventions(self) -> str:
        return _read_conventions()


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _read_conventions() -> str:
    local = Path(__file__).resolve().parents[2] / "prompts" / "plc-rules.md"
    if local.exists():
        return local.read_text(encoding="utf-8")
    return (
        "# Delta PLC code rules\n"
        "- ST only in phase 1; never touch ladder POUs.\n"
        "- Use existing global symbols and device addresses; do not invent them.\n"
        "- Every output must have exactly one driver.\n"
        "- Keep scan time bounded: no unbounded loops.\n"
    )


def service_version() -> str:
    return __version__
