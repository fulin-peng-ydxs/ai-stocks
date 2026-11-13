"""本地与 GitHub 共用的 CI 编排；默认发现测试，专项例外由唯一登记表维护。"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from backend.devtools.isolated_environment import (
    create_ci_artifact_dir,
    isolated_storage_environment,
)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "config/ci-suites.json"
DOC = ROOT / "agent-works/architecture/continuous-integration.md"


def registry() -> dict:
    """读取并校验执行分类；路径失效、未知执行器及无说明例外直接失败。"""
    data = json.loads(REGISTRY.read_text())
    suites = data["suites"]
    for name, suite in suites.items():
        if not name or suite["kind"] not in {"frontend", "backend", "database"}:
            raise ValueError(f"非法 CI 套件：{name}")
        if not isinstance(suite["common"], bool) or not suite["description"]:
            raise ValueError(f"CI 套件信息不完整：{name}")
    for category in ("special_files", "special_nodes"):
        for path, entry in data[category].items():
            if (
                entry["suite"] not in {*suites, "manual-market", "not-applicable"}
                or not entry["reason"]
            ):
                raise ValueError(f"CI 专项登记不完整：{path}")
            target = entry["suite"]
            if target in suites:
                kind = suites[target]["kind"]
                if kind == "frontend" or (category == "special_nodes" and kind == "database"):
                    raise ValueError(f"Python 测试不能分流至此执行器：{path}")
            if category == "special_nodes" and path.split("::")[0] in data["special_files"]:
                raise ValueError(f"文件与用例专项登记重叠：{path}")
            source = (ROOT / path.split("::")[0]).resolve()
            if not source.is_file() or not source.is_relative_to(ROOT / "backend/tests"):
                raise ValueError(f"CI 专项登记路径失效：{path}")
    return data


def plan(suite: str = "common") -> dict:
    """按登记生成 Actions 矩阵；新常用套件无需另改触发器或调用方。"""
    suites = registry()["suites"]
    if suite != "common" and suite not in suites:
        raise ValueError(f"未知 CI 套件 {suite}；可选 common、" + "、".join(suites))
    result = {
        "include": [
            {"suite": name, "kind": entry["kind"]}
            for name, entry in suites.items()
            if (entry["common"] if suite == "common" else name == suite)
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
        common = "是" if entry["common"] else "否"
        lines.append(f"| `{name}` | {entry['kind']} | {common} | {entry['description']} |")
    lines += ["", "| 专项文件或用例 | 归属 | 原因 |", "| --- | --- | --- |"]
    for category in ("special_files", "special_nodes"):
        for name, entry in data[category].items():
            lines.append(f"| `{name}` | `{entry['suite']}` | {entry['reason']} |")
    return "\n".join(lines)


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
    artifact_dir = create_ci_artifact_dir()
    with (
        gate_server(artifact_dir) as admin,
        isolated_storage_environment(admin, artifact_dir) as env,
    ):
        env["AI_STOCKS_CI_SUITE"] = suite
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
        return run_test_process(
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
            ],
            env,
        )


def run_suite(suite: str, scale_stocks: int | None = None) -> int:
    """常用编排和手动专项最终调用相同执行器，任一失败使总入口失败。"""
    check_document()
    for item in plan(suite)["include"]:
        name, kind = item["suite"], item["kind"]
        print(f"CI 开始：{name}", flush=True)
        if kind == "backend":
            code = run_backend(name, scale_stocks)
        elif kind == "database":
            from backend.devtools.database_gate import run_gate

            code = run_gate(suite=name)
        else:
            code = subprocess.run(
                ["npm", "run", "check"], cwd=ROOT / "frontend", check=False
            ).returncode
        if code:
            return code
    return 0


def main() -> int:
    # Actions 取消时仍退出上下文，清理自建数据库与进程；不改变业务服务状态。
    def terminate(_signum, _frame):
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "plan", "check", "docs"))
    parser.add_argument("suite", nargs="?", default="common")
    parser.add_argument("--scale-stocks", type=int)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "plan":
            print(json.dumps(plan(args.suite)))
        elif args.action in {"check", "docs"}:
            check_document(write=args.action == "docs" and args.write)
        else:
            return run_suite(args.suite, args.scale_stocks)
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
