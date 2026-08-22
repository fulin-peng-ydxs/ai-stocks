"""交易纪律 T1：PG 模型、索引与可回滚 RBAC 状态机。"""

from __future__ import annotations

import argparse
import json

import pytest

from backend.auth.constants import TRADE_DISCIPLINE_RESOURCE_CODES
from backend.cli import cmd_trade_discipline_rbac
from backend.common.exceptions import StorageError
from backend.storage.pg_ddl import (
    ASSET_PK,
    TRADE_DISCIPLINE_RBAC_MARKER,
    _rollback_trade_discipline_rbac,
    _seed_trade_discipline_rbac,
    _trade_discipline_marker_state,
    seed_rbac,
)

TD_TABLES = {
    "trade_discipline_rule",
    "trade_discipline_rule_name_claim",
    "trade_discipline_rule_draft",
    "trade_discipline_draft_stock_rule",
    "trade_discipline_draft_action_rule",
    "trade_discipline_rule_version",
    "trade_discipline_stock_rule",
    "trade_discipline_action_rule",
    "trade_discipline_rule_activation",
    "trade_discipline_checkin",
    "trade_discipline_checkin_revision",
    "trade_discipline_reason",
    "trade_discipline_violation",
    "trade_discipline_operation",
}


def _delete_td_rbac(pg) -> None:
    resource_ids = list(TRADE_DISCIPLINE_RESOURCE_CODES)
    with pg.transaction() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM sys_role_resource WHERE resource_id = ANY(%s)", [resource_ids])
        cur.execute("DELETE FROM sys_role_menu WHERE menu_id=%s", ["/trade-discipline"])
        cur.execute("DELETE FROM sys_resource WHERE id = ANY(%s)", [resource_ids])
        cur.execute("DELETE FROM sys_menu WHERE id=%s", ["/trade-discipline"])
        cur.execute("DELETE FROM app_config WHERE key=%s", [TRADE_DISCIPLINE_RBAC_MARKER])


@pytest.fixture
def td_rbac_sandbox(pg):
    perm_versions = pg.query_df("SELECT id, perm_ver FROM sys_user").to_dict("records")
    _delete_td_rbac(pg)
    _seed_trade_discipline_rbac(pg)
    try:
        yield
    finally:
        _delete_td_rbac(pg)
        _seed_trade_discipline_rbac(pg)
        for row in perm_versions:
            pg.execute(
                "UPDATE sys_user SET perm_ver=%s WHERE id=%s",
                [int(row["perm_ver"]), row["id"]],
            )


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
            "td_rule_name_claim_rule_unique",
            "td_rule_latest_version_fk",
            "td_checkin_current_revision_fk",
        ]],
    )["conname"])
    assert len(checks) == 6

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
        "SELECT 1 FROM sys_menu WHERE id=%s", ["/trade-discipline"]
    ).empty
    assert pg.query_df(
        "SELECT 1 FROM sys_resource WHERE id = ANY(%s)",
        [list(TRADE_DISCIPLINE_RESOURCE_CODES)],
    ).empty

    seed_rbac(pg)
    assert pg.query_df(
        "SELECT 1 FROM sys_menu WHERE id=%s", ["/trade-discipline"]
    ).empty
    marker = json.loads(pg.query_df(
        "SELECT value FROM app_config WHERE key=%s", [TRADE_DISCIPLINE_RBAC_MARKER]
    ).iloc[0]["value"])
    assert marker["applied"] is False and marker["rolled_back"] is True


def test_trade_discipline_seed_conflict_rolls_back_atomically(pg, td_rbac_sandbox):
    _rollback_trade_discipline_rbac(pg)
    pg.execute("DELETE FROM app_config WHERE key=%s", [TRADE_DISCIPLINE_RBAC_MARKER])
    pg.execute(
        "INSERT INTO sys_menu "
        "(id,code,title,type,route_path,visible,is_builtin) "
        "VALUES (%s,%s,%s,'leaf',%s,'login',FALSE)",
        ["pytest-td-conflict", "pytest-td-conflict", "占用路由", "/trade-discipline"],
    )
    try:
        with pytest.raises(StorageError, match="身份已被占用"):
            _seed_trade_discipline_rbac(pg)
        assert pg.query_df(
            "SELECT 1 FROM sys_resource WHERE id = ANY(%s)",
            [list(TRADE_DISCIPLINE_RESOURCE_CODES)],
        ).empty
        assert pg.query_df(
            "SELECT 1 FROM app_config WHERE key=%s", [TRADE_DISCIPLINE_RBAC_MARKER]
        ).empty
    finally:
        pg.execute("DELETE FROM sys_menu WHERE id=%s", ["pytest-td-conflict"])


def test_trade_discipline_rollback_refuses_untracked_custom_role_grant(pg, td_rbac_sandbox):
    role_id = "pytest-td-custom-role"
    pg.execute(
        "INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
        "VALUES (%s,%s,%s,'custom',FALSE,FALSE)",
        [role_id, role_id, "交易纪律测试角色"],
    )
    try:
        pg.execute(
            "INSERT INTO sys_role_resource (role_id,resource_id) VALUES (%s,%s)",
            [role_id, "trade-discipline:view"],
        )
        with pytest.raises(StorageError, match="账本外授权"):
            _rollback_trade_discipline_rbac(pg)
        state = json.loads(pg.query_df(
            "SELECT value FROM app_config WHERE key=%s", [TRADE_DISCIPLINE_RBAC_MARKER]
        ).iloc[0]["value"])
        assert state["applied"] is True and state["rolled_back"] is False
    finally:
        pg.execute("DELETE FROM sys_role_resource WHERE role_id=%s", [role_id])
        pg.execute("DELETE FROM sys_role WHERE id=%s", [role_id])


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
