"""分类检查项的版本、核对守卫与不可变修订回归。"""

from uuid import uuid4

import pytest

from backend.common.exceptions import NotFoundError, ValidationError
from backend.services.trade_discipline_conditions import (
    condition_violations,
    condition_warnings,
    prepare_checklist_items,
    prepare_checklist_results,
)
from backend.tests.conftest import clean_owner
from backend.tests.test_trade_discipline_t3 import _operation, _rule_payload, _seed_market, _service


def _items():
    return [
        {
            "item_id": "trend",
            "category": "technical",
            "text": "多头排列累计涨幅不超过50%",
            "display_order": 1,
        }
    ]


def test_legacy_category_is_technical_without_mutating_source():
    legacy = [
        {**_items()[0], "item_id": "first", "category": "technical"},
        {**_items()[0], "item_id": "second", "category": "other"},
    ]
    prepared = prepare_checklist_items(legacy)
    assert [item["item_id"] for item in prepared] == ["first", "second"]
    assert [item["category"] for item in prepared] == ["technical", "technical"]
    assert legacy[1]["category"] == "other"


def test_legacy_formal_snapshot_remains_unchanged_when_saving_draft(pg, market):
    from psycopg.types.json import Jsonb

    from backend.tests.conftest import TEST_TENANT

    owner = f"pytest_checklist_{uuid4().hex}"
    service = _service(pg, market, owner=owner)
    _seed_market(market)
    try:
        payload = _rule_payload()
        rule_id = service.create_rule(payload)["id"]
        service.publish_rule(rule_id, expected_revision=1)
        # 仅为此随机归属的临时版本构造旧格式，不触碰真实业务版本。
        legacy = [{**_items()[0], "category": "other"}]
        pg.execute(
            "UPDATE trade_discipline_stock_rule SET checklist_items=%s "
            "WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s AND version_no=1",
            [Jsonb(legacy), TEST_TENANT, owner, rule_id],
        )
        draft = service.open_draft(rule_id)
        saved = service.save_draft(rule_id, draft, expected_revision=draft["draft_revision"])
        assert saved["stock_rules"][0]["checklist_items"][0]["category"] == "technical"
        assert service.repo.load_version(rule_id, 1)["stock_rules"][0]["checklist_items"] == legacy
    finally:
        clean_owner(pg, owner=owner)


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        [None],
        [{"item_id": "", "text": "条件"}],
        [{"category": "bad category"}],
        [{"display_order": True}],
        _items() * 2,
    ],
)
def test_invalid_checklist_rejected(value):
    with pytest.raises(ValidationError):
        prepare_checklist_items(value)


@pytest.mark.parametrize(
    "results",
    [
        None,
        [],
        [{"item_id": "foreign", "status": "yes"}],
        [{"item_id": "trend", "status": "yes"}] * 2,
        [{"item_id": "trend", "status": "bad"}],
    ],
)
def test_results_must_exactly_match_selected_rule(results):
    with pytest.raises(ValidationError):
        prepare_checklist_results(
            {"checklist_items": _items()},
            {
                "side": "buy",
                "checklist_results": results,
            },
        )


def test_unknown_is_not_violation_and_sell_not_checked():
    rule = {"checklist_items": _items()}
    operation = {"side": "buy", "checklist_results": [{"item_id": "trend", "status": "unknown"}]}
    assert condition_violations(rule, operation) == []
    assert "未知" in condition_warnings(rule, operation)[0]
    operation["checklist_results"][0]["status"] = "no"
    assert "不符合" in condition_violations(rule, operation)[0]
    assert condition_warnings(rule, {**operation, "side": "sell"}) == []
    with pytest.raises(ValidationError):
        prepare_checklist_results(rule, {**operation, "side": "sell"})


