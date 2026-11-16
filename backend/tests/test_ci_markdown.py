"""说明文档可减量，程序输入、混改、未知范围和失败证据不能借此绕过完整门禁。"""

import json
import re
import subprocess
import sys

import pytest

from backend.devtools import ci, ci_changes, ci_results
from backend.devtools.isolated_environment import create_ci_artifact_dir


@pytest.fixture
def known_changes(monkeypatch):
    monkeypatch.setattr(ci, "commit_range", lambda *_args: ("a" * 40, "b" * 40))
    monkeypatch.setattr(ci_results, "source_identity", lambda: {"commit": "b" * 40, "sha256": "c" * 64})
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    def choose(paths):
        monkeypatch.setattr(ci, "changed_paths", lambda _scope: paths)
        return ci_results.execution_plan("change")

    return choose


@pytest.mark.parametrize("paths", [
    {"agent-works/architecture/continuous-integration.md"},
    {"notes/explanation.md", "notes/new-guide.md"},
    {"removed-explanation.md"},
])
def test_explanation_only_keeps_real_light_checks_and_explicit_common_stays_full(known_changes, paths):
    plan = known_changes(paths)
    assert plan["profile"] == "markdown"
    assert {item["suite"] for item in plan["include"]} == {"secrets", "quality"}
    assert not plan["pending_checks"] and not plan["required_specials"]
    assert {"secrets", "quality", "frontend", "backend", "database"} <= {
        item["suite"] for item in ci.plan("common")["include"]
    }
    assert ci_results.execution_plan("common")["profile"] == "standard"
    assert ci_results.execution_plan("frontend")["include"] == [{"suite": "frontend", "kind": "frontend"}]


@pytest.mark.parametrize("path", [
    "AGENTS.md", "CLAUDE.md", "README.md", "DESIGN.md",
    "agent-works/testing/guide.md", "agent-works/e2e-automation/guide.md",
    "agent-works/configurable-layout-system/page-template.md",
    "agent-works/configurable-layout-system/responsive-components.md",
    "agent-works/configurable-layout-system/responsive-pages.md",
])
def test_program_and_execution_contract_markdown_retains_full_common(known_changes, path):
    plan = known_changes({path})
    assert plan["profile"] == "standard"
    assert {"frontend", "backend", "database"} <= {item["suite"] for item in plan["include"]}


@pytest.mark.parametrize("paths", [
    {"notes.md", "backend/api/trade_discipline.py"},
    {"notes.md", "frontend/package-lock.json"},
    {"notes.md", "deleted_source.py"},
    set(), None,
])
def test_mixed_empty_and_unknown_ranges_are_not_lightweight(known_changes, paths):
    plan = known_changes(paths)
    assert plan["profile"] == "standard"
    assert {"frontend", "backend", "database"} <= {item["suite"] for item in plan["include"]}
    if paths is None or paths and "frontend/package-lock.json" in paths:
        assert "dependency-audit" in {item["suite"] for item in plan["include"]}


def test_symlink_is_not_treated_as_an_explanation(tmp_path, monkeypatch):
    (tmp_path / "guide.md").symlink_to("external-target")
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    assert not ci.markdown_only({"guide.md"}, {"markdown_only": {"full_ci_paths": ["DESIGN.md"]}})
    assert not ci.markdown_only({"guide.md"}, {})


def test_deleted_code_renamed_to_markdown_cannot_disappear_from_range(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    git("config", "user.name", "CI probe")
    git("config", "user.email", "ci@example.invalid")
    (tmp_path / "source.py").write_text("original code\n")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (tmp_path / "source.py").rename(tmp_path / "guide.md")
    git("add", "-A")
    git("commit", "-qm", "rename")
    head = git("rev-parse", "HEAD")
    monkeypatch.setattr(ci_changes, "ROOT", tmp_path)
    paths = ci_changes.changed_paths((base, head))
    assert paths == {"source.py", "guide.md"}
    assert not ci.markdown_only(paths, ci.registry())


@pytest.mark.parametrize("kind", ["browser", "manual"])
def test_registered_requirement_takes_priority_over_markdown_extension(tmp_path, monkeypatch, known_changes, kind):
    data = ci.registry()
    if kind == "browser":
        data["suites"]["e2e-ladder"]["impact_paths"].append("agent-works/architecture/continuous-integration.md")
    else:
        data["special_files"]["frontend/e2e/app-row-actions.spec.ts"]["impact_paths"] = [
            "agent-works/architecture/continuous-integration.md"
        ]
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(data))
    monkeypatch.setattr(ci, "REGISTRY", registry)
    plan = known_changes({"agent-works/architecture/continuous-integration.md"})
    assert plan["profile"] == "standard"
    assert "frontend" in {item["suite"] for item in plan["include"]}
    assert bool(plan["pending_checks"]) is (kind == "manual")
    if kind == "browser":
        assert "e2e-ladder" in {item["suite"] for item in plan["include"]}


