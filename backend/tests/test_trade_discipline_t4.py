"""T4：交易纪律 API 契约、权限、股票搜索与归属隔离。"""

from __future__ import annotations

import uuid
from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.tests.conftest import clean_owner

_SECRET = "pytest-trade-discipline-t4-0123456789abcdef"
_HTTP_VERBS = {"GET", "POST", "PUT", "DELETE"}


@pytest.fixture()
def client(monkeypatch, pg, redis_cli):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.main import create_app

    return TestClient(create_app())


def _auth(user_id: str, tenant_id: str) -> dict[str, str]:
    from backend.auth.jwt_tokens import issue_access

    return {"Authorization": "Bearer " + issue_access(user_id, tenant_id, 0)}


def _make_user(pg, codes: list[str]) -> tuple[str, str, str]:
    suffix = uuid.uuid4().hex[:10]
    tenant_id = f"tdt4_t_{suffix}"
    user_id = f"tdt4_u_{suffix}"
    role_id = f"tdt4_r_{suffix}"
    pg.execute(
        "INSERT INTO sys_tenant (id,name,status) VALUES (%s,%s,'active')",
        [tenant_id, tenant_id],
    )
    pg.execute(
        "INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
        "VALUES (%s,%s,%s,'normal',0,'active')",
        [user_id, tenant_id, user_id],
    )
    pg.execute(
        "INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
        "VALUES (%s,%s,%s,'custom',FALSE,FALSE)",
        [role_id, role_id, role_id],
    )
    pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)", [user_id, role_id])
    for code in codes:
        pg.execute(
            "INSERT INTO sys_role_resource (role_id,resource_id) VALUES (%s,%s)",
            [role_id, code],
        )
    return user_id, tenant_id, role_id


def _remove_user(pg, identity: tuple[str, str, str]) -> None:
    user_id, tenant_id, role_id = identity
    clean_owner(pg, tenant_id, user_id)
    pg.execute("DELETE FROM sys_user WHERE id=%s", [user_id])
    pg.execute("DELETE FROM sys_role WHERE id=%s", [role_id])
    pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tenant_id])


def _route_codes(route) -> set[str]:
    return {
        dependency.call.resource_code
        for dependency in route.dependant.dependencies
        if hasattr(dependency.call, "resource_code")
    }


def test_trade_discipline_routes_are_openapi_visible_and_precisely_guarded(client):
    expected = {
        "/api/trade-discipline/summary": {
            "trade-discipline:view",
            "trade-discipline:checkin-view",
        },
        "/api/trade-discipline/stock-options": {"trade-discipline:checkin-submit"},
    }
    found: dict[str, set[str]] = {}
    for route in client.app.routes:
        path = getattr(route, "path", "")
        methods = (getattr(route, "methods", set()) or set()) & _HTTP_VERBS
        if path.startswith("/api/trade-discipline") and methods:
            codes = _route_codes(route)
            assert codes, f"交易纪律路由缺少精确权限守卫: {path}"
            found[path] = codes
    assert expected.items() <= found.items()
    assert set(found) <= set(client.app.openapi()["paths"])


def test_permission_matrix_and_dedicated_stock_search(client, pg, market, monkeypatch):
    market.execute(
        "INSERT INTO stock_basic (code,name,board,industry,delist_date) VALUES "
        "('000001.SZ','平安银行','主板','银行',NULL),"
        "('000002.SZ','已退市样本','主板','地产','2025-01-01')"
    )
    monkeypatch.setattr("backend.api.trade_discipline.get_client", lambda: market)

    viewer = _make_user(pg, ["trade-discipline:view"])
    dual_viewer = _make_user(
        pg,
        ["trade-discipline:view", "trade-discipline:checkin-view"],
    )
    submitter = _make_user(pg, ["trade-discipline:checkin-submit"])
    try:
        assert client.get("/api/trade-discipline/rules").status_code == 401
        assert client.get(
            "/api/trade-discipline/summary?trade_date=2025-01-02",
            headers=_auth(viewer[0], viewer[1]),
        ).status_code == 403
        summary = client.get(
            "/api/trade-discipline/summary?trade_date=2025-01-02",
            headers=_auth(dual_viewer[0], dual_viewer[1]),
        )
        assert summary.status_code not in (401, 403)  # 已通过摘要所需的双权限守卫

        search = client.get(
            "/api/trade-discipline/stock-options?q=平安&limit=20",
            headers=_auth(submitter[0], submitter[1]),
        )
        assert search.status_code == 200
        assert search.json()["data"]["list"] == [
            {"code": "000001.SZ", "name": "平安银行", "board": "主板", "industry": "银行"}
        ]
        assert client.get(
            "/api/stocks",
            headers=_auth(submitter[0], submitter[1]),
        ).status_code == 403
        assert client.get(
            "/api/trade-discipline/stock-options?q=%20%20",
            headers=_auth(submitter[0], submitter[1]),
        ).status_code == 422
        assert client.get(
            "/api/trade-discipline/stock-options?q=平安&limit=21",
            headers=_auth(submitter[0], submitter[1]),
        ).status_code == 422
    finally:
        _remove_user(pg, viewer)
        _remove_user(pg, dual_viewer)
        _remove_user(pg, submitter)


