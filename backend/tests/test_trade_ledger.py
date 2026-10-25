"""真实交易账本：顺序、成本、幂等、归属和最新日修正回归。"""

from datetime import date
from uuid import uuid4

import pytest

from backend.common.exceptions import ConflictError, ValidationError
from backend.services.trade_ledger import assessment, calculate_day, prepare_opening
from backend.services.trade_ledger_service import TradeLedgerService
from backend.storage.trade_ledger_repository import TradeLedgerRepository
from backend.tests.conftest import TEST_OWNER, TEST_TENANT
from backend.tests.test_trade_discipline_t3 import _operation, _published_rule, _seed_market

DAY = date(2026, 10, 23)


@pytest.mark.parametrize("price,quantity,total", [
    ("10.1234", "3", "30.37"), ("0", "100", "0.00"),
    (None, "100", None), ("0.005", "1", "0.01"),
])
def test_opening_cost_is_derived_from_unit_cost(price, quantity, total):
    position = prepare_opening([{"stock_code": "A", "quantity": quantity, "cost_price": price}])[0]
    assert position["cost"] == total


def test_opening_rejects_conflicting_total_precision_and_overflow():
    for extra in ({"cost_price": "10", "cost": "999"}, {"cost_price": "1.00001"},
                  {"cost_price": "9999999999999999", "quantity": "1000"}):
        with pytest.raises(ValidationError):
            prepare_opening([{"stock_code": "A", "quantity": "100", **extra}])


def test_adjustment_unit_cost_and_cash_direction_derive_without_duplicate_inputs():
    result = calculate_day([], [event(kind="position", adjustment_type="transfer",
                                     quantity="3", cost_price="10.1234", note="转入"),
                                event(order=2, kind="cash", adjustment_type="withdrawal",
                                      amount="10", note="出金")], DAY, opening_cash="100")
    assert result["positions"][0]["cost"] == result["events"][0]["amount"] == "30.37"
    assert result["events"][1]["direction"] == "out"
    assert result["cash"] == "90.00"
    assert result["buy_amount"] == "0.00"


@pytest.mark.parametrize("extra", [{"side": "sell"}, {"amount": "1"}, {"cost_price": "1"}])
def test_bonus_rejects_decrease_and_extra_cost(extra):
    with pytest.raises(ValidationError):
        calculate_day([], [event(kind="position", adjustment_type="bonus", note="送股", **extra)], DAY)


def event(code="A", side="buy", order=1, **extra):
    return {"event_id": f"event-{order}", "stock_code": code, "side": side,
            "quantity": "100", "price": "10", "fee": "0", "display_order": order,
            "operated_at": f"{DAY}T10:{order:02d}:00+08:00", **extra}


def test_order_determines_intraday_peak_and_partial_sell_keeps_stock():
    opening = prepare_opening([{"stock_code": "A", "quantity": "100", "cost": "900"},
                               {"stock_code": "B", "quantity": "100", "cost": "1000"}])
    buy_then_sell = calculate_day(opening, [event("C"), event("A", "sell", 2)], DAY)
    sell_then_buy = calculate_day(opening, [event("A", "sell"), event("C", order=2)], DAY)
    assert buy_then_sell["peak_positions"] == 3
    assert sell_then_buy["peak_positions"] == 2
    assert len(buy_then_sell["positions"]) == len(sell_then_buy["positions"]) == 2
    partial = calculate_day(opening, [event("A", "sell", quantity="50")], DAY)
    assert partial["peak_positions"] == len(partial["positions"]) == 2
    assert partial["realized_pnl"] == "50.00"


def test_automatic_amount_rounding_manual_override_and_fee():
    auto = calculate_day([], [event(price="10.1234", quantity="3", fee="5")], DAY, opening_cash="100")
    assert auto["buy_amount"] == "30.37"
    assert auto["cash"] == "64.63"
    assert auto["positions"][0]["cost"] == "35.37"
    manual = calculate_day([], [event(price="10.1234", quantity="3", fee="5",
                                      amount_mode="manual", amount="30.38")], DAY)
    assert manual["events"][0]["computed_amount"] == "30.37"
    assert manual["buy_amount"] == "30.38"


def test_cannot_sell_new_purchase_or_more_than_available():
    with pytest.raises(ValidationError, match="数量不足"):
        calculate_day([], [event(), event(side="sell", order=2)], DAY)
    opening = prepare_opening([{"stock_code": "A", "quantity": "50"}])
    with pytest.raises(ValidationError, match="数量不足"):
        calculate_day(opening, [event(side="sell")], DAY)


