"""交易纪律 T1：PG 模型、索引与可回滚 RBAC 状态机。"""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.cli import cmd_trade_discipline_rbac
from backend.common.exceptions import StorageError
from backend.storage import pg_ddl
from backend.storage.pg_ddl import (
    ASSET_PK,
    TRADE_DISCIPLINE_RBAC_MARKER,
    _rollback_trade_discipline_rbac,
    _seed_trade_discipline_rbac,
    _trade_discipline_marker_state,
    seed_rbac,
)
from backend.tests.conftest import insert_test_role

TD_TABLES = {
    "trade_discipline_rule",
    "trade_discipline_rule_name_claim",
    "trade_discipline_rule_draft",
    "trade_discipline_draft_stock_rule",
    "trade_discipline_draft_action_rule",
    "trade_discipline_rule_version",
    "trade_discipline_stock_rule",
    "trade_discipline_action_subtype",
    "trade_discipline_action_rule",
    "trade_discipline_rule_activation",
    "trade_discipline_checkin",
    "trade_discipline_checkin_revision",
    "trade_discipline_reason",
    "trade_discipline_violation",
    "trade_discipline_operation",
}


def _delete_td_rbac(pg, contract) -> None:
    resource_ids = list(contract.resource_codes)
    with pg.transaction() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM sys_role_resource WHERE resource_id = ANY(%s)", [resource_ids])
        cur.execute("DELETE FROM sys_role_menu WHERE menu_id=%s", [contract.menu_id])
        cur.execute("DELETE FROM sys_resource WHERE id = ANY(%s)", [resource_ids])
        cur.execute("DELETE FROM sys_menu WHERE id=%s", [contract.menu_id])
        cur.execute("DELETE FROM app_config WHERE key=%s", [contract.marker_key])


@pytest.fixture
def td_rbac_sandbox(pg, monkeypatch):
    """用随机 RBAC 身份验证状态机，禁止删除或重建运行中的真实菜单和授权。"""
    suffix = uuid4().hex[:10]
    menu_id = f"pytest_td_menu_{suffix}"
    marker_key = f"pytest.td_marker_{suffix}"
    role_ids = tuple(f"pytest_td_role_{suffix}_{kind}" for kind in ("system", "admin", "normal"))
    resource_codes = tuple(f"pytest-td-{suffix}:{index}" for index in range(1, 5))
    resources = tuple(
        (
            menu_id,
            code,
            f"交易纪律测试功能点{index}",
            "api",
            "GET" if index in (1, 3) else "POST",
            f"/api/pytest-trade-discipline/{suffix}/{index}",
        )
        for index, code in enumerate(resource_codes, start=1)
    )
    contract = SimpleNamespace(
        menu_id=menu_id,
        marker_key=marker_key,
        resource_codes=resource_codes,
        system_role=role_ids[0],
        tenant_admin_role=role_ids[1],
        normal_role=role_ids[2],
    )
    for role_id in role_ids:
        insert_test_role(pg, role_id)
    monkeypatch.setattr(pg_ddl, "_TRADE_DISCIPLINE_MENU_ID", menu_id)
    monkeypatch.setattr(pg_ddl, "TRADE_DISCIPLINE_RBAC_MARKER", marker_key)
    monkeypatch.setattr(pg_ddl, "TRADE_DISCIPLINE_RBAC_LOCK", 8500000000 + int(suffix[:6], 16))
    monkeypatch.setattr(pg_ddl, "TRADE_DISCIPLINE_RESOURCE_CODES", resource_codes)
    monkeypatch.setattr(pg_ddl, "_SEED_RESOURCES", (*pg_ddl._SEED_RESOURCES, *resources))
    monkeypatch.setattr(pg_ddl, "ROLE_SYSTEM", contract.system_role)
    monkeypatch.setattr(pg_ddl, "ROLE_TENANT_ADMIN", contract.tenant_admin_role)
    monkeypatch.setattr(pg_ddl, "ROLE_NORMAL", contract.normal_role)
    _delete_td_rbac(pg, contract)
    _seed_trade_discipline_rbac(pg)
    try:
        yield contract
    finally:
        _delete_td_rbac(pg, contract)
        for role_id in role_ids:
            pg.execute("DELETE FROM sys_role WHERE id=%s", [role_id])