def test_api_status_mapping_owner_isolation_conflict_and_forbidden_fields(client, pg):
    manager = _make_user(
        pg,
        ["trade-discipline:view", "trade-discipline:rule-manage"],
    )
    outsider = _make_user(pg, ["trade-discipline:view"])
    try:
        headers = _auth(manager[0], manager[1])
        forbidden = client.post(
            "/api/trade-discipline/rules",
            headers=headers,
            json={"tenant_id": "other"},
        )
        assert forbidden.status_code == 422

        created = client.post(
            "/api/trade-discipline/rules",
            headers=headers,
            json={"name": "T4 接口规则", "capital": "100000", "stock_rules": [], "action_rules": []},
        )
        assert created.status_code == 200
        rule_id = created.json()["data"]["id"]

        hidden = client.get(
            f"/api/trade-discipline/rules/{rule_id}",
            headers=_auth(outsider[0], outsider[1]),
        )
        assert hidden.status_code == 404 and hidden.json()["code"] == 4004

        conflict = client.post(
            f"/api/trade-discipline/rules/{rule_id}/publish",
            headers=headers,
            json={"expected_revision": 2},
        )
        assert conflict.status_code == 409 and conflict.json()["code"] == 4090

        audit = pg.query_df(
            "SELECT action,target_id,context FROM audit_log WHERE event_category='business' "
            "AND event_type='trade_discipline' AND target_id=%s ORDER BY event_time DESC",
            [rule_id],
        )
        assert "rule_create" in set(audit["action"])
        serialized = " ".join(str(value) for value in audit["context"])
        assert "T4 接口规则" not in serialized and "100000" not in serialized
    finally:
        _remove_user(pg, manager)
        _remove_user(pg, outsider)


