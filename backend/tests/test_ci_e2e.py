"""浏览器专项的计划、逐项结果与服务恢复协议；不连接业务环境。"""

import copy
import json
import socket
from types import SimpleNamespace

import pytest

from backend.devtools import ci, ci_e2e


def report():
    """与 Playwright JSON reporter 相同的最小有效材料。"""
    return {
        "config": {"forbidOnly": True, "workers": 1,
                   "projects": [{"name": "chromium-standard", "retries": 0, "repeatEach": 1}]},
        "errors": [], "stats": {"expected": 1, "unexpected": 0, "flaky": 0, "skipped": 0},
        "suites": [{"specs": [{
            "id": "stable-test-id", "file": "example.spec.ts", "title": "required behavior", "ok": True,
            "tests": [{"projectName": "chromium-standard", "expectedStatus": "passed",
                       "status": "expected", "results": [{"status": "passed", "retry": 0, "errors": []}]}],
        }]}],
    }


@pytest.mark.parametrize("mode", [
    "pass", "empty", "missing-case", "duplicate", "skipped", "flaky", "retried", "expected-failure",
    "attempt-error", "collection-error", "wrong-project", "wrong-summary", "retries-enabled", "only-allowed",
    "empty-project",
])
def test_e2e_report_rejects_incomplete_or_weakened_execution(mode):
    planned, actual = report(), report()
    spec = actual["suites"][0]["specs"][0]
    case = spec["tests"][0]
    if mode == "empty":
        actual["suites"] = []
    elif mode == "missing-case":
        planned["suites"][0]["specs"].append({**copy.deepcopy(spec), "id": "second-id"})
    elif mode == "duplicate":
        actual["suites"][0]["specs"].append(copy.deepcopy(spec))
    elif mode in {"skipped", "flaky"}:
        case["status"] = mode
    elif mode == "retried":
        case["results"].append({"status": "passed", "retry": 1, "errors": []})
    elif mode == "expected-failure":
        case["expectedStatus"] = "failed"
    elif mode == "attempt-error":
        case["results"][0]["errors"] = [{"message": "failure"}]
    elif mode == "collection-error":
        actual["errors"] = [{"message": "cannot collect"}]
    elif mode == "wrong-project":
        case["projectName"] = "chromium-default"
    elif mode == "wrong-summary":
        actual["stats"]["expected"] = 2
    elif mode == "retries-enabled":
        actual["config"]["projects"][0]["retries"] = 1
    elif mode == "only-allowed":
        actual["config"]["forbidOnly"] = False
    elif mode == "empty-project":
        for entry in (planned, actual):
            entry["config"]["projects"].append({"name": "chromium-default", "retries": 0, "repeatEach": 1})
    if mode == "pass":
        assert ci_e2e.validate_report(planned, actual) == 1
    else:
        with pytest.raises(RuntimeError):
            ci_e2e.validate_report(planned, actual)


@pytest.mark.parametrize("registered", [{"example.spec.ts"}, {"example.spec.ts", "empty.spec.ts"}])
def test_e2e_every_registered_file_must_collect_cases(registered):
    if registered == {"example.spec.ts"}:
        assert ci_e2e.validate_report(report(), report(), registered) == 1
    else:
        with pytest.raises(RuntimeError, match="登记文件未全部收集"):
            ci_e2e.validate_report(report(), report(), registered)


