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