def test_trade_discipline_tables_primary_keys_and_numeric_money(pg):
    tables = set(pg.query_df(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name = ANY(%s)",
        [list(TD_TABLES)],
    )["table_name"])
    assert tables == TD_TABLES
    assert TD_TABLES <= set(ASSET_PK)
    assert all(keys[:2] == ["tenant_id", "owner_user_id"] for keys in (
        ASSET_PK[table] for table in TD_TABLES
    ))

    money_columns = pg.query_df(
        "SELECT table_name, column_name, data_type, numeric_scale "
        "FROM information_schema.columns WHERE table_schema='public' "
        "AND table_name = ANY(%s) AND column_name = ANY(%s)",
        [list(TD_TABLES), ["capital", "max_capital", "price", "quantity", "amount", "fee"]],
    )
    assert not money_columns.empty
    assert set(money_columns["data_type"]) == {"numeric"}
    assert {int(scale) for scale in money_columns["numeric_scale"]} <= {2, 4}


def test_trade_discipline_foreign_keys_include_owner_and_indexes_exist(pg):
    definitions = pg.query_df(
        "SELECT pg_get_constraintdef(c.oid) AS definition FROM pg_constraint c "
        "JOIN pg_class t ON t.oid=c.conrelid "
        "WHERE c.contype='f' AND t.relname = ANY(%s)",
        [list(TD_TABLES)],
    )["definition"].tolist()
    assert definitions
    assert all("FOREIGN KEY (tenant_id, owner_user_id" in definition for definition in definitions)

    indexes = set(pg.query_df(
        "SELECT indexname FROM pg_indexes WHERE schemaname='public' "
        "AND indexname = ANY(%s)",
        [[
            "idx_td_rule_owner_status",
            "idx_td_activation_effective",
            "idx_td_checkin_history",
            "idx_td_revision_detail",
            "idx_td_operation_stock",
            "idx_td_violation_reason_name",
        ]],
    )["indexname"])
    assert len(indexes) == 6

    checks = set(pg.query_df(
        "SELECT conname FROM pg_constraint WHERE conname = ANY(%s)",
        [[
            "td_rule_lifecycle_consistency_check",
            "td_checkin_status_time_check",
            "td_revision_kind_no_check",
            "td_rule_latest_version_fk",
            "td_checkin_current_revision_fk",
            "td_checkin_submission_source_check",
            "td_revision_assessment_check",
            "td_revision_violation_detail_check",
            "td_operation_compliance_status_check",
        ]],
    )["conname"])
    assert len(checks) == 9

    source = pg.query_df(
        "SELECT column_default,is_nullable FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='trade_discipline_checkin' "
        "AND column_name='submission_source'"
    ).iloc[0]
    assert "workbench" in source["column_default"] and source["is_nullable"] == "NO"

    compliance_column = pg.query_df(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='trade_discipline_operation' "
        "AND column_name='compliance_status'"
    ).iloc[0]
    assert compliance_column["is_nullable"] == "YES"

    obsolete_name_uniques = pg.query_df(
        "SELECT c.conname FROM pg_constraint c "
        "WHERE c.conrelid='trade_discipline_rule_name_claim'::regclass AND c.contype='u' "
        "AND (SELECT array_agg(a.attname ORDER BY k.ordinality) "
        "FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ordinality) "
        "JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum)="
        "ARRAY['tenant_id','owner_user_id','rule_id']::name[]"
    )
    assert obsolete_name_uniques.empty

    with pytest.raises(StorageError):
        pg.execute(
            "INSERT INTO trade_discipline_rule "
            "(id,tenant_id,owner_user_id,status,latest_version_no) "
            "VALUES (%s,%s,%s,'active',1)",
            ["pytest-invalid-active", "pytest", "pytest_owner"],
        )


def test_trade_discipline_marker_parser_rejects_unknown_and_conflicting_states(pg):
    raw = pg.query_df(
        "SELECT value FROM app_config WHERE key=%s", [TRADE_DISCIPLINE_RBAC_MARKER]
    ).iloc[0]["value"]
    state, ledger = _trade_discipline_marker_state(raw)
    assert state == "applied"
    assert ledger is not None

    tombstone = {**ledger, "applied": False, "rolled_back": True}
    assert _trade_discipline_marker_state(tombstone)[0] == "rolled_back"
    assert _trade_discipline_marker_state("not-json")[0] == "invalid"
    assert _trade_discipline_marker_state({**ledger, "version": 99})[0] == "invalid"
    assert _trade_discipline_marker_state({**ledger, "version": True})[0] == "invalid"
    assert _trade_discipline_marker_state({**ledger, "rolled_back": True})[0] == "invalid"
    duplicated = {**ledger, "inserted_resource_ids": ledger["inserted_resource_ids"] * 2}
    assert _trade_discipline_marker_state(duplicated)[0] == "invalid"
    reordered = {**ledger, "inserted_resource_ids": list(reversed(ledger["inserted_resource_ids"]))}
    assert _trade_discipline_marker_state(reordered)[0] == "invalid"


