"""新账户日结入口的真实鉴权、归属与持久化契约。"""

from uuid import uuid4

from backend.tests.test_trade_discipline_t3 import _seed_market
from backend.tests.test_trade_discipline_t4 import (
    _auth,
    _make_user,
    _remove_user,
    client,  # noqa: F401 -- 复用真实鉴权 pytest 夹具。
)


def test_ledger_api_actual_record_and_private_read(client, pg, market, monkeypatch):  # noqa: F811
    dates = _seed_market(market)
    monkeypatch.setattr("backend.services.trade_discipline_service.get_client", lambda: market)
    identity = _make_user(pg, ["trade-discipline:view", "trade-discipline:checkin-view", "trade-discipline:checkin-submit"])
    readonly = _make_user(pg, ["trade-discipline:view", "trade-discipline:checkin-view"])
    headers = _auth(identity[0], identity[1])
    target = str(dates[0])
    try:
        response = client.get("/api/trade-discipline/ledger", params={"trade_date": target}, headers=headers)
        assert response.status_code == 200
        assert response.json()["data"]["initialized_on"] is None
        initialized = client.post("/api/trade-discipline/ledger/initialize", json={
            "trade_date": target, "expected_revision": 0, "positions": [
                {"stock_code": "600000.SH", "quantity": "3", "cost_price": "10.1234"},
            ], "cash": "10000",
        }, headers=headers)
        assert initialized.status_code == 200, initialized.text
        assert initialized.json()["data"]["opening_positions"][0]["cost"] == "30.37"
        invalid = client.post("/api/trade-discipline/ledger/days", json={
            "trade_date": target, "request_id": uuid4().hex, "expected_account_revision": 1,
            "expected_revision": 0, "events": [{"event_id": "invalid-cash", "kind": "cash",
                "adjustment_type": "deposit", "direction": "in", "amount": "50", "note": "测试入金",
                "display_order": 1, "operated_at": f"{target}T10:00:00+08:00",
                "rule_checks": [{"rule_id": "r", "stock_rule_id": "s", "action_rule_id": "a"}]}],
        }, headers=headers)
        assert invalid.status_code == 422, invalid.text
        payload = {"trade_date": target, "request_id": uuid4().hex, "expected_account_revision": 1,
                   "expected_revision": 0, "events": [{"event_id": "actual-fill", "stock_code": "600000.SH",
                   "side": "buy", "price": "10", "quantity": "100", "fee": "0",
                   "display_order": 1, "operated_at": f"{target}T10:00:00+08:00"}]}
        submitted = client.post("/api/trade-discipline/ledger/days", json=payload, headers=headers)
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["data"]["assessment"] == "breached"
        assert submitted.json()["data"]["positions"][0]["quantity"] == "103"
        assert submitted.json()["data"]["positions"][0]["cost"] == "1030.37"
        assert client.post("/api/trade-discipline/ledger/days", json=payload, headers=headers).json()["data"]["idempotent"]
        history = client.get("/api/trade-discipline/ledger/history", params={"assessment": "breached"}, headers=headers)
        assert history.json()["data"]["total"] == 1
        assert history.json()["data"]["list"][0]["snapshot"]["operation_count"] == 1
        assert history.json()["data"]["list"][0]["snapshot"]["events"] == []
        foreign = _auth(readonly[0], readonly[1])
        assert client.get("/api/trade-discipline/ledger/history", headers=foreign).json()["data"]["total"] == 0
        assert client.get(f"/api/trade-discipline/ledger/revisions/{target}/1", headers=foreign).status_code == 404
        assert client.post("/api/trade-discipline/ledger/days", json=payload, headers=foreign).status_code == 403
        assert client.post("/api/trade-discipline/checkins", json={
            "rule_id": "legacy", "trade_date": target, "assessment": "complied", "no_operation": True,
        }, headers=headers).status_code == 422
    finally:
        _remove_user(pg, identity)
        _remove_user(pg, readonly)


def test_financial_report_restriction_api_persistence_evaluation_and_private_scope(client, pg, market, monkeypatch):  # noqa: F811
    from datetime import date

    from backend.tests.test_trade_discipline_t3 import _rule_payload

    target = date(2027, 8, 2)
    market.execute("INSERT INTO stock_basic(code,name,board) VALUES ('600000.SH','测试股票','主板')")
    market.execute("INSERT INTO trade_calendar VALUES (?, TRUE)", [target])
    market.execute("INSERT INTO daily_bar(code,trade_date) VALUES ('600000.SH', ?)", [target])
    monkeypatch.setattr("backend.services.trade_discipline_service.get_client", lambda: market)
    owner = _make_user(pg, ["trade-discipline:view", "trade-discipline:rule-manage",
                            "trade-discipline:checkin-view", "trade-discipline:checkin-submit"])
    reader = _make_user(pg, ["trade-discipline:view", "trade-discipline:checkin-view"])
    headers, other_headers = _auth(owner[0], owner[1]), _auth(reader[0], reader[1])
    try:
        payload = dict(_rule_payload(), restrict_financial_report_months=True)
        invalid = client.post("/api/trade-discipline/rules", json=dict(payload, restrict_financial_report_months="true"), headers=headers)
        assert invalid.status_code == 422
        created = client.post("/api/trade-discipline/rules", json=payload, headers=headers)
        assert created.status_code == 200, created.text
        rid = created.json()["data"]["id"]
        path = f"/api/trade-discipline/rules/{rid}"
        loaded = client.get(path, headers=headers)
        assert loaded.json()["data"]["draft"]["restrict_financial_report_months"] is True
        assert client.get(path, headers=other_headers).status_code == 404
        assert client.put(f"{path}/draft", json=dict(payload, expected_revision=1), headers=other_headers).status_code == 403
        published = client.post(f"{path}/publish", json={"expected_revision": 1}, headers=headers)
        assert published.status_code == 200, published.text
        assert published.json()["data"]["effective_from_trade_date"] == target.isoformat()
        assert client.get(path, headers=headers).json()["data"]["latest_version"]["restrict_financial_report_months"] is True
        initialized = client.post("/api/trade-discipline/ledger/initialize", json={
            "trade_date": str(target), "expected_revision": 0, "cash": None,
            "positions": [{"stock_code": "600000.SH", "quantity": "100", "rule_id": rid,
                           "stock_rule_id": "stock-1"}],
        }, headers=headers)
        assert initialized.status_code == 200, initialized.text
        content = {"trade_date": str(target), "request_id": uuid4().hex,
                   "expected_account_revision": 1, "expected_revision": 0,
                   "events": [], "omissions": []}
        preview = client.post("/api/trade-discipline/ledger/preview", json=content, headers=headers)
        saved = client.post("/api/trade-discipline/ledger/days", json=content, headers=headers)
        assert preview.status_code == saved.status_code == 200, (preview.text, saved.text)
        result = saved.json()["data"]
        assert result["assessment"] == "breached"
        assert result["rules"][0]["restrict_financial_report_months"] is True
        assert result["evaluations"] == preview.json()["data"]["evaluations"]
        assert "禁持" in result["evaluations"][0]["issues"][0]
        assert client.post("/api/trade-discipline/ledger/days", json=content, headers=headers).json()["data"]["idempotent"]
        quick = client.post("/api/trade-discipline/checkins/quick-no-operation", json={"rule_id": rid, "trade_date": str(target)}, headers=headers)
        assert quick.status_code == 409
        assert client.get("/api/trade-discipline/ledger/history", headers=other_headers).json()["data"]["total"] == 0
    finally:
        _remove_user(pg, owner)
        _remove_user(pg, reader)
