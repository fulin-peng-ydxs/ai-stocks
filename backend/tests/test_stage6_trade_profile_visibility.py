"""阶段六 T7：买卖方案可见性 API、复制和回测 ref 解析。"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.backtest.engine import BacktestEngine
from backend.indicators.definition import IndicatorDefRepo
from backend.services.backtest_service import BacktestService
from backend.signals.trade_profile import TradeProfileRepo

_SECRET = "test-secret-trade-profile-visibility-0123456789abcdef"

_BUY = {"op": "AND", "children": [{"indicator": "bull_arrange", "cmp": "==", "value": True}]}
_SELL = {"op": "OR", "children": [{"indicator": "below_ma", "params": {"n": 20}, "cmp": "==", "value": True}]}
_BACKSTOP = {"stop_loss": 0.08}


@pytest.fixture()
def client(monkeypatch, pg, redis_cli):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.main import create_app

    return TestClient(create_app())


def _auth(uid: str, tid: str, pv: int = 0) -> dict:
    from backend.auth.jwt_tokens import issue_access

    return {"Authorization": "Bearer " + issue_access(uid, tid, pv)}


def _mk_user(pg, codes: list[str], tenant: str | None = None) -> tuple[str, str, str]:
    tid = tenant or ("tpv_t_" + uuid.uuid4().hex[:8])
    uid = "tpv_u_" + uuid.uuid4().hex[:8]
    rid = "tpv_r_" + uuid.uuid4().hex[:8]
    pg.execute(
        "INSERT INTO sys_tenant (id,name,status) VALUES (%s,'t','active') ON CONFLICT DO NOTHING",
        [tid],
    )
    pg.execute(
        "INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
        "VALUES (%s,%s,%s,'normal',0,'active')",
        [uid, tid, uid],
    )
    pg.execute(
        "INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
        "VALUES (%s,%s,'tpv','custom',FALSE,FALSE)",
        [rid, rid],
    )
    pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)", [uid, rid])
    for code in codes:
        pg.execute(
            "INSERT INTO sys_role_resource (role_id,resource_id) VALUES (%s,%s) "
            "ON CONFLICT DO NOTHING",
            [rid, code],
        )
    return uid, tid, rid


def _rm_user(pg, uid: str, tid: str, rid: str) -> None:
    pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    pg.execute("DELETE FROM sys_role WHERE id=%s", [rid])
    pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])


def _profile_body(pid: str) -> dict:
    return {
        "id": pid,
        "name": "租户公开买卖方案",
        "buy_tree": _BUY,
        "sell_tree": _SELL,
        "backstop": _BACKSTOP,
    }


def test_trade_profile_tenant_visibility_copy_and_owner_guards(client, pg):
    tenant = "trade_vis_tenant_" + uuid.uuid4().hex[:8]
    owner, tid, owner_role = _mk_user(
        pg,
        [
            "trade-profile:view",
            "trade-profile:save",
            "trade-profile:delete",
            "trade-profile:publish-tenant",
        ],
        tenant=tenant,
    )
    viewer, _, viewer_role = _mk_user(
        pg,
        ["trade-profile:view", "trade-profile:save", "trade-profile:delete"],
        tenant=tenant,
    )
    outsider, otid, outsider_role = _mk_user(pg, ["trade-profile:view"])
    pid = "trade_vis_" + uuid.uuid4().hex[:6]
    copy_id = "trade_copy_" + uuid.uuid4().hex[:6]
    try:
        saved = client.post("/api/trade-profiles", json=_profile_body(pid), headers=_auth(owner, tid))
        assert saved.status_code == 200 and saved.json()["code"] == 0

        denied = client.post(
            f"/api/trade-profiles/{pid}/visibility",
            json={"visibility": "public"},
            headers=_auth(owner, tid),
        )
        assert denied.status_code == 200 and denied.json()["code"] == 403

        published = client.post(
            f"/api/trade-profiles/{pid}/visibility",
            json={"visibility": "tenant"},
            headers=_auth(owner, tid),
        )
        assert published.status_code == 200 and published.json()["data"]["visibility"] == "tenant"

        rows = client.get("/api/trade-profiles", headers=_auth(viewer, tid)).json()["data"]
        shared = next(r for r in rows if r["id"] == pid)
        assert shared["readonly"] is True
        assert shared["source"] == "tenant"
        assert shared["profile_ref"].startswith("avr_")

        detail = client.get(f"/api/trade-profiles/{shared['profile_ref']}", headers=_auth(viewer, tid))
        assert detail.status_code == 200
        assert detail.json()["data"]["readonly"] is True

        delete_denied = client.delete(
            f"/api/trade-profiles/{shared['profile_ref']}",
            headers=_auth(viewer, tid),
        )
        assert delete_denied.status_code == 200 and delete_denied.json()["code"] == 403

        publish_denied = client.post(
            f"/api/trade-profiles/{shared['profile_ref']}/visibility",
            json={"visibility": "private"},
            headers=_auth(viewer, tid),
        )
        assert publish_denied.status_code == 200 and publish_denied.json()["code"] == 403

        copied = client.post(
            f"/api/trade-profiles/{shared['profile_ref']}/copy",
            json={"id": copy_id, "name": "我的买卖副本"},
            headers=_auth(viewer, tid),
        )
        assert copied.status_code == 200 and copied.json()["data"]["version"] == 1
        audit = pg.query_df(
            "SELECT action, resource_code, target_type, target_id FROM audit_log "
            "WHERE tenant_id=%s AND actor_user_id=%s AND event_type='asset_copy' "
            "AND action='trade_profile_copy' AND target_id=%s",
            [tid, viewer, copy_id],
        )
        assert not audit.empty
        assert audit.iloc[0]["resource_code"] == "trade-profile:save"
        copied_detail = client.get(f"/api/trade-profiles/{copy_id}", headers=_auth(viewer, tid)).json()["data"]
        assert copied_detail["name"] == "我的买卖副本"
        assert copied_detail["visibility"] == "private"
        assert copied_detail["readonly"] is False

        duplicated = client.post(
            f"/api/trade-profiles/{shared['profile_ref']}/copy",
            json={"id": copy_id, "name": "覆盖副本"},
            headers=_auth(viewer, tid),
        )
        assert duplicated.status_code == 200 and duplicated.json()["code"] == 409

        outsider_rows = client.get("/api/trade-profiles", headers=_auth(outsider, otid)).json()["data"]
        assert pid not in {r["id"] for r in outsider_rows}
    finally:
        for owner_id in (owner, viewer, outsider):
            pg.execute("DELETE FROM trade_profile WHERE owner_user_id=%s", [owner_id])
            pg.execute("DELETE FROM trade_profile_version WHERE owner_user_id=%s", [owner_id])
        _rm_user(pg, owner, tid, owner_role)
        _rm_user(pg, viewer, tid, viewer_role)
        _rm_user(pg, outsider, otid, outsider_role)


def test_backtest_resolves_visible_trade_profile_ref(market, pg):
    IndicatorDefRepo(market).seed_builtins()
    owner = "trade_run_owner_" + uuid.uuid4().hex[:6]
    viewer = "trade_run_viewer_" + uuid.uuid4().hex[:6]
    tenant = "trade_run_tenant_" + uuid.uuid4().hex[:6]
    profile_id = "trade_run_" + uuid.uuid4().hex[:6]
    try:
        owner_repo = TradeProfileRepo(market=market, pg=pg, tenant_id=tenant, owner_user_id=owner)
        owner_repo.save(profile_id, "可运行公开买卖", _BUY, _SELL, _BACKSTOP)
        shared = owner_repo.set_visibility(profile_id, "tenant", published_by=owner)

        svc = BacktestService(client=market, tenant_id=tenant, owner_user_id=viewer)
        versions = svc._resolve_versions({"trade_profile_id": shared["profile_ref"]})
        assert versions["trade_profile_version"] == 1

        out = BacktestEngine(
            market,
            tenant_id=tenant,
            owner_user_id=viewer,
        ).run({
            "date_start": "2024-01-01",
            "date_end": "2024-01-02",
            "trade_profile_id": shared["profile_ref"],
        })
        assert out.get("error") != f"买卖方案不存在: {shared['profile_ref']}"
    finally:
        for owner_id in (owner, viewer):
            pg.execute("DELETE FROM trade_profile WHERE owner_user_id=%s", [owner_id])
            pg.execute("DELETE FROM trade_profile_version WHERE owner_user_id=%s", [owner_id])
