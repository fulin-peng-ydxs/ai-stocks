"""未履约事项的服务守卫、修订快照与成交事实隔离回归。"""

import pytest
from pydantic import ValidationError as BodyValidationError

from backend.api.trade_discipline import CheckinContentBody
from backend.common.exceptions import NotFoundError, ValidationError
from backend.tests.test_trade_discipline_t3 import (
    _operation,
    _published_rule,
    _seed_market,
    _service,
)


def _content(**patch):
    return dict(
        {
            "assessment": "breached",
            "no_operation": True,
            "operations": [],
            "reason_code": "missed_required_action",
            "violation_detail": "未按计划执行\n下次提醒",
            "violation_items": ["missed_buy", "missed_sell"],
            "peak_positions": 2,
        },
        **patch,
    )


@pytest.mark.parametrize(
    "items", [None, [], "missed_buy", ["unknown"], ["missed_buy", "missed_buy"], [{}], [True]]
)
def test_no_operation_requires_valid_items(pg, market, items):
    trade_date, *_ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    with pytest.raises(ValidationError, match="未履约事项"):
        service.submit_checkin(rule_id, trade_date, _content(violation_items=items))
    assert service.repo.get_checkin_by_rule_date(rule_id, trade_date) is None


@pytest.mark.parametrize(
    "peak,items",
    [
        (0, ["missed_buy"]),
        (0, ["missed_sell"]),
        (None, ["other"]),
        (2, ["missed_sell", "missed_buy"]),
    ],
)
def test_items_do_not_infer_direction_from_position_count(pg, market, peak, items):
    trade_date, *_ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    result = service.submit_checkin(
        rule_id,
        trade_date,
        _content(
            peak_positions=peak,
            violation_items=items,
        ),
    )
    assert set(result["violation_items"]) == set(items)
    assert result["peak_positions"] == peak
    assert result["operations"] == []
    assert result["violation_detail"] == "未按计划执行\n下次提醒"


def test_amendment_preserves_items_and_owner_boundary(pg, market):
    trade_date, *_ = _seed_market(market)
    service = _service(pg, market)
    result = service.submit_checkin(_published_rule(service), trade_date, _content())
    amended = service.amend_checkin(
        result["checkin_id"],
        _content(
            violation_items=["other"],
        ),
        expected_revision=1,
    )
    assert amended["violation_items"] == ["other"]
    assert service.get_revision(result["checkin_id"], 1)["violation_items"] == [
        "missed_buy",
        "missed_sell",
    ]
    assert service.get_checkin_context(result["rule_id"], trade_date)["checkin"][
        "violation_items"
    ] == ["other"]
    from backend.services.trade_discipline_service import TradeDisciplineService
    from backend.storage.trade_discipline_repository import TradeDisciplineRepository

    foreign = TradeDisciplineService(
        repo=TradeDisciplineRepository(
            pg, tenant_id="foreign-tenant", owner_user_id="foreign-user"
        ),
        market=market,
    )
    with pytest.raises(NotFoundError):
        foreign.get_revision(result["checkin_id"], 1)


@pytest.mark.parametrize("assessment", ["partial", "breached"])
def test_real_operations_can_coexist_with_missed_actions(pg, market, assessment):
    trade_date, *_ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    operation = _operation(trade_date)
    if assessment == "partial":
        operation["compliance_status"] = "complied"
    result = service.submit_checkin(
        rule_id,
        trade_date,
        _content(
            assessment=assessment,
            no_operation=False,
            operations=[operation],
            violation_items=["missed_sell"],
        ),
    )
    assert result["violation_items"] == ["missed_sell"]
    assert len(result["operations"]) == 1
    history = service.list_checkins()["list"]
    assert history[0]["operation_count"] == 1


def test_complied_cannot_carry_violation_items_and_quick_stays_empty(pg, market):
    trade_date, *_ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    with pytest.raises(ValidationError, match="已履约不能填写未履约事项"):
        service.submit_checkin(
            rule_id,
            trade_date,
            {
                "assessment": "complied",
                "no_operation": True,
                "violation_items": ["other"],
            },
        )
    quick = service.quick_no_operation(rule_id, trade_date)
    assert quick["violation_items"] == []


def test_request_model_rejects_invalid_enum_type_and_excess_items():
    for items in (["unknown"], "missed_buy", [True], ["other"] * 4):
        with pytest.raises(BodyValidationError):
            CheckinContentBody(assessment="breached", no_operation=True, violation_items=items)


def test_legacy_null_survives_upgrade_and_amend_requires_items(pg, market):
    from backend.storage.pg_ddl import _TRADE_DISCIPLINE_VIOLATION_ITEMS_UPGRADES

    trade_date, *_ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    # 使用仓库重建升级前快照；不从历史原因推断新事项。
    with service.repo.transaction() as conn:
        service.repo.create_checkin(
            conn,
            checkin_id="legacy-violation-items",
            rule_id=rule_id,
            trade_date=trade_date,
            submission_source="workbench",
        )
        service.repo.insert_revision(
            conn,
            checkin_id="legacy-violation-items",
            revision_no=1,
            rule_id=rule_id,
            version_no=1,
            assessment="breached",
            no_operation=True,
            violation_detail="历史漏卖",
            review_note=None,
        )
    pg.execute(_TRADE_DISCIPLINE_VIOLATION_ITEMS_UPGRADES)
    pg.execute(_TRADE_DISCIPLINE_VIOLATION_ITEMS_UPGRADES)
    assert service.get_revision("legacy-violation-items", 1)["violation_items"] is None
    with pytest.raises(ValidationError, match="未履约事项"):
        service.amend_checkin(
            "legacy-violation-items", _content(violation_items=None), expected_revision=1
        )
    amended = service.amend_checkin("legacy-violation-items", _content(), expected_revision=1)
    assert amended["violation_items"] == ["missed_buy", "missed_sell"]
    assert service.get_revision("legacy-violation-items", 1)["violation_items"] is None