def test_unknown_opening_cost_is_not_zero_profit():
    opening = prepare_opening([{"stock_code": "A", "quantity": "100"}])
    result = calculate_day(opening, [event(side="sell")], DAY)
    assert result["realized_pnl"] is None
    assert result["cash"] is None


@pytest.mark.parametrize("positive,negative,complete,expected", [
    (0, 0, True, "complied"), (1, 1, True, "partial"), (0, 1, True, "breached"),
    (1, 0, False, None), (0, 1, False, None),
])
def test_assessment_has_separate_completeness(positive, negative, complete, expected):
    assert assessment(positive, negative, complete=complete) == expected


def test_one_breached_trade_does_not_create_partial_from_other_passing_conditions():
    result = calculate_day([], [event(issues=["选股不符合"])], DAY)
    assert result["assessment"] == "breached"


def test_initial_limit_and_buy_caused_limit_are_explicit():
    rule = {"rule_id": "r", "version_no": 1, "name": "纪律", "max_positions": 1}
    opening = prepare_opening([{"stock_code": "A", "quantity": "100"},
                               {"stock_code": "B", "quantity": "100"}])
    assert calculate_day(opening, [], DAY, rules=[rule])["assessment"] == "breached"
    result = calculate_day(opening[:1], [event("C", rule_id="r")], DAY, rules=[rule])
    assert result["events"][0]["compliance_status"] == "breached"
    assert result["assessment"] == "breached"


def test_adjustments_are_not_trade_amounts_and_need_reason():
    result = calculate_day([], [event(kind="position", adjustment_type="transfer", amount="500", note="转入"),
                                event(order=2, kind="cash", adjustment_type="deposit", direction="in", amount="200", note="入金")],
                           DAY, opening_cash="1000")
    assert result["cash"] == "1200.00"
    assert result["buy_amount"] == result["fee"] == "0.00"
    assert result["positions"][0]["cost"] == "500.00"
    with pytest.raises(ValidationError, match="原因"):
        calculate_day([], [event(kind="position", amount="500")], DAY)


def test_duplicate_ids_order_and_missing_time_are_rejected():
    for events in ([event(), event()], [event(operated_at=None)],
                   [event(), event(order=2, event_id="event-2", display_order=1)]):
        with pytest.raises(ValidationError):
            calculate_day([], events, DAY)


def ledger(pg, market, *, owner=TEST_OWNER):
    return TradeLedgerService(TradeLedgerRepository(pg, tenant_id=TEST_TENANT, owner_user_id=owner), market)


def submit_payload(context, events):
    return {"request_id": uuid4().hex, "expected_account_revision": context["account_revision"],
            "expected_revision": context["current_revision_no"], "events": events, "omissions": []}


def test_real_service_initialization_idempotency_amendment_and_latest_day(pg, market):
    dates = _seed_market(market)
    service = ledger(pg, market)
    rule_id = _published_rule(service.discipline)
    context = service.initialize(dates[0], [], "100000", 0)
    operation = dict(_operation(dates[0]), event_id="actual-fill", rule_id=rule_id)
    payload = submit_payload(context, [operation])
    first = service.submit(dates[0], payload)
    assert first["positions"][0]["quantity"] == "1000"
    assert first["buy_amount"] == "10123.40"
    assert service.submit(dates[0], payload)["idempotent"]
    changed = dict(payload, review_note="不同内容")
    with pytest.raises(ConflictError, match="不同内容"):
        service.submit(dates[0], changed)
    context = service.context(dates[0])
    operation["quantity"] = "2000"
    amended = service.submit(dates[0], submit_payload(context, [operation]))
    assert amended["positions"][0]["quantity"] == "2000"
    assert service.revisions(dates[0], 1)["snapshot"]["positions"][0]["quantity"] == "1000"
    next_day = service.context(dates[1])
    service.submit(dates[1], submit_payload(next_day, []))
    assert not service.context(dates[0])["can_edit"]
    with pytest.raises(ConflictError, match="最新交易日"):
        service.submit(dates[0], submit_payload(service.context(dates[0]), []))
    context = service.context(dates[1])
    service.withdraw(dates[1], context["account_revision"])
    assert service.context(dates[0])["can_edit"]


def test_cross_owner_and_uninitialized_are_closed(pg, market):
    dates = _seed_market(market)
    service = ledger(pg, market)
    service.initialize(dates[0], [], None, 0)
    foreign = ledger(pg, market, owner=f"foreign_{uuid4().hex}")
    assert foreign.context(dates[0])["initialized_on"] is None
    with pytest.raises(ValidationError, match="初始化"):
        foreign.submit(dates[0], submit_payload(foreign.context(dates[0]), []))
    # 失败写入只创建本例临时账户身份，按精确归属清除。
    pg.execute("DELETE FROM trade_discipline_account WHERE tenant_id=%s AND owner_user_id=%s",
               list(foreign.repo.owner))


