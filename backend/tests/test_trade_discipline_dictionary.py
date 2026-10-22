"""使用随机全局字典和临时业务归属验证字典到历史的完整消费。"""

from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from backend.common.exceptions import NotFoundError, ValidationError
from backend.services import trade_discipline_dictionary as dictionaries
from backend.services import trade_discipline_service as services
from backend.storage.dict_repository import DictRepository
from backend.tests.conftest import TEST_OWNER, TEST_TENANT
from backend.tests.test_trade_discipline_t3 import _operation, _rule_payload, _seed_market, _service
from backend.tests.test_trade_discipline_t4 import _auth, _make_user, _remove_user
from backend.tests.test_trade_discipline_t4 import client as client  # noqa: PLC0414


@pytest.fixture
def dictionary(pg, monkeypatch):
    repo = DictRepository(pg)
    codes = {}
    for name in ("BUY_TYPES", "SELL_TYPES", "CONDITION_CATEGORIES"):
        code = f"pytest_td_{uuid4().hex}"
        repo.create_type(code=code, name=name, sort=100, enabled=True, remark=None)
        monkeypatch.setattr(dictionaries, name, code)
        if hasattr(services, name):
            monkeypatch.setattr(services, name, code)
        codes[name] = code

    def add(kind, code, label, enabled=True):
        return repo.create_item(
            type_code=codes[kind],
            code=code,
            label=label,
            enabled=enabled,
            sort=10,
            color=None,
            remark=None,
        )

    add("BUY_TYPES", "open_position", "建仓")
    add("BUY_TYPES", "pullback", "趋势回踩")
    add("SELL_TYPES", "liquidate", "清仓")
    add("CONDITION_CATEGORIES", "technical", "技术形态")
    add("CONDITION_CATEGORIES", "fundamental", "基本面")
    try:
        yield repo, codes, add
    finally:
        for code in codes.values():
            pg.execute("DELETE FROM dict_item WHERE type_code=%s", [code])
            pg.execute("DELETE FROM dict_type WHERE code=%s", [code])


def payload():
    value = _rule_payload()
    value["action_rules"][0]["action_subtype"] = "pullback"
    value["action_rules"][0]["action_subtype_label"] = "伪造类型名"
    value["stock_rules"][0]["checklist_items"] = [
        {
            "item_id": "earnings",
            "category": "fundamental",
            "category_label": "伪造分类名",
            "text": "业绩持续增长",
            "display_order": 1,
        }
    ]
    return value


def test_dictionary_snapshot_publish_checkin_amend_copy_and_isolation(pg, market, dictionary):
    repo, codes, _ = dictionary
    trade_date, *_ = _seed_market(market)
    service = _service(pg, market)
    rule_id = service.create_rule(payload())["id"]
    service.publish_rule(rule_id, expected_revision=1)
    version = service.repo.load_version(rule_id, 1)
    assert version["action_rules"][0]["action_subtype_label"] == "趋势回踩"
    assert version["stock_rules"][0]["checklist_items"][0]["category_label"] == "基本面"
    repo.update_item(
        codes["BUY_TYPES"],
        "pullback",
        label="回踩新版",
        enabled=False,
        sort=20,
        color=None,
        remark=None,
    )
    repo.delete_item(codes["CONDITION_CATEGORIES"], "fundamental")
    draft = service.open_draft(rule_id)
    draft["action_rules"][0]["action_subtype_label"] = "再次伪造"
    draft["stock_rules"][0]["checklist_items"][0]["category_label"] = "再次伪造"
    saved = service.save_draft(rule_id, draft, expected_revision=1)
    assert saved["action_rules"][0]["action_subtype_label"] == "趋势回踩"
    assert saved["stock_rules"][0]["checklist_items"][0]["category_label"] == "基本面"
    assert service.publish_rule(rule_id, expected_revision=2)["changed"] is False
    copied = service.copy_rule(rule_id)
    assert copied["draft"]["action_rules"][0]["action_subtype_label"] == "趋势回踩"
    copied_item = copied["draft"]["stock_rules"][0]["checklist_items"][0]
    assert copied_item["item_id"] != "earnings" and copied_item["category_label"] == "基本面"
    operation = _operation(trade_date, complete=False)
    operation["checklist_results"] = [{"item_id": "earnings", "status": "unknown"}]
    body = {"assessment": "complied", "no_operation": False, "operations": [operation]}
    checkin = service.submit_checkin(rule_id, trade_date, body)
    revised = service.amend_checkin(
        checkin["checkin_id"],
        {**body, "amendment_reason": "补充说明", "note": "核对说明"},
        expected_revision=1,
    )
    revised = service.get_revision(checkin["checkin_id"], revised["revision_no"])
    assert (
        revised["rule_version"]["stock_rules"][0]["checklist_items"][0]["category_label"]
        == "基本面"
    )
    assert service.get_revision(checkin["checkin_id"], 1)["rule_version"] == version
    with pytest.raises(NotFoundError):
        _service(pg, market, owner="other_owner").get_rule(rule_id)
    assert service.repo.list_action_subtypes() == []


@pytest.mark.parametrize("target", ["type", "category", "side", "disabled", "reserved"])
def test_new_reference_must_be_enabled_and_belong_to_dictionary(pg, market, dictionary, target):
    repo, codes, _ = dictionary
    value = payload()
    if target == "type":
        value["action_rules"][0]["action_subtype"] = "not_registered"
    if target == "category":
        value["stock_rules"][0]["checklist_items"][0]["category"] = "not_registered"
    if target == "side":
        value["action_rules"][0]["action_subtype"] = "liquidate"
    if target == "reserved":
        value["stock_rules"][0]["checklist_items"][0]["category"] = "notes"
    if target == "disabled":
        repo.update_type(codes["BUY_TYPES"], name="已停用", enabled=False, sort=100, remark=None)
    with pytest.raises(ValidationError):
        _service(pg, market).create_rule(value)


