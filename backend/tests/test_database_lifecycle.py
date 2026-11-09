"""数据库门禁：独立真实 PG + 内存 DuckDB，依赖缺失不允许 skip。

通过 database gate 自动准备隔离集群，或显式指定测试管理 DSN 后单跑本文件。
不使用共享 conftest.pg，也不修改任何开发/生产数据库中的对象。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.devtools.database_gate import ADMIN_DSN_ENV, temporary_database
from backend.storage import database_lifecycle as lifecycle
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.schema_contract import (
    create_declared_schema,
    duck_schema,
    load_contract,
    pg_schema,
    schema_differences,
    schema_report,
)


@pytest.fixture
def databases(monkeypatch):
    admin = os.environ.get(ADMIN_DSN_ENV)
    if not admin:
        pytest.fail(f"必须通过 database gate 或设置 {ADMIN_DSN_ENV}，数据库门禁禁止跳过")
    monkeypatch.setenv("AI_STOCKS_ENV", "test")
    monkeypatch.setenv("AI_STOCKS_ADMIN_PASSWORD", "isolated-gate-password")
    monkeypatch.setenv("AI_STOCKS_TASK_STORAGE_BACKEND", "auto")
    with temporary_database(admin) as pg, DuckDBClient(":memory:") as duck:
        from backend.auth import perm_resolver
        from backend.storage import duckdb_client, pg_client

        # 间接配置读取与兼容仓储也必须落在隔离库，不能读取机器默认业务连接。
        monkeypatch.setattr(pg_client, "_client", pg)
        monkeypatch.setattr(duckdb_client, "_client", duck)
        monkeypatch.setattr(perm_resolver, "clear_perms_cache", lambda _users: None)
        yield duck, pg


@pytest.fixture
def installed(databases):
    duck, pg = databases
    report = lifecycle.initialize_database(duck, pg, mode="init")
    assert report["ok"], report
    return duck, pg


def test_declared_empty_schema_matches_committed_contract(databases):
    duck, pg = databases
    create_declared_schema(duck, pg)
    actual = {"duckdb": duck_schema(duck), "postgres": pg_schema(pg)}
    assert not schema_differences(load_contract(), actual)


def test_fresh_install_is_complete_and_uses_pg(installed):
    duck, pg = installed
    report = lifecycle.verify_database(duck, pg, require_pg_routes=True)
    assert report["ok"], report
    from backend.services.migrate_config_storage import config_storage_backend
    from backend.storage.task_runtime import task_runtime_backend

    assert task_runtime_backend(refresh=True, pg_client=pg) == "postgres"
    assert config_storage_backend(pg) == "postgres"
    # 初始化只落系统基础数据，不能隐含采集行情、伪造业务任务或创建调试账号。
    for table in ("daily_bar", "stock_basic", "stock_st_status_daily"):
        assert duck.query_df(f'SELECT 1 FROM "{table}" LIMIT 1').empty
    for table in ("async_task", "task_log", "scheduled_job", "backtest_run"):
        assert pg.query_df(f'SELECT 1 FROM "{table}" LIMIT 1').empty
    assert pg.query_df("SELECT id FROM sys_user WHERE account LIKE 'debug_%%'").empty


def test_repeat_preserves_configuration_password_and_asset_versions(installed):
    duck, pg = installed
    pg.execute("UPDATE sys_menu SET title='人工标题',visible='system',sort=913 WHERE id='/board'")
    pg.execute("UPDATE sys_resource SET name='人工功能名',sort=915 WHERE code='board:view'")
    pg.execute("UPDATE app_config SET value='123' WHERE key='audit.retention_days'")
    pg.execute("UPDATE dict_item SET label='人工状态',enabled=false WHERE id='user_status:locked'")
    password = pg.query_df("SELECT password_hash FROM sys_user WHERE id='admin'").iloc[0, 0]
    versions = pg.query_df("SELECT id,version FROM score_profile ORDER BY id").to_dict("records")
    duck.execute("UPDATE indicator_def SET enabled=false,categories='[]' WHERE key='close'")
    report = lifecycle.initialize_database(duck, pg, mode="init")
    assert report["ok"]
    assert pg.query_df("SELECT title,visible,sort FROM sys_menu WHERE id='/board'").iloc[
        0
    ].tolist() == [
        "人工标题",
        "system",
        913,
    ]
    assert pg.query_df("SELECT name,sort FROM sys_resource WHERE code='board:view'").iloc[
        0
    ].tolist() == [
        "人工功能名",
        915,
    ]
    assert (
        pg.query_df("SELECT value FROM app_config WHERE key='audit.retention_days'").iloc[0, 0]
        == "123"
    )
    assert pg.query_df("SELECT label,enabled FROM dict_item WHERE id='user_status:locked'").iloc[
        0
    ].tolist() == [
        "人工状态",
        False,
    ]
    assert pg.query_df("SELECT password_hash FROM sys_user WHERE id='admin'").iloc[0, 0] == password
    assert (
        pg.query_df("SELECT id,version FROM score_profile ORDER BY id").to_dict("records")
        == versions
    )
    assert duck.query_df("SELECT enabled,categories FROM indicator_def WHERE key='close'").iloc[
        0
    ].tolist() == [
        False,
        "[]",
    ]


@pytest.mark.parametrize(
    "engine,statement,object_path",
    [
        ("duckdb", "ALTER TABLE daily_bar DROP COLUMN pre_close", "daily_bar.columns.pre_close"),
        (
            "duckdb",
            "ALTER TABLE daily_bar ALTER COLUMN close TYPE VARCHAR",
            "daily_bar.columns.close",
        ),
        (
            "postgres",
            "ALTER TABLE score_snapshot_meta DROP COLUMN param_hash",
            "score_snapshot_meta.columns.param_hash",
        ),
        (
            "postgres",
            "ALTER TABLE sys_user ALTER COLUMN perm_ver DROP NOT NULL",
            "sys_user.columns.perm_ver",
        ),
        (
            "postgres",
            "ALTER TABLE sys_user ALTER COLUMN perm_ver SET DEFAULT 8",
            "sys_user.columns.perm_ver",
        ),
        (
            "postgres",
            "ALTER TABLE sys_role_resource DROP CONSTRAINT sys_role_resource_pkey",
            "sys_role_resource",
        ),
        (
            "postgres",
            "ALTER TABLE sys_user_role DROP CONSTRAINT sys_user_role_role_id_fkey",
            "sys_user_role",
        ),
        (
            "postgres",
            "ALTER TABLE storage_migration DROP CONSTRAINT storage_migration_state_check",
            "storage_migration",
        ),
        ("postgres", "DROP INDEX idx_sys_menu_parent_sort", "idx_sys_menu_parent_sort"),
    ],
)
def test_structure_drift_is_rejected(installed, engine, statement, object_path):
    duck, pg = installed
    (duck if engine == "duckdb" else pg).execute(statement)
    report = lifecycle.verify_database(duck, pg)
    assert not report["ok"]
    assert any(object_path in violation for violation in report["checks"]["schema"]["violations"])


def test_missing_seed_is_rejected_and_repaired(installed):
    duck, pg = installed
    pg.execute("DELETE FROM app_config WHERE key='audit.retention_days'")
    report = lifecycle.verify_database(duck, pg)
    assert not report["ok"]
    assert "平台默认配置: 缺少 audit.retention_days" in report["checks"]["seeds"]["violations"]
    assert lifecycle.initialize_database(duck, pg, mode="upgrade")["ok"]


def test_known_legacy_upgrade_converges_and_preserves_business_rows(databases):
    duck, pg = databases
    fixture = Path(__file__).parent / "fixtures/database"
    duck.execute((fixture / "pre-lifecycle-v1-duck.sql").read_text())
    with pg.transaction() as conn, conn.cursor() as cur:
        cur.execute((fixture / "pre-lifecycle-v1-pg.sql").read_text())
    pg.execute("INSERT INTO app_config(key,value) VALUES ('audit.retention_days','121')")
    duck.execute(
        "INSERT INTO daily_bar(code,trade_date,close) VALUES ('600000.SH','2024-01-02',10)"
    )
    report = lifecycle.initialize_database(duck, pg, mode="upgrade")
    assert report["ok"]
    assert schema_report(duck, pg)["ok"]
    assert duck.query_df("SELECT close FROM daily_bar WHERE code='600000.SH'").iloc[0, 0] == 10
    assert (
        pg.query_df("SELECT value FROM app_config WHERE key='audit.retention_days'").iloc[0, 0]
        == "121"
    )
    # 旧库升级不能伪造跨库存储迁移完成状态。
    from backend.storage.task_runtime import task_runtime_backend

    assert task_runtime_backend(refresh=True, pg_client=pg) == "duckdb"


def test_failed_seed_rolls_back_pg_and_fresh_retry_completes(databases, monkeypatch):
    duck, pg = databases
    original = lifecycle.seed_platform_profiles

    def fail_after_write(_duck, target):
        target.execute("UPDATE sys_menu SET title='不得提交的失败写入' WHERE id='/board'")
        raise RuntimeError("注入 seed 故障")

    monkeypatch.setattr(lifecycle, "seed_platform_profiles", fail_after_write)
    with pytest.raises(Exception, match="注入 seed 故障"):
        lifecycle.initialize_database(duck, pg, mode="init")
    assert lifecycle._tables(pg, "public") == set()
    monkeypatch.setattr(lifecycle, "seed_platform_profiles", original)
    assert lifecycle.initialize_database(duck, pg, mode="init")["ok"]


def test_upgrade_failure_does_not_advance_completion_marker(installed, monkeypatch):
    duck, pg = installed
    before = pg.query_df(
        "SELECT details,updated_at FROM storage_migration WHERE marker=%s",
        [lifecycle.LIFECYCLE_MARKER],
    ).to_dict("records")

    def fail(_duck, target):
        target.execute("UPDATE app_config SET value='999' WHERE key='audit.retention_days'")
        raise RuntimeError("注入升级失败")

    monkeypatch.setattr(lifecycle, "seed_platform_profiles", fail)
    with pytest.raises(Exception, match="注入升级失败"):
        lifecycle.initialize_database(duck, pg, mode="upgrade")
    assert (
        pg.query_df(
            "SELECT details,updated_at FROM storage_migration WHERE marker=%s",
            [lifecycle.LIFECYCLE_MARKER],
        ).to_dict("records")
        == before
    )
    assert (
        pg.query_df("SELECT value FROM app_config WHERE key='audit.retention_days'").iloc[0, 0]
        == "90"
    )


def test_init_refuses_legacy_target_without_writing(installed):
    duck, pg = installed
    pg.execute("DELETE FROM storage_migration WHERE marker=%s", [lifecycle.LIFECYCLE_MARKER])
    with pytest.raises(Exception, match="既有数据/结构"):
        lifecycle.initialize_database(duck, pg, mode="init")


def test_check_never_repairs_or_seeds(installed):
    duck, pg = installed
    pg.execute("DELETE FROM app_config WHERE key='audit.retention_days'")
    assert not lifecycle.verify_database(duck, pg)["ok"]
    assert pg.query_df("SELECT key FROM app_config WHERE key='audit.retention_days'").empty


def test_pg_execute_and_queries_share_outer_transaction(databases):
    _, pg = databases
    with pytest.raises(Exception, match="回滚"), pg.transaction():
        pg.execute("CREATE TABLE rollback_probe(id INTEGER PRIMARY KEY)")
        with pg.transaction():
            pg.execute("INSERT INTO rollback_probe VALUES (1)")
        assert pg.query_df("SELECT id FROM rollback_probe").iloc[0, 0] == 1
        raise RuntimeError("回滚")
    assert "rollback_probe" not in lifecycle._tables(pg, "public")


@pytest.mark.parametrize("outcome", ["skip", "xfail"])
def test_gate_rejects_skipped_and_expected_failure_tests(tmp_path, outcome):
    """通过真实 pytest 子进程证明插件拒绝跳过，不靠源码字符串断言。"""
    from backend.config import PROJECT_ROOT

    probe = tmp_path / "test_gate_probe.py"
    probe.write_text(f"import pytest\ndef test_probe():\n    pytest.{outcome}('probe')\n")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "backend.devtools.database_gate_plugin",
            str(probe),
            "-q",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr


def test_empty_builtin_role_grants_stay_empty_after_restart(installed):
    duck, pg = installed
    pg.execute("DELETE FROM sys_role_menu WHERE role_id='normal'")
    pg.execute("DELETE FROM sys_role_resource WHERE role_id='normal'")
    assert lifecycle.initialize_database(duck, pg, mode="upgrade")["ok"]
    assert pg.query_df("SELECT 1 FROM sys_role_menu WHERE role_id='normal'").empty
    assert pg.query_df("SELECT 1 FROM sys_role_resource WHERE role_id='normal'").empty


def test_completed_install_rejects_lost_route_marker(installed):
    duck, pg = installed
    from backend.storage.task_runtime import TASK_RUNTIME_MIGRATION_MARKER

    pg.execute("DELETE FROM storage_migration WHERE marker=%s", [TASK_RUNTIME_MIGRATION_MARKER])
    report = lifecycle.verify_database(duck, pg)
    assert not report["ok"]
    assert "新装任务运行态未启用 PostgreSQL" in report["checks"]["seeds"]["violations"]


def test_completed_install_rejects_stale_completion_digest(installed):
    duck, pg = installed
    pg.execute(
        "UPDATE storage_migration SET details=jsonb_set(details,'{contract_sha256}',%s::jsonb) "
        "WHERE marker=%s",
        [json.dumps("0" * 64), lifecycle.LIFECYCLE_MARKER],
    )
    assert not lifecycle.verify_database(duck, pg)["checks"]["completion"]["ok"]
    assert lifecycle.initialize_database(duck, pg, mode="upgrade")["ok"]


def test_startup_uses_complete_initializer(databases, monkeypatch):
    duck, pg = databases
    from backend import storage
    from backend.main import create_app

    monkeypatch.setattr(storage, "get_redis_client", lambda: SimpleNamespace(ping=lambda: True))
    app = create_app()
    next(handler for handler in app.router.on_startup if handler.__name__ == "_check_storages")()
    assert lifecycle.verify_database(duck, pg, require_pg_routes=True)["ok"]


def test_required_duck_migration_failure_stops_and_can_retry(databases, monkeypatch):
    duck, pg = databases
    from backend.storage import ddl

    migrations = ddl._MIGRATIONS
    monkeypatch.setattr(
        ddl, "_MIGRATIONS", [*migrations, "ALTER TABLE missing_required_table ADD COLUMN x INTEGER"]
    )
    with pytest.raises(Exception, match="missing_required_table"):
        lifecycle.initialize_database(duck, pg, mode="init")
    assert not lifecycle._tables(pg, "public")
    monkeypatch.setattr(ddl, "_MIGRATIONS", migrations)
    assert lifecycle.initialize_database(duck, pg, mode="init")["ok"]


def test_contract_normalization_preserves_literal_semantics():
    from backend.storage.schema_contract import _sql

    assert _sql(" 'a  b'::text") != _sql(" 'a b'::text")
    assert _sql("'public.\"literal\"'") == "'public.\"literal\"'"


def test_real_cli_plan_fingerprint_apply_check_and_catalog(databases, tmp_path):
    _, pg = databases
    from backend.config import PROJECT_ROOT
    from backend.storage.schema_contract import target_fingerprint

    market_file = tmp_path / "cli.duckdb"
    config = tmp_path / "settings.yaml"
    config.write_text(f"paths:\n  duckdb_file: {market_file}\n", encoding="utf-8")
    env = {**os.environ, "AI_STOCKS_PG_DSN": pg.conninfo, "AI_STOCKS_CONFIG": str(config)}

    def cli(*arguments):
        return subprocess.run(
            [sys.executable, "-m", "backend.cli", *arguments],
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    plan = cli("database", "plan")
    assert plan.returncode == 0, plan.stdout + plan.stderr
    assert not market_file.exists() and not lifecycle._tables(pg, "public")
    rejected = cli("database", "init", "--apply", "--expected-target-fingerprint", "invalid")
    assert rejected.returncode != 0
    assert not market_file.exists() and not lifecycle._tables(pg, "public")
    initialized = cli(
        "database",
        "init",
        "--apply",
        "--expected-target-fingerprint",
        target_fingerprint(pg, market_file),
    )
    assert initialized.returncode == 0, initialized.stdout + initialized.stderr
    checked = cli("database", "check")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    catalog = cli("verify-catalog")
    assert catalog.returncode == 0, catalog.stdout + catalog.stderr
    report = json.loads(next(line for line in catalog.stdout.splitlines() if line.startswith("{")))
    assert report["ok"] and report["field_count"] > 0


@pytest.mark.parametrize(
    "name",
    [
        "test_startup_init_preserves_every_existing_menu_and_resource_row",
        "test_seed_role_grants_acquires_shared_publish_lock",
        "test_seed_role_grants_atomic_rollback_on_failure",
        "test_seed_role_grants_preserves_explicit_empty_menus",
        "test_seed_role_grants_preserves_explicit_empty_grants",
        "test_asset_publish_open_rollback_restores_c4_baseline",
    ],
)
def test_existing_rbac_initialization_regressions(installed, name):
    """复用既有 RBAC 回归，平台级改写只允许在此隔离 PG 库内运行。"""
    from backend.tests import test_rbac_schema

    _, pg = installed
    getattr(test_rbac_schema, name)(pg)


def test_known_legacy_constraints_converge_without_losing_state(installed):
    duck, pg = installed
    fixture = Path(__file__).parent / "fixtures/database"
    duck.execute((fixture / "legacy-constraints-v1-duck.sql").read_text())
    pg.execute((fixture / "legacy-constraints-v1-pg.sql").read_text())
    duck.execute(
        "INSERT INTO stock_board_correlation_state "
        "(code,as_of_date,computed_at,algorithm_version,benchmark_code,industry_empty_reason,"
        "industry_max_sample_20) VALUES ('600000.SH','2024-01-02','2024-01-02','legacy',"
        "'000300.SH','insufficient_samples',12)"
    )
    assert lifecycle.initialize_database(duck, pg, mode="upgrade")["ok"]
    row = duck.query_df(
        "SELECT algorithm_version,industry_empty_reason,industry_max_sample_20 "
        "FROM stock_board_correlation_state WHERE code='600000.SH'"
    ).iloc[0]
    assert row.tolist() == ["legacy", "insufficient_samples", 12]
    assert schema_report(duck, pg)["ok"]


def test_legacy_actor_violations_abort_upgrade_without_rewriting_history(installed):
    duck, pg = installed
    fixture = Path(__file__).parent / "fixtures/database/legacy-constraints-v1-pg.sql"
    pg.execute(fixture.read_text())
    pg.execute(
        "INSERT INTO limit_ladder_task_ledger(command_id,trade_date,source,actor_kind,tenant_id,"
        "actor_account,status,rule_version) VALUES ('legacy-invalid','2024-01-02',"
        "'auto_first_load','system','legacy-tenant','legacy-account','failed','legacy')"
    )
    before = pg.query_df("SELECT * FROM limit_ladder_task_ledger WHERE command_id='legacy-invalid'")
    with pytest.raises(Exception, match="ll_actor_consistency_check"):
        lifecycle.initialize_database(duck, pg, mode="upgrade")
    after = pg.query_df("SELECT * FROM limit_ladder_task_ledger WHERE command_id='legacy-invalid'")
    assert before.to_dict("records") == after.to_dict("records")


def test_explicit_discipline_rollback_is_preserved(installed):
    duck, pg = installed
    from backend.storage import pg_ddl

    pg_ddl._rollback_trade_discipline_rbac(pg)
    assert lifecycle.initialize_database(duck, pg, mode="upgrade")["ok"]
    assert pg.query_df("SELECT id FROM sys_menu WHERE code='/trade-discipline'").empty
    assert lifecycle.verify_database(duck, pg)["ok"]


def test_readonly_startup_verifies_without_initializing(installed, monkeypatch):
    duck, _pg = installed
    from backend import storage
    from backend.main import create_app

    def forbidden(*args, **kwargs):
        raise AssertionError("只读启动不能初始化")

    monkeypatch.setattr(duck, "read_only", True)
    monkeypatch.setattr(lifecycle, "initialize_database", forbidden)
    monkeypatch.setattr(storage, "get_redis_client", lambda: SimpleNamespace(ping=lambda: True))
    app = create_app()
    next(handler for handler in app.router.on_startup if handler.__name__ == "_check_storages")()


def test_dependency_failure_precedes_initialization(databases, monkeypatch):
    _, pg = databases
    from backend import storage
    from backend.main import create_app

    monkeypatch.setattr(storage, "get_redis_client", lambda: SimpleNamespace(ping=lambda: False))
    app = create_app()
    handler = next(
        handler for handler in app.router.on_startup if handler.__name__ == "_check_storages"
    )
    with pytest.raises(RuntimeError, match="Redis"):
        handler()
    assert not lifecycle._tables(pg, "public")


def test_non_dev_fresh_install_requires_explicit_admin_password(databases, monkeypatch):
    duck, pg = databases
    monkeypatch.setenv("AI_STOCKS_ENV", "prod")
    monkeypatch.delenv("AI_STOCKS_ADMIN_PASSWORD", raising=False)
    with pytest.raises(Exception, match="显式设置 AI_STOCKS_ADMIN_PASSWORD"):
        lifecycle.initialize_database(duck, pg, mode="init")
    assert not lifecycle._tables(pg, "public")
    assert not lifecycle._tables(duck, "main")


def test_first_adoption_preserves_existing_empty_role_grants(installed):
    duck, pg = installed
    pg.execute("DELETE FROM app_config WHERE key='migration.builtin_role_defaults_v1.normal'")
    pg.execute("DELETE FROM sys_role_menu WHERE role_id='normal'")
    pg.execute("DELETE FROM sys_role_resource WHERE role_id='normal'")
    assert lifecycle.initialize_database(duck, pg, mode="upgrade")["ok"]
    assert pg.query_df("SELECT 1 FROM sys_role_menu WHERE role_id='normal'").empty
    assert pg.query_df("SELECT 1 FROM sys_role_resource WHERE role_id='normal'").empty


def test_restart_preserves_user_with_all_roles_revoked(installed):
    duck, pg = installed
    pg.execute(
        "INSERT INTO sys_user(id,tenant_id,account,role_code) "
        "VALUES ('revoked-user','default','revoked-user','normal')"
    )
    assert lifecycle.initialize_database(duck, pg, mode="upgrade")["ok"]
    assert pg.query_df("SELECT 1 FROM sys_user_role WHERE user_id='revoked-user'").empty


def test_missing_authoritative_role_relation_is_not_guessed(installed):
    duck, pg = installed
    pg.execute("DROP TABLE sys_user_role")
    with pytest.raises(Exception, match="拒绝猜测恢复用户授权"):
        lifecycle.initialize_database(duck, pg, mode="upgrade")
    assert "sys_user_role" not in lifecycle._tables(pg, "public")


def test_explicit_clients_do_not_read_machine_default_databases(databases, monkeypatch):
    duck, pg = databases
    from backend.storage import duckdb_client, pg_client

    class Forbidden:
        def __getattr__(self, name):
            raise AssertionError(f"禁止访问默认业务库: {name}")

    default_pg, default_duck = Forbidden(), Forbidden()
    monkeypatch.setattr(pg_client, "_client", default_pg)
    monkeypatch.setattr(duckdb_client, "_client", default_duck)
    assert lifecycle.initialize_database(duck, pg, mode="init")["ok"]
    assert lifecycle.verify_database(duck, pg)["ok"]
    assert pg_client.get_pg_client() is default_pg
    assert duckdb_client.get_client() is default_duck


def test_explicit_catalog_does_not_poison_default_runtime_cache(installed):
    duck, pg = installed
    from backend.storage import task_runtime

    task_runtime._backend_cache = "duckdb"
    assert lifecycle.verify_database(duck, pg)["ok"]
    assert task_runtime._backend_cache == "duckdb"


def test_gate_rejects_partial_selection(tmp_path):
    from backend.config import PROJECT_ROOT

    probe = tmp_path / "test_gate_subset.py"
    probe.write_text("def test_first():\n    assert True\ndef test_second():\n    assert True\n")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "backend.devtools.database_gate_plugin",
            str(probe),
            "-k",
            "first",
            "-q",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "deselected" in result.stdout


def test_gate_runner_removes_environment_selection(monkeypatch):
    from contextlib import contextmanager

    from backend.devtools import database_gate

    @contextmanager
    def fake_server():
        yield "dbname=isolated-admin"

    def subprocess_probe(arguments, **options):
        assert "PYTEST_ADDOPTS" not in options["env"]
        assert "PYTEST_PLUGINS" not in options["env"]
        assert options["env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
        assert "addopts=" in arguments
        return SimpleNamespace(returncode=0)

    monkeypatch.setenv("PYTEST_ADDOPTS", "-k only_one_test")
    monkeypatch.setenv("PYTEST_PLUGINS", "untrusted_plugin")
    monkeypatch.setattr(database_gate, "gate_server", fake_server)
    monkeypatch.setattr(database_gate.subprocess, "run", subprocess_probe)
    assert database_gate.run_gate() == 0


def test_quoted_identifier_constraints_remain_distinguishable(databases):
    _, pg = databases
    pg.execute(
        'CREATE TABLE quote_probe(value TEXT,"public.value" TEXT, '
        'CONSTRAINT probe_check CHECK ("public.value" IS NOT NULL))'
    )
    before = pg_schema(pg)["tables"]["quote_probe"]
    pg.execute("ALTER TABLE quote_probe DROP CONSTRAINT probe_check")
    pg.execute("ALTER TABLE quote_probe ADD CONSTRAINT probe_check CHECK (value IS NOT NULL)")
    after = pg_schema(pg)["tables"]["quote_probe"]
    assert schema_differences(before, after)


def test_duck_ddl_and_rows_roll_back_on_original_connection(tmp_path):
    with DuckDBClient(tmp_path / "rollback.duckdb") as duck:
        duck.execute("CREATE TABLE original_table(id INTEGER)")
        duck.execute("INSERT INTO original_table VALUES (1)")
        with pytest.raises(Exception, match="missing_table"), duck.transaction():
            duck.execute("ALTER TABLE original_table RENAME TO renamed_table")
            duck.execute("UPDATE renamed_table SET id=2")
            duck.execute("INSERT INTO missing_table VALUES (1)")
        assert duck.query_df("SELECT id FROM original_table").iloc[0, 0] == 1
        assert "renamed_table" not in lifecycle._tables(duck, "main")


@pytest.mark.parametrize("extra", ["column", "index", "constraint", "type"])
def test_unknown_source_structure_is_rejected_before_duck_rebuild(installed, extra):
    duck, _pg = installed
    from backend.storage import ddl

    fixture = Path(__file__).parent / "fixtures/database/legacy-constraints-v1-duck.sql"
    duck.execute(fixture.read_text())
    if extra == "column":
        duck.execute("ALTER TABLE stock_board_correlation_state ADD COLUMN audit_note VARCHAR")
    elif extra == "index":
        duck.execute("CREATE INDEX custom_state_index ON stock_board_correlation_state(code)")
    elif extra == "type":
        duck.execute(
            "ALTER TABLE stock_board_correlation_state ALTER COLUMN industry_max_sample_20 TYPE DOUBLE"
        )
    else:
        # DuckDB 不支持 ADD CHECK，按相同旧形态创建一个附加业务约束的表。
        duck.execute("DROP TABLE stock_board_correlation_state")
        source = ddl.DDL_STOCK_BOARD_CORRELATION_STATE.replace(
            "PRIMARY KEY (code, as_of_date)", "CHECK (length(code)>0), PRIMARY KEY (code)"
        )
        duck.execute(source)
    duck.execute(
        "INSERT INTO stock_board_correlation_state"
        "(code,as_of_date,computed_at,algorithm_version,benchmark_code,industry_max_sample_20) "
        "VALUES ('600000.SH','2024-01-02','2024-01-02','legacy','000300.SH',12)"
    )
    before = duck_schema(duck)["tables"]["stock_board_correlation_state"]
    with pytest.raises(Exception, match="未识别的源结构|未知 CHECK"):
        if extra == "constraint":
            ddl._migrate_stock_board_correlation_snapshot_keys(duck)
        else:
            ddl._migrate_correlation_state_checks(duck)
    assert duck_schema(duck)["tables"]["stock_board_correlation_state"] == before
    assert (
        duck.query_df("SELECT industry_max_sample_20 FROM stock_board_correlation_state").iloc[0, 0]
        == 12
    )


def test_existing_staging_table_is_not_deleted(installed):
    duck, _pg = installed
    from backend.storage import ddl

    duck.execute("DROP TABLE stock_board_correlation_state")
    duck.execute(
        ddl.DDL_STOCK_BOARD_CORRELATION_STATE.replace(
            "PRIMARY KEY (code, as_of_date)", "PRIMARY KEY (code)"
        )
    )
    duck.execute("CREATE TABLE stock_board_correlation_state_pk_new(note VARCHAR)")
    duck.execute("INSERT INTO stock_board_correlation_state_pk_new VALUES ('保留原有内容')")
    original_connection = duck.conn
    with pytest.raises(Exception, match="already exists"):
        ddl._migrate_stock_board_correlation_snapshot_keys(duck)
    assert (
        original_connection.execute(
            "SELECT note FROM stock_board_correlation_state_pk_new"
        ).fetchone()[0]
        == "保留原有内容"
    )


@pytest.mark.parametrize(
    "statement,fragment",
    [
        ("UPDATE sys_role SET is_locked=false WHERE code='system'", "内置角色"),
        ("UPDATE layout_preset SET enabled=false WHERE is_builtin IS TRUE", "视觉预设"),
        (
            "UPDATE app_config SET value='\"invalid\"' WHERE key='audit.retention_days'",
            "类型或范围",
        ),
    ],
)
def test_seed_presence_is_not_enough_to_pass(installed, statement, fragment):
    duck, pg = installed
    pg.execute(statement)
    report = lifecycle.verify_database(duck, pg)
    assert not report["ok"]
    assert any(fragment in issue for issue in report["checks"]["seeds"]["violations"])


def test_target_fingerprint_includes_market_file(databases, tmp_path):
    _, pg = databases
    from backend.storage.schema_contract import target_fingerprint

    assert target_fingerprint(pg, tmp_path / "first.duckdb") != target_fingerprint(
        pg, tmp_path / "second.duckdb"
    )


def test_reordered_legacy_columns_keep_their_original_meaning(installed):
    duck, _ = installed
    from backend.storage import ddl

    duck.execute("DROP TABLE stock_special_trading_day")
    legacy = ddl.DDL_STOCK_SPECIAL_TRADING_DAY.replace(
        "event_type IN ('delisting_first_day', 'resumption_no_limit')",
        "event_type = 'delisting_first_day'",
    )
    lines = legacy.splitlines()
    source = next(
        index for index, line in enumerate(lines) if line.strip().startswith("source_ref ")
    )
    note = next(index for index, line in enumerate(lines) if line.strip().startswith("note "))
    lines[source], lines[note] = lines[note], lines[source]
    duck.execute("\n".join(lines))
    duck.execute(
        "INSERT INTO stock_special_trading_day(code,trade_date,event_type,announcement_date,"
        "source_ref,note,active,task_id,updated_at) VALUES ('600000.SH','2024-01-02',"
        "'delisting_first_day','2024-01-01','official-url','人工核验说明',true,'original','2024-01-02')"
    )
    ddl._migrate_special_day_event_types(duck)
    assert duck.query_df("SELECT source_ref,note FROM stock_special_trading_day").iloc[
        0
    ].tolist() == [
        "official-url",
        "人工核验说明",
    ]


@pytest.mark.parametrize(
    "table,expression",
    [
        ("trade_discipline_action_rule", "action_subtype <> 'restricted'"),
        ("trade_discipline_checkin_revision", "assessment <> 'restricted'"),
        ("trade_discipline_stock_rule", "length(btrim(content)) < 1000"),
    ],
)
def test_pg_upgrade_does_not_silently_drop_custom_checks(installed, table, expression):
    duck, pg = installed
    pg.execute(f"ALTER TABLE {table} ADD CONSTRAINT custom_check CHECK ({expression})")
    before = pg_schema(pg)["tables"][table]
    with pytest.raises(Exception, match="未知 CHECK"):
        lifecycle.initialize_database(duck, pg, mode="upgrade")
    assert pg_schema(pg)["tables"][table] == before


def test_dimension_labels_are_preserved_on_repeat(installed):
    duck, pg = installed
    duck.execute(
        "UPDATE data_dimension_registry SET descr='人工说明' WHERE dimension='shareholders'"
    )
    assert lifecycle.initialize_database(duck, pg, mode="upgrade")["ok"]
    assert (
        duck.query_df(
            "SELECT descr FROM data_dimension_registry WHERE dimension='shareholders'"
        ).iloc[0, 0]
        == "人工说明"
    )


@pytest.mark.parametrize(
    "table,expression",
    [
        (
            "trade_discipline_action_rule",
            "action_subtype IN ('open_position','add_position','liquidate','reduce_position')",
        ),
        ("trade_discipline_checkin_revision", "assessment IN ('complied','breached')"),
    ],
)
def test_recognized_pg_legacy_checks_still_upgrade(installed, table, expression):
    duck, pg = installed
    pg.execute(f"ALTER TABLE {table} ADD CONSTRAINT recognized_legacy CHECK ({expression})")
    assert lifecycle.initialize_database(duck, pg, mode="upgrade")["ok"]
    assert schema_report(duck, pg)["ok"]


def test_non_dev_upgrade_never_generates_or_logs_admin_password(installed, monkeypatch, caplog):
    duck, pg = installed
    pg.execute("UPDATE sys_user SET password_hash=NULL WHERE id='admin'")
    monkeypatch.setenv("AI_STOCKS_ENV", "prod")
    monkeypatch.delenv("AI_STOCKS_ADMIN_PASSWORD", raising=False)
    with pytest.raises(Exception, match="显式设置 AI_STOCKS_ADMIN_PASSWORD"):
        lifecycle.initialize_database(duck, pg, mode="upgrade")
    assert pg.query_df("SELECT password_hash FROM sys_user WHERE id='admin'").iloc[0, 0] is None
    assert "随机初始密码" not in caplog.text


def test_corrupt_completion_metadata_cannot_be_silently_rewritten(installed):
    duck, pg = installed
    pg.execute(
        "UPDATE storage_migration SET details='{}' WHERE marker=%s", [lifecycle.LIFECYCLE_MARKER]
    )
    assert not lifecycle.verify_database(duck, pg)["ok"]
    with pytest.raises(Exception, match="完成标记损坏"):
        lifecycle.initialize_database(duck, pg, mode="upgrade")
    assert (
        pg.query_df(
            "SELECT details FROM storage_migration WHERE marker=%s", [lifecycle.LIFECYCLE_MARKER]
        ).iloc[0, 0]
        == {}
    )


def test_pre_rbac_users_receive_roles_once_with_perm_version(databases):
    duck, pg = databases
    from backend.storage import pg_ddl

    pg.execute(pg_ddl.DDL_SYS_TENANT)
    pg.execute(pg_ddl.DDL_SYS_USER)
    pg.execute(
        "INSERT INTO sys_user(id,tenant_id,account,role_code,perm_ver) "
        "VALUES ('legacy-user','default','legacy-user','normal',7)"
    )
    assert lifecycle.initialize_database(duck, pg, mode="upgrade")["ok"]
    assert (
        pg.query_df("SELECT role_id FROM sys_user_role WHERE user_id='legacy-user'").iloc[0, 0]
        == "normal"
    )
    version = pg.query_df("SELECT perm_ver FROM sys_user WHERE id='legacy-user'").iloc[0, 0]
    assert version > 7
    assert lifecycle.initialize_database(duck, pg, mode="upgrade")["ok"]
    assert pg.query_df("SELECT perm_ver FROM sys_user WHERE id='legacy-user'").iloc[0, 0] == version


@pytest.mark.parametrize(
    "case", ["pg_roundtrip", "pg_rollback", "legacy_correlation", "legacy_special_day"]
)
def test_existing_storage_regressions_in_isolated_databases(installed, case):
    duck, pg = installed
    if case == "pg_roundtrip":
        from backend.tests.test_storage_clients import test_pg_execute_query_roundtrip

        test_pg_execute_query_roundtrip(pg)
    elif case == "pg_rollback":
        from backend.tests.test_storage_clients import test_pg_transaction_rollback

        test_pg_transaction_rollback(pg)
    elif case == "legacy_correlation":
        from backend.tests.test_stock_board_correlation_storage import (
            test_init_db_migrates_old_current_state_primary_keys_and_preserves_rows,
        )

        test_init_db_migrates_old_current_state_primary_keys_and_preserves_rows()
    else:
        from backend.tests.test_stock_special_trading_day import (
            test_legacy_constraint_upgrade_preserves_facts_and_is_idempotent,
        )

        test_legacy_constraint_upgrade_preserves_facts_and_is_idempotent(duck)


def test_existing_pg_task_transaction_admission(installed, monkeypatch):
    from backend.tests.test_task_runtime_storage import (
        test_writer_admission_honors_oldest_ladder_and_releases_expired_queue,
    )

    duck, pg = installed
    test_writer_admission_honors_oldest_ladder_and_releases_expired_queue(pg, duck, monkeypatch)
