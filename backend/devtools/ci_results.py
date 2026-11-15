"""同一源码的计划、执行回执及最终验收；不执行业务库操作或接受手填通过状态。"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree

from backend.devtools.isolated_environment import artifact_scope

ROOT = Path(__file__).resolve().parents[2]


def source_identity() -> dict:
    """包含未提交、新文件及删除；报告不可冒用另一提交或修改前的工作区。"""
    from backend.devtools.ci_changes import git

    digest = hashlib.sha256()
    paths = sorted(set(filter(None, git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0"))))
    for name in paths:
        path = ROOT / name
        digest.update(name.encode() + b"\0")
        if path.is_symlink():
            digest.update(b"link\0" + os.readlink(path).encode())
        elif path.is_file():
            digest.update(b"executable\0" if path.stat().st_mode & 0o111 else b"file\0")
            digest.update(path.read_bytes())
        else:
            digest.update(b"deleted")
        digest.update(b"\0")
    return {"commit": git("rev-parse", "HEAD").strip(), "sha256": digest.hexdigest()}


def results_directory(path: Path | None = None) -> Path:
    """远端各矩阵使用同名目录以合并产物，本地每次使用独立目录。"""
    if path is None:
        run = os.environ.get("GITHUB_RUN_ID")
        attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
        suffix = f"{run}-{attempt}" if run and run.isdigit() and attempt.isdigit() else uuid4().hex
        path = ROOT / ".local/tmp/ai-agent" / f"ci-results-{suffix}"
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def change_matrix(base: str | None = None, head: str | None = None) -> dict:
    """常用集合之外仅追加命中的专项，规模采用登记的代表性参数。"""
    from backend.devtools import ci

    data = ci.registry()
    assessment = ci.assess(base, head)
    selected = assessment["range"] or (None, None)
    items = ci.plan("common", *selected)["include"]
    for required in assessment["required_specials"]:
        name = required["suite"]
        entry = {"suite": name, "kind": data["suites"][name]["kind"]}
        if name == "backend-scale":
            entry["scale_stocks"] = data["suites"][name]["scale_stocks"]
        items.append(entry)
    return {"include": items}


def execution_plan(suite: str, base: str | None = None, head: str | None = None,
                   scale_stocks: int | None = None) -> dict:
    """计划保留必跑与待接入范围；直接改动未接入测试时不得静默漏检。"""
    from backend.devtools import ci

    assessment = ci.assess(base, head)
    items = ci.plan(suite, base, head)["include"]
    if suite == "backend-scale":
        if scale_stocks is None or not 100 <= scale_stocks <= 5000:
            raise ValueError("backend-scale 必须显式传 --scale-stocks 100..5000")
        items[0]["scale_stocks"] = scale_stocks
    changed = assessment["changed_paths"]
    pending = [entry for entry in assessment["not_integrated_e2e"] if changed is None or (
        entry["file"] in changed or any(fnmatch.fnmatch(path, pattern)
                                       for path in changed for pattern in entry.get("impact_paths", []))
    )]
    return {
        "schema": 1, "mode": suite, "source": source_identity(),
        "range": list(assessment["range"]) if assessment["range"] else None,
        "include": items, "required_specials": assessment["required_specials"],
        "not_integrated_e2e": assessment["not_integrated_e2e"],
        "pending_checks": pending if suite == "change" else [],
        "scope": assessment["scope"],
    }


def save_json(path: Path, value: dict) -> None:
    """先写临时文件再替换，取消时不留下貌似完整的回执。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def execute(suite: str, directory: Path, scale_stocks: int | None = None,
            base: str | None = None, head: str | None = None) -> int:
    """复用正式执行器；失败、异常及执行中源码变化均写失败回执并保留原因。"""
    from backend.devtools import ci

    receipt_path = directory / "receipts" / f"{suite}.json"
    if receipt_path.exists():
        raise ValueError(f"已有回执，重跑须使用新结果目录，禁止覆盖失败证据：{receipt_path}")
    selected_range = ci.assess(base, head)["range"]
    receipt = {
        "schema": 1, "suite": suite, "source": source_identity(),
        "range": list(selected_range) if selected_range else None, "status": "not-completed",
        "parameters": {"scale_stocks": scale_stocks} if suite == "backend-scale" else {},
        "reports": [], "exit_code": None,
    }
    artifacts = directory / "artifacts" / suite
    started = time.monotonic()
    try:
        with artifact_scope(artifacts):
            code = ci.run_suite(suite, scale_stocks, base, head)
        receipt["exit_code"] = code
        receipt["status"] = "passed" if code == 0 else "failed"
        return code
    except BaseException as exc:
        receipt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if source_identity() != receipt["source"]:
            receipt.update(status="failed", error="执行期间源码已变化，报告不适用于当前版本")
        for path in sorted(artifacts.rglob("*")):
            if path.is_file() and path.suffix in {".json", ".xml", ".info"}:
                receipt["reports"].append({
                    "path": path.relative_to(directory).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                })
        receipt["duration_seconds"] = round(time.monotonic() - started, 3)
        save_json(receipt_path, receipt)