def test_dictionary_codes_can_be_shared_between_directions(pg, market, dictionary):
    _, _, add = dictionary
    add("SELL_TYPES", "pullback", "回踩卖出")
    value = payload()
    value["action_rules"][1]["action_subtype"] = "pullback"
    draft = _service(pg, market).create_rule(value)["draft"]
    assert [row["action_subtype_label"] for row in draft["action_rules"]] == [
        "趋势回踩",
        "回踩卖出",
    ]


def test_legacy_category_kept_only_for_its_original_item(pg, market, dictionary):
    service = _service(pg, market)
    rule_id = service.create_rule(_rule_payload())["id"]
    old = [
        {
            "item_id": "old",
            "category": "retired",
            "category_label": "旧分类",
            "text": "旧条件",
            "display_order": 1,
        }
    ]
    pg.execute(
        "UPDATE trade_discipline_draft_stock_rule SET checklist_items=%s WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s",
        [Jsonb(old), TEST_TENANT, TEST_OWNER, rule_id],
    )
    draft = service.repo.load_draft(rule_id)
    saved = service.save_draft(rule_id, draft, expected_revision=1)
    assert saved["stock_rules"][0]["checklist_items"] == old
    draft["stock_rules"][0]["checklist_items"][0]["item_id"] = "new"
    with pytest.raises(ValidationError, match="分类"):
        service.save_draft(rule_id, draft, expected_revision=2)


def test_authorized_api_consumes_new_dictionary_and_rejects_bypass(
    client, pg, market, dictionary, monkeypatch
):
    from backend.storage.trade_discipline_repository import TradeDisciplineRepository

    _seed_market(market)
    identity = _make_user(pg, ["trade-discipline:view", "trade-discipline:rule-manage"])
    headers = _auth(identity[0], identity[1])
    monkeypatch.setattr(
        "backend.api.trade_discipline._service",
        lambda: services.TradeDisciplineService(TradeDisciplineRepository(pg), market),
    )
    try:
        invalid = payload()
        invalid["stock_rules"][0]["checklist_items"][0]["category"] = "unregistered"
        assert (
            client.post("/api/trade-discipline/rules", headers=headers, json=invalid).status_code
            == 422
        )
        created = client.post("/api/trade-discipline/rules", headers=headers, json=payload())
        assert created.status_code == 200, created.text
        value = created.json()["data"]
        assert value["draft"]["action_rules"][0]["action_subtype_label"] == "趋势回踩"
        assert value["draft"]["stock_rules"][0]["checklist_items"][0]["category_label"] == "基本面"
        # 有交易规则管理权限也不能把个人输入写到共享字典。
        forbidden = client.post(
            "/api/dict/items",
            headers=headers,
            json={"type_code": dictionary[1]["BUY_TYPES"], "code": "forged", "label": "越权新增"},
        )
        assert forbidden.status_code == 403
    finally:
        _remove_user(pg, identity)


def test_public_dictionary_respects_disabled_type_and_returns_complete_candidates(pg, dictionary):
    from backend.services.dict_service import DictService

    repo, codes, _ = dictionary
    kind = codes["CONDITION_CATEGORIES"]
    with pg.transaction() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO dict_item (id,type_code,code,label) VALUES (%s,%s,%s,%s)",
            [
                (f"{kind}:{index}", kind, f"scale_{index}", f"条件分类{index}")
                for index in range(501)
            ],
        )
    assert len(DictService(repo).get_enabled_items(kind)["items"]) == 503
    repo.update_type(kind, name="停用分类", enabled=False, sort=100, remark=None)
    result = DictService(repo).get_enabled_items(kind)
    assert result["fallback"] is False and result["items"] == []


@pytest.mark.parametrize("code", ["notes", "other"])
def test_reserved_category_dictionary_codes_cannot_be_created(pg, code):
    from backend.services.dict_service import DictService

    with pytest.raises(ValidationError, match="保留编码"):
        DictService(DictRepository(pg)).create_item(
            type_code="trade_discipline_condition_category", code=code, label="保留分类"
        )


def test_hydrating_legacy_names_does_not_publish_an_extra_version(pg, market, dictionary):
    _seed_market(market)
    service = _service(pg, market)
    value = _rule_payload()
    value["stock_rules"][0]["checklist_items"] = [
        {
            "item_id": "legacy",
            "category": "technical",
            "text": "旧条件",
            "display_order": 1,
        }
    ]
    rule_id = service.create_rule(value)["id"]
    service.publish_rule(rule_id, expected_revision=1)
    pg.execute(
        "UPDATE trade_discipline_action_rule SET action_subtype_label=NULL WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s",
        [TEST_TENANT, TEST_OWNER, rule_id],
    )
    pg.execute(
        "UPDATE trade_discipline_stock_rule SET checklist_items=%s WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s",
        [Jsonb(value["stock_rules"][0]["checklist_items"]), TEST_TENANT, TEST_OWNER, rule_id],
    )
    draft = service.open_draft(rule_id)
    service.save_draft(rule_id, draft, expected_revision=1)
    assert service.publish_rule(rule_id, expected_revision=2)["changed"] is False
    assert service.repo.load_version(rule_id, 1)["action_rules"][0]["action_subtype_label"] is None
