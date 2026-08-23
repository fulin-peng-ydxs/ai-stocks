"""T10：交易纪律后端跨阶段验收回归。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from backend.auth.constants import TRADE_DISCIPLINE_RESOURCE_CODES
from backend.common.exceptions import ConflictError
from backend.services.trade_discipline_service import TradeDisciplineService
from backend.storage.pg_ddl import TRADE_DISCIPLINE_RBAC_LOCK, TRADE_DISCIPLINE_RBAC_MARKER
from backend.storage.trade_discipline_repository import TradeDisciplineRepository
from backend.tests.conftest import TEST_OWNER, TEST_TENANT

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _payload() -> dict:
    return {
        "name": "T10 交易纪律",
        "capital": "100000.00",
        "stock_rules": [
            {
                "detail_id": "stock-1",
                "name": "趋势选股",
                "max_capital": "60000.00",
                "content": "只在趋势明确时参与",
                "display_order": 1,
                "enabled": True,
            }
        ],
        "action_rules": [
            {
                "detail_id": "buy-1",
                "name": "确认买入",
                "action_type": "buy",
                "action_subtype": "open_position",
                "content": "突破确认后建仓",
                "display_order": 1,
                "enabled": True,
            },
            {
                "detail_id": "sell-1",
                "name": "纪律卖出",
                "action_type": "sell",
                "action_subtype": "liquidate",
                "content": "跌破纪律线后清仓",
                "display_order": 1,
                "enabled": True,
            },
        ],
    }


def _service(pg, market) -> TradeDisciplineService:
    return TradeDisciplineService(
        TradeDisciplineRepository(pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER),
        market,
    )


def _seed_future_calendar(market) -> None:
    tomorrow = datetime.now(_SHANGHAI).date() + timedelta(days=1)
    frame = pd.DataFrame(
        [
            {"trade_date": tomorrow, "is_open": True},
            {"trade_date": tomorrow + timedelta(days=1), "is_open": True},
        ]
    )
    market.register_df("_td_t10_calendar", frame)
    market.execute(
        "INSERT INTO trade_calendar SELECT * FROM _td_t10_calendar "
        "ON CONFLICT (trade_date) DO UPDATE SET is_open=EXCLUDED.is_open"
    )
    market.unregister("_td_t10_calendar")


def _count(pg, table: str, rule_id: str) -> int:
    return int(
        pg.query_df(
            f"SELECT count(*) AS n FROM {table} "
            "WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s",
            [TEST_TENANT, TEST_OWNER, rule_id],
        ).iloc[0]["n"]
    )


@pytest.mark.parametrize(
    ("occurred_at", "calendar", "expected"),
    [
        (
            datetime(2026, 8, 21, 10, 30, tzinfo=_SHANGHAI),
            [(date(2026, 8, 21), True), (date(2026, 8, 24), True)],
            date(2026, 8, 24),
        ),
        (
            datetime(2026, 8, 21, 18, 30, tzinfo=_SHANGHAI),
            [(date(2026, 8, 21), True), (date(2026, 8, 24), True)],
            date(2026, 8, 24),
        ),
        (
            datetime(2026, 8, 22, 10, 30, tzinfo=_SHANGHAI),
            [(date(2026, 8, 22), False), (date(2026, 8, 24), True)],
            date(2026, 8, 24),
        ),
        (
            datetime(2026, 10, 2, 10, 30, tzinfo=_SHANGHAI),
            [(date(2026, 10, 2), False), (date(2026, 10, 8), False), (date(2026, 10, 9), True)],
            date(2026, 10, 9),
        ),
    ],
    ids=["intraday", "after-close", "weekend", "holiday"],
)
def test_lifecycle_effective_date_is_first_open_day_after_shanghai_action_date(
    market, occurred_at, calendar, expected
):
    frame = pd.DataFrame(
        [{"trade_date": trade_date, "is_open": is_open} for trade_date, is_open in calendar]
    )
    market.register_df("_td_t10_scenario_calendar", frame)
    market.execute("INSERT INTO trade_calendar SELECT * FROM _td_t10_scenario_calendar")
    market.unregister("_td_t10_scenario_calendar")

    # 该用例只验证 DuckDB 日历裁决，不应隐式构造默认 PG 仓库。
    service = TradeDisciplineService(repo=object(), market=market)  # type: ignore[arg-type]
    assert service._next_trade_date(occurred_at) == expected


@pytest.mark.parametrize(
    ("action", "expected_status", "expected_versions", "expected_events", "expected_seq"),
    [
        ("publish", "unpublished", 0, 0, 0),
        ("archive", "active", 1, 1, 1),
        ("restore", "archived", 1, 2, 2),
    ],
)
def test_lifecycle_failure_after_event_allocation_rolls_back_all_state(
    pg,
    market,
    monkeypatch,
    action,
    expected_status,
    expected_versions,
    expected_events,
    expected_seq,
):
    _seed_future_calendar(market)
    service = _service(pg, market)
    rule_id = service.create_rule(_payload())["id"]
    if action in {"archive", "restore"}:
        service.publish_rule(rule_id, expected_revision=1)
    if action == "restore":
        service.archive_rule(rule_id)

    def fail_lifecycle_update(*args, **kwargs):
        raise ConflictError("T10 注入生命周期最终更新失败")

    monkeypatch.setattr(service.repo, "update_lifecycle", fail_lifecycle_update)
    with pytest.raises(ConflictError, match="T10 注入生命周期最终更新失败"):
        if action == "publish":
            service.publish_rule(rule_id, expected_revision=1)
        else:
            getattr(service, f"{action}_rule")(rule_id)

    rule = service.get_rule(rule_id)
    assert rule["status"] == expected_status
    assert int(rule["next_activation_seq"]) == expected_seq
    assert _count(pg, "trade_discipline_rule_version", rule_id) == expected_versions
    assert _count(pg, "trade_discipline_rule_activation", rule_id) == expected_events
    assert (rule["draft"] is not None) is (action == "publish")


def test_lifecycle_event_uses_action_clock_inside_long_transaction(pg, market, monkeypatch):
    _seed_future_calendar(market)
    service = _service(pg, market)
    rule_id = service.create_rule(_payload())["id"]
    transaction_started_at = []
    original_lock_rule = service.repo.lock_rule

    def delayed_lock(conn, target_rule_id):
        row = original_lock_rule(conn, target_rule_id)
        with conn.cursor() as cur:
            cur.execute("SELECT transaction_timestamp()")
            transaction_started_at.append(cur.fetchone()[0])
            cur.execute("SELECT pg_sleep(0.02)")
        return row

    monkeypatch.setattr(service.repo, "lock_rule", delayed_lock)
    service.publish_rule(rule_id, expected_revision=1)
    occurred_at = pg.query_df(
        "SELECT occurred_at FROM trade_discipline_rule_activation "
        "WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s",
        [TEST_TENANT, TEST_OWNER, rule_id],
    ).iloc[0]["occurred_at"]

    assert transaction_started_at
    assert (occurred_at - transaction_started_at[0]).total_seconds() >= 0.015


def test_manual_sql_rbac_rollback_contract_matches_runtime_constants():
    sql = (
        _PROJECT_ROOT
        / "agent-works/trading-discipline-checkin/trading-discipline-schema.sql"
    ).read_text(encoding="utf-8")
    rollback = sql.split("-- ========== 确定性 RBAC 回滚", maxsplit=1)[1]

    assert sql.count(f"pg_advisory_xact_lock({TRADE_DISCIPLINE_RBAC_LOCK})") >= 2
    assert sql.count(TRADE_DISCIPLINE_RBAC_MARKER) >= 4
    assert "marker 不存在，拒绝破坏性回滚" in rollback
    assert "marker 非法，拒绝破坏性回滚" in rollback
    assert "存在迁移账本外授权，拒绝级联回滚" in rollback
    assert "DELETE FROM sys_role_resource" in rollback
    assert "DELETE FROM sys_role_menu" in rollback
    assert "DELETE FROM sys_resource" in rollback
    assert "DELETE FROM sys_menu" in rollback
    assert "SET perm_ver=perm_ver+1" in rollback
    assert "'{\"applied\":false,\"rolled_back\":true}'::jsonb" in rollback
    for resource_code in TRADE_DISCIPLINE_RESOURCE_CODES:
        assert resource_code in rollback
