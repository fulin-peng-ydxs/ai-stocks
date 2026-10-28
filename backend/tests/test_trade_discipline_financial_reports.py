"""财报月份限制：预算、真实交易日清仓期限及版本化日结闭环。"""

from copy import deepcopy
from datetime import date, timedelta

import pytest
from pydantic import ValidationError as ModelValidationError

from backend.api.trade_discipline import RuleDraftBody
from backend.common.exceptions import ConflictError, ValidationError
from backend.services.trade_discipline_service import TradeDisciplineService
from backend.services.trade_ledger import calculate_day, prepare_opening
from backend.storage.pg_ddl import _TRADE_DISCIPLINE_FINANCIAL_REPORT_UPGRADES
from backend.tests.test_trade_discipline_t3 import _rule_payload
from backend.tests.test_trade_ledger import event, ledger, submit_payload

HALF_DAY = date(2027, 7, 15)
LAST_DAY = date(2027, 7, 30)  # 周五；下一开市日8月2日，不能用自然月末判断。
REPORT_DAY = date(2027, 8, 2)


def rule(rid="r", *, restricted=True):
    return {"rule_id": rid, "name": rid, "version_no": 1,
            "restrict_financial_report_months": restricted,
            "stock_rules": [{"detail_id": "a", "name": "分组A", "max_capital": "60000", "enabled": True},
                            {"detail_id": "b", "name": "分组B", "max_capital": "40000", "enabled": True}]}


def holding(cost="30000", *, rid="r", sid="a", code="A"):
    return {"stock_code": code, "quantity": "100", "cost": cost,
            "rule_id": rid, "stock_rule_id": sid}


def recorded(day=HALF_DAY, **patch):
    return event(rule_id="r", stock_rule_id="a", operated_at=f"{day}T10:00:00+08:00", **patch)


def calculate(opening=(), events=(), *, day=HALF_DAY, rules=None, next_day=None):
    return calculate_day(prepare_opening(list(opening)), list(events), day,
                         rules=[rule()] if rules is None else rules,
                         next_trade_date=next_day or day + timedelta(days=1))


@pytest.mark.parametrize("month", [3, 7, 9])
@pytest.mark.parametrize("cost,expected", [("30000", "complied"), ("30000.01", "breached")])
def test_half_capital_in_each_preceding_month(month, cost, expected):
    result = calculate([holding(cost)], day=date(2027, month, 15))
    assert result["assessment"] == expected
    if expected == "breached":
        assert "50%" in result["evaluations"][0]["issues"][0]


@pytest.mark.parametrize("month", [1, 2, 5, 6, 11, 12])
def test_other_months_keep_original_capital_limit(month):
    assert calculate([holding("50000")], day=date(2027, month, 15))["assessment"] == "complied"
    assert calculate([holding("60000.01")], day=date(2027, month, 15))["assessment"] == "breached"


def test_budgets_cannot_be_borrowed_between_groups_or_rules():
    result = calculate([holding("30000.01"), holding("10000", sid="b", code="B"),
                        holding("60000", rid="other")], rules=[rule(), rule("other", restricted=False)])
    states = {item["rule_id"]: item for item in result["evaluations"]}
    assert states["r"]["assessment"] == "breached"
    assert "分组A" in states["r"]["issues"][0]
    assert states["other"]["assessment"] == "complied"


def test_fees_are_part_of_half_capital_and_odd_cent_budget_is_not_rounded_up():
    assert calculate(events=[recorded(price="300", quantity="100", fee="0")])["assessment"] == "complied"
    result = calculate(events=[recorded(price="300", quantity="100", fee="0.01")])
    assert result["events"][0]["compliance_status"] == "breached"
    assert result["positions"][0]["cost"] == "30000.01"
    value = rule()
    value["stock_rules"][0]["max_capital"] = "60000.01"
    assert calculate([holding("30000.01")], rules=[value])["assessment"] == "breached"


def test_each_recorded_trade_is_checked_and_reduction_does_not_repeat_breach():
    # 卖出原持仓后剩余成本已低于半仓，仍保留此前买入的超限依据。
    result = calculate([holding("10000")], [
        recorded(price="201", quantity="100"),
        recorded(side="sell", order=2, quantity="100"),
    ])
    assert result["positions"][0]["cost"] == "15050.00"
    assert result["events"][0]["compliance_status"] == "breached"
    assert result["events"][1]["compliance_status"] == "complied"
    assert result["assessment"] == "partial"