def test_all_trade_discipline_endpoint_contracts_return_unified_response(
    client, pg, monkeypatch
):
    class StubMarket:
        @staticmethod
        def query_df(sql, params=None):
            return pd.DataFrame({"trade_date": [date(2025, 1, 2)]})

    class StubService:
        market = StubMarket()

        @staticmethod
        def _rule(rule_id="tdr_stub"):
            return {"id": rule_id, "status": "unpublished", "latest_version_no": None}

        def summary(self, trade_date):
            return {"trade_date": trade_date, "total": 0, "completed": 0, "pending": 0, "rules": []}

        def list_rules(self):
            return [self._rule()]

        def create_rule(self, payload=None):
            return self._rule()

        def get_rule(self, rule_id):
            return self._rule(rule_id)

        def effective_version(self, rule_id, trade_date):
            return None

        def open_draft(self, rule_id):
            return {"rule_id": rule_id, "draft_revision": 1}

        def save_draft(self, rule_id, payload, expected_revision):
            return {"rule_id": rule_id, "draft_revision": expected_revision + 1}

        def discard_draft(self, rule_id):
            return self._rule(rule_id)

        def publish_rule(self, rule_id, expected_revision):
            return {"rule_id": rule_id, "version_no": 1}

        def archive_rule(self, rule_id):
            return {"rule_id": rule_id, "event_type": "archive"}

        def restore_rule(self, rule_id):
            return {"rule_id": rule_id, "event_type": "restore"}

        def copy_rule(self, rule_id, source):
            return self._rule("tdr_copy")

        def delete_rule(self, rule_id):
            return None

        def get_checkin_context(self, rule_id, trade_date):
            return {"rule_id": rule_id, "trade_date": trade_date, "checkin": None}

        def submit_checkin(self, rule_id, trade_date, payload):
            return {"checkin_id": "tdc_stub", "revision_no": 1}

        def quick_no_operation(self, rule_id, trade_date):
            return {"checkin_id": "tdc_stub", "revision_no": 1, "idempotent": False}

        def amend_checkin(self, checkin_id, payload, expected_revision):
            return {"checkin_id": checkin_id, "revision_no": expected_revision + 1}

        def list_checkins(self, **filters):
            return {"total": 0, "page": 1, "page_size": 20, "list": []}

        def get_revision(self, checkin_id, revision_no):
            return {"checkin_id": checkin_id, "revision_no": revision_no}

        def list_reasons(self):
            return []

        def delete_reason(self, reason_id):
            return None

    stub = StubService()
    monkeypatch.setattr("backend.api.trade_discipline._service", lambda: stub)
    identity = _make_user(
        pg,
        [
            "trade-discipline:view",
            "trade-discipline:rule-manage",
            "trade-discipline:checkin-view",
            "trade-discipline:checkin-submit",
        ],
    )
    headers = _auth(identity[0], identity[1])
    draft = {
        "name": "接口契约",
        "capital": "100000",
        "stock_rules": [],
        "action_rules": [],
    }
    checkin = {
        "assessment": "complied",
        "no_operation": True,
        "operations": [],
    }
    calls = [
        ("GET", "/api/trade-discipline/summary?trade_date=2025-01-02", None),
        ("GET", "/api/trade-discipline/rules?trade_date=2025-01-02", None),
        ("POST", "/api/trade-discipline/rules", draft),
        ("GET", "/api/trade-discipline/rules/tdr_stub?trade_date=2025-01-02", None),
        ("POST", "/api/trade-discipline/rules/tdr_stub/draft/open", None),
        ("PUT", "/api/trade-discipline/rules/tdr_stub/draft", {**draft, "expected_revision": 1}),
        ("DELETE", "/api/trade-discipline/rules/tdr_stub/draft", None),
        ("POST", "/api/trade-discipline/rules/tdr_stub/publish", {"expected_revision": 1}),
        ("POST", "/api/trade-discipline/rules/tdr_stub/archive", None),
        ("POST", "/api/trade-discipline/rules/tdr_stub/restore", None),
        ("POST", "/api/trade-discipline/rules/tdr_stub/copy", {"source": "published"}),
        ("DELETE", "/api/trade-discipline/rules/tdr_stub", None),
        ("GET", "/api/trade-discipline/checkins/current?rule_id=tdr_stub&trade_date=2025-01-02", None),
        ("POST", "/api/trade-discipline/checkins", {**checkin, "rule_id": "tdr_stub", "trade_date": "2025-01-02"}),
        ("POST", "/api/trade-discipline/checkins/quick-no-operation", {"rule_id": "tdr_stub", "trade_date": "2025-01-02"}),
        ("POST", "/api/trade-discipline/checkins/tdc_stub/amendments", {**checkin, "expected_revision": 1}),
        ("GET", "/api/trade-discipline/checkins?page=1&page_size=20", None),
        ("GET", "/api/trade-discipline/checkins/tdc_stub/revisions/1", None),
        ("GET", "/api/trade-discipline/reasons", None),
        ("DELETE", "/api/trade-discipline/reasons/tdreason_stub", None),
    ]
    try:
        for method, path, body in calls:
            response = client.request(method, path, headers=headers, json=body)
            assert response.status_code == 200, (method, path, response.text)
            assert set(response.json()) == {"code", "msg", "data"}
            assert response.json()["code"] == 0

        invalid_range = client.get(
            "/api/trade-discipline/checkins?date_from=2025-02-01&date_to=2025-01-01",
            headers=headers,
        )
        assert invalid_range.status_code == 422
    finally:
        _remove_user(pg, identity)