@pytest.mark.parametrize("outcome", ["passed", "command-failed", "missing-report", "changed-report", "missing-receipt"])
def test_lightweight_formal_entry_uses_actual_exit_and_existing_evidence_gate(
    tmp_path, monkeypatch, known_changes, outcome,
):
    # 本例验证本地总计划落盘；远端矩阵保留总计划由 test_ci_results 的矩阵用例验证。
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    known_changes({"agent-works/architecture/continuous-integration.md"})
    invoked = []

    def run(suite, *_args):
        invoked.append(suite)
        if suite == "secrets" and outcome != "missing-report":
            artifacts = create_ci_artifact_dir()
            for name in ("secrets-source.json", "secrets-commits.json"):
                (artifacts / name).write_text("[]")
        # 真实子进程退出；不以手填 passed 作为执行证据。
        return subprocess.run([sys.executable, "-c", "raise SystemExit(3)" if outcome == "command-failed"
                               and suite == "quality" else "raise SystemExit(0)"], check=False).returncode

    monkeypatch.setattr(ci, "run_suite", run)
    monkeypatch.setattr(sys, "argv", ["ci", "run", "change", "--results-dir", str(tmp_path)])
    code = ci.main()
    assert invoked == ["secrets", "quality"]
    assert (code == 0) is (outcome not in {"command-failed", "missing-report"})
    plan = json.loads((tmp_path / "ci-plan.json").read_text())
    if outcome == "changed-report":
        next(tmp_path.rglob("secrets-source.json")).write_text("{}")
    elif outcome == "missing-receipt":
        (tmp_path / "receipts/quality.json").unlink()
    result = ci_results.reconcile(plan, tmp_path)
    assert (result["status"] == "passed") is (outcome == "passed")
    assert result["profile"] == "markdown"
    assert "不代表业务回归" in (tmp_path / "ci-result.md").read_text()


def test_lightweight_plan_cannot_be_relabelled_after_code_is_added(tmp_path, monkeypatch, known_changes):
    plan = known_changes({"notes.md"})
    assert plan["profile"] == "markdown"
    known_changes({"notes.md", "backend/api/trade_discipline.py"})
    with pytest.raises(ValueError, match="漂移|遗漏"):
        ci_results.reconcile(plan, tmp_path)


@pytest.mark.parametrize("profile", ["standard", None])
def test_lightweight_success_cannot_claim_a_standard_profile(tmp_path, known_changes, profile):
    plan = known_changes({"notes.md"})
    if profile is None:
        plan.pop("profile")
    else:
        plan["profile"] = profile
    with pytest.raises(ValueError, match="漂移|遗漏"):
        ci_results.reconcile(plan, tmp_path)


def test_generated_inventory_lists_shared_rules_once():
    text = ci.inventory()
    assert text.count("`frontend/playwright*.ts`") == 1
    assert "本组追加路径" in text and "纯 Markdown 的轻量集合" in text


@pytest.mark.parametrize("suites", [["quality"], ["secrets"], ["frontend"], ["quality", "quality", "secrets"], [None]])
def test_lightweight_policy_cannot_remove_its_remaining_checks(tmp_path, monkeypatch, suites):
    data = ci.registry()
    data["markdown_only"]["suites"] = suites
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(ci, "REGISTRY", path)
    with pytest.raises(ValueError, match="必须保留"):
        ci.registry()


@pytest.mark.parametrize("suite", ["secrets", "quality"])
def test_lightweight_check_must_remain_in_common(tmp_path, monkeypatch, suite):
    data = ci.registry()
    data["suites"][suite]["common"] = False
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(ci, "REGISTRY", path)
    with pytest.raises(ValueError, match="必须保留"):
        ci.registry()


@pytest.mark.parametrize("path", [
    "frontend/src/components/AppDataTable.vue", "frontend/src/components/AppForm.vue",
    "frontend/src/components/PageDrawer.vue",
    "frontend/src/styles/global.css", "frontend/src/directives/permission.ts",
    "backend/auth/middleware.py", "backend/api/auth.py",
])
def test_shared_rendering_and_authentication_select_all_browser_consumers(known_changes, path):
    assert (ci.ROOT / path).is_file()
    plan = known_changes({path})
    expected = {name for name, entry in ci.registry()["suites"].items() if entry["kind"] == "e2e"}
    assert {item["suite"] for item in plan["include"] if item["kind"] == "e2e"} == expected
    assert plan["profile"] == "standard" and not plan["pending_checks"]


def test_trade_api_change_requires_its_real_browser_chain(known_changes):
    plan = known_changes({"backend/api/trade_discipline.py"})
    assert {item["suite"] for item in plan["include"] if item["kind"] == "e2e"} == {"e2e-trade"}