def test_opening_breach_is_daily_and_adjustment_breach_is_not_a_fake_trade():
    result = calculate([holding("30000.01")], [recorded(side="sell", quantity="100")])
    assert result["positions"] == []
    assert len(result["evaluations"][0]["issues"]) == 1
    assert result["events"][0]["issues"] == []
    adjusted = calculate(events=[recorded(kind="position", adjustment_type="transfer", note="转入",
                                        quantity="100", cost_price="301")])
    assert adjusted["buy_amount"] == "0.00"
    assert adjusted["assessment"] == "breached"
    assert "50%" in adjusted["evaluations"][0]["issues"][0]


@pytest.mark.parametrize("patch", [{"cost": None}, {"stock_rule_id": "removed"}, {"stock_rule_id": None}])
def test_missing_cost_or_matching_group_is_pending(patch):
    opening = holding()
    opening.update(patch)
    result = calculate([opening])
    assert result["assessment"] is None
    assert result["evaluations"][0]["warnings"]


@pytest.mark.parametrize("budget,enabled", [(None, True), ("0", True), ("60000", False)])
def test_missing_or_disabled_budget_does_not_silently_pass(budget, enabled):
    value = rule()
    value["stock_rules"][0].update(max_capital=budget, enabled=enabled)
    assert calculate([holding()], rules=[value])["assessment"] is None


@pytest.mark.parametrize("month", [4, 8, 10])
@pytest.mark.parametrize("cost", [None, "0", "100"])
def test_report_month_checks_quantity_even_without_cost(month, cost):
    result = calculate([holding(cost)], day=date(2027, month, 15))
    assert result["assessment"] == "breached"
    assert result["evaluations"][0]["warnings"] == []
    assert "禁持" in result["evaluations"][0]["issues"][0]


def test_report_month_empty_buy_and_liquidation():
    assert calculate(day=REPORT_DAY)["assessment"] == "complied"
    bought = calculate(events=[recorded(REPORT_DAY)], day=REPORT_DAY)
    assert bought["events"][0]["compliance_status"] == "breached"
    sold = calculate([holding("100")], [recorded(REPORT_DAY, side="sell", quantity="100")], day=REPORT_DAY)
    assert sold["positions"] == []
    assert sold["evaluations"][0]["issues"]  # 期初持仓违规仍保留。
    assert sold["events"][0]["issues"] == []  # 清仓行为本身不再罚一次。


@pytest.mark.parametrize("day,next_day", [(date(2027, 3, 31), date(2027, 4, 1)),
                                          (LAST_DAY, REPORT_DAY),
                                          (date(2027, 9, 30), date(2027, 10, 8))])
def test_last_trading_day_requires_final_empty_position(day, next_day):
    retained = calculate([holding()], day=day, next_day=next_day)
    assert retained["assessment"] == "breached"
    assert "最后一个交易日" in retained["evaluations"][0]["issues"][0]
    cleared = calculate([holding()], [recorded(day, side="sell", quantity="100")], day=day, next_day=next_day)
    assert cleared["assessment"] == "complied"
    assert cleared["positions"] == []


@pytest.mark.parametrize("next_day", [None, HALF_DAY, date(2027, 9, 1), date(2028, 7, 16)])
def test_calendar_is_required_only_for_enabled_preceding_month(next_day):
    with pytest.raises(ValidationError, match="交易日历"):
        calculate_day([], [], HALF_DAY, rules=[rule()], next_trade_date=next_day)
    assert calculate_day([], [], HALF_DAY, rules=[rule(restricted=False)])["assessment"] == "complied"


def test_linked_rule_check_does_not_duplicate_primary_budget():
    linked = recorded(price="400", quantity="100", rule_checks=[{
        "rule_id": "linked", "rule_name": "附加", "issues": [], "warnings": [],
    }])
    result = calculate(events=[linked], rules=[rule(restricted=False), rule("linked")])
    assert result["assessment"] == "complied"
    assert len(result["positions"]) == 1
    assert {p["rule_id"] for p in result["positions"]} == {"r"}


@pytest.mark.parametrize("value", [None, "true", "false", 1, 0, [], {}])
def test_restriction_rejects_non_boolean_in_api_and_service(value):
    with pytest.raises(ModelValidationError):
        RuleDraftBody(restrict_financial_report_months=value)
    # 输入校验无需数据库，也不把旧客户端缺字段与显式非法值混为一谈。
    with pytest.raises(ValidationError, match="布尔"):
        TradeDisciplineService()._prepare_draft({"restrict_financial_report_months": value})