def validate_evidence(suite: str, receipt: dict, directory: Path) -> None:
    """重新检查机器报告，不能仅凭回执中手填的 passed 或进程退出码通过。"""
    from backend.devtools import ci

    paths = []
    for report in receipt["reports"]:
        path = directory / report["path"]
        if not path.resolve().is_relative_to(directory.resolve()) or path.is_symlink():
            raise ValueError("报告路径越界")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != report["sha256"]:
            raise ValueError("报告缺失或摘要不匹配")
        paths.append(path)

    def one(filename):
        matches = [p for p in paths if p.name == filename]
        if len(matches) != 1:
            raise ValueError(f"报告缺失或重复：{filename}")
        return matches[0]

    kind = ci.registry()["suites"][suite]["kind"]
    if kind == "e2e":
        from backend.devtools.ci_e2e import validate_report

        expected = {Path(f).relative_to("frontend/e2e").as_posix()
                    for f, item in ci.registry()["special_files"].items() if item["suite"] == suite}
        count = validate_report(json.loads(one("e2e-planned.json").read_text()),
                                json.loads(one("e2e-actual.json").read_text()), expected)
        execution = json.loads(one("e2e-execution.json").read_text())
        if execution.get("status") != "passed" or execution.get("passed") != count or execution.get("service_restored") is not True:
            raise ValueError("浏览器执行或服务恢复未通过")
    elif kind in {"backend", "database"}:
        report = one(f"ci-{suite}.xml")
        suites = list(ElementTree.parse(report).iter("testsuite"))
        count = sum(int(s.get("tests", "0")) for s in suites)
        if count <= 0 or any(int(s.get(k, "0")) for s in suites for k in ("failures", "errors", "skipped")):
            raise ValueError("Python 测试为空、失败或包含跳过")
        if len(list(ElementTree.parse(report).iter("testcase"))) != count:
            raise ValueError("Python 测试汇总与实际用例不符")
        if kind == "backend":
            manifest = json.loads(one("ci-test-manifest.json").read_text())
            if manifest["suite"] != suite or len(manifest["selected"]) != count:
                raise ValueError("Python 实际清单与报告不符")
        if suite == "backend-scale":
            execution = json.loads(one("scale-execution.json").read_text())
            if execution["status"] != "passed" or execution["scale_stocks"] != receipt["parameters"]["scale_stocks"]:
                raise ValueError("规模参数或结果不符")
        else:
            from backend.devtools.ci_coverage import validate_report

            validate_report(report.parent)
    elif kind == "frontend":
        value = json.loads(one("ci-frontend.json").read_text())
        cases = [a for result in value["testResults"] for a in result["assertionResults"]]
        if (not value["success"] or not cases or value["numTotalTests"] != len(cases)
                or value["numPassedTests"] != len(cases)
                or any(c["status"] != "passed" for c in cases)
                or any(value[k] for k in ("numFailedTests", "numPendingTests", "numTodoTests"))):
            raise ValueError("前端测试失败或执行不完整")
        summary = json.loads(one("coverage-summary.json").read_text())
        measured = json.loads(one("coverage-final.json").read_text())
        if (summary["total"]["lines"]["total"] <= 0 or not measured
                or "SF:" not in one("lcov.info").read_text()):
            raise ValueError("前端覆盖率为空")
    elif kind == "audit":
        from backend.devtools.ci_dependencies import locked_versions

        python = json.loads(one("audit-python.json").read_text())
        npm = json.loads(one("audit-npm.json").read_text())
        actual = {d["name"].lower().replace("_", "-"): d["version"] for d in python["dependencies"]}
        if (actual != locked_versions() or any(d.get("vulns") or d.get("skip_reason") for d in python["dependencies"])
                or npm.get("error") or not npm["metadata"]["dependencies"]["total"]
                or npm["vulnerabilities"] or npm["metadata"]["vulnerabilities"]["total"]):
            raise ValueError("审计存在漏洞、未审计项或错误")
    elif kind == "secrets":
        # 精确例外及到期由原执行器判断；仍要求原始报告存在且可解析。
        if suite != "secrets-history":
            json.loads(one("secrets-source.json").read_text())
        json.loads(one("secrets-history.json" if suite == "secrets-history" else "secrets-commits.json").read_text())
    # quality 原执行器包含 Ruff 与 actionlint，非零或异常不能生成成功回执。