def test_rebuild_all_owners_in_isolated_schema_preserves_latest_and_drafts(pg):
    """全用户重置仅在本例独立模式演练，绝不清理共享开发库真实用户。"""
    from psycopg import sql

    from backend.devtools.trade_discipline_reset import _rebuild
    from backend.storage.pg_ddl import _ASSET_TABLES
    from backend.tests.test_trade_discipline_t3 import _rule_payload

    schema = f"pytest_ledger_reset_{uuid4().hex}"
    with pg.transaction() as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conn.execute(sql.SQL("SET LOCAL search_path TO {},public").format(sql.Identifier(schema)))
        for name, ddl in _ASSET_TABLES.items():
            if name.startswith("trade_discipline_"):
                conn.execute(ddl)
        for owner, status in (("one", "active"), ("two", "archived")):
            repo = TradeLedgerRepository(pg, tenant_id="isolated", owner_user_id=owner)
            conn.execute("INSERT INTO trade_discipline_rule(id,tenant_id,owner_user_id,status) "
                         "VALUES ('same-id','isolated',%s,'unpublished')", [owner])
            version = _rule_payload()
            version["normalized_name"] = "first"
            repo.insert_version(conn, "same-id", 1, version)
            version.update(name=f"{owner}-latest", normalized_name=f"{owner}-latest")
            repo.insert_version(conn, "same-id", 2, version)
            repo.update_lifecycle(conn, "same-id", status=status, name=version["name"],
                                  normalized_name=version["normalized_name"], latest_version_no=2)
            conn.execute("INSERT INTO trade_discipline_rule_draft "
                         "(tenant_id,owner_user_id,rule_id,draft_revision,source_version_no) "
                         "VALUES ('isolated',%s,'same-id',1,2)", [owner])
        conn.execute("CREATE TABLE unrelated_business(value TEXT)")
        conn.execute("INSERT INTO unrelated_business VALUES ('keep')")
        result = _rebuild(conn, pg, DAY)
        assert result["owners"] == result["retained_rules"] == 2
        rows = conn.execute("SELECT owner_user_id,name,version_no FROM trade_discipline_rule_version "
                            "ORDER BY owner_user_id").fetchall()
        assert rows == [("one", "one-latest", 1), ("two", "two-latest", 1)]
        assert conn.execute("SELECT status FROM trade_discipline_rule ORDER BY owner_user_id").fetchall() == [
            ("active",), ("archived",),
        ]
        assert conn.execute("SELECT source_version_no,draft_revision FROM trade_discipline_rule_draft").fetchall() == [(1, 2), (1, 2)]
        assert conn.execute("SELECT value FROM unrelated_business").fetchone()[0] == "keep"
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_one_trade_can_be_checked_by_two_rules_without_double_posting(pg, market):
    from backend.tests.test_trade_discipline_t3 import _rule_payload

    dates = _seed_market(market)
    service = ledger(pg, market)
    first_rule = _published_rule(service.discipline)
    second_rule = service.discipline.create_rule(_rule_payload("第二套纪律"))["id"]
    service.discipline.publish_rule(second_rule, expected_revision=1)
    context = service.initialize(dates[0], [], "100000", 0)
    operation = dict(_operation(dates[0]), event_id="one-real-trade", rule_id=first_rule,
                     rule_checks=[{"rule_id": second_rule, "stock_rule_id": "stock-1",
                                   "action_rule_id": "buy-1", "action_matches": False}])
    payload = submit_payload(context, [operation])
    result = service.submit(dates[0], payload)
    assert len(result["events"]) == 1
    assert result["positions"][0]["quantity"] == "1000"
    assert {row["rule_id"]: row["assessment"] for row in result["evaluations"]} == {
        first_rule: "complied", second_rule: "breached",
    }
    assert result["assessment"] == "breached"
    assert service.submit(dates[0], payload)["idempotent"]