def seed_service(pg, market, *, restricted=True, target=LAST_DAY):
    """行情只写内存库，PG复用测试归属；用未来真实日历避免运行日期漂移。"""
    market.execute("INSERT INTO stock_basic(code,name,board) VALUES ('600000.SH','测试股票','主板')")
    for day in (LAST_DAY - timedelta(days=1), LAST_DAY, REPORT_DAY, REPORT_DAY + timedelta(days=1)):
        market.execute("INSERT INTO trade_calendar VALUES (?, TRUE)", [day])
        market.execute("INSERT INTO daily_bar(code,trade_date) VALUES ('600000.SH', ?)", [day])
    service = ledger(pg, market)
    payload = dict(_rule_payload(), restrict_financial_report_months=restricted)
    rid = service.discipline.create_rule(payload)["id"]
    service.discipline.publish_rule(rid, expected_revision=1)
    context = service.initialize(target, [{"stock_code": "600000.SH", "quantity": "100",
                                          "cost_price": "10", "rule_id": rid,
                                          "stock_rule_id": "stock-1"}], None, 0)
    return service, rid, context, payload


def test_version_flag_default_toggle_only_publish_copy_and_upgrade_idempotence(pg, market):
    service, rid, _, payload = seed_service(pg, market, restricted=False)
    old = service.discipline.repo.load_version(rid, 1)
    assert old["restrict_financial_report_months"] is False
    pg.execute(_TRADE_DISCIPLINE_FINANCIAL_REPORT_UPGRADES)
    pg.execute(_TRADE_DISCIPLINE_FINANCIAL_REPORT_UPGRADES)
    draft = service.discipline.open_draft(rid)
    assert draft["restrict_financial_report_months"] is False
    payload["restrict_financial_report_months"] = True
    saved = service.discipline.save_draft(rid, payload, expected_revision=draft["draft_revision"])
    copied_draft = service.discipline.copy_rule(rid, source="draft")
    assert service.discipline.repo.load_draft(copied_draft["id"])["restrict_financial_report_months"] is True
    published = service.discipline.publish_rule(rid, expected_revision=saved["draft_revision"])
    assert published["changed"] and published["version_no"] == 2
    assert service.discipline.repo.load_version(rid, 1) == old
    copied = service.discipline.copy_rule(rid, source="published")
    assert service.discipline.repo.load_draft(copied["id"])["restrict_financial_report_months"] is True
    reopened = service.discipline.open_draft(rid)
    assert reopened["restrict_financial_report_months"] is True
    assert service.discipline.publish_rule(rid, expected_revision=reopened["draft_revision"])["changed"] is False


def test_real_no_operation_preview_submit_revise_and_history_pin_version(pg, market):
    service, rid, context, payload = seed_service(pg, market)
    with pytest.raises(ConflictError, match="正式打卡"):
        service.quick_no_operation(rid, LAST_DAY)
    assert service.context(LAST_DAY)["current_revision_no"] == 0
    content = submit_payload(context, [])
    preview = service.submit(LAST_DAY, content, preview=True)
    assert preview["assessment"] == "breached"
    saved = service.submit(LAST_DAY, content)
    assert preview["evaluations"] == saved["evaluations"]
    assert saved["calculation_version"] == "ledger-v4"
    assert service.submit(LAST_DAY, content)["idempotent"]
    original = deepcopy(service.revisions(LAST_DAY, 1)["snapshot"])
    # 新发布关闭开关，旧日结修正仍须使用原来启用的版本。
    draft = service.discipline.open_draft(rid)
    payload["restrict_financial_report_months"] = False
    service.discipline.save_draft(rid, payload, expected_revision=draft["draft_revision"])
    service.discipline.publish_rule(rid, expected_revision=draft["draft_revision"] + 1)
    context = service.context(LAST_DAY)
    assert context["rules"][0]["restrict_financial_report_months"] is True
    sell = dict(event(side="sell", quantity="100", rule_id=rid, stock_rule_id="stock-1", action_rule_id="sell-1"),
                stock_code="600000.SH", operated_at=f"{LAST_DAY}T14:00:00+08:00")
    amended = service.submit(LAST_DAY, submit_payload(context, [sell]))
    assert amended["assessment"] == "complied"
    assert amended["positions"] == []
    assert service.revisions(LAST_DAY, 1)["snapshot"] == original
    assert amended["rules"][0]["version_no"] == 1


def test_real_calendar_failure_does_not_write_or_advance_account(pg, market):
    service, _, context, _ = seed_service(pg, market)
    market.execute("DELETE FROM trade_calendar WHERE trade_date > ?", [LAST_DAY])
    with pytest.raises(ValidationError, match="交易日历"):
        service.submit(LAST_DAY, submit_payload(context, []))
    loaded = service.context(LAST_DAY)
    assert loaded["account_revision"] == context["account_revision"]
    assert loaded["current_revision_no"] == 0


def test_old_missing_flag_remains_unrestricted():
    old = rule()
    old.pop("restrict_financial_report_months")
    assert calculate([holding()], day=REPORT_DAY, rules=[old])["assessment"] == "complied"
