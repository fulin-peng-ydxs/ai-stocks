"""阶段六 T6：筛选方案可见性 API、复制和运行时 ref 解析。"""

from __future__ import annotations

import uuid
from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.backtest.engine import BacktestEngine
from backend.screening.presets import PRESET_PROFILES
from backend.screening.profile import ProfileRepo
from backend.services.backtest_service import BacktestService
from backend.services.screen_score import ScreenScoreService
from backend.tests.conftest import insert_test_role

_SECRET = "test-secret-screen-profile-visibility-0123456789abcdef"
_EXPR = PRESET_PROFILES[0]["expression"]


@pytest.fixture()
def client(monkeypatch, pg, redis_cli):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.main import create_app

    return TestClient(create_app())


def _auth(uid: str, tid: str, pv: int = 0) -> dict:
    from backend.auth.jwt_tokens import issue_access

    return {"Authorization": "Bearer " + issue_access(uid, tid, pv)}


def _mk_user(pg, codes: list[str], tenant: str | None = None) -> tuple[str, str, str]:
    tid = tenant or ("spv_t_" + uuid.uuid4().hex[:8])
    uid = "spv_u_" + uuid.uuid4().hex[:8]
    rid = "spv_r_" + uuid.uuid4().hex[:8]
    pg.execute(
        "INSERT INTO sys_tenant (id,name,status) VALUES (%s,'t','active') ON CONFLICT DO NOTHING",
        [tid],
    )
    pg.execute(
        "INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
        "VALUES (%s,%s,%s,'normal',0,'active')",
        [uid, tid, uid],
    )
    insert_test_role(pg, rid)
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
        "name": "租户公开筛选方案",
        "expression": _EXPR,
    }


def test_screen_profile_tenant_visibility_copy_and_owner_guards(client, pg):
    tenant = "screen_vis_tenant_" + uuid.uuid4().hex[:8]
    owner, tid, owner_role = _mk_user(
        pg,
        [
            "screen-profile:view",
            "screen-profile:save",
            "screen-profile:delete",
            "screen-profile:publish-tenant",
        ],
        tenant=tenant,
    )
    viewer, _, viewer_role = _mk_user(
        pg,
        ["screen-profile:view", "screen-profile:save", "screen-profile:delete"],
        tenant=tenant,
    )
    outsider, otid, outsider_role = _mk_user(pg, ["screen-profile:view"])
    pid = "screen_vis_" + uuid.uuid4().hex[:6]
    try:
        saved = client.post("/api/profiles", json=_profile_body(pid), headers=_auth(owner, tid))
        assert saved.status_code == 200 and saved.json()["code"] == 0

        viewer_profile_id = "screen_no_publish_" + uuid.uuid4().hex[:6]
        viewer_saved = client.post(
            "/api/profiles",
            json=_profile_body(viewer_profile_id),
            headers=_auth(viewer, tid),
        )
        assert viewer_saved.status_code == 200 and viewer_saved.json()["code"] == 0
        bypass = client.post(
            f"/api/profiles/{viewer_profile_id}/visibility",
            json={"visibility": "tenant "},
            headers=_auth(viewer, tid),
        )
        assert bypass.status_code == 200 and bypass.json()["code"] == 403
        bypass_case = client.post(
            f"/api/profiles/{viewer_profile_id}/visibility",
            json={"visibility": "Tenant"},
            headers=_auth(viewer, tid),
        )
        assert bypass_case.status_code == 200 and bypass_case.json()["code"] == 403
        invalid = client.post(
            f"/api/profiles/{viewer_profile_id}/visibility",
            json={"visibility": "tenantx"},
            headers=_auth(viewer, tid),
        )
        assert invalid.status_code == 422
        viewer_profile = ProfileRepo(pg=pg, tenant_id=tid, owner_user_id=viewer).get(viewer_profile_id)
        assert viewer_profile is not None and viewer_profile["visibility"] == "private"

        denied = client.post(
            f"/api/profiles/{pid}/visibility",
            json={"visibility": "public"},
            headers=_auth(owner, tid),
        )
        assert denied.status_code == 200 and denied.json()["code"] == 403

        published = client.post(
            f"/api/profiles/{pid}/visibility",
            json={"visibility": "tenant"},
            headers=_auth(owner, tid),
        )
        assert published.status_code == 200 and published.json()["data"]["visibility"] == "tenant"

        rows = client.get("/api/profiles", headers=_auth(viewer, tid)).json()["data"]
        shared = next(r for r in rows if r["id"] == pid)
        assert shared["readonly"] is True
        assert shared["source"] == "tenant"
        assert shared["profile_ref"].startswith("avr_")

        detail = client.get(f"/api/profiles/{shared['profile_ref']}", headers=_auth(viewer, tid))
        assert detail.status_code == 200
        assert detail.json()["data"]["readonly"] is True

        delete_denied = client.delete(f"/api/profiles/{shared['profile_ref']}", headers=_auth(viewer, tid))
        assert delete_denied.status_code == 200 and delete_denied.json()["code"] == 403

        publish_denied = client.post(
            f"/api/profiles/{shared['profile_ref']}/visibility",
            json={"visibility": "private"},
            headers=_auth(viewer, tid),
        )
        assert publish_denied.status_code == 200 and publish_denied.json()["code"] == 403

        copied = client.post(
            f"/api/profiles/{shared['profile_ref']}/copy",
            json={"name": "我的筛选副本"},  # C8：前端不传 id，后端生成
            headers=_auth(viewer, tid),
        )
        assert copied.status_code == 200 and copied.json()["data"]["version"] == 1
        new_id = copied.json()["data"]["id"]
        assert new_id and copied.json()["data"]["profile_ref"]
        audit = pg.query_df(
            "SELECT action, resource_code, target_type, target_id FROM audit_log "
            "WHERE tenant_id=%s AND actor_user_id=%s AND event_type='asset_copy' "
            "AND action='screen_profile_copy' AND target_id=%s",
            [tid, viewer, new_id],
        )
        assert not audit.empty
        assert audit.iloc[0]["resource_code"] == "screen-profile:save"
        copied_detail = client.get(
            f"/api/profiles/{copied.json()['data']['profile_ref']}", headers=_auth(viewer, tid)).json()["data"]
        assert copied_detail["name"] == "我的筛选副本"
        assert copied_detail["visibility"] == "private"
        assert copied_detail["readonly"] is False

        # C8 单击即复制：再次复制成功且生成不同 id（不再 409 冲突）
        duplicated = client.post(
            f"/api/profiles/{shared['profile_ref']}/copy",
            json={"name": "我的筛选副本"},
            headers=_auth(viewer, tid),
        )
        assert duplicated.status_code == 200 and duplicated.json()["code"] == 0
        assert duplicated.json()["data"]["id"] != new_id

        outsider_rows = client.get("/api/profiles", headers=_auth(outsider, otid)).json()["data"]
        assert pid not in {r["id"] for r in outsider_rows}
    finally:
        for owner_id in (owner, viewer, outsider):
            pg.execute("DELETE FROM screen_profile WHERE owner_user_id=%s", [owner_id])
            pg.execute("DELETE FROM screen_profile_version WHERE owner_user_id=%s", [owner_id])
        _rm_user(pg, owner, tid, owner_role)
        _rm_user(pg, viewer, tid, viewer_role)
        _rm_user(pg, outsider, otid, outsider_role)


