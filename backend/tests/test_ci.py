"""CI 分类、自动接入、环境隔离及严格失败判定的行为回归。"""

from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from backend.devtools import ci, ci_pytest_plugin


def test_common_plan_and_special_suite():
    assert {item["suite"] for item in ci.plan()["include"]} == {"frontend", "backend", "database"}
    assert ci.plan("backend-scale")["include"] == [{"suite": "backend-scale", "kind": "backend"}]
    with pytest.raises(ValueError, match="未知"):
        ci.plan("unknown")


def test_new_suite_automatically_enters_common_and_document(monkeypatch, tmp_path):
    data = ci.registry()
    data["suites"]["new-domain"] = {
        "kind": "backend",
        "common": True,
        "description": "新领域回归",
    }
    source = tmp_path / "registry.json"
    source.write_text(json.dumps(data))
    monkeypatch.setattr(ci, "REGISTRY", source)
    assert ci.plan()["include"][-1]["suite"] == "new-domain"
    assert "新领域回归" in ci.inventory()


def test_empty_common_set_fails(monkeypatch, tmp_path):
    data = ci.registry()
    for suite in data["suites"].values():
        suite["common"] = False
    source = tmp_path / "ci.json"
    source.write_text(json.dumps(data))
    monkeypatch.setattr(ci, "REGISTRY", source)
    with pytest.raises(ValueError, match="集合为空"):
        ci.plan()


def test_inherited_business_and_test_options_are_removed(monkeypatch):
    for key in (
        "AI_STOCKS_PG_DSN",
        "AI_STOCKS_REDIS_URL",
        "AI_STOCKS_CONFIG",
        "AI_STOCKS_SMTP_PASSWORD",
        "AI_STOCKS_E2E_WRITE",
        "PYTEST_ADDOPTS",
        "ENV",
    ):
        monkeypatch.setenv(key, "must-not-inherit")
    env = ci.clean_environment()
    assert "must-not-inherit" not in env.values()
    assert env["AI_STOCKS_ENV"] == "test"
    assert env["AI_STOCKS_SMTP_ENABLED"] == "0"
    assert env["AI_STOCKS_ENV_FILE"] == "/dev/null"
    assert env["PYTHON"] == sys.executable
    assert len(env["AI_STOCKS_JWT_SECRET"]) >= 32


def test_document_drift_fails_and_only_generated_block_changes(monkeypatch, tmp_path):
    doc = tmp_path / "ci.md"
    doc.write_text("before\n<!-- ci-inventory:start -->\nold\n<!-- ci-inventory:end -->\nafter\n")
    monkeypatch.setattr(ci, "DOC", doc)
    with pytest.raises(ValueError, match="过期"):
        ci.check_document()
    ci.check_document(write=True)
    ci.check_document()
    assert doc.read_text().startswith("before\n")
    assert doc.read_text().endswith("\nafter\n")


def test_stale_file_registration_fails(monkeypatch, tmp_path):
    data = ci.registry()
    data["special_files"]["backend/tests/missing.py"] = {"suite": "database", "reason": "bad"}
    source = tmp_path / "ci.json"
    source.write_text(json.dumps(data))
    monkeypatch.setattr(ci, "REGISTRY", source)
    with pytest.raises(ValueError, match="路径失效"):
        ci.registry()


def test_python_case_cannot_be_routed_to_frontend(monkeypatch, tmp_path):
    data = ci.registry()
    next(iter(data["special_nodes"].values()))["suite"] = "frontend"
    source = tmp_path / "ci.json"
    source.write_text(json.dumps(data))
    monkeypatch.setattr(ci, "REGISTRY", source)
    with pytest.raises(ValueError, match="不能分流"):
        ci.registry()


def test_database_gate_discovers_new_registered_file(monkeypatch, tmp_path):
    from backend.devtools.database_gate import gate_test_paths

    folder = tmp_path / "backend/tests"
    folder.mkdir(parents=True)
    paths = ["backend/tests/test_database.py", "backend/tests/test_new_database.py"]
    for path in paths:
        (tmp_path / path).write_text("def test_new(): pass")
    source = tmp_path / "ci.json"
    source.write_text(
        json.dumps(
            {
                "suites": {
                    "database": {"kind": "database", "common": True, "description": "数据库"}
                },
                "special_files": {
                    path: {"suite": "database", "reason": "结构契约"} for path in paths
                },
                "special_nodes": {},
            }
        )
    )
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    monkeypatch.setattr(ci, "REGISTRY", source)
    assert gate_test_paths() == paths


def test_new_test_automatically_collected_and_special_routed():
    config = SimpleNamespace(
        _ci_registry={
            "special_files": {},
            "special_nodes": {
                "test.py::large": {"suite": "backend-scale"},
            },
        },
        _ci_suite="backend",
        _ci_routed=[],
    )
    items = [SimpleNamespace(nodeid=node) for node in ("test.py::large", "new.py::test_new")]
    ci_pytest_plugin.pytest_collection_modifyitems(config, items)
    assert [item.nodeid for item in items] == ["new.py::test_new"]
    assert config._ci_routed == ["test.py::large"]


def test_missing_special_node_is_error():
    config = SimpleNamespace(
        _ci_registry={
            "special_nodes": {
                "deleted.py::old": {"suite": "backend-scale"},
            }
        },
        _ci_suite="backend",
    )
    with pytest.raises(pytest.UsageError, match="失效"):
        ci_pytest_plugin.pytest_collection_modifyitems(config, [])


@pytest.mark.parametrize(
    "body,extra,success",
    [
        ("def test_ok(): pass", [], True),
        ("def test_bad(): assert False", [], False),
        ("import pytest\ndef test_skip(): pytest.skip('missing dependency')", [], False),
        ("import pytest\n@pytest.mark.xfail\ndef test_x(): assert False", [], False),
        ("import pytest\n@pytest.mark.xfail\ndef test_x(): pass", [], False),
        ("x = 1", [], False),
        ("def test_a(): pass\ndef test_b(): pass", ["-k", "test_a"], False),
    ],
)
def test_strict_gate_cannot_turn_incomplete_run_green(tmp_path, body, extra, success):
    path = tmp_path / "test_probe.py"
    path.write_text(body)
    env = ci.clean_environment()
    env["PYTHONPATH"] = str(ci.ROOT)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(path),
            "-p",
            "backend.devtools.database_gate_plugin",
            "-o",
            "addopts=",
            "-q",
            *extra,
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is success, result.stdout + result.stderr


def test_frontend_and_database_wrappers_do_not_duplicate_push_triggers():
    import yaml

    for name in ("frontend-contracts", "database-contracts"):
        workflow = yaml.safe_load((ci.ROOT / f".github/workflows/{name}.yml").read_text())
        # PyYAML 使用 YAML 1.1，把未加引号的 on 解析成 True。
        triggers = workflow.get("on", workflow.get(True))
        assert set(triggers) == {"workflow_call", "workflow_dispatch"}
        assert next(iter(workflow["jobs"].values()))["uses"] == "./.github/workflows/ci-suite.yml"


def test_scale_requires_explicit_bounded_input():
    with pytest.raises(ValueError, match="scale-stocks"):
        ci.run_backend("backend-scale")