def reconcile(plan: dict, directory: Path) -> dict:
    """输出必跑、已跑、未完成；缺失、失败、旧源码或损坏报告一律不能验收。"""
    from backend.devtools import ci

    if plan.get("schema") != 1:
        raise ValueError("验收计划版本无效")
    registered = ci.registry()["suites"]
    if len({item["suite"] for item in plan["include"]}) != len(plan["include"]) or any(
        item["suite"] not in registered or item["kind"] != registered[item["suite"]]["kind"]
        for item in plan["include"]
    ):
        raise ValueError("验收计划存在重复或错误执行器")
    if plan["mode"] == "change":
        expected = execution_plan("change", *(plan["range"] or (None, None)))
        if any(plan[key] != expected[key] for key in (
            "include", "pending_checks", "required_specials", "source", "scope",
        )):
            raise ValueError("验收计划已漂移或遗漏必跑项，须重新规划")
    else:
        expected = ci.plan(plan["mode"], *(plan["range"] or (None, None)))["include"]
        names = {item["suite"] for item in plan["include"]}
        if not {item["suite"] for item in expected}.issubset(names) or any(
            name not in {item["suite"] for item in expected} and name != "dependency-audit"
            for name in names
        ):
            raise ValueError("套件计划遗漏必跑项或包含未登记项")
    rows = []
    current = source_identity()
    for item in plan["include"]:
        name = item["suite"]
        row = {"suite": name, "required": True, "status": "not-executed"}
        path = directory / "receipts" / f"{name}.json"
        if path.is_file():
            try:
                receipt = json.loads(path.read_text())
                expected = {"scale_stocks": item["scale_stocks"]} if name == "backend-scale" else {}
                if (receipt["schema"] != 1 or receipt["suite"] != name
                        or receipt["source"] != plan["source"] or current != plan["source"]
                        or receipt["range"] != plan["range"] or receipt["parameters"] != expected):
                    raise ValueError("回执不属于本次源码、范围或参数")
                if receipt["status"] != "passed" or receipt["exit_code"] != 0:
                    raise ValueError(receipt.get("error", "执行未通过"))
                validate_evidence(name, receipt, directory)
                row.update(status="passed", receipt=path.relative_to(directory).as_posix())
            except (ValueError, KeyError, TypeError, OSError, RuntimeError, ElementTree.ParseError) as exc:
                row.update(status="failed", reason=str(exc))
        rows.append(row)
    pending = plan["pending_checks"]
    passed = bool(rows) and all(r["status"] == "passed" for r in rows) and not pending
    if plan["mode"] == "change" and plan["scope"] != "known":
        passed = False
    result = {"schema": 1, "mode": plan["mode"], "source": plan["source"],
              "status": "passed" if passed else "not-completed", "checks": rows,
              "pending_checks": pending, "not_integrated_e2e": plan["not_integrated_e2e"]}
    save_json(directory / "ci-result.json", result)
    summary = [f"CI {plan['mode']}：{'通过' if passed else '未完成'}", "",
               "| 必跑检查 | 实际结果 |", "| --- | --- |"]
    labels = {"passed": "通过", "failed": "失败", "not-executed": "未执行"}
    summary += [f"| {row['suite']} | {labels[row['status']]} |" for row in rows]
    summary += [f"| {entry['file']} | 未完成：{entry['reason']} |" for entry in pending]
    text = "\n".join(summary) + "\n"
    (directory / "ci-result.md").write_text(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as output:
            output.write(text)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return result


def run_plan(plan: dict, directory: Path, base: str | None = None, head: str | None = None) -> int:
    """本地沿正式入口逐项执行，专项先行、常用最后；失败仍记录其他项和最终缺口。"""
    if any((directory / "receipts" / f"{item['suite']}.json").exists() for item in plan["include"]):
        raise ValueError("结果目录已有本次所选套件的回执；重跑使用新目录，复核已有证据使用 result")
    # 本地分步执行和远端矩阵都不能用局部计划覆盖已有总计划。
    save_json(directory / "plans" / f"{plan['mode']}.json", plan)
    global_path = directory / "ci-plan.json"
    if not os.environ.get("GITHUB_ACTIONS") and not global_path.exists():
        save_json(global_path, plan)
    from backend.devtools import ci

    common_names = {name for name, entry in ci.registry()["suites"].items() if entry["common"]}
    for item in sorted(plan["include"], key=lambda item: item["suite"] in common_names):
        try:
            execute(item["suite"], directory, item.get("scale_stocks"), base, head)
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
            print(f"CI {item['suite']} 未完成：{exc}", flush=True)
    total = json.loads(global_path.read_text()) if global_path.exists() else plan
    target = total if total["mode"] == "change" else plan
    return 0 if reconcile(target, directory)["status"] == "passed" else 1