@pytest.mark.parametrize("running,body_failure,restore_failure", [
    (False, False, False), (True, False, False), (True, True, False), (True, False, True),
])
def test_ci_e2e_restores_original_runtime_after_success_or_failure(
    tmp_path, monkeypatch, running, body_failure, restore_failure,
):
    calls = []

    def service(*arguments, **_options):
        calls.append(arguments)
        if arguments and arguments[0] == "snapshot-runtime":
            (tmp_path / "backend-runtime-before.json").write_text(json.dumps({"safeEnv": {"AI_STOCKS_ENV": "dev"}}))
        if restore_failure and any(call[0] == "restore-runtime" for call in calls):
            return SimpleNamespace(stdout="运行中 /api/health=503")
        return SimpleNamespace(stdout="运行中 /api/health=200" if running else "未运行")

    monkeypatch.setattr(ci_e2e, "service_command", service)
    # 模拟端口预检，只验证生命周期调用；不启动或停止真实后端。
    class Probe:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def bind(self, address):
            assert address == ("127.0.0.1", 8000)

        def setsockopt(self, *arguments):
            assert arguments == (socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        def listen(self, backlog):
            assert backlog == 1

        def settimeout(self, timeout):
            assert timeout == 0.3

        def connect_ex(self, address):
            assert address == ("127.0.0.1", 8000)
            return 1

    monkeypatch.setattr(ci_e2e.socket, "socket", Probe)
    if body_failure or restore_failure:
        with pytest.raises(RuntimeError), ci_e2e.backend_lifecycle(tmp_path):
            if body_failure:
                raise RuntimeError("test body failed")
    else:
        with ci_e2e.backend_lifecycle(tmp_path):
            pass
    assert ("stop", "--force") in calls
    assert any(call[0] == "restore-runtime" for call in calls) is running
    assert (tmp_path / "backend-runtime-before.json").exists() is restore_failure


@pytest.mark.parametrize("filename", ["new.spec.ts", "new.test.ts", "new.spec.js", "new.test.mts"])
def test_new_e2e_file_requires_explicit_fixture_ownership(tmp_path, monkeypatch, filename):
    source = tmp_path / "config.json"
    source.write_text(json.dumps({
        "suites": {"backend": {"kind": "backend", "common": True, "description": "backend"}},
        "special_files": {}, "special_nodes": {},
    }))
    folder = tmp_path / "frontend/e2e"
    folder.mkdir(parents=True)
    (folder / filename).write_text("// new browser path")
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    monkeypatch.setattr(ci, "REGISTRY", source)
    with pytest.raises(ValueError, match="缺少专项归属"):
        ci.registry()


def test_removed_impact_source_must_update_registration(tmp_path, monkeypatch):
    """重命名入口后不能留下永不命中的旧规则，避免后续专项漏判。"""
    data = ci.registry()
    data["suites"]["backend-scale"]["impact_paths"] = ["backend/services/retired_scale_entry.py"]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(ci, "REGISTRY", path)
    with pytest.raises(ValueError, match="变更路径登记失效"):
        ci.registry()


def test_ci_e2e_refuses_to_stop_production_or_unknown_environment(tmp_path, monkeypatch):
    """即使可保存运行档案，也不能把生产身份当作可停止的本地调试服务。"""
    calls = []

    def service(*arguments, **_options):
        calls.append(arguments)
        if arguments[0] == "snapshot-runtime":
            (tmp_path / "backend-runtime-before.json").write_text(json.dumps({
                "safeEnv": {"AI_STOCKS_ENV": "production"}
            }))
        return SimpleNamespace(stdout="运行中 /api/health=200")

    monkeypatch.setattr(ci_e2e, "service_command", service)
    with pytest.raises(RuntimeError, match="不是已确认的本地测试环境"), ci_e2e.backend_lifecycle(tmp_path):
        pytest.fail("must not run against production")
    assert not any(call[0].startswith(("stop", "restore")) for call in calls)


@pytest.mark.parametrize("paths,required", [
    ({"README.md"}, set()),
    ({"backend/services/intraday_archive.py"}, {"backend-scale"}),
    ({"frontend/src/router/index.ts"}, "all-e2e"),
    ({"frontend/src/views/data/QualityView.vue"}, {"e2e-sectors"}),
    ({"frontend/src/views/ConfigView.vue"}, {"e2e-sectors"}),
    ({"frontend/src/utils/sectorCompare.ts"}, {"e2e-sectors"}),
    ({"frontend/src/components/ChartOperationGroup.vue"}, {"e2e-stocks", "e2e-sectors"}),
    ({"frontend/src/components/KlineRangeSelect.vue"}, {"e2e-stocks", "e2e-sectors"}),
    ({"frontend/src/components/MarketAnalysisHeader.vue"}, {"e2e-stocks", "e2e-sectors"}),
    ({"frontend/src/composables/useKlineHeaderQuote.ts"}, {"e2e-stocks", "e2e-sectors"}),
    ({"frontend/src/composables/useKlinePrefs.ts"}, {"e2e-stocks", "e2e-sectors"}),
    (None, "all-specials"),
])
def test_impact_assessment_lists_required_not_executed_specials(monkeypatch, paths, required):
    monkeypatch.setenv("GITHUB_EVENT_PATH", "unknown-event")
    monkeypatch.setattr(ci, "commit_range", lambda *_args: None)
    monkeypatch.setattr(ci, "changed_paths", lambda _selected: paths)
    result = ci.assess()
    if required in ("all-e2e", "all-specials"):
        browser_suites = {name for name, entry in ci.registry()["suites"].items() if entry["kind"] == "e2e"}
        required = browser_suites | ({"backend-scale"} if required == "all-specials" else set())
    assert {entry["suite"] for entry in result["required_specials"]} == required
    assert all(entry["status"] == "not-executed" for entry in result["required_specials"])
    assert bool(result["not_integrated_e2e"])
    assert result["scope"] == ("review-required" if paths is None else "known")


def test_busy_unknown_port_does_not_stop_its_owner(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ci_e2e, "service_command", lambda *args, **_kw: calls.append(args) or SimpleNamespace(stdout="未运行"))
    class Busy:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def bind(self, _address):
            raise OSError("port belongs to another process")

        def setsockopt(self, *_arguments):
            pass

        def settimeout(self, _timeout):
            pass

        def connect_ex(self, _address):
            return 0

    monkeypatch.setattr(socket, "socket", Busy)
    with pytest.raises(RuntimeError, match="8000 被占用"), ci_e2e.backend_lifecycle(tmp_path):
        pytest.fail("must not execute while ports are occupied")
    assert calls == [("status",)]


def test_ci_frontend_port_does_not_reuse_existing_preview():
    """真实占用首选端口时分配独立端口；不要求结束其它预览进程。"""
    original = ci_e2e.frontend_port()
    assert 1024 <= original <= 65535
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", original))
        occupied.listen()
        chosen = ci_e2e.frontend_port()
        assert chosen != original