def test_representative_day_load_calculate_and_persist_thousand_fills(pg, market):
    dates = _seed_market(market)
    service = ledger(pg, market)
    rule_id = _published_rule(service.discipline)
    context = service.initialize(dates[0], [{"stock_code": "600000.SH", "quantity": "5000",
                                           "cost": "40000", "rule_id": rule_id,
                                           "stock_rule_id": "stock-1"}], "100000", 0)
    events = [dict(_operation(dates[0], side="buy" if i % 2 == 0 else "sell"),
                   event_id=f"fill-{i}", rule_id=rule_id, price="10", quantity="1", fee="0",
                   display_order=i + 1) for i in range(1000)]
    result = service.submit(dates[0], submit_payload(context, events))
    assert len(result["events"]) == 1000
    assert result["positions"][0]["quantity"] == "5000"
    assert result["cash"] == "100000.00"
    assert result["buy_amount"] == result["sell_amount"] == "5000.00"
    saved = service.revisions(dates[0], 1)["snapshot"]
    assert len(saved["events"]) == 1000
    assert saved["assessment"] == "complied"
    history = service.repo.history()
    assert history["list"][0]["snapshot"]["operation_count"] == 1000
    assert history["list"][0]["snapshot"]["events"] == []


def test_computed_amount_overflow_is_input_error():
    with pytest.raises(ValidationError, match="成交金额"):
        calculate_day([], [event(price="9999999999999999", quantity="9999999999999999")], DAY)


def test_dividend_is_separate_from_capital_and_needs_stock(pg, market):
    dates = _seed_market(market)
    service = ledger(pg, market)
    context = service.initialize(dates[0], [], "1000", 0)
    operation = dict(event(kind="cash", adjustment_type="dividend", direction="in",
                           amount="25", note="现金分红"), operated_at=f"{dates[0]}T10:00:00+08:00")
    operation.pop("stock_code")
    with pytest.raises(ValidationError, match="股票"):
        service.submit(dates[0], submit_payload(context, [operation]))
    operation["stock_code"] = "600000.SH"
    result = service.submit(dates[0], submit_payload(context, [operation]))
    assert result["cash"] == "1025.00"
    assert result["dividend"] == "25.00"
    assert result["capital_flow"] == result["buy_amount"] == "0.00"


def test_supplemental_stock_condition_false_is_breach(pg, market):
    dates = _seed_market(market)
    service = ledger(pg, market)
    rule_id = _published_rule(service.discipline)
    context = service.initialize(dates[0], [], None, 0)
    operation = dict(_operation(dates[0]), event_id="stock-extra-check", rule_id=rule_id,
                     stock_matches=False)
    result = service.submit(dates[0], submit_payload(context, [operation]))
    assert result["assessment"] == "breached"
    assert "不符合补充选股条件" in result["events"][0]["issues"]


def test_context_before_opening_date_does_not_expose_future_positions(pg, market):
    dates = _seed_market(market)
    service = ledger(pg, market)
    service.initialize(dates[1], [{"stock_code": "600000.SH", "quantity": "100", "cost": "1000"}], "500", 0)
    earlier = service.context(dates[0])
    assert earlier["positions"] == earlier["opening_positions"] == []
    assert earlier["cash"] is earlier["opening_cash"] is None
    assert not earlier["can_edit"]


def test_opening_same_stock_can_split_by_rule_but_count_only_once():
    opening = prepare_opening([{"stock_code": "A", "quantity": "100", "cost": "900", "rule_id": "one", "stock_rule_id": "s"},
                               {"stock_code": "A", "quantity": "200", "cost": "2000", "rule_id": "two", "stock_rule_id": "s"}])
    result = calculate_day(opening, [event(side="sell", quantity="150", rule_id="two", stock_rule_id="s")], DAY)
    assert result["peak_positions"] == 1
    assert [(p["rule_id"], p["quantity"]) for p in result["positions"]] == [("one", "100"), ("two", "50")]
    assert result["realized_pnl"] == "0.00"
    with pytest.raises(ValidationError, match="不能重复"):
        prepare_opening([opening[0], opening[0]])


@pytest.mark.parametrize("side,delta,expected", [("sell", "150", ["50.0000", "100.0000"]),
                                                 ("buy", "300", ["200.0000", "400.0000"])])
def test_split_preserves_cost_and_allocates_quantity_across_groups(side, delta, expected):
    opening = prepare_opening([
        {"stock_code": "A", "quantity": "100", "cost": "1000", "rule_id": "one"},
        {"stock_code": "A", "quantity": "200", "cost": None, "rule_id": "two"},
    ])
    result = calculate_day(opening, [event(kind="position", adjustment_type="split", side=side,
                                           quantity=delta, amount=None, note="拆并股")], DAY, opening_cash="500")
    assert [p["quantity"] for p in result["positions"]] == expected
    assert [p["available_quantity"] for p in result["positions"]] == expected
    assert [p["cost"] for p in result["positions"]] == ["1000.00", None]
    assert result["cash"] == "500.00"
    assert result["buy_amount"] == result["sell_amount"] == "0.00"
    assert result["calculation_version"] == "ledger-v2"


