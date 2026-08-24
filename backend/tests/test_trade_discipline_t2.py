"""交易纪律 T2：规则仓库与生命周期服务。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from backend.common.exceptions import ConflictError, NotFoundError, ValidationError
from backend.services.trade_discipline_service import TradeDisciplineService
from backend.storage.trade_discipline_repository import TradeDisciplineRepository
from backend.tests.conftest import TEST_OWNER, TEST_TENANT, clean_owner


def _payload(name: str = "趋势纪律") -> dict:
    return {
        "name": name,
        "capital": "100000.00",
        "stock_rules": [
            {
                "detail_id": "stock-1",
                "name": "只做趋势龙头",
                "max_capital": "60000.00",
                "content": "站上 20 日线\n且放量",
                "display_order": 1,
                "enabled": True,
            }
        ],
        "action_rules": [
            {
                "detail_id": "buy-1",
                "name": "确认后开仓",
                "action_type": "buy",
                "action_subtype": "open_position",
                "content": "突破后回踩不破",
                "display_order": 1,
                "enabled": True,
            },
            {
                "detail_id": "sell-1",
                "name": "跌破离场",
                "action_type": "sell",
                "action_subtype": "liquidate",
                "content": "收盘跌破 20 日线",
                "display_order": 1,
                "enabled": True,
            },
        ],
    }


def _service(pg, market, *, owner: str = TEST_OWNER) -> TradeDisciplineService:
    repo = TradeDisciplineRepository(pg, tenant_id=TEST_TENANT, owner_user_id=owner)
    return TradeDisciplineService(repo, market)


def _seed_next_days(market) -> tuple[date, date]:
    first = datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=1)
    second = first + timedelta(days=1)
    frame = pd.DataFrame(
        [{"trade_date": first, "is_open": True}, {"trade_date": second, "is_open": True}]
    )
    market.register_df("_td_calendar", frame)
    market.execute(
        "INSERT INTO trade_calendar SELECT * FROM _td_calendar "
        "ON CONFLICT (trade_date) DO UPDATE SET is_open=EXCLUDED.is_open"
    )
    market.unregister("_td_calendar")
    return first, second


def _count(pg, table: str, rule_id: str, *, owner: str = TEST_OWNER) -> int:
    return int(
        pg.query_df(
            f"SELECT count(*) AS n FROM {table} "
            "WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s",
            [TEST_TENANT, owner, rule_id],
        ).iloc[0]["n"]
    )


def test_draft_rename_reserves_formal_and_proposed_names(pg, market):
    _seed_next_days(market)
    service = _service(pg, market)
    created = service.create_rule(_payload("Ａ规则 "))
    rule_id = created["id"]
    published = service.publish_rule(rule_id, expected_revision=1)
    assert published["version_no"] == 1

    draft = service.open_draft(rule_id)
    renamed = _payload("B规则")
    service.save_draft(rule_id, renamed, expected_revision=int(draft["draft_revision"]))

    claims = pg.query_df(
        "SELECT normalized_name FROM trade_discipline_rule_name_claim "
        "WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s ORDER BY normalized_name",
        [TEST_TENANT, TEST_OWNER, rule_id],
    )["normalized_name"].tolist()
    assert claims == ["a规则", "b规则"]
    with pytest.raises(ConflictError):
        service.create_rule(_payload("Ａ规则"))
    with pytest.raises(ConflictError):
        service.create_rule(_payload("ｂ规则"))


def test_draft_optimistic_lock_and_archived_edit_rejected(pg, market):
    _seed_next_days(market)
    service = _service(pg, market)
    rule_id = service.create_rule(_payload())["id"]
    saved = service.save_draft(rule_id, _payload("更新名"), expected_revision=1)
    assert int(saved["draft_revision"]) == 2
    with pytest.raises(ConflictError):
        service.save_draft(rule_id, _payload("过期写"), expected_revision=1)

    service.publish_rule(rule_id, expected_revision=2)
    service.archive_rule(rule_id)
    with pytest.raises(ConflictError):
        service.open_draft(rule_id)


def test_custom_action_subtype_is_reusable_and_unique_across_sides(pg, market):
    service = _service(pg, market)
    payload = _payload()
    payload["action_rules"][0]["action_subtype"] = " 趋势回踩 "
    rule_id = service.create_rule(payload)["id"]

    options = service.list_action_subtypes()
    assert any(
        item["name"] == "趋势回踩"
        and item["action_type"] == "buy"
        and item["builtin"] is False
        for item in options
    )
    assert any(item.get("label") == "建仓" and item["builtin"] is True for item in options)

    draft = service.get_rule(rule_id)["draft"]
    conflicting = _payload()
    conflicting["action_rules"][1]["action_subtype"] = "ＴＲＥＮＤ"
    saved = service.save_draft(
        rule_id,
        conflicting,
        expected_revision=int(draft["draft_revision"]),
    )
    other = _payload("另一套纪律")
    other["action_rules"][0]["action_subtype"] = "trend"
    with pytest.raises(ConflictError, match="另一方向"):
        service.create_rule(other)

    assert int(saved["draft_revision"]) == 2


def test_publish_effective_version_and_no_material_change(pg, market):
    first, _ = _seed_next_days(market)
    service = _service(pg, market)
    rule_id = service.create_rule(_payload())["id"]
    result = service.publish_rule(rule_id, expected_revision=1)
    assert result["effective_from_trade_date"] == first
    assert service.effective_version(rule_id, first - timedelta(days=1)) is None
    effective = service.effective_version(rule_id, first)
    assert effective is not None
    assert effective["version_no"] == 1
    assert effective["stock_rules"][0]["content"] == "站上 20 日线\n且放量"

    draft = service.open_draft(rule_id)
    draft["action_rules"].reverse()
    saved = service.save_draft(rule_id, draft, expected_revision=int(draft["draft_revision"]))
    unchanged = service.publish_rule(rule_id, expected_revision=int(saved["draft_revision"]))
    assert unchanged == {"changed": False, "rule_id": rule_id, "version_no": 1}
    assert _count(pg, "trade_discipline_rule_version", rule_id) == 1
    assert _count(pg, "trade_discipline_rule_activation", rule_id) == 1
    assert service.get_rule(rule_id)["draft"] is None


def test_same_day_archive_restore_uses_event_sequence_even_if_timestamps_equal(pg, market):
    first, _ = _seed_next_days(market)
    service = _service(pg, market)
    rule_id = service.create_rule(_payload())["id"]
    service.publish_rule(rule_id, expected_revision=1)
    archived = service.archive_rule(rule_id)
    restored = service.restore_rule(rule_id)
    assert archived["effective_from_trade_date"] == restored["effective_from_trade_date"] == first
    assert restored["event_seq"] > archived["event_seq"]

    pg.execute(
        "UPDATE trade_discipline_rule_activation SET occurred_at=TIMESTAMPTZ '2026-08-22 00:00:00+00', "
        "activated_at=TIMESTAMPTZ '2026-08-22 00:00:00+00' "
        "WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s",
        [TEST_TENANT, TEST_OWNER, rule_id],
    )
    assert service.effective_version(rule_id, first) is not None


def test_rule_state_dto_survives_refresh_and_list_is_single_pg_query(pg, market, monkeypatch):
    first, _ = _seed_next_days(market)
    service = _service(pg, market)
    rule_id = service.create_rule(_payload())["id"]
    published = service.publish_rule(rule_id, expected_revision=1)

    calls = 0
    original = service.repo.pg.query_df

    def counted(sql, params=None):
        nonlocal calls
        calls += 1
        return original(sql, params)

    monkeypatch.setattr(service.repo.pg, "query_df", counted)
    before = service.list_rules_with_state(first - timedelta(days=1))
    assert calls == 1
    assert before[0]["id"] == rule_id
    assert before[0]["management_status"] == "active"
    assert before[0]["effective_status"] == "unpublished"
    assert before[0]["has_pending_management_action"] is True
    management = before[0]["latest_management_event"]
    assert management["event_type"] == "publish"
    assert management["event_seq"] == published["event_seq"]
    assert management["version_no"] == 1
    assert management["occurred_at"] is not None
    assert management["activated_at"] is not None
    assert management["effective_from_trade_date"] == first

    calls = 0
    effective = service.list_rules_with_state(first)
    assert calls == 1
    assert effective[0]["effective_status"] == "active"
    assert effective[0]["effective_version"]["version_no"] == 1
    assert effective[0]["has_pending_management_action"] is False


def test_calendar_failure_rolls_back_version_event_counter_and_keeps_draft(pg, market):
    service = _service(pg, market)
    rule_id = service.create_rule(_payload())["id"]
    with pytest.raises(ValidationError, match="交易日历"):
        service.publish_rule(rule_id, expected_revision=1)

    rule = service.get_rule(rule_id)
    assert rule["status"] == "unpublished"
    assert int(rule["next_activation_seq"]) == 0
    assert rule["draft"] is not None
    assert _count(pg, "trade_discipline_rule_version", rule_id) == 0
    assert _count(pg, "trade_discipline_rule_activation", rule_id) == 0


def test_copy_is_new_unpublished_draft_without_history(pg, market):
    _seed_next_days(market)
    service = _service(pg, market)
    original_id = service.create_rule(_payload())["id"]
    service.publish_rule(original_id, expected_revision=1)

    copied = service.copy_rule(original_id)
    copied_id = copied["id"]
    assert copied["status"] == "unpublished"
    assert copied["latest_version_no"] is None
    assert copied["draft"]["proposed_name"] == "趋势纪律-副本"
    assert _count(pg, "trade_discipline_rule_version", copied_id) == 0
    assert _count(pg, "trade_discipline_rule_activation", copied_id) == 0


def test_owner_isolation_and_unpublished_delete(pg, market):
    service = _service(pg, market)
    other_owner = f"{TEST_OWNER}_other"
    clean_owner(pg, TEST_TENANT, other_owner)
    try:
        rule_id = service.create_rule(_payload())["id"]
        other = _service(pg, market, owner=other_owner)
        with pytest.raises(NotFoundError):
            other.get_rule(rule_id)
        other_rule = other.create_rule(_payload())["id"]
        assert other_rule != rule_id
        service.delete_rule(rule_id)
        with pytest.raises(NotFoundError):
            service.get_rule(rule_id)
    finally:
        clean_owner(pg, TEST_TENANT, other_owner)


def test_concurrent_publish_creates_single_version_and_event(pg, market):
    _seed_next_days(market)
    service = _service(pg, market)
    rule_id = service.create_rule(_payload())["id"]

    def publish_once():
        worker = _service(pg, market)
        try:
            return worker.publish_rule(rule_id, expected_revision=1)
        except (ConflictError, NotFoundError) as exc:
            return type(exc).__name__

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: publish_once(), range(2)))

    assert sum(isinstance(result, dict) for result in results) == 1
    assert _count(pg, "trade_discipline_rule_version", rule_id) == 1
    assert _count(pg, "trade_discipline_rule_activation", rule_id) == 1
    assert int(service.get_rule(rule_id)["next_activation_seq"]) == 1


def test_concurrent_archive_and_restore_each_create_one_event(pg, market):
    _seed_next_days(market)
    service = _service(pg, market)
    rule_id = service.create_rule(_payload())["id"]
    service.publish_rule(rule_id, expected_revision=1)

    def run(action: str):
        worker = _service(pg, market)
        try:
            return getattr(worker, f"{action}_rule")(rule_id)
        except ConflictError as exc:
            return type(exc).__name__

    with ThreadPoolExecutor(max_workers=2) as executor:
        archived = list(executor.map(lambda _: run("archive"), range(2)))
    assert sum(isinstance(result, dict) for result in archived) == 1

    with ThreadPoolExecutor(max_workers=2) as executor:
        restored = list(executor.map(lambda _: run("restore"), range(2)))
    assert sum(isinstance(result, dict) for result in restored) == 1
    assert _count(pg, "trade_discipline_rule_activation", rule_id) == 3
    assert int(service.get_rule(rule_id)["next_activation_seq"]) == 3


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p.update(capital="0"), "总资金必须大于 0"),
        (
            lambda p: p["stock_rules"][0].update(enabled=False),
            "至少启用一条选股规则",
        ),
        (
            lambda p: p["action_rules"][0].update(enabled=False),
            "至少启用一条买入规则",
        ),
        (
            lambda p: p["stock_rules"][0].update(max_capital="100001"),
            "趋势龙头.*超出总资金 1.00 元",
        ),
        (
            lambda p: p["stock_rules"].append(
                {
                    "detail_id": "stock-2",
                    "name": "只做确定性机会",
                    "max_capital": "60000",
                    "content": "盈亏比足够",
                    "display_order": 2,
                    "enabled": True,
                }
            ),
            "合计超出总资金 20000.00 元",
        ),
    ],
)
def test_publish_validation_keeps_draft(pg, market, mutate, message):
    _seed_next_days(market)
    service = _service(pg, market)
    payload = _payload()
    mutate(payload)
    rule_id = service.create_rule(payload)["id"]
    with pytest.raises(ValidationError, match=message):
        service.publish_rule(rule_id, expected_revision=1)
    assert service.get_rule(rule_id)["draft"] is not None
    assert _count(pg, "trade_discipline_rule_version", rule_id) == 0


def test_draft_rejects_fractional_cent_and_non_boolean_enabled(pg, market):
    service = _service(pg, market)
    fractional = _payload()
    fractional["capital"] = "1.001"
    with pytest.raises(ValidationError, match="两位小数"):
        service.create_rule(fractional)

    wrong_boolean = _payload()
    wrong_boolean["stock_rules"][0]["enabled"] = "false"
    with pytest.raises(ValidationError, match="布尔值"):
        service.create_rule(wrong_boolean)


def test_money_enforces_postgres_numeric_20_2_range():
    assert TradeDisciplineService._money("999999999999999999.99") == Decimal(
        "999999999999999999.99"
    )
    for invalid in (
        "1000000000000000000.00",
        "1000000000000000000",
        "1.001",
    ):
        with pytest.raises(ValidationError):
            TradeDisciplineService._money(invalid)
