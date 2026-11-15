"""CI 分类、自动接入、环境隔离及严格失败判定的行为回归。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.devtools import ci, ci_pytest_plugin
from backend.devtools.isolated_environment import clean_environment


def test_common_plan_and_special_suite():
    assert {item["suite"] for item in ci.plan()["include"]} == {
        "quality",
        "frontend",
        "backend",
        "database",
    }
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
    env = clean_environment()
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


@pytest.mark.parametrize("target", ["frontend", "quality"])
def test_python_case_cannot_be_routed_to_frontend(monkeypatch, tmp_path, target):
    data = ci.registry()
    next(iter(data["special_nodes"].values()))["suite"] = target
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
    env = clean_environment()
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


@pytest.mark.parametrize("fail", [False, True], ids=["success", "failure"])
def test_new_database_file_default_clients_are_isolated_and_cleaned(tmp_path, monkeypatch, fail):
    """新文件无需专属隔离 fixture；真实三库写入及断言失败均由执行器清理。"""
    import psycopg

    from backend.devtools import database_gate

    evidence = tmp_path / "targets.json"
    probe = tmp_path / "test_new_database.py"
    probe.write_text(
        """import json
import os
from pathlib import Path

import pytest
from psycopg.conninfo import conninfo_to_dict

pytest_plugins = ["backend.tests.conftest"]


@pytest.fixture(scope="session", autouse=True)
def confirm_targets_before_connecting():
    # 先验证目标，再允许公共 pg/redis 夹具连接；回归失败也不能访问默认业务库。
    for key in ("AI_STOCKS_CONFIG", "AI_STOCKS_PG_DSN", "AI_STOCKS_REDIS_URL"):
        assert os.environ.get(key), f"missing isolated target: {key}"
    from backend.config import get_settings
    settings = get_settings()
    root = Path(os.environ["AI_STOCKS_CONFIG"]).parent
    assert root.name.startswith("ai-ci-")
    assert settings.duckdb_path().parent == root
    assert conninfo_to_dict(settings.pg_conninfo())["dbname"].startswith("ai_stocks_gate_")
    assert settings.redis_url().startswith("unix://" + str(root) + "/")
    return settings


def test_default_clients(confirm_targets_before_connecting, pg, redis_cli):
    from backend.storage import get_client, get_pg_client
    settings = confirm_targets_before_connecting
    market = get_client()
    market.execute("CREATE TABLE isolated_probe(value INTEGER)")
    market.execute("INSERT INTO isolated_probe VALUES (7)")
    assert market.query_df("SELECT value FROM isolated_probe").iloc[0, 0] == 7
    pg.execute("INSERT INTO app_config(key,value) VALUES ('ci.isolation.probe','7')")
    default_pg = get_pg_client()
    assert default_pg.query_df(
        "SELECT value FROM app_config WHERE key='ci.isolation.probe'"
    ).iloc[0, 0] == '7'
    redis_cli.client.set("ci:isolation:probe", "7", ex=60)
    assert redis_cli.client.get("ci:isolation:probe") == "7"
    targets = {
        "database": pg.query_df("SELECT current_database()").iloc[0, 0],
        "duckdb_path": str(settings.duckdb_path()),
        "redis_socket": redis_cli.client.connection_pool.connection_kwargs["path"],
        "log_dir": str(settings.paths.log_dir),
    }
    Path(__EVIDENCE__).write_text(json.dumps(targets))
    assert not __FAIL__, "intentional failure after isolated writes"


def test_fresh_database_fixture(installed):
    from backend.storage.database_lifecycle import verify_database
    duck, pg = installed
    assert verify_database(duck, pg)["ok"]
""".replace("__EVIDENCE__", repr(str(evidence))).replace("__FAIL__", repr(fail))
    )
    original_run = database_gate.subprocess.run
    reports = []
    service_files = set((ci.ROOT / "logs").glob("*"))

    def run_probe(arguments, **options):
        # 使用执行器真实报告路径，成功和失败都必须保留在独立临时目录。
        reports.extend(
            Path(argument.split("=", 1)[1])
            for argument in arguments
            if argument.startswith("--junitxml=")
        )
        return original_run(arguments, **options)

    # 使用真实临时集群，模拟新增文件已经通过登记分流；不改动仓库登记表。
    with database_gate.gate_server() as admin:
        monkeypatch.setenv(database_gate.ADMIN_DSN_ENV, admin)
        monkeypatch.setenv("AI_STOCKS_PG_DSN", "postgresql://blocked@127.0.0.1:1/forbidden")
        monkeypatch.setenv("AI_STOCKS_REDIS_URL", "redis://127.0.0.1:1/15")
        monkeypatch.setenv("AI_STOCKS_CONFIG", str(tmp_path / "forbidden-settings.yaml"))
        monkeypatch.setattr(database_gate, "gate_test_paths", lambda _suite: [str(probe)])
        monkeypatch.setattr(database_gate.subprocess, "run", run_probe)
        assert database_gate.run_gate() == int(fail)
        targets = json.loads(evidence.read_text())
        with psycopg.connect(admin) as connection:
            assert (
                connection.execute(
                    "SELECT 1 FROM pg_database WHERE datname=%s", [targets["database"]]
                ).fetchone()
                is None
            )
        assert not Path(targets["duckdb_path"]).parent.exists()
        assert not Path(targets["redis_socket"]).exists()
    assert len(reports) == 1
    report = reports[0]
    assert report.is_file()
    assert report.parent.parent == ci.ROOT / ".local/tmp/ai-agent"
    assert Path(targets["log_dir"]) == report.parent
    assert list(report.parent.glob("ci-redis-*.log"))
    assert set((ci.ROOT / "logs").glob("*")) == service_files