def test_screen_run_visible_ref_persists_for_viewer_not_source_owner(pg, market):
    owner = "screen_run_owner_" + uuid.uuid4().hex[:6]
    viewer = "screen_run_viewer_" + uuid.uuid4().hex[:6]
    tenant = "screen_run_tenant_" + uuid.uuid4().hex[:6]
    profile_id = "screen_run_" + uuid.uuid4().hex[:6]
    try:
        owner_repo = ProfileRepo(pg=pg, tenant_id=tenant, owner_user_id=owner)
        owner_repo.save(profile_id, "可运行公开筛选", _EXPR)
        shared = owner_repo.set_visibility(profile_id, "tenant", published_by=owner)

        svc = ScreenScoreService(client=market, tenant_id=tenant, owner_user_id=viewer)

        class _Engine:
            def run_ast(self, expression, run_date):
                assert expression == _EXPR
                return pd.DataFrame({"code": ["000001.SZ"], "hit": [True]})

        class _Assets:
            def __init__(self):
                self.rows = None

            def upsert(self, table, df):
                assert table == "screen_result"
                self.rows = df.copy()
                return len(df)

        assets = _Assets()
        svc.engine = _Engine()
        svc.assets = assets

        hits = svc.run_profile(shared["profile_ref"], date(2024, 1, 2), persist=True)

        assert hits == ["000001.SZ"]
        assert assets.rows is not None
        assert assets.rows.iloc[0]["profile_id"] == profile_id
        assert svc.assets is assets
        assert svc.owner_user_id == viewer
    finally:
        for owner_id in (owner, viewer):
            pg.execute("DELETE FROM screen_profile WHERE owner_user_id=%s", [owner_id])
            pg.execute("DELETE FROM screen_profile_version WHERE owner_user_id=%s", [owner_id])


def test_backtest_resolves_visible_screen_profile_ref(pg, market, monkeypatch):
    owner = "screen_bt_owner_" + uuid.uuid4().hex[:6]
    viewer = "screen_bt_viewer_" + uuid.uuid4().hex[:6]
    tenant = "screen_bt_tenant_" + uuid.uuid4().hex[:6]
    profile_id = "screen_bt_" + uuid.uuid4().hex[:6]
    try:
        owner_repo = ProfileRepo(pg=pg, tenant_id=tenant, owner_user_id=owner)
        owner_repo.save(profile_id, "可回测公开筛选", _EXPR)
        shared = owner_repo.set_visibility(profile_id, "tenant", published_by=owner)

        svc = BacktestService(client=market, tenant_id=tenant, owner_user_id=viewer)
        versions = svc._resolve_versions({"profile_id": shared["profile_ref"]})
        assert versions["profile_version"] == 1

        def fake_precompute(self, expression, d0, d1):
            assert expression == _EXPR
            return {}

        days = [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")]
        monkeypatch.setattr(BacktestEngine, "_trading_days", lambda self, d0, d1: days)
        monkeypatch.setattr(BacktestEngine, "_load_prices", lambda self, lo, hi, ma: {})
        monkeypatch.setattr(
            BacktestEngine,
            "_load_scores",
            lambda self, d0, d1: {
                days[0]: pd.DataFrame(columns=["code", "grade", "total_score"]),
            },
        )
        monkeypatch.setattr(
            BacktestEngine,
            "_benchmark",
            lambda self, bench_code, ds: pd.Series([1.0, 1.0], index=days),
        )
        monkeypatch.setattr("backend.backtest.precompute.HitPrecomputer.precompute", fake_precompute)
        out = BacktestEngine(
            market,
            tenant_id=tenant,
            owner_user_id=viewer,
        ).run({
            "date_start": "2024-01-01",
            "date_end": "2024-01-02",
            "profile_id": shared["profile_ref"],
        })
        assert out.get("error") != f"方案不存在: {shared['profile_ref']}"
    finally:
        for owner_id in (owner, viewer):
            pg.execute("DELETE FROM screen_profile WHERE owner_user_id=%s", [owner_id])
            pg.execute("DELETE FROM screen_profile_version WHERE owner_user_id=%s", [owner_id])