def test_trade_discipline_seed_is_idempotent_and_rollback_tombstone_does_not_revive(
    pg, td_rbac_sandbox
):
    before = pg.query_df("SELECT id, perm_ver FROM sys_user ORDER BY id").to_dict("records")
    assert _seed_trade_discipline_rbac(pg)["state"] == "applied"
    assert pg.query_df("SELECT id, perm_ver FROM sys_user ORDER BY id").to_dict("records") == before

    report = _rollback_trade_discipline_rbac(pg)
    assert report["state"] == "rolled_back"
    assert report["deleted"] == 20
    assert pg.query_df(
        "SELECT 1 FROM sys_menu WHERE id=%s", [td_rbac_sandbox.menu_id]
    ).empty
    assert pg.query_df(
        "SELECT 1 FROM sys_resource WHERE id = ANY(%s)",
        [list(td_rbac_sandbox.resource_codes)],
    ).empty

    seed_rbac(pg)
    assert pg.query_df(
        "SELECT 1 FROM sys_menu WHERE id=%s", [td_rbac_sandbox.menu_id]
    ).empty
    marker = json.loads(pg.query_df(
        "SELECT value FROM app_config WHERE key=%s", [td_rbac_sandbox.marker_key]
    ).iloc[0]["value"])
    assert marker["applied"] is False and marker["rolled_back"] is True


def test_trade_discipline_seed_preserves_runtime_menu_configuration(pg, td_rbac_sandbox):
    """管理员维护菜单和功能点后，启动期状态机不得覆盖或拒绝运行时配置。"""
    parent_id = f"{td_rbac_sandbox.menu_id}_parent"
    pg.execute(
        "INSERT INTO sys_menu "
        "(id,parent_id,code,title,type,route_path,icon,sort,visible,is_builtin) "
        "VALUES (%s,NULL,%s,%s,'group',NULL,'Menu',900,'login',FALSE)",
        [parent_id, parent_id, "交易测试分组"],
    )
    try:
        pg.execute(
            "UPDATE sys_menu SET parent_id=%s,title=%s,type='group',route_path=NULL,icon=NULL,"
            "sort=%s,visible='system',updated_at=now() WHERE id=%s",
            [parent_id, "运行期交易纪律", 70, td_rbac_sandbox.menu_id],
        )
        pg.execute(
            "UPDATE sys_resource SET menu_id=%s,name=%s,type='button',api_method='PATCH',"
            "api_path=%s,sort=700 WHERE id=%s",
            [
                td_rbac_sandbox.menu_id,
                "运行期功能点",
                "/api/runtime-trade-discipline",
                td_rbac_sandbox.resource_codes[0],
            ],
        )
        seed_rbac(pg)
        row = pg.query_df(
            "SELECT parent_id,title,type,route_path,icon,sort,visible FROM sys_menu WHERE id=%s",
            [td_rbac_sandbox.menu_id],
        ).iloc[0]
        assert row["parent_id"] == parent_id
        assert row["title"] == "运行期交易纪律"
        assert row["type"] == "group"
        assert row["route_path"] is None
        assert row["icon"] is None
        assert int(row["sort"]) == 70
        assert row["visible"] == "system"
        resource = pg.query_df(
            "SELECT name,type,api_method,api_path,sort FROM sys_resource WHERE id=%s",
            [td_rbac_sandbox.resource_codes[0]],
        ).iloc[0]
        assert resource["name"] == "运行期功能点"
        assert resource["type"] == "button"
        assert resource["api_method"] == "PATCH"
        assert resource["api_path"] == "/api/runtime-trade-discipline"
        assert int(resource["sort"]) == 700
    finally:
        pg.execute(
            "UPDATE sys_menu SET parent_id=NULL WHERE id=%s",
            [td_rbac_sandbox.menu_id],
        )
        pg.execute("DELETE FROM sys_menu WHERE id=%s", [parent_id])


