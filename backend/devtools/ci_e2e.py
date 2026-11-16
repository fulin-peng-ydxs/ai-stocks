"""复用既有 Playwright runner，在可销毁三库中执行登记的浏览器专项。"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.request import urlopen

from backend.devtools.isolated_environment import (
    create_ci_artifact_dir,
    isolated_storage_environment,
)

ROOT = Path(__file__).resolve().parents[2]
RUNNERS = {
    "shell": "scripts/run-playwright.sh",
    "sectors": "scripts/run-sector-e2e.sh",
    "correlation": "scripts/run-stock-board-correlation-e2e.sh",
    "trade": "scripts/run-trade-discipline-e2e.sh",
    "backtest": "scripts/run-playwright.sh",
    "stocks": "scripts/run-playwright.sh",
}


def report_cases(report: dict) -> dict[tuple[str, str], tuple[dict, dict]]:
    """以 Playwright 稳定 test id 和项目名核对计划/实际集合，拒绝重复或空集合。"""
    result = {}

    def visit(suite):
        for spec in suite.get("specs", []):
            for case in spec["tests"]:
                key = (spec["id"], case["projectName"])
                if key in result:
                    raise RuntimeError("Playwright 报告含重复用例")
                result[key] = (spec, case)
        for child in suite.get("suites", []):
            visit(child)

    for suite in report["suites"]:
        visit(suite)
    if report.get("errors") or not result:
        raise RuntimeError("Playwright 收集失败或用例集合为空")
    return result


def validate_collection(report: dict, expected_files: set[str] | None = None) -> dict:
    """每个登记项目和文件都须收集到用例，避免两份报告同时少跑而集合仍相等。"""
    cases = report_cases(report)
    projects = {project["name"] for project in report["config"]["projects"]}
    if {project for _case_id, project in cases} != projects:
        raise RuntimeError("Playwright 登记项目未全部收集到用例")
    if expected_files is not None and {spec["file"] for spec, _case in cases.values()} != expected_files:
        raise RuntimeError("Playwright 登记文件未全部收集到用例或存在额外文件")
    return cases


def validate_report(planned: dict, actual: dict, expected_files: set[str] | None = None) -> int:
    """专项不能以少跑、skip、xfail、重试或残缺 JSON 冒充验收通过。"""
    for report in (planned, actual):
        config = report.get("config", {})
        projects = config.get("projects", [])
        if config.get("forbidOnly") is not True or config.get("workers") != 1 or not projects or any(
            project.get("retries") != 0 or project.get("repeatEach") != 1 for project in projects
        ):
            raise RuntimeError("Playwright CI 配置未禁止聚焦/重试或执行方式发生变化")
    expected = validate_collection(planned, expected_files)
    observed = validate_collection(actual, expected_files)
    if expected.keys() != observed.keys():
        raise RuntimeError("Playwright 实际执行集合与收集计划不一致")
    for spec, case in observed.values():
        attempts = case["results"]
        if (
            not spec["ok"] or case["expectedStatus"] != "passed"
            or case["status"] != "expected" or len(attempts) != 1
            or attempts[0]["status"] != "passed" or attempts[0]["retry"] != 0
            or attempts[0].get("errors")
        ):
            raise RuntimeError(f"Playwright 用例未完整通过：{spec['file']} / {spec['title']}")
    stats = actual["stats"]
    if stats["expected"] != len(observed) or any(stats[key] for key in ("unexpected", "flaky", "skipped")):
        raise RuntimeError("Playwright 汇总与逐项通过结果不一致")
    return len(observed)


def service_command(*arguments: str, env: dict | None = None, capture=False):
    """服务启停与恢复统一经 start.sh；调用方决定是否读取输出。"""
    return subprocess.run(
        [str(ROOT / "start.sh"), *arguments], cwd=ROOT, env=env,
        text=True, capture_output=capture, check=True, timeout=120,
    )


def port_is_listening(port: int) -> bool:
    """先按实际环回地址探测已有监听，避免 macOS 地址重用掩盖通配地址监听。"""
    with socket.socket() as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def frontend_port() -> int:
    """优先使用既有 5181；已被预览占用时申请独立端口，不接管其它进程。"""
    for port in (5181, 0):
        if port and port_is_listening(port):
            continue
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
                # macOS 上 SO_REUSEADDR 的 bind 可成功，但 listen 仍会与已有监听冲突。
                probe.listen(1)
            except OSError:
                if port == 0:
                    raise
                continue
            return probe.getsockname()[1]
    raise RuntimeError("无法取得独立的 E2E 前端端口")


@contextmanager
def backend_lifecycle(artifacts: Path):
    """先保存可信日常服务，再让专项独占既有端口；所有出口恢复原运行方式。"""
    status = service_command("status", capture=True).stdout
    if "异常" in status:
        raise RuntimeError("日常后端状态异常，拒绝切换 E2E 服务")
    snapshot = artifacts / "backend-runtime-before.json"
    was_running = "运行中" in status
    if was_running:
        service_command("assert-idle")
        service_command("snapshot-runtime", str(snapshot))
        state = json.loads(snapshot.read_text())
        safe = state.get("safeEnv", {})
        if safe.get("AI_STOCKS_ENV", safe.get("ENV")) not in {"dev", "test", "local"}:
            raise RuntimeError("日常服务不是已确认的本地测试环境，拒绝停止并切换 E2E")
        service_command("stop-if-idle")
    owns_backend = False
    try:
        # 端口被未知进程占用时，在创建任何服务前失败，不接管该进程。
        if port_is_listening(8000):
            raise RuntimeError("E2E 后端端口 8000 被占用，拒绝接管未知进程")
        with socket.socket() as probe:
            # 与 Uvicorn 相同的地址重用语义，正常停止后的 TIME_WAIT 不算端口被接管。
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", 8000))
                probe.listen(1)
            except OSError as exc:
                raise RuntimeError("E2E 后端端口 8000 被占用，拒绝接管未知进程") from exc
        owns_backend = True
        yield
    finally:
        # 专项脚本也会清理自己的服务；重复 stop 在原本停止时幂等。
        if owns_backend:
            service_command("stop", "--force")
        if was_running:
            service_command("restore-runtime", str(snapshot))
            restored = service_command("status", capture=True).stdout
            if "/api/health=200" not in restored:
                raise RuntimeError(f"日常后端恢复失败，保留运行档案：{snapshot}")
        snapshot.unlink(missing_ok=True)


def backend_fingerprint() -> str:
    """只读取本轮固定本机后端的 E2E 健康入口，账号写入继续复用既有指纹守卫。"""
    with urlopen("http://127.0.0.1:8000/api/health/e2e", timeout=5) as response:
        report = json.load(response)
    fingerprint = (report.get("data") or {}).get("pgFingerprint")
    if report.get("code") != 0 or not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise RuntimeError("E2E 后端未返回有效 PostgreSQL 指纹")
    return fingerprint


def run_e2e(suite: str) -> int:
    """固定登记范围、无重试运行，保存收集清单、实际报告及服务恢复结果。"""
    from backend.devtools.ci import check_installed, registry
    from backend.devtools.database_gate import gate_server

    data = registry()
    entry = data["suites"][suite]
    profile = entry["e2e"]
    expected_files = {
        Path(path).relative_to("frontend/e2e").as_posix()
        for path, registration in data["special_files"].items() if registration["suite"] == suite
    }
    check_installed()
    artifacts = create_ci_artifact_dir()
    summary = {"suite": suite, "status": "not-completed", "profile": profile}
    try:
        port = frontend_port()
        summary["base_url"] = f"http://127.0.0.1:{port}"
        with (
            backend_lifecycle(artifacts),
            gate_server(artifacts) as admin,
            isolated_storage_environment(admin, artifacts) as isolated,
        ):
            env = {key: value for key, value in isolated.items() if not key.startswith("E2E_")}
            env.update({
                "CI": "1", "AI_STOCKS_CI_SUITE": suite,
                "AI_STOCKS_CI_ARTIFACT_DIR": str(artifacts),
                "AI_STOCKS_E2E_WRITE": "1", "AI_STOCKS_E2E_LOGIN_BYPASS": "1",
                "AI_STOCKS_DUCKDB_READ_ONLY": "0", "E2E_API_URL": "http://127.0.0.1:8000/api",
                "E2E_BASE_URL": str(summary["base_url"]), "E2E_WEB_PORT": str(port),
                # 公开回测 helper 的文件锁和缓存同样隔离，不能复用其它轮的状态。
                "TMPDIR": str(artifacts),
            })
            arguments = ["--config=playwright.ci.config.ts"]
            backend_log = ROOT / "logs/backend.log"
            before_log = backend_log.stat() if backend_log.exists() else None
            try:
                collect = subprocess.run(
                    [str(ROOT / "scripts/run-playwright.sh"), *arguments, "--list", "--reporter=json"],
                    cwd=ROOT, env=env, text=True, capture_output=True, check=True, timeout=120,
                )
                planned = json.loads(collect.stdout)
                validate_collection(planned, expected_files)
                (artifacts / "e2e-planned.json").write_text(json.dumps(planned, ensure_ascii=False))
                subprocess.run(
                    [sys.executable, "-c", "from backend.devtools.ci import bootstrap; bootstrap()"],
                    cwd=ROOT, env=env, check=True, timeout=120,
                )
                if profile["runner"] == "backtest":
                    subprocess.run(
                        [sys.executable, "-c",
                         ("from backend.devtools.e2e_backtest_runs import seed_ci_market; "
                          "from backend.storage.duckdb_client import get_client; "
                          "print(seed_ci_market(get_client()))")],
                        cwd=ROOT, env=env, check=True, timeout=120,
                    )
                elif profile["runner"] == "stocks":
                    # 复用公开回测的空库行情协议，另备齐页面可选基准；偏好仍写正式 PG。
                    subprocess.run(
                        [sys.executable, "-c",
                         ("from datetime import timedelta; "
                          "from backend.common.timeutil import shanghai_now_naive; "
                          "from backend.devtools.e2e_market_data import seed_ci_market; "
                          "from backend.storage.duckdb_client import get_client; "
                          "print(seed_ci_market(get_client(), suite='e2e-stocks', "
                          "end=shanghai_now_naive().date()-timedelta(days=1), "
                          "benchmark_codes=('000905.SH','000300.SH')))")],
                        cwd=ROOT, env=env, check=True, timeout=120,
                    )
                service_command(env=env)
                fingerprint = backend_fingerprint()
                service_command("dev-users", "--expected-pg-fingerprint", fingerprint, env=env, capture=True)
                if profile["runner"] == "backtest":
                    service_command("stop-if-idle", env=env)
                    env["AI_STOCKS_DUCKDB_READ_ONLY"] = "1"
                    service_command(env=env)
                    if backend_fingerprint() != fingerprint:
                        raise RuntimeError("只读 E2E 后端 PostgreSQL 目标发生变化")
                from backend.devtools.ci import run_test_process

                code = run_test_process([str(ROOT / RUNNERS[profile["runner"]]), *arguments], env)
                actual = json.loads((artifacts / "e2e-actual.json").read_text())
                summary["passed"] = validate_report(planned, actual, expected_files)
                if code:
                    raise RuntimeError(f"E2E runner 非零退出：{code}")
                summary["status"] = "passed"
            finally:
                # 在销毁随机 PG/Redis/DuckDB 前关闭服务和文件锁，不能先删库再停服。
                service_command("stop", "--force", env=env)
                if backend_log.exists():
                    current = backend_log.stat()
                    offset = before_log.st_size if before_log and before_log.st_ino == current.st_ino else 0
                    with backend_log.open("rb") as source:
                        source.seek(offset)
                        (artifacts / "e2e-backend.log").write_bytes(source.read())
        summary["service_restored"] = True
        print(f"CI E2E {suite}：{summary['passed']} 项通过，无跳过或重试；报告 {artifacts}", flush=True)
        return 0
    except Exception:
        summary["status"] = "failed"
        raise
    finally:
        (artifacts / "e2e-execution.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
