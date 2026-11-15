"""统一验收必须拒绝漏跑、旧源码、伪成功及损坏报告；只使用临时材料。"""

import hashlib
import json
import os
import subprocess
import sys

import pytest

from backend.devtools import ci, ci_results

IDENTITY = {"commit": "a" * 40, "sha256": "b" * 64}


@pytest.fixture
def fixed_source(monkeypatch):
    monkeypatch.setattr(ci_results, "source_identity", lambda: IDENTITY.copy())


def frontend_material(directory):
    """真实 JSON reporter 协议；测试逐项状态，不能只有汇总 passed。"""
    report = directory / "artifacts/frontend/ci-example/ci-frontend.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "success": True, "numTotalTests": 1, "numPassedTests": 1,
        "numFailedTests": 0, "numPendingTests": 0, "numTodoTests": 0,
        "testResults": [{"assertionResults": [{"status": "passed"}]}],
    }))
    coverage = report.with_name("lcov.info")
    coverage.write_text("SF:src/real.ts\nDA:1,1\nend_of_record\n")
    summary = report.with_name("coverage-summary.json")
    summary.write_text(json.dumps({"total": {"lines": {"total": 1}}}))
    measured = report.with_name("coverage-final.json")
    measured.write_text(json.dumps({"real.ts": {"s": {"1": 1}}}))
    return report, coverage, summary, measured


