"""本地与 GitHub 共用的 CI 编排；默认发现测试，专项例外由唯一登记表维护。"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

from backend.devtools.ci_changes import changed_paths, commit_range
from backend.devtools.ci_dependencies import check_installed, check_lock
from backend.devtools.isolated_environment import (
    create_ci_artifact_dir,
    isolated_storage_environment,
)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "config/ci-suites.json"
DOC = ROOT / "agent-works/architecture/continuous-integration.md"
E2E_TEST_FILE = re.compile(r".+\.(?:spec|test)\.[cm]?[jt]sx?$")


def validate_impact_paths(name: str, paths) -> None:
    """执行专项和待整合测试共用路径契约，防止改名后登记永不命中。"""
    if (not isinstance(paths, list) or not paths or any(
        not isinstance(path, str) or not path or path.startswith("/")
        or ".." in Path(path).parts for path in paths
    )):
        raise ValueError(f"专项变更路径规则不完整：{name}")
    if any(not any(source.is_file() for source in ROOT.glob(path)) for path in paths):
        raise ValueError(f"专项变更路径登记失效：{name}")


def registry() -> dict:
    """读取并校验执行分类；路径失效、未知执行器及无说明例外直接失败。"""
    data = json.loads(REGISTRY.read_text())
    suites = data["suites"]
    if any(entry["kind"] == "e2e" for entry in suites.values()):
        validate_impact_paths("共用浏览器执行基础设施", data.get("e2e_impact_paths"))
    for name, suite in suites.items():
        if not name or suite["kind"] not in {"frontend", "backend", "database", "quality", "secrets", "audit", "e2e"}:
            raise ValueError(f"非法 CI 套件：{name}")
        if not isinstance(suite["common"], bool) or not suite["description"]:
            raise ValueError(f"CI 套件信息不完整：{name}")
        if suite.get("when") not in {None, "dependencies"}:
            raise ValueError(f"未知 CI 调用条件：{name}")
        if suite.get("when") and not data.get("dependency_paths"):
            raise ValueError("条件套件缺少依赖路径规则")
        if name == "backend-scale" and (
            type(suite.get("scale_stocks")) is not int or not 100 <= suite["scale_stocks"] <= 5000
        ):
            raise ValueError("规模专项缺少有效的代表性参数")
        if "impact_paths" in suite:
            validate_impact_paths(name, suite["impact_paths"])
        if suite["kind"] == "e2e":
            from backend.devtools.ci_e2e import RUNNERS

            profile = suite.get("e2e", {})
            projects = profile.get("projects", [])
            if profile.get("runner") not in RUNNERS or not projects:
                raise ValueError(f"E2E 专项缺少已有 runner 或项目：{name}")
            names = [project.get("name") for project in projects]
            if len(set(names)) != len(names) or any(
                project not in {"chromium-standard", "chromium-compact", "chromium-default"}
                for project in names
            ):
                raise ValueError(f"E2E 专项项目重复或失效：{name}")
            if any(
                key in project and (not isinstance(project[key], str) or not project[key])
                for project in projects for key in ("title", "exclude_title")
            ):
                raise ValueError(f"E2E 项目用例选择条件不完整：{name}")
    for category in ("special_files", "special_nodes"):
        for path, entry in data[category].items():
            if (
                entry["suite"] not in {*suites, "manual-market", "manual-e2e", "not-applicable"}
                or not entry["reason"]
            ):
                raise ValueError(f"CI 专项登记不完整：{path}")
            target = entry["suite"]
            source = (ROOT / path.split("::")[0]).resolve()
            if source.is_relative_to(ROOT / "frontend/e2e"):
                if category != "special_files" or not E2E_TEST_FILE.fullmatch(source.name) or (
                    target != "manual-e2e" and suites.get(target, {}).get("kind") != "e2e"
                ):
                    raise ValueError(f"E2E 用例不能分流至此执行器：{path}")
                if not source.is_file():
                    raise ValueError(f"CI 专项登记路径失效：{path}")
                if target == "manual-e2e" and entry.get("review_status") not in {
                    "manual-design", "migration-required",
                }:
                    raise ValueError(f"未整合 E2E 缺少具体审查结论：{path}")
                if "impact_paths" in entry:
                    validate_impact_paths(path, entry["impact_paths"])
                continue
            if target == "manual-e2e":
                raise ValueError(f"后端测试不能分流至 E2E：{path}")
            if target in suites:
                kind = suites[target]["kind"]
                if kind not in {"backend", "database"} or (
                    category == "special_nodes" and kind == "database"
                ):
                    raise ValueError(f"Python 测试不能分流至此执行器：{path}")
            if category == "special_nodes" and path.split("::")[0] in data["special_files"]:
                raise ValueError(f"文件与用例专项登记重叠：{path}")
            if not source.is_file() or not source.is_relative_to(ROOT / "backend/tests"):
                raise ValueError(f"CI 专项登记路径失效：{path}")
    # E2E 的物理夹具不能靠目录猜测。新文件必须选择可执行专项或明确登记待接入原因。
    unregistered = {
        path.relative_to(ROOT).as_posix() for path in (ROOT / "frontend/e2e").rglob("*")
        if path.is_file() and E2E_TEST_FILE.fullmatch(path.name)
    } - data["special_files"].keys()
    if unregistered:
        raise ValueError("E2E 文件缺少专项归属登记：" + ", ".join(sorted(unregistered)))
    for name, suite in suites.items():
        if suite["kind"] == "e2e" and not any(
            entry["suite"] == name for entry in data["special_files"].values()
        ):
            raise ValueError(f"E2E 专项缺少用例登记：{name}")
    return data


def suite_impact_paths(data: dict, entry: dict) -> list[str]:
    """新增浏览器组自动继承共享装配规则，领域路径只在本组维护。"""
    shared = data.get("e2e_impact_paths", []) if entry["kind"] == "e2e" else []
    return list(dict.fromkeys([*shared, *entry.get("impact_paths", [])]))


def plan(suite: str = "common", base: str | None = None, head: str | None = None) -> dict:
    """按登记生成 Actions 矩阵；新常用套件无需另改触发器或调用方。"""
    if suite == "change":
        from backend.devtools.ci_results import change_matrix

        return change_matrix(base, head)
    data = registry()
    suites = data["suites"]
    if suite != "common" and suite not in suites:
        raise ValueError(f"未知 CI 套件 {suite}；可选 common、" + "、".join(suites))
    paths = changed_paths(commit_range(base, head)) if suite == "common" else None
    result = {
        "include": [
            {"suite": name, "kind": entry["kind"]}
            for name, entry in suites.items()
            if (
                entry["common"] and (
                    entry.get("when") != "dependencies" or paths is None
                    or any(fnmatch.fnmatch(path, pattern) for path in paths
                           for pattern in data["dependency_paths"])
                ) if suite == "common" else name == suite
            )
        ]
    }
    if not result["include"]:
        raise ValueError("常用 CI 集合为空，禁止以未执行冒充通过")
    return result


def inventory() -> str:
    """文档的套件与例外表均从登记生成，不人工维护第二份列表。"""
    data = registry()
    lines = ["| 套件 | 类别 | 常用入口自动调用 | 覆盖 |", "| --- | --- | --- | --- |"]
    for name, entry in data["suites"].items():
        common = "依赖变更时；范围未知时保守执行" if entry.get("when") == "dependencies" else (
            "是" if entry["common"] else "否"
        )
        lines.append(f"| `{name}` | {entry['kind']} | {common} | {entry['description']} |")
    lines += ["", "| 专项文件或用例 | 归属 | 原因 |", "| --- | --- | --- |"]
    for category in ("special_files", "special_nodes"):
        for name, entry in data[category].items():
            lines.append(f"| `{name}` | `{entry['suite']}` | {entry['reason']} |")
    lines += ["", "| 专项 | 变更命中路径 | 执行方式 |", "| --- | --- | --- |"]
    for name, entry in data["suites"].items():
        patterns = suite_impact_paths(data, entry)
        if patterns:
            paths = "、".join(f"`{path}`" for path in patterns)
            lines.append(f"| `{name}` | {paths} | `run change` 按命中调用；`run {name}` 显式执行 |")
    return "\n".join(lines)


def assess(base: str | None = None, head: str | None = None) -> dict:
    """变更命中专项即列为应执行；范围未知不推断无影响，计划不冒充执行结果。"""
    from backend.devtools.ci_changes import git

    data = registry()
    selected = commit_range(base, head)
    if selected is None and base is None and head is None and not os.getenv("GITHUB_EVENT_PATH"):
        revision = git("rev-parse", "HEAD").strip()
        selected = commit_range(revision, revision)
    paths = changed_paths(selected)
    required = []
    for name, entry in data["suites"].items():
        patterns = suite_impact_paths(data, entry)
        matched = sorted(path for path in paths or [] if any(fnmatch.fnmatch(path, p) for p in patterns))
        if patterns and (paths is None or matched):
            required.append({
                "suite": name, "status": "not-executed", "matched_paths": matched,
                "command": f"scripts/run-ci.sh run {name}",
                "required_parameters": {"scale_stocks": {"minimum": 100, "maximum": 5000}}
                if name == "backend-scale" else {},
            })
    return {
        "range": selected, "scope": "known" if paths is not None else "review-required",
        "changed_paths": sorted(paths) if paths is not None else None,
        "required_specials": required,
        "not_integrated_e2e": [
            {"file": path, "reason": entry["reason"], "review_status": entry["review_status"],
             "impact_paths": entry.get("impact_paths", [])}
            for path, entry in data["special_files"].items() if entry["suite"] == "manual-e2e"
        ],
        "note": "这是必跑计划，不是通过证据；命中专项须实际执行并核对其报告，未编码语义仍须审查。",
    }


def check_document(*, write: bool = False) -> None:
    """检查/更新限定生成块；保护块外机制正文。"""
    source = DOC.read_text()
    start, end = "<!-- ci-inventory:start -->", "<!-- ci-inventory:end -->"
    before, rest = source.split(start)
    _, after = rest.split(end)
    generated = "\n".join("  " + line if line else "" for line in inventory().splitlines())
    expected = before + start + "\n" + generated + "\n  " + end + after
    if write:
        DOC.write_text(expected)
    elif source != expected:
        raise ValueError("CI 文档登记已过期，请执行 scripts/run-ci.sh docs --write")


def bootstrap() -> None:
    """子进程在显式临时连接下走正式初始化；环境必须在导入配置前设置。"""
    from backend.storage.database_lifecycle import initialize_database
    from backend.storage.duckdb_client import get_client
    from backend.storage.pg_client import get_pg_client

    report = initialize_database(get_client(), get_pg_client(), mode="init")
    if not report["ok"]:
        raise RuntimeError("CI 临时数据库初始化失败")


def run_test_process(command: list[str], env: dict[str, str]) -> int:
    """测试及其 spawn 工作进程归同一进程组；取消/超时不能遗留进程池。"""
    process = subprocess.Popen(command, cwd=ROOT, env=env, start_new_session=True)
    try:
        return process.wait(timeout=1500)
    finally:
        # 正常退出也清理可能泄漏的子进程，进程组号不会与业务服务相同。
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def run_backend(suite: str, scale_stocks: int | None = None) -> int:
    """先准备独立三库，再执行同一套收集和失败关闭机制。"""
    from backend.devtools.database_gate import gate_server

    if suite == "backend-scale" and (scale_stocks is None or not 100 <= scale_stocks <= 5000):
        raise ValueError("backend-scale 必须显式传 --scale-stocks 100..5000")
    check_installed()
    artifact_dir = create_ci_artifact_dir()
    with (
        gate_server(artifact_dir) as admin,
        isolated_storage_environment(admin, artifact_dir) as env,
    ):
        env["AI_STOCKS_CI_SUITE"] = suite
        env["AI_STOCKS_CI_TEST_MANIFEST"] = str(artifact_dir / "ci-test-manifest.json")
        if scale_stocks is not None:
            env.update(
                {
                    "INTRADAY_SCALE_STOCKS": str(scale_stocks),
                    "STOCK_INGEST_SCALE_STOCKS": str(scale_stocks),
                }
            )
        subprocess.run(
            [sys.executable, "-c", "from backend.devtools.ci import bootstrap; bootstrap()"],
            cwd=ROOT,
            env=env,
            check=True,
        )
        from backend.devtools.ci_coverage import pytest_arguments, validate_report

        coverage = pytest_arguments(artifact_dir, env) if suite == "backend" else []
        code = run_test_process(
            [
                sys.executable,
                "-m",
                "pytest",
                "backend/tests",
                "-p",
                "backend.devtools.ci_pytest_plugin",
                "-o",
                "addopts=",
                "--strict-markers",
                "-v",
                "-o",
                "faulthandler_timeout=120",
                "--durations=15",
                "--tb=short",
                f"--junitxml={artifact_dir / ('ci-' + suite + '.xml')}",
                "-o", "junit_logging=all",
                *coverage,
            ],
            env,
        )
        if code == 0 and coverage:
            validate_report(artifact_dir)
        if suite == "backend-scale":
            (artifact_dir / "scale-execution.json").write_text(json.dumps({
                "suite": suite, "scale_stocks": scale_stocks,
                "status": "passed" if code == 0 else "failed",
                "junit": str(artifact_dir / f"ci-{suite}.xml"),
                "manifest": str(artifact_dir / "ci-test-manifest.json"),
            }, ensure_ascii=False, indent=2))
        return code


def run_suite(suite: str, scale_stocks: int | None = None,
              base: str | None = None, head: str | None = None) -> int:
    """常用编排和手动专项最终调用相同执行器，任一失败使总入口失败。"""
    check_document()
    check_lock()
    for item in plan(suite, base, head)["include"]:
        name, kind = item["suite"], item["kind"]
        print(f"CI 开始：{name}", flush=True)
        if kind == "backend":
            code = run_backend(name, scale_stocks)
        elif kind == "database":
            from backend.devtools.database_gate import run_gate

            check_installed()
            code = run_gate(suite=name, coverage=True)
        elif kind == "quality":
            from backend.devtools.ci_quality import run_quality

            code = run_quality()
        elif kind == "secrets":
            from backend.devtools.ci_secrets import run_secrets

            code = run_secrets(commit_range(base, head), history=name == "secrets-history")
        elif kind == "audit":
            from backend.devtools.ci_dependencies import run_audit

            code = run_audit()
        elif kind == "e2e":
            from backend.devtools.ci_e2e import run_e2e

            code = run_e2e(name)
        else:
            env = os.environ.copy()
            env["CI"] = "1"
            env["AI_STOCKS_CI_ARTIFACT_DIR"] = str(create_ci_artifact_dir())
            code = run_test_process(["npm", "--prefix", "frontend", "run", "ci"], env)
        if code:
            return code
    return 0


def main() -> int:
    # Actions 取消时仍退出上下文，清理自建数据库与进程；不改变业务服务状态。
    def terminate(_signum, _frame):
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "plan", "assess", "check", "docs", "lock", "prepare", "result"))
    parser.add_argument("suite", nargs="?", default="common")
    parser.add_argument("--scale-stocks", type=int)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--upgrade-package", action="append", default=[])
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument("--plan-file", type=Path)
    args = parser.parse_args()
    try:
        if args.action in {"prepare", "result"}:
            from backend.devtools.ci_results import (
                execution_plan,
                reconcile,
                results_directory,
                save_json,
            )

            directory = results_directory(args.results_dir)
            if args.action == "prepare":
                check_document()
                check_lock()
                value = execution_plan(args.suite, args.base, args.head, args.scale_stocks)
                save_json(directory / "ci-plan.json", value)
                print(json.dumps({"include": value["include"]}))
            else:
                value = json.loads((args.plan_file or directory / "ci-plan.json").read_text())
                return 0 if reconcile(value, directory)["status"] == "passed" else 1
        elif args.action == "plan":
            check_lock()
            print(json.dumps(plan(args.suite, args.base, args.head)))
        elif args.action == "assess":
            check_lock()
            print(json.dumps(assess(args.base, args.head), ensure_ascii=False, indent=2))
        elif args.action in {"check", "docs"}:
            check_document(write=args.action == "docs" and args.write)
            check_lock()
        elif args.action == "lock":
            from backend.devtools.ci_dependencies import lock_requirements

            return lock_requirements(args.upgrade_package)
        else:
            from backend.devtools.ci_results import execution_plan, results_directory, run_plan

            check_document()
            check_lock()
            directory = results_directory(args.results_dir)
            print(f"CI 统一结果目录：{directory}", flush=True)
            value = execution_plan(args.suite, args.base, args.head, args.scale_stocks)
            return run_plan(value, directory, args.base, args.head)
    except (
        ValueError,
        RuntimeError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(f"CI 失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