def test_checklist_publish_copy_checkin_amend_history_and_owner(pg, market):
    owner = f"pytest_checklist_{uuid4().hex}"
    service = _service(pg, market, owner=owner)
    trade_date, second, third = _seed_market(market)
    try:
        payload = _rule_payload()
        original = payload["stock_rules"][0]["content"]
        rule_id = service.create_rule(payload)["id"]
        service.publish_rule(rule_id, expected_revision=1)
        service.open_draft(rule_id)
        payload["stock_rules"][0].update(content=None, checklist_items=_items())
        draft = service.save_draft(rule_id, payload, expected_revision=1)
        service.publish_rule(rule_id, expected_revision=draft["draft_revision"])
        old = service.repo.load_version(rule_id, 1)["stock_rules"][0]
        assert old["content"] == original and old["checklist_items"] == []
        version = service.repo.load_version(rule_id, 2)
        assert version["stock_rules"][0]["content"] is None
        copied = service.copy_rule(rule_id, source="published")
        copied_item = copied["draft"]["stock_rules"][0]["checklist_items"][0]
        assert copied_item["item_id"] != "trend"
        assert copied_item["text"] == _items()[0]["text"]
        with pytest.raises(NotFoundError):
            _service(pg, market, owner=f"other_{owner}").get_rule(rule_id)
        # 单独修改检查项也必须生成新版本，旧版本原文保持不变。
        service.open_draft(rule_id)
        payload["stock_rules"][0]["checklist_items"][0]["text"] = "一年内涨幅不超过100%"
        draft = service.save_draft(rule_id, payload, expected_revision=1)
        result = service.publish_rule(rule_id, expected_revision=draft["draft_revision"])
        assert result["version_no"] == 3
        assert (
            service.repo.load_version(rule_id, 2)["stock_rules"][0]["checklist_items"]
            == [{**item, "category_label": "技术形态"} for item in _items()]
        )
        operation = _operation(trade_date)
        content = {"assessment": "complied", "no_operation": False, "operations": [operation]}
        with pytest.raises(ValidationError, match="逐项核对"):
            service.submit_checkin(rule_id, trade_date, content)
        operation["checklist_results"] = [{"item_id": "trend", "status": "no"}]
        with pytest.raises(ValidationError, match="不能选择已履约"):
            service.submit_checkin(rule_id, trade_date, content)
        content.update(
            assessment="partial", reason_code="stock_rule_violation", violation_detail="未满足条件"
        )
        operation["compliance_status"] = "complied"
        with pytest.raises(ValidationError, match="不能选择已履约"):
            service.submit_checkin(rule_id, trade_date, content)
        operation["compliance_status"] = "breached"
        created = service.submit_checkin(rule_id, trade_date, content)
        assert created["operations"][0]["checklist_results"][0]["status"] == "no"
        assert "不符合" in created["operations"][0]["condition_warnings"][0]
        content.update(assessment="complied", reason_code=None, violation_detail=None)
        operation.update(
            compliance_status=None, checklist_results=[{"item_id": "trend", "status": "unknown"}]
        )
        amended = service.amend_checkin(created["checkin_id"], content, expected_revision=1)
        assert amended["operations"][0]["checklist_results"][0]["status"] == "unknown"
        assert (
            service.get_revision(created["checkin_id"], 1)["operations"][0]["checklist_results"][0][
                "status"
            ]
            == "no"
        )
        assert service.quick_no_operation(rule_id, second)["no_operation"]
        sold = service.submit_checkin(
            rule_id,
            third,
            {
                "assessment": "complied",
                "no_operation": False,
                "operations": [_operation(third, side="sell")],
            },
        )
        assert sold["operations"][0]["checklist_results"] is None
    finally:
        clean_owner(pg, owner=owner)


def test_empty_item_cannot_publish_but_structured_rule_needs_no_notes(pg, market):
    owner = f"pytest_checklist_{uuid4().hex}"
    service = _service(pg, market, owner=owner)
    _seed_market(market)
    try:
        payload = _rule_payload()
        payload["stock_rules"][0].update(
            content=None, checklist_items=[{**_items()[0], "text": ""}]
        )
        rule_id = service.create_rule(payload)["id"]
        with pytest.raises(ValidationError, match="检查项内容不能为空"):
            service.publish_rule(rule_id, expected_revision=1)
        payload["stock_rules"][0].update(checklist_items=[], price_max="30")
        draft = service.save_draft(rule_id, payload, expected_revision=1)
        assert service.publish_rule(rule_id, expected_revision=draft["draft_revision"])["changed"]
    finally:
        clean_owner(pg, owner=owner)