def write_receipt(directory, plan, paths):
    ci_results.save_json(directory / "receipts/frontend.json", {
        "schema": 1, "suite": "frontend", "source": plan["source"], "range": plan["range"],
        "parameters": {}, "exit_code": 0, "status": "passed",
        "reports": [{"path": p.relative_to(directory).as_posix(),
                     "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
    })


@pytest.mark.parametrize("mode", [
    "pass", "missing", "different-source", "different-range", "different-parameter", "failed",
    "interrupted", "deleted-report", "tampered-report", "skip", "failure", "empty", "bad-total",
    "empty-coverage", "escaped-report",
])
def test_overall_result_checks_real_reports_and_version(tmp_path, fixed_source, mode):
    plan = ci_results.execution_plan("frontend")
    paths = frontend_material(tmp_path)
    if mode == "skip":
        data = json.loads(paths[0].read_text())
        data["testResults"][0]["assertionResults"][0]["status"] = "pending"
        paths[0].write_text(json.dumps(data))
    elif mode in {"failure", "empty", "bad-total"}:
        data = json.loads(paths[0].read_text())
        if mode == "failure":
            data["success"] = False
        elif mode == "empty":
            data["testResults"] = []
        else:
            data["numTotalTests"] = 2
        paths[0].write_text(json.dumps(data))
    elif mode == "empty-coverage":
        paths[1].write_text("")
    write_receipt(tmp_path, plan, paths)
    receipt_path = tmp_path / "receipts/frontend.json"
    receipt = json.loads(receipt_path.read_text())
    if mode == "missing":
        receipt_path.unlink()
    elif mode == "different-source":
        receipt["source"] = {**IDENTITY, "sha256": "c" * 64}
    elif mode == "different-range":
        receipt["range"] = ["c" * 40, "d" * 40]
    elif mode == "different-parameter":
        receipt["parameters"] = {"grep": "only one"}
    elif mode in {"failed", "interrupted"}:
        receipt["status"] = mode
    elif mode == "escaped-report":
        receipt["reports"][0]["path"] = "../outside.json"
    elif mode == "deleted-report":
        paths[0].unlink()
    elif mode == "tampered-report":
        paths[0].write_text("{}")
    if mode != "missing":
        receipt_path.write_text(json.dumps(receipt))
    result = ci_results.reconcile(plan, tmp_path)
    assert (result["status"] == "passed") is (mode == "pass")
    assert result["checks"][0]["status"] == (
        "passed" if mode == "pass" else "not-executed" if mode == "missing" else "failed"
    )
    assert json.loads((tmp_path / "ci-result.json").read_text()) == result


def test_changed_workspace_invalidates_previously_successful_result(tmp_path, fixed_source, monkeypatch):
    plan = ci_results.execution_plan("frontend")
    write_receipt(tmp_path, plan, frontend_material(tmp_path))
    monkeypatch.setattr(ci_results, "source_identity", lambda: {**IDENTITY, "sha256": "c" * 64})
    assert ci_results.reconcile(plan, tmp_path)["status"] == "not-completed"


def test_change_plan_automatically_adds_only_required_specials(monkeypatch, fixed_source):
    original = ci.assess()
    assessment = {**original, "changed_paths": ["frontend/src/router/index.ts"],
                  "required_specials": [{"suite": "e2e-shell", "status": "not-executed"}]}
    monkeypatch.setattr(ci, "assess", lambda *_args: assessment)
    result = ci_results.execution_plan("change")
    names = [i["suite"] for i in result["include"]]
    assert "e2e-shell" in names and "backend" in names
    assert "backend-scale" not in names and "e2e-trade" not in names
    # 计划中删掉必跑项，即使其它套件报告齐全也不能验收。
    result["include"] = [i for i in result["include"] if i["suite"] != "e2e-shell"]
    with pytest.raises(ValueError, match="遗漏必跑"):
        ci_results.reconcile(result, ci.ROOT)


def test_registry_change_selects_every_affected_group_and_explicit_scale(fixed_source, monkeypatch):
    monkeypatch.setattr(ci, "changed_paths", lambda _range: {"config/ci-suites.json"})
    plan = ci_results.execution_plan("change")
    scale = next(i for i in plan["include"] if i["suite"] == "backend-scale")
    assert scale["scale_stocks"] == ci.registry()["suites"]["backend-scale"]["scale_stocks"]
    assert {i["suite"] for i in plan["include"] if i["kind"] == "e2e"} == {
        name for name, entry in ci.registry()["suites"].items() if entry["kind"] == "e2e"
    }


@pytest.mark.parametrize("code", [0, 3])
def test_execution_receipt_uses_actual_process_exit_and_preserves_first_result(
    tmp_path, fixed_source, monkeypatch, code,
):
    def actual_process(*_args):
        return subprocess.run([sys.executable, "-c", f"raise SystemExit({code})"], check=False).returncode

    monkeypatch.setattr(ci, "run_suite", actual_process)
    assert ci_results.execute("quality", tmp_path) == code
    receipt_path = tmp_path / "receipts/quality.json"
    value = receipt_path.read_bytes()
    receipt = json.loads(value)
    assert receipt["exit_code"] == code
    assert receipt["status"] == ("passed" if code == 0 else "failed")
    with pytest.raises(ValueError, match="禁止覆盖失败证据"):
        ci_results.execute("quality", tmp_path)
    assert receipt_path.read_bytes() == value


def test_exception_and_mid_run_edit_cannot_produce_success(tmp_path, fixed_source, monkeypatch):
    def fail(*_args):
        raise RuntimeError("tool unavailable")

    monkeypatch.setattr(ci, "run_suite", fail)
    with pytest.raises(RuntimeError, match="tool unavailable"):
        ci_results.execute("quality", tmp_path)
    receipt = json.loads((tmp_path / "receipts/quality.json").read_text())
    assert receipt["status"] == "failed" and receipt["exit_code"] is None


def test_directly_modified_unintegrated_test_is_reported_incomplete(monkeypatch, fixed_source):
    original = ci.assess()
    file = original["not_integrated_e2e"][0]["file"]
    monkeypatch.setattr(ci, "assess", lambda *_args: {**original, "changed_paths": [file]})
    value = ci_results.execution_plan("change")
    assert [i["file"] for i in value["pending_checks"]] == [file]


def test_missing_result_fails_from_formal_cli(tmp_path, fixed_source, monkeypatch):
    plan = ci_results.execution_plan("frontend")
    ci_results.save_json(tmp_path / "ci-plan.json", plan)
    monkeypatch.setattr(sys, "argv", ["ci", "result", "--results-dir", str(tmp_path)])
    assert ci.main() == 1


def test_matrix_local_plans_do_not_overwrite_global_required_plan(tmp_path, fixed_source, monkeypatch):
    global_plan = {"mode": "change", "must_keep": True}
    ci_results.save_json(tmp_path / "ci-plan.json", global_plan)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(ci_results, "execute", lambda *_args: 0)
    monkeypatch.setattr(ci_results, "reconcile", lambda *_args: {"status": "passed"})
    assert ci_results.run_plan(ci_results.execution_plan("quality"), tmp_path) == 0
    assert json.loads((tmp_path / "ci-plan.json").read_text()) == global_plan


def test_all_manual_e2e_entries_have_specific_review_and_existing_tests_reused():
    data = ci.registry()
    for entry in data["special_files"].values():
        if entry["suite"] == "manual-e2e":
            assert entry["review_status"] in {"manual-design", "migration-required"}
            assert "既有专项尚未纳入" not in entry["reason"]
    assert data["special_files"]["frontend/e2e/asset-search-drawer.spec.ts"]["suite"] == "e2e-assets"
    assert data["special_files"]["frontend/e2e/schedule-dependency.spec.ts"]["suite"] == "e2e-schedule"
    assert data["special_files"]["frontend/e2e/stock-board-correlation-t9.spec.ts"]["suite"] == "e2e-correlation"


def test_source_identity_tracks_uncommitted_deleted_and_new_sources_without_following_links(tmp_path, monkeypatch):
    from backend.devtools import ci_changes

    monkeypatch.setattr(ci_results, "ROOT", tmp_path)
    names = ["existing.py", "new.py", "deleted.py", "link"]
    monkeypatch.setattr(ci_changes, "git", lambda *args: "\0".join(names) if args[0] == "ls-files" else "a" * 40)
    (tmp_path / "existing.py").write_text("before")
    (tmp_path / "new.py").write_text("new source")
    (tmp_path / "link").symlink_to("missing-external-target")
    before = ci_results.source_identity()
    (tmp_path / "existing.py").write_text("after")
    edited = ci_results.source_identity()
    (tmp_path / "existing.py").unlink()
    deleted = ci_results.source_identity()
    (tmp_path / "deleted.py").write_text("restored")
    restored = ci_results.source_identity()
    assert len({v["sha256"] for v in (before, edited, deleted, restored)}) == 4
    assert all(v["commit"] == "a" * 40 for v in (before, edited, deleted, restored))


@pytest.mark.parametrize("ci_mode", [False, True])
def test_existing_physical_runner_uses_registry_in_ci_and_keeps_local_defaults(tmp_path, ci_mode):
    """实际执行 Bash helper，避免只加登记却仍被 runner 的固定文件过滤掉。"""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    runner = scripts / "run-playwright.sh"
    runner.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n')
    runner.chmod(0o755)
    env = os.environ.copy()
    env.pop("AI_STOCKS_CI_SUITE", None)
    if ci_mode:
        env["AI_STOCKS_CI_SUITE"] = "e2e-sectors"
    result = subprocess.run([
        "bash", "-c",
        ('set -euo pipefail; PROJECT_ROOT="$1"; source "$2"; '
         'run_e2e_playwright 2 first.spec.ts second.spec.ts --config=playwright.ci.config.ts'),
        "helper-test", str(tmp_path), str(ci.ROOT / "scripts/e2e-backend-lifecycle.sh"),
    ], env=env, capture_output=True, text=True, check=True)
    expected = ["--workers=1", "--config=playwright.ci.config.ts"]
    assert result.stdout.splitlines() == (expected if ci_mode else ["first.spec.ts", "second.spec.ts", *expected])


@pytest.mark.parametrize("entrypoint", [
    "run-sector-e2e.sh", "run-stock-board-correlation-e2e.sh", "run-trade-discipline-e2e.sh",
])
def test_physical_runner_loads_shared_helper_before_environment_guard(entrypoint):
    """执行真实入口的无写入启动段，防止 helper 单测通过而调用脚本漏加载。"""
    env = {**os.environ, "AI_STOCKS_ENV_FILE": "/dev/null", "AI_STOCKS_ENV": "invalid-test-environment"}
    result = subprocess.run([
        "bash", "-c",
        "trap 'declare -F run_e2e_playwright >/dev/null || exit 42' EXIT; source \"$1\"",
        "entrypoint-test", str(ci.ROOT / "scripts" / entrypoint),
    ], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "AI_STOCKS_ENV=dev|test|local" in result.stdout


def test_changed_business_path_cannot_ignore_unintegrated_browser_requirement(monkeypatch, fixed_source):
    monkeypatch.setattr(ci, "changed_paths", lambda _selected: {"frontend/src/views/StockDetailView.vue"})
    value = ci_results.execution_plan("change")
    assert any(entry["file"].endswith("stock-detail-chart-workspace.spec.ts") for entry in value["pending_checks"])


def test_local_partial_run_preserves_and_grades_existing_overall_plan(tmp_path, fixed_source, monkeypatch):
    overall = ci_results.execution_plan("change")
    ci_results.save_json(tmp_path / "ci-plan.json", overall)
    observed = []
    monkeypatch.setattr(ci_results, "execute", lambda *_args: 0)
    monkeypatch.setattr(ci_results, "reconcile", lambda plan, _dir: observed.append(plan) or {"status": "not-completed"})
    assert ci_results.run_plan(ci_results.execution_plan("frontend"), tmp_path) == 1
    assert observed == [overall]
    assert json.loads((tmp_path / "ci-plan.json").read_text()) == overall


def test_rerun_cannot_silently_reuse_an_existing_passed_receipt(tmp_path, fixed_source, monkeypatch):
    plan = ci_results.execution_plan("frontend")
    write_receipt(tmp_path, plan, frontend_material(tmp_path))
    monkeypatch.setattr(ci_results, "execute", lambda *_args: pytest.fail("must stop before execution"))
    with pytest.raises(ValueError, match="重跑使用新目录"):
        ci_results.run_plan(plan, tmp_path)


@pytest.mark.parametrize("path,expected", [
    ("frontend/src/components/asset-search/AssetSearchDrawer.vue", {"e2e-assets", "e2e-correlation", "e2e-backtest"}),
    ("frontend/src/views/ScreenView.vue", {"e2e-assets", "e2e-correlation"}),
    ("frontend/src/components/PageSettingsDrawer.vue", {"e2e-settings"}),
    ("frontend/src/views/system/RoleManageView.vue", {"e2e-rbac"}),
])
def test_local_domain_change_does_not_run_unrelated_browser_groups(monkeypatch, path, expected):
    monkeypatch.setattr(ci, "changed_paths", lambda _scope: {path})
    actual = ci.assess()
    assert {entry["suite"] for entry in actual["required_specials"]} == expected


def test_new_browser_group_inherits_shared_infrastructure_rules(tmp_path, monkeypatch):
    data = ci.registry()
    data["suites"]["new-browser-group"] = {
        "kind": "e2e", "common": False, "description": "new browser domain",
        "impact_paths": ["frontend/e2e/app-row-actions.spec.ts"],
        "e2e": {"runner": "shell", "projects": [{"name": "chromium-standard"}]},
    }
    data["special_files"]["frontend/e2e/app-row-actions.spec.ts"] = {
        "suite": "new-browser-group", "reason": "isolated fixture reviewed",
    }
    source = tmp_path / "registry.json"
    source.write_text(json.dumps(data))
    monkeypatch.setattr(ci, "REGISTRY", source)
    monkeypatch.setattr(ci, "changed_paths", lambda _scope: {"scripts/e2e-backend-lifecycle.sh"})
    assert "new-browser-group" in {item["suite"] for item in ci.assess()["required_specials"]}