@pytest.mark.parametrize("path,expected", [
    ("frontend/src/views/system/PermissionTree.vue", {"e2e-rbac"}),
    ("frontend/src/api/role.ts", {"e2e-rbac"}),
    ("backend/api/roles.py", {"e2e-rbac"}),
    ("backend/api/resources.py", {"e2e-rbac"}),
    ("frontend/src/api/menu.ts", {"e2e-rbac", "e2e-shell"}),
    ("backend/api/menus.py", {"e2e-rbac", "e2e-shell"}),
    ("frontend/src/api/data.ts", {"e2e-sectors", "e2e-correlation", "e2e-schedule", "e2e-tasks"}),
    ("backend/api/data_tasks.py", {"e2e-sectors", "e2e-correlation", "e2e-schedule", "e2e-tasks"}),
    ("frontend/src/api/screening.ts", {"e2e-assets", "e2e-correlation", "e2e-backtest"}),
    ("backend/api/profiles.py", {"e2e-assets", "e2e-correlation", "e2e-backtest"}),
    ("frontend/src/api/scoreProfile.ts", {"e2e-backtest"}),
    ("backend/api/trade_profiles.py", {"e2e-backtest"}),
])
def test_api_and_permission_tree_changes_select_their_browser_groups(known_changes, path, expected):
    assert (ci.ROOT / path).is_file()
    plan = known_changes({path})
    assert {item["suite"] for item in plan["include"] if item["kind"] == "e2e"} == expected


def test_push_pr_and_final_status_remain_present_for_lightweight_changes():
    import yaml

    workflow = yaml.safe_load((ci.ROOT / ".github/workflows/ci.yml").read_text())
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["push"] is None and triggers["pull_request"] is None
    result = workflow["jobs"]["result"]
    assert result["if"] == "always()" and set(result["needs"]) == {"plan", "checks"}
    install = next(step for step in result["steps"] if step.get("name") == "Install locked result validation dependencies")
    assert "needs.plan.result == 'success'" in install["if"]
    assert "contains(fromJSON(needs.plan.outputs.matrix).include.*.kind, 'audit')" in install["if"]


def test_lightweight_result_reconciles_without_site_packages(tmp_path):
    """真实干净解释器核验轻量回执，证明汇总不依赖完整业务安装。"""
    program = '''
import importlib.util, json, sys
from pathlib import Path
from backend.devtools import ci, ci_results
assert importlib.util.find_spec('packaging') is None
ci.commit_range = lambda *_: ('a' * 40, 'b' * 40)
ci.changed_paths = lambda _: {'explanation.md'}
directory = Path(sys.argv[1])
plan = ci_results.execution_plan('change')
for name in ('secrets', 'quality'):
    ci_results.save_json(directory / 'receipts' / (name + '.json'), {
        'schema': 1, 'suite': name, 'source': plan['source'], 'range': plan['range'],
        'parameters': {}, 'exit_code': 0, 'status': 'passed', 'reports': []})
receipt_path = directory / 'receipts/secrets.json'
receipt = json.loads(receipt_path.read_text())
import hashlib
for name in ('secrets-source.json', 'secrets-commits.json'):
    path = directory / 'artifacts' / name
    ci_results.save_json(path, [])
    receipt['reports'].append({'path': path.relative_to(directory).as_posix(),
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
ci_results.save_json(receipt_path, receipt)
result = ci_results.reconcile(plan, directory)
assert result['profile'] == 'markdown' and result['status'] == 'passed'
'''
    completed = subprocess.run([sys.executable, "-S", "-c", program, str(tmp_path)],
                               cwd=ci.ROOT, text=True, capture_output=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_markdown_inputs_in_code_must_keep_full_validation_or_existing_document_gate():
    """代码字面量指向仓库 Markdown 时保守要求登记；动态路径仍须语义审查。"""
    data = ci.registry()
    paths = [p for folder, pattern in (("backend", "*.py"), ("frontend/src", "*.ts"),
                                     ("frontend/scripts", "*.mjs"), ("scripts", "*.sh"))
             for p in (ci.ROOT / folder).rglob(pattern)]
    inputs = set()
    for source in paths:
        for name in re.findall(r"['\"]([^'\"\n]*\.md)['\"]", source.read_text()):
            for candidate in (ci.ROOT / name, source.parent / name, ci.ROOT / "frontend" / name):
                candidate = candidate.resolve()
                if candidate.is_relative_to(ci.ROOT) and candidate.is_file():
                    inputs.add(candidate)
    assert ci.ROOT / "DESIGN.md" in inputs
    assert ci.ROOT / "README.md" in inputs
    for path in inputs - {ci.DOC}:
        assert not ci.markdown_only({path.relative_to(ci.ROOT).as_posix()}, data), path
