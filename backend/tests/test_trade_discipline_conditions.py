"""选股结构化条件、持仓峰值和不可变打卡事实的服务/仓库回归。"""

from decimal import Decimal

import pytest

from backend.common.exceptions import ValidationError
from backend.services.trade_discipline_conditions import condition_violations, condition_warnings
from backend.tests.test_trade_discipline_t3 import (
    _operation,
    _rule_payload,
    _seed_market,
    _service,
)


@pytest.mark.parametrize("patch", [
    {"price_min": "0"}, {"price_max": "1.00001"},
    {"price_min": "10", "price_max": "9"}, {"st_filter": "invalid"},
])
def test_invalid_stock_conditions_rejected(pg, market, patch):
    payload = _rule_payload()
    payload["stock_rules"][0].update(patch)
    with pytest.raises(ValidationError):
        _service(pg, market).create_rule(payload)


@pytest.mark.parametrize("value", [0, -1, True, 2.5, "2", 2147483648])
def test_invalid_position_limit_rejected(pg, market, value):
    payload = dict(_rule_payload(), max_positions=value)
    with pytest.raises(ValidationError):
        _service(pg, market).create_rule(payload)


def test_condition_changes_publish_and_copy_without_rewriting_old_version(pg, market):
    _seed_market(market)
    service = _service(pg, market)
    payload = _rule_payload()
    rule_id = service.create_rule(payload)["id"]
    service.publish_rule(rule_id, expected_revision=1)
    service.open_draft(rule_id)
    payload["max_positions"] = 2
    payload["stock_rules"][0].update(price_min="5.1234", price_max="20", st_filter="exclude")
    draft = service.save_draft(rule_id, payload, expected_revision=1)
    service.publish_rule(rule_id, expected_revision=draft["draft_revision"])
    version = service.repo.load_version(rule_id, 2)
    assert version["max_positions"] == 2
    assert version["stock_rules"][0]["price_min"] == Decimal("5.1234")
    old = service.repo.load_version(rule_id, 1)
    assert old["max_positions"] is None
    assert old["stock_rules"][0]["st_filter"] == "any"
    copy = service.copy_rule(rule_id, source="published")
    copied = service.repo.load_draft(copy["id"])
    assert copied["max_positions"] == 2
    assert copied["stock_rules"][0]["price_max"] == Decimal(20)


def test_checkin_requires_explicit_facts_and_preserves_snapshot_on_amend(pg, market, monkeypatch):
    trade_date, *_ = _seed_market(market)
    service = _service(pg, market)
    payload = dict(_rule_payload(), max_positions=2)
    payload["stock_rules"][0].update(
        price_min="5", price_max="10", st_filter="exclude",
        loss_filter="exclude", st_risk_filter="exclude",
    )
    rule_id = service.create_rule(payload)["id"]
    service.publish_rule(rule_id, expected_revision=1)
    with pytest.raises(ValidationError, match="持仓"):
        service.quick_no_operation(rule_id, trade_date)
    operation = _operation(trade_date)
    content = {"assessment": "complied", "no_operation": False, "operations": [operation]}
    with pytest.raises(ValidationError, match="持仓"):
        service.submit_checkin(rule_id, trade_date, content)
    content["peak_positions"] = 3
    with pytest.raises(ValidationError, match="未知"):
        service.submit_checkin(rule_id, trade_date, content)
    operation.update(loss_status="no", st_risk_status="unknown")
    monkeypatch.setattr(service, "_st_statuses", lambda *_: {"600000.SH": False})
    with pytest.raises(ValidationError, match="不能选择已履约"):
        service.submit_checkin(rule_id, trade_date, content)
    content.update(assessment="breached", reason_code="stock_rule_violation", violation_detail="条件违规")
    created = service.submit_checkin(rule_id, trade_date, content)
    assert created["assessment"] == "breached"
    assert created["peak_positions"] == 3
    facts = created["operations"][0]["selection_facts"]
    assert facts["is_st"] is False
    assert "成交价不符合股价条件" in created["operations"][0]["condition_warnings"]
    assert "ST风险未知，无法核对" in created["operations"][0]["condition_warnings"]
    monkeypatch.setattr(service, "_st_statuses", lambda *_: {"600000.SH": True})
    content["peak_positions"] = 2
    amended = service.amend_checkin(created["checkin_id"], content, expected_revision=1)
    assert amended["operations"][0]["selection_facts"]["is_st"] is False
    assert service.get_revision(created["checkin_id"], 1)["peak_positions"] == 3
    assert service.summary(trade_date)["rules"][0]["max_positions"] == 2


def test_no_operation_still_checks_peak_and_excess_cannot_be_complied(pg, market):
    trade_date, second, *_ = _seed_market(market)
    service = _service(pg, market)
    rule_id = service.create_rule(dict(_rule_payload(), max_positions=1))["id"]
    service.publish_rule(rule_id, expected_revision=1)
    for target, peak in ((trade_date, 0), (second, 3)):
        content = {"assessment": "complied", "no_operation": True, "operations": [], "peak_positions": peak}
        if peak > 1:
            with pytest.raises(ValidationError, match="不能选择已履约"):
                service.submit_checkin(rule_id, target, content)
            content.update(assessment="breached", reason_code="other", violation_detail="持仓超限", violation_items=["other"])
        result = service.submit_checkin(rule_id, target, content)
        assert result["peak_positions"] == peak