def test_trade_discipline_seed_conflict_rolls_back_atomically(pg, td_rbac_sandbox):
    _rollback_trade_discipline_rbac(pg)
    pg.execute("DELETE FROM app_config WHERE key=%s", [td_rbac_sandbox.marker_key])
    conflict_id = f"{td_rbac_sandbox.menu_id}_conflict"
    pg.execute(
        "INSERT INTO sys_menu "
        "(id,code,title,type,route_path,visible,is_builtin) "
        "VALUES (%s,%s,%s,'leaf',%s,'login',FALSE)",
        [conflict_id, conflict_id, "占用路由", td_rbac_sandbox.menu_id],
    )
    try:
        with pytest.raises(StorageError, match="身份已被占用"):
            _seed_trade_discipline_rbac(pg)
        assert pg.query_df(
            "SELECT 1 FROM sys_resource WHERE id = ANY(%s)",
            [list(td_rbac_sandbox.resource_codes)],
        ).empty
        assert pg.query_df(
            "SELECT 1 FROM app_config WHERE key=%s", [td_rbac_sandbox.marker_key]
        ).empty
    finally:
        pg.execute("DELETE FROM sys_menu WHERE id=%s", [conflict_id])


def test_trade_discipline_rollback_refuses_untracked_custom_role_grant(pg, td_rbac_sandbox):
    role_id = f"{td_rbac_sandbox.menu_id}_role"
    pg.execute(
        "INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
        "VALUES (%s,%s,%s,'custom',FALSE,FALSE)",
        [role_id, role_id, "交易纪律测试角色"],
    )
    try:
        pg.execute(
            "INSERT INTO sys_role_resource (role_id,resource_id) VALUES (%s,%s)",
            [role_id, td_rbac_sandbox.resource_codes[0]],
        )
        with pytest.raises(StorageError, match="账本外授权"):
            _rollback_trade_discipline_rbac(pg)
        state = json.loads(pg.query_df(
            "SELECT value FROM app_config WHERE key=%s", [td_rbac_sandbox.marker_key]
        ).iloc[0]["value"])
        assert state["applied"] is True and state["rolled_back"] is False
    finally:
        pg.execute("DELETE FROM sys_role_resource WHERE role_id=%s", [role_id])
        pg.execute("DELETE FROM sys_role WHERE id=%s", [role_id])


def test_trade_discipline_default_grants_can_be_revoked_without_restart_failure(
    pg, td_rbac_sandbox
):
    pg.execute(
        "DELETE FROM sys_role_resource WHERE role_id=%s AND resource_id=%s",
        [td_rbac_sandbox.normal_role, td_rbac_sandbox.resource_codes[3]],
    )
    pg.execute(
        "DELETE FROM sys_role_menu WHERE role_id=%s AND menu_id=%s",
        [td_rbac_sandbox.tenant_admin_role, td_rbac_sandbox.menu_id],
    )

    assert _seed_trade_discipline_rbac(pg)["state"] == "applied"
    assert pg.query_df(
        "SELECT 1 FROM sys_role_resource WHERE role_id=%s AND resource_id=%s",
        [td_rbac_sandbox.normal_role, td_rbac_sandbox.resource_codes[3]],
    ).empty
    assert pg.query_df(
        "SELECT 1 FROM sys_role_menu WHERE role_id=%s AND menu_id=%s",
        [td_rbac_sandbox.tenant_admin_role, td_rbac_sandbox.menu_id],
    ).empty

    report = _rollback_trade_discipline_rbac(pg)
    assert report["state"] == "rolled_back"


def test_trade_discipline_cli_requires_exact_marker(monkeypatch):
    called = False

    def fake_rollback():
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(
        "backend.storage.pg_ddl._rollback_trade_discipline_rbac", fake_rollback
    )
    result = cmd_trade_discipline_rbac(argparse.Namespace(confirm_marker="wrong"))
    assert result == 2
    assert called is False


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError, StorageError])
def test_trade_discipline_cli_failure_keeps_nonzero_exit_and_reason(monkeypatch, capsys, error_type):
    """CLI 最终边界保持原有失败退出码，不把运行时拒绝遗漏为未处理异常。"""
    def fail_rollback():
        raise error_type("拒绝回滚测试")

    monkeypatch.setattr(pg_ddl, "_rollback_trade_discipline_rbac", fail_rollback)
    result = cmd_trade_discipline_rbac(argparse.Namespace(confirm_marker=TRADE_DISCIPLINE_RBAC_MARKER))
    assert result == 1
    assert "拒绝回滚测试" in capsys.readouterr().err
