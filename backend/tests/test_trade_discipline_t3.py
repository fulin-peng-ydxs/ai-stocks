"""交易纪律 T3：打卡、原因、操作与历史服务。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from backend.api.response import ApiResponse
from backend.common.exceptions import ConflictError, NotFoundError, ValidationError
from backend.services.trade_discipline_service import TradeDisciplineService
from backend.storage.trade_discipline_repository import TradeDisciplineRepository
from backend.tests.conftest import TEST_OWNER, TEST_TENANT, clean_owner

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_operation_decimals_enforce_postgres_numeric_ranges():
    parse = TradeDisciplineService._decimal
    assert parse(
        "9999999999999999.9999", places=4, label="成交价格"
    ) == Decimal("9999999999999999.9999")
    assert parse(
        "999999999999999999.99", places=2, label="成交金额"
    ) == Decimal("999999999999999999.99")
    for value, places, label in (
        ("10000000000000000.0000", 4, "成交价格"),
        ("10000000000000000", 4, "成交数量"),
        ("1.00001", 4, "成交价格"),
        ("1000000000000000000.00", 2, "成交金额"),
        ("1.001", 2, "交易费用"),
    ):
        with pytest.raises(ValidationError):
            parse(value, places=places, label=label)


def _rule_payload(name: str = "履约纪律") -> dict:
    return {
        "name": name,
        "capital": "100000",
        "stock_rules": [
            {
                "detail_id": "stock-1",
                "name": "趋势选股",
                "max_capital": "50000",
                "content": "趋势向上\n量价配合",
                "display_order": 1,
                "enabled": True,
            }
        ],
        "action_rules": [
            {
                "detail_id": "buy-1",
                "name": "回踩买入",
                "action_type": "buy",
                "action_subtype": "open_position",
                "content": "回踩不破",
                "display_order": 1,
                "enabled": True,
            },
            {
                "detail_id": "sell-1",
                "name": "破位卖出",
                "action_type": "sell",
                "action_subtype": "liquidate",
                "content": "跌破离场",
                "display_order": 1,
                "enabled": True,
            },
        ],
    }


def _service(pg, market, *, owner: str = TEST_OWNER) -> TradeDisciplineService:
    return TradeDisciplineService(
        TradeDisciplineRepository(pg, tenant_id=TEST_TENANT, owner_user_id=owner),
        market,
    )


def _seed_market(market) -> tuple[date, date, date]:
    market.execute(
        "INSERT INTO stock_basic(code,name,board,industry) "
        "VALUES ('600000.SH','浦发银行','主板','银行') "
        "ON CONFLICT(code) DO UPDATE SET name=EXCLUDED.name"
    )
    first = datetime.now(SHANGHAI).date() + timedelta(days=1)
    dates = (first, first + timedelta(days=1), first + timedelta(days=2))
    for current in dates:
        market.execute(
            "INSERT INTO trade_calendar(trade_date,is_open) VALUES (?,TRUE) "
            "ON CONFLICT(trade_date) DO UPDATE SET is_open=TRUE",
            [current],
        )
        market.execute(
            "INSERT INTO daily_bar(code,trade_date) VALUES ('600000.SH',?) "
            "ON CONFLICT(code,trade_date) DO NOTHING",
            [current],
        )
    return dates


def _published_rule(service: TradeDisciplineService) -> str:
    rule_id = service.create_rule(_rule_payload())["id"]
    service.publish_rule(rule_id, expected_revision=1)
    return rule_id


def _operation(trade_date: date, *, side: str = "buy", complete: bool = True) -> dict:
    action_id = "buy-1" if side == "buy" else "sell-1"
    item = {
        "stock_code": "600000.SH",
        "stock_name_snapshot": "浦发银行",
        "side": side,
        "stock_rule_id": "stock-1",
        "action_rule_id": action_id,
        "amount": "10000.00",
        "display_order": 1,
    }
    if complete:
        item.update(
            {
                "price": "10.1234",
                "quantity": "1000",
                "fee": "5.00",
                "operated_at": datetime.combine(trade_date, time(10, 30), tzinfo=SHANGHAI),
            }
        )
    return item


def _partial_operations(trade_date: date) -> list[dict]:
    return [
        dict(_operation(trade_date), compliance_status="complied", display_order=1),
        dict(
            _operation(trade_date, side="sell"),
            compliance_status="breached",
            display_order=2,
        ),
    ]


def _count(pg, table: str, *, owner: str = TEST_OWNER) -> int:
    return int(
        pg.query_df(
            f"SELECT count(*) AS n FROM {table} WHERE tenant_id=%s AND owner_user_id=%s",
            [TEST_TENANT, owner],
        ).iloc[0]["n"]
    )


@pytest.mark.parametrize(
    ("assessment", "no_operation", "reason_kind"),
    [
        ("complied", True, None),
        ("complied", False, None),
        ("breached", True, "builtin"),
        ("breached", False, "custom"),
    ],
)
def test_four_assessment_operation_combinations(pg, market, assessment, no_operation, reason_kind):
    trade_date, _, _ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    payload = {
        "assessment": assessment,
        "no_operation": no_operation,
        "operations": [] if no_operation else [_operation(trade_date)],
        "review_note": "保持复盘\n不覆盖事实",
    }
    if reason_kind == "builtin":
        payload.update(
            reason_code="missed_required_action",
            violation_detail="计划内动作没有执行\n下次设置提醒",
        )
    elif reason_kind == "custom":
        payload.update(
            reason_text="  Ａ计划外  ",
            violation_detail="临时改变计划",
        )

    result = service.submit_checkin(rule_id, trade_date, payload)
    assert int(result["revision_no"]) == 1
    assert result["assessment"] == assessment
    assert bool(result["no_operation"]) is no_operation
    assert len(result["operations"]) == (0 if no_operation else 1)
    assert result["financial_complete"] is True
    if assessment == "breached":
        assert result["reason_name_snapshot"]
        assert result["violation_detail"] == payload["violation_detail"]
    else:
        assert result["reason_name_snapshot"] is None


@pytest.mark.parametrize("operation_status", ["complied", "breached"])
def test_partial_assessment_accepts_single_operation_status(pg, market, operation_status):
    trade_date, _, _ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)

    result = service.submit_checkin(
        rule_id,
        trade_date,
        {
            "assessment": "partial",
            "no_operation": False,
            "reason_code": "unplanned_operation",
            "violation_detail": "整体规则存在偏差，单笔操作单独记录履约状态",
            "operations": [
                dict(
                    _operation(trade_date),
                    compliance_status=operation_status,
                    display_order=1,
                )
            ],
        },
    )

    assert result["assessment"] == "partial"
    assert result["reason_name_snapshot"] == "计划外操作"
    assert [item["compliance_status"] for item in result["operations"]] == [operation_status]
    page = service.list_checkins(assessment="partial")
    assert page["total"] == 1
    assert page["list"][0]["id"] == result["checkin_id"]


@pytest.mark.parametrize(
    ("payload_patch", "message"),
    [
        ({"no_operation": True, "operations": []}, "部分履约必须填写实际操作"),
        ({"operations": []}, "部分履约至少需要一条操作"),
        (
            {
                "operations": [
                    dict(_partial_operations(date(2099, 1, 1))[0], compliance_status=None),
                    _partial_operations(date(2099, 1, 1))[1],
                ]
            },
            "每笔操作都必须选择履约状态",
        ),
    ],
)
def test_partial_assessment_rejects_missing_operation_status(
    pg, market, payload_patch, message
):
    trade_date, _, _ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    operations = payload_patch.get("operations")
    if operations:
        for operation in operations:
            operation["operated_at"] = datetime.combine(
                trade_date, time(10, 30), tzinfo=SHANGHAI
            )
    payload = {
        "assessment": "partial",
        "no_operation": False,
        "reason_code": "unplanned_operation",
        "violation_detail": "部分操作没有履约",
        "operations": _partial_operations(trade_date),
        **payload_patch,
    }
    with pytest.raises(ValidationError, match=message):
        service.submit_checkin(rule_id, trade_date, payload)


def test_non_partial_assessment_rejects_operation_compliance_status(pg, market):
    trade_date, _, _ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    with pytest.raises(ValidationError, match="仅部分履约"):
        service.submit_checkin(
            rule_id,
            trade_date,
            {
                "assessment": "complied",
                "no_operation": False,
                "operations": [
                    dict(_operation(trade_date), compliance_status="complied")
                ],
            },
        )


def test_incomplete_financial_facts_allowed_and_rule_links_enforced(pg, market):
    trade_date, _, _ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    payload = {
        "assessment": "complied",
        "no_operation": False,
        "operations": [_operation(trade_date, complete=False)],
    }
    result = service.submit_checkin(rule_id, trade_date, payload)
    assert result["financial_complete"] is False
    assert result["operations"][0]["financial_complete"] is False

    second_rule = service.create_rule(_rule_payload("第二套纪律"))["id"]
    service.publish_rule(second_rule, expected_revision=1)
    bad = {
        "assessment": "complied",
        "no_operation": False,
        "operations": [dict(_operation(trade_date), action_rule_id="sell-1")],
    }
    with pytest.raises(ValidationError, match="方向错误"):
        service.submit_checkin(second_rule, trade_date, bad)


def test_custom_reason_reused_deleted_and_history_snapshot_retained(pg, market):
    first, second, _ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    first_result = service.submit_checkin(
        rule_id,
        first,
        {
            "assessment": "breached",
            "no_operation": True,
            "reason_text": "  Ａ计划外  ",
            "violation_detail": "第一次说明",
            "operations": [],
        },
    )
    second_result = service.submit_checkin(
        rule_id,
        second,
        {
            "assessment": "breached",
            "no_operation": True,
            "reason_text": "a计划外",
            "violation_detail": "第二次说明",
            "operations": [],
        },
    )
    assert first_result["reason_id"] == second_result["reason_id"]
    assert _count(pg, "trade_discipline_reason") == 1

    reason_id = str(first_result["reason_id"])
    service.delete_reason(reason_id)
    assert all(item.get("id") != reason_id for item in service.list_reasons())
    detail = service.get_revision(str(first_result["checkin_id"]), 1)
    assert detail["reason_name_snapshot"] == "A计划外"
    assert detail["violation_detail"] == "第一次说明"


def test_reason_and_checkin_rollback_together_on_revision_failure(pg, market, monkeypatch):
    trade_date, _, _ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)

    def fail_revision(*args, **kwargs):
        raise ConflictError("注入失败")

    monkeypatch.setattr(service.repo, "insert_revision", fail_revision)
    with pytest.raises(ConflictError, match="注入失败"):
        service.submit_checkin(
            rule_id,
            trade_date,
            {
                "assessment": "breached",
                "no_operation": True,
                "reason_text": "事务内新原因",
                "violation_detail": "必须回滚",
                "operations": [],
            },
        )
    assert _count(pg, "trade_discipline_reason") == 0
    assert _count(pg, "trade_discipline_checkin") == 0
    assert _count(pg, "trade_discipline_checkin_revision") == 0


def test_amendment_keeps_original_version_and_history_is_immutable(pg, market):
    first, _, _ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    initial = service.submit_checkin(
        rule_id,
        first,
        {"assessment": "complied", "no_operation": True, "operations": []},
    )
    draft = service.open_draft(rule_id)
    changed = _rule_payload("履约纪律 v2")
    saved = service.save_draft(rule_id, changed, expected_revision=int(draft["draft_revision"]))
    service.publish_rule(rule_id, expected_revision=int(saved["draft_revision"]))

    amended = service.amend_checkin(
        str(initial["checkin_id"]),
        {
            "assessment": "breached",
            "no_operation": True,
            "reason_code": "other",
            "violation_detail": "修正后仍绑定原版本",
            "operations": [],
        },
        expected_revision=1,
    )
    assert int(amended["revision_no"]) == 2
    assert int(amended["version_no"]) == 1
    assert service.get_revision(str(initial["checkin_id"]), 1)["assessment"] == "complied"
    assert service.get_revision(str(initial["checkin_id"]), 2)["assessment"] == "breached"
    with pytest.raises(ConflictError):
        service.amend_checkin(
            str(initial["checkin_id"]),
            {"assessment": "complied", "no_operation": True, "operations": []},
            expected_revision=1,
        )


def test_quick_no_operation_is_idempotent_under_concurrency(pg, market):
    trade_date, _, _ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    pending = service.summary(trade_date)
    assert pending["total"] == pending["pending"] == 1
    assert pending["completed"] == 0

    def submit_once():
        return _service(pg, market).quick_no_operation(rule_id, trade_date)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit_once(), range(2)))
    assert sorted(result["idempotent"] for result in results) == [False, True]
    assert len({result["checkin_id"] for result in results}) == 1
    assert _count(pg, "trade_discipline_checkin") == 1
    summary = service.summary(trade_date)
    assert summary["total"] == summary["completed"] == 1
    assert summary["pending"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"assessment": "complied", "no_operation": True, "operations": []},
        {
            "assessment": "breached",
            "no_operation": True,
            "reason_code": "other",
            "violation_detail": "普通入口记录为未履约",
            "operations": [],
        },
        {
            "assessment": "complied",
            "no_operation": False,
            "operations": ["operation"],
        },
    ],
)
def test_quick_no_operation_conflicts_with_existing_workbench_record(pg, market, payload):
    trade_date, _, _ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    actual = dict(payload)
    if actual["operations"] == ["operation"]:
        actual["operations"] = [_operation(trade_date)]
    existing = service.submit_checkin(rule_id, trade_date, actual)

    with pytest.raises(ConflictError, match="已有正式记录") as raised:
        service.quick_no_operation(rule_id, trade_date)
    assert raised.value.data == {
        "checkin_id": existing["checkin_id"],
        "rule_id": rule_id,
        "trade_date": str(trade_date),
    }


def test_quick_no_operation_conflicts_after_quick_record_was_amended(pg, market):
    trade_date, _, _ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    quick = service.quick_no_operation(rule_id, trade_date)
    service.amend_checkin(
        quick["checkin_id"],
        {
            "assessment": "breached",
            "no_operation": True,
            "reason_code": "other",
            "violation_detail": "快捷记录已被修正",
            "operations": [],
        },
        expected_revision=1,
    )

    with pytest.raises(ConflictError, match="已有正式记录"):
        service.quick_no_operation(rule_id, trade_date)


def test_operation_rejects_unknown_stock_code_in_one_batch(pg, market):
    trade_date, _, _ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    operation = _operation(trade_date)
    operation["stock_code"] = "999999.SZ"
    with pytest.raises(ValidationError, match="股票代码不存在：999999.SZ"):
        service.submit_checkin(
            rule_id,
            trade_date,
            {"assessment": "complied", "no_operation": False, "operations": [operation]},
        )


def test_operation_enforces_point_in_time_stock_lifecycle_and_server_name(pg, market):
    trade_date, _, _ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)

    market.execute(
        "UPDATE stock_basic SET list_date=?,delist_date=?,name='服务端名称' WHERE code='600000.SH'",
        [trade_date - timedelta(days=1), trade_date + timedelta(days=1)],
    )
    operation = _operation(trade_date)
    operation.pop("stock_name_snapshot")
    submitted = service.submit_checkin(
        rule_id,
        trade_date,
        {"assessment": "complied", "no_operation": False, "operations": [operation]},
    )
    assert submitted["operations"][0]["stock_name_snapshot"] == "服务端名称"


@pytest.mark.parametrize(
    ("list_date_offset", "delist_date_offset", "message"),
    [
        (1, None, "履约日期尚未上市：600000.SH"),
        (-1, 0, "履约日期已经退市：600000.SH"),
        (-2, -1, "履约日期已经退市：600000.SH"),
    ],
)
def test_operation_rejects_stock_outside_point_in_time_lifecycle(
    pg,
    market,
    list_date_offset,
    delist_date_offset,
    message,
):
    trade_date, _, _ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    list_date = trade_date + timedelta(days=list_date_offset)
    delist_date = (
        None if delist_date_offset is None else trade_date + timedelta(days=delist_date_offset)
    )
    market.execute(
        "UPDATE stock_basic SET list_date=?,delist_date=? WHERE code='600000.SH'",
        [list_date, delist_date],
    )
    with pytest.raises(ValidationError, match=message):
        service.submit_checkin(
            rule_id,
            trade_date,
            {
                "assessment": "complied",
                "no_operation": False,
                "operations": [_operation(trade_date)],
            },
        )


def test_multiple_operations_validate_stock_codes_with_one_market_query(pg, market, monkeypatch):
    trade_date, _, _ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    stock_queries = 0
    original = market.query_df

    def counted(sql, params=None):
        nonlocal stock_queries
        if "FROM stock_basic" in sql:
            stock_queries += 1
        return original(sql, params)

    monkeypatch.setattr(market, "query_df", counted)
    first = _operation(trade_date)
    second = _operation(trade_date, side="sell")
    second["display_order"] = 2
    service.submit_checkin(
        rule_id,
        trade_date,
        {
            "assessment": "complied",
            "no_operation": False,
            "operations": [first, second],
        },
    )
    assert stock_queries == 1


def test_history_filters_pagination_and_owner_isolation(pg, market):
    first, second, _ = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    service.submit_checkin(
        rule_id,
        first,
        {"assessment": "complied", "no_operation": True, "operations": []},
    )
    breached = service.submit_checkin(
        rule_id,
        second,
        {
            "assessment": "breached",
            "no_operation": False,
            "reason_code": "unplanned_operation",
            "violation_detail": "计划外交易",
            "operations": [_operation(second, side="sell")],
        },
    )
    page = service.list_checkins(
        assessment="breached",
        no_operation=False,
        stock="浦发",
        reason="计划外",
        page=1,
        page_size=1,
    )
    assert page["total"] == 1
    assert page["list"][0]["id"] == breached["checkin_id"]
    assert int(page["list"][0]["operation_count"]) == 1
    assert page["list"][0]["amended_at"] is None
    assert '"amended_at":null' in ApiResponse(data=page).model_dump_json()

    ascending = service.list_checkins(sort_by="trade_date", sort_order="asc")
    assert [row["trade_date"] for row in ascending["list"]] == [first, second]
    with pytest.raises(ValidationError, match="排序字段"):
        service.list_checkins(sort_by="updated_at")
    with pytest.raises(ValidationError, match="排序方向"):
        service.list_checkins(sort_order="sideways")

    other_owner = f"{TEST_OWNER}_t3_other"
    clean_owner(pg, TEST_TENANT, other_owner)
    try:
        other = _service(pg, market, owner=other_owner)
        assert other.list_checkins()["total"] == 0
        with pytest.raises(NotFoundError):
            other.get_revision(str(breached["checkin_id"]), 1)
    finally:
        clean_owner(pg, TEST_TENANT, other_owner)


def test_invalid_date_assessment_reason_operation_time_and_negative_value(pg, market):
    first, _, third = _seed_market(market)
    service = _service(pg, market)
    rule_id = _published_rule(service)
    invalid_date = third + timedelta(days=10)
    with pytest.raises(ValidationError, match="已有行情交易日"):
        service.quick_no_operation(rule_id, invalid_date)
    with pytest.raises(ValidationError, match="详细说明"):
        service.submit_checkin(
            rule_id,
            first,
            {
                "assessment": "breached",
                "no_operation": True,
                "reason_code": "other",
                "violation_detail": "  ",
                "operations": [],
            },
        )
    with pytest.raises(ValidationError, match="单个文本"):
        service.submit_checkin(
            rule_id,
            first,
            {
                "assessment": "breached",
                "no_operation": True,
                "reason_text": ["其他", "冲动交易"],
                "violation_detail": "原因格式非法",
                "operations": [],
            },
        )
    with pytest.raises(ValidationError, match="只能选择一个原因"):
        service.submit_checkin(
            rule_id,
            first,
            {
                "assessment": "breached",
                "no_operation": True,
                "reason_code": "other",
                "reason_text": "另一个原因",
                "violation_detail": "不能多选",
                "operations": [],
            },
        )
    wrong_time = _operation(first)
    wrong_time["operated_at"] = datetime.combine(
        first + timedelta(days=1), time(10), tzinfo=SHANGHAI
    )
    with pytest.raises(ValidationError, match="履约交易日"):
        service.submit_checkin(
            rule_id,
            first,
            {"assessment": "complied", "no_operation": False, "operations": [wrong_time]},
        )
    negative = _operation(first)
    negative["fee"] = "-0.01"
    with pytest.raises(ValidationError, match="不能为负数"):
        service.submit_checkin(
            rule_id,
            first,
            {"assessment": "complied", "no_operation": False, "operations": [negative]},
        )
