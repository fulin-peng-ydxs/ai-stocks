"""选股结构化条件、持仓峰值和不可变打卡事实的服务/仓库回归。"""

from decimal import Decimal

import pytest

from backend.common.exceptions import ValidationError
from backend.services.trade_discipline_conditions import condition_warnings
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
    created = service.submit_checkin(rule_id, trade_date, content)
    assert created["assessment"] == "complied"  # 提示不替用户裁决
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


def test_no_operation_still_requires_peak_but_allows_zero_or_excess(pg, market):
    trade_date, second, *_ = _seed_market(market)
    service = _service(pg, market)
    rule_id = service.create_rule(dict(_rule_payload(), max_positions=1))["id"]
    service.publish_rule(rule_id, expected_revision=1)
    for target, peak in ((trade_date, 0), (second, 3)):
        result = service.submit_checkin(rule_id, target, {
            "assessment": "complied", "no_operation": True, "operations": [],
            "peak_positions": peak,
        })
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
                 "action_rule_id": "a", "display_order": 1}
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