def test_warning_boundaries_unknown_and_sell():
    rule = {"price_min": Decimal(5), "price_max": Decimal(10), "loss_filter": "only"}
    for value in ("5", "10"):
        assert condition_warnings(rule, {
            "side": "buy", "price": Decimal(value), "selection_facts": {"loss_status": "yes"},
        }) == []
    assert condition_warnings(rule, {"side": "sell"}) == []
    assert len(condition_warnings(rule, {"side": "buy"})) == 2


def test_request_models_reject_forged_st_and_fractional_counts():
    from pydantic import ValidationError as BodyValidationError

    from backend.api.trade_discipline import CheckinContentBody, OperationBody, RuleDraftBody

    operation = {"stock_code": "600000.SH", "side": "buy", "stock_rule_id": "s",
                 "action_rule_id": "a", "display_order": 1,
                 "price": "10", "quantity": "100", "amount": "1000", "fee": "0"}
    for patch in ({"selection_facts": {"is_st": False}}, {"is_st": False},
                  {"loss_status": "unverified"}):
        with pytest.raises(BodyValidationError):
            OperationBody(**operation, **patch)
    for value in (True, 1.5, "2", -1):
        with pytest.raises(BodyValidationError):
            CheckinContentBody(assessment="complied", no_operation=True, peak_positions=value)
    with pytest.raises(BodyValidationError):
        RuleDraftBody(max_positions=0)
    assert OperationBody(**operation, loss_status="unknown").loss_status == "unknown"


@pytest.mark.parametrize("field,fact,value", [
    ("st_filter", "is_st", True), ("loss_filter", "loss_status", "yes"),
    ("st_risk_filter", "st_risk_status", "yes"),
])
@pytest.mark.parametrize("mode", ["exclude", "only", "any"])
def test_known_conditions_match_rule_mode(field, fact, value, mode):
    rule = {field: mode}
    operation = {"side": "buy", "selection_facts": {fact: value}}
    assert bool(condition_violations(rule, operation)) == (mode == "exclude")
    operation["selection_facts"][fact] = False if fact == "is_st" else "no"
    assert bool(condition_violations(rule, operation)) == (mode == "only")
    operation["selection_facts"][fact] = None
    assert condition_violations(rule, operation) == []
    assert condition_violations(rule, {**operation, "side": "sell"}) == []


@pytest.mark.parametrize("price,violates", [(None, False), ("4.9999", True), ("5", False), ("10", False), ("10.0001", True)])
def test_known_price_violations_exclude_unknown(price, violates):
    assert bool(condition_violations(
        {"price_min": Decimal(5), "price_max": Decimal(10)},
        {"side": "buy", "price": Decimal(price) if price else None},
    )) == violates


def test_authoritative_st_blocks_complied_and_partial_operation(pg, market, monkeypatch):
    trade_date, second, third = _seed_market(market)
    service = _service(pg, market)
    payload = _rule_payload()
    payload["stock_rules"][0]["st_filter"] = "exclude"
    rule_id = service.create_rule(payload)["id"]
    service.publish_rule(rule_id, expected_revision=1)
    monkeypatch.setattr(service, "_st_statuses", lambda *_: {"600000.SH": True})
    operation = dict(_operation(trade_date), is_st=False)
    content = {"assessment": "complied", "no_operation": False, "operations": [operation]}
    with pytest.raises(ValidationError, match="ST状态"):
        service.submit_checkin(rule_id, trade_date, content)
    content.update(assessment="partial", reason_code="stock_rule_violation", violation_detail="ST违规")
    operation["compliance_status"] = "complied"
    with pytest.raises(ValidationError, match="不能选择已履约"):
        service.submit_checkin(rule_id, trade_date, content)
    operation["compliance_status"] = "breached"
    content["operations"].append(dict(
        _operation(trade_date, side="sell"), compliance_status="complied", display_order=2,
    ))
    created = service.submit_checkin(rule_id, trade_date, content)
    assert created["assessment"] == "partial"
    operation["compliance_status"] = "complied"
    with pytest.raises(ValidationError, match="不能选择已履约"):
        service.amend_checkin(created["checkin_id"], content, expected_revision=1)
    # 同规则卖出 ST 不套用买入选股限制；未知 ST 也不伪造成违规。
    sell = _operation(second)
    sell.update(side="sell", action_rule_id="sell-1")
    assert service.submit_checkin(rule_id, second, {"assessment":"complied", "no_operation":False, "operations":[sell]})["assessment"] == "complied"
    monkeypatch.setattr(service, "_st_statuses", lambda *_: {})
    assert service.submit_checkin(rule_id, third, {"assessment":"complied", "no_operation":False, "operations":[_operation(third)]})["assessment"] == "complied"


def test_quick_with_limit_records_confirmed_peak_and_checks_idempotency(pg, market):
    from backend.common.exceptions import ConflictError
    trade_date, second, _ = _seed_market(market)
    service = _service(pg, market)
    rule_id = service.create_rule(dict(_rule_payload(), max_positions=2))["id"]
    service.publish_rule(rule_id, expected_revision=1)
    with pytest.raises(ValidationError, match="持仓"):
        service.quick_no_operation(rule_id, trade_date)
    with pytest.raises(ValidationError, match="不能选择已履约"):
        service.quick_no_operation(rule_id, trade_date, peak_positions=3)
    created = service.quick_no_operation(rule_id, trade_date, peak_positions=2)
    assert created["peak_positions"] == 2 and created["no_operation"]
    assert service.quick_no_operation(rule_id, trade_date, peak_positions=2)["idempotent"]
    with pytest.raises(ConflictError):
        service.quick_no_operation(rule_id, trade_date, peak_positions=0)
    assert service.quick_no_operation(rule_id, second, peak_positions=0)["peak_positions"] == 0