def test_split_keeps_new_bought_shares_unavailable_and_rejects_zero_position():
    opening = prepare_opening([{"stock_code": "A", "quantity": "100", "cost": "1000"}])
    result = calculate_day(opening, [event(), event(kind="position", adjustment_type="split", side="sell",
                          order=2, quantity="100", amount=None, note="合股")], DAY)
    assert result["positions"][0]["quantity"] == "100"
    assert result["positions"][0]["available_quantity"] == "50.0000"
    assert result["positions"][0]["cost"] == "2000.00"
    for quantity, amount in (("100", None), ("50", "100")):
        with pytest.raises(ValidationError, match="拆并股"):
            calculate_day(opening, [event(kind="position", adjustment_type="split", side="sell",
                                         quantity=quantity, amount=amount, note="合股")], DAY)


def test_partial_sell_does_not_count_existing_buy_limit_breach_again():
    rule = {"rule_id": "r", "version_no": 1, "name": "纪律", "max_positions": 1}
    opening = prepare_opening([{"stock_code": "A", "quantity": "100", "cost": "1000", "rule_id": "r"}])
    result = calculate_day(opening, [event("B", rule_id="r"),
                                    event("A", side="sell", order=2, rule_id="r", quantity="50")], DAY, rules=[rule])
    evaluation = result["evaluations"][0]
    assert evaluation["assessment"] == "partial"
    assert evaluation["breached_count"] == evaluation["compliant_count"] == 1
    assert evaluation["issues"] == []


def test_non_trade_adjustments_reject_trade_checks_and_incomplete_group(pg, market):
    dates = _seed_market(market)
    service = ledger(pg, market)
    rule_id = _published_rule(service.discipline)
    context = service.initialize(dates[0], [], None, 0)
    adjustment = dict(event(kind="cash", adjustment_type="deposit", direction="in", amount="50", note="入金"),
                      operated_at=f"{dates[0]}T10:00:00+08:00")
    adjustment["rule_checks"] = [{"rule_id": rule_id, "stock_rule_id": "stock-1", "action_rule_id": "buy-1"}]
    with pytest.raises(ValidationError, match="非交易调整"):
        service.submit(dates[0], submit_payload(context, [adjustment]))
    adjustment.update(kind="position", adjustment_type="transfer", rule_id=rule_id, rule_checks=[])
    with pytest.raises(ValidationError, match="分组"):
        service.submit(dates[0], submit_payload(context, [adjustment]))
    assert service.context(dates[0])["current_revision_no"] == 0


def test_opening_rejects_disabled_stock_group(pg, market):
    from backend.tests.test_trade_discipline_t3 import _rule_payload

    dates = _seed_market(market)
    service = ledger(pg, market)
    payload = _rule_payload()
    payload["stock_rules"].append({**payload["stock_rules"][0], "detail_id": "disabled",
                                  "name": "已停用分组", "display_order": 2, "enabled": False})
    rule_id = service.discipline.create_rule(payload)["id"]
    service.discipline.publish_rule(rule_id, expected_revision=1)
    with pytest.raises(ValidationError, match="启用"):
        service.initialize(dates[0], [{"stock_code": "600000.SH", "quantity": "100",
                           "rule_id": rule_id, "stock_rule_id": "disabled"}], None, 0)
    assert service.context(dates[0])["initialized_on"] is None


def test_withdrawn_day_is_auditable_but_excluded_by_default(pg, market):
    dates = _seed_market(market)
    service = ledger(pg, market)
    context = service.initialize(dates[0], [], None, 0)
    service.submit(dates[0], submit_payload(context, []))
    service.withdraw(dates[0], service.context(dates[0])["account_revision"])
    assert service.repo.history()["total"] == 0
    history = service.repo.history(include_withdrawn=True)
    assert history["total"] == 1
    assert history["list"][0]["withdrawn"] is True
    assert service.revisions(dates[0], 1)["snapshot"]["events"] == []
    assert service.context(dates[0])["latest_trade_date"] is None


def test_rule_resolution_uses_same_database_snapshot_as_account(pg, market):
    dates = _seed_market(market)
    service = ledger(pg, market)
    with service.repo.transaction() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        service.repo.account(conn)  # 固定读快照，随后在另一连接发布不能穿透当前快照。
        rule_id = _published_rule(service.discipline)
        assert service._rules(dates[0], conn) == []
    assert service.context(dates[0])["rules"][0]["rule_id"] == rule_id
