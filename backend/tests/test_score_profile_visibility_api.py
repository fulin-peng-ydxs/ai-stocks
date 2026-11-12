"""评分方案可见性 API 回归：保存、租户公开、只读引用与复制。"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.tests.conftest import insert_test_role

_SECRET = "test-secret-score-profile-visibility-0123456789abcdef"


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
    pg.execute("INSERT INTO sys_tenant (id,name,status) VALUES (%s,'t','active') ON CONFLICT DO NOTHING", [tid])
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
        "name": "租户公开评分方案",
        "items": [{
            "indicator": "rs_pct",
            "weight": 1.0,
            "scoring": {"type": "linear", "min": 0, "max": 100},
        }],
        "grade_thresholds": {"watch": 80},
    }


def test_score_profile_tenant_visibility_and_copy(client, pg):
    tenant = "spv_tenant_" + uuid.uuid4().hex[:8]
    owner, tid, owner_role = _mk_user(
        pg,
        ["score-profile:view", "score-profile:save", "score-profile:publish-tenant"],
        tenant=tenant,
    )
    viewer, _, viewer_role = _mk_user(
        pg,
        ["score-profile:view", "score-profile:save"],
        tenant=tenant,
    )
    outsider, otid, outsider_role = _mk_user(pg, ["score-profile:view"])
    pid = "spv_profile_" + uuid.uuid4().hex[:6]
    try:
        saved = client.post("/api/score-profiles", json=_profile_body(pid), headers=_auth(owner, tid))
        assert saved.status_code == 200 and saved.json()["code"] == 0

        viewer_profile_id = "spv_no_publish_" + uuid.uuid4().hex[:6]
        viewer_saved = client.post(
            "/api/score-profiles",
            json=_profile_body(viewer_profile_id),
            headers=_auth(viewer, tid),
        )
        assert viewer_saved.status_code == 200 and viewer_saved.json()["code"] == 0
        bypass = client.post(
            f"/api/score-profiles/{viewer_profile_id}/visibility",
            json={"visibility": "tenant "},
            headers=_auth(viewer, tid),
        )
        assert bypass.status_code == 200 and bypass.json()["code"] == 403
        bypass_case = client.post(
            f"/api/score-profiles/{viewer_profile_id}/visibility",
            json={"visibility": "Tenant"},
            headers=_auth(viewer, tid),
        )
        assert bypass_case.status_code == 200 and bypass_case.json()["code"] == 403
        invalid = client.post(
            f"/api/score-profiles/{viewer_profile_id}/visibility",
            json={"visibility": "tenantx"},
            headers=_auth(viewer, tid),
        )
        assert invalid.status_code == 422
        row = pg.query_df(
            "SELECT visibility FROM score_profile WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [tid, viewer, viewer_profile_id],
        )
        assert not row.empty and row.iloc[0]["visibility"] == "private"

        denied = client.post(
            f"/api/score-profiles/{pid}/visibility",
            json={"visibility": "public"},
            headers=_auth(owner, tid),
        )
        assert denied.status_code == 200 and denied.json()["code"] == 403

        pub = client.post(
            f"/api/score-profiles/{pid}/visibility",
            json={"visibility": "tenant"},
            headers=_auth(owner, tid),
        )
        assert pub.status_code == 200 and pub.json()["data"]["visibility"] == "tenant"
        visibility_audit = pg.query_df(
            "SELECT action, resource_code, target_type, target_id, changes FROM audit_log "
            "WHERE tenant_id=%s AND actor_user_id=%s AND event_type='asset_visibility' "
            "AND action='score_profile_visibility' AND target_id=%s",
            [tid, owner, pid],
        )
        assert not visibility_audit.empty
        assert visibility_audit.iloc[0]["resource_code"] == "score-profile:publish-tenant"

        listed = client.get("/api/score-profiles", headers=_auth(viewer, tid))
        rows = listed.json()["data"]
        shared = next(r for r in rows if r["id"] == pid)
        assert shared["readonly"] is True
        assert shared["source"] == "tenant"

        detail = client.get(f"/api/score-profiles/{shared['profile_ref']}", headers=_auth(viewer, tid))
        assert detail.status_code == 200
        assert detail.json()["data"]["readonly"] is True

        copied = client.post(
            f"/api/score-profiles/{shared['profile_ref']}/copy",
            json={"name": "我的副本"},  # C8：前端不传 id，后端生成
            headers=_auth(viewer, tid),
        )
        assert copied.status_code == 200 and copied.json()["data"]["version"] == 1
        new_id = copied.json()["data"]["id"]
        assert new_id and copied.json()["data"]["profile_ref"]
        copy_audit = pg.query_df(
            "SELECT action, resource_code, target_type, target_id FROM audit_log "
            "WHERE tenant_id=%s AND actor_user_id=%s AND event_type='asset_copy' "
            "AND action='score_profile_copy' AND target_id=%s",
            [tid, viewer, new_id],
        )
        assert not copy_audit.empty
        assert copy_audit.iloc[0]["resource_code"] == "score-profile:save"
        # C8 单击即复制：再次复制成功且生成不同 id（不再有「已存在」409 冲突）
        duplicated = client.post(
            f"/api/score-profiles/{shared['profile_ref']}/copy",
            json={"name": "我的副本"},
            headers=_auth(viewer, tid),
        )
        assert duplicated.status_code == 200 and duplicated.json()["code"] == 0
        assert duplicated.json()["data"]["id"] != new_id

        out = client.get("/api/score-profiles", headers=_auth(outsider, otid))
        assert pid not in {r["id"] for r in out.json()["data"]}
    finally:
        for owner_id in (owner, viewer):
            pg.execute("DELETE FROM score_profile WHERE owner_user_id=%s", [owner_id])
            pg.execute("DELETE FROM score_profile_version WHERE owner_user_id=%s", [owner_id])
        _rm_user(pg, owner, tid, owner_role)
        _rm_user(pg, viewer, tid, viewer_role)
        _rm_user(pg, outsider, otid, outsider_role)


def test_score_profile_public_owner_label_masks_cross_tenant_owner(client, pg):
    owner, tid, owner_role = _mk_user(
        pg,
        ["score-profile:view", "score-profile:save", "score-profile:publish-public"],
    )
    outsider, otid, outsider_role = _mk_user(pg, ["score-profile:view"])
    pid = "spv_public_" + uuid.uuid4().hex[:6]
    try:
        saved = client.post("/api/score-profiles", json=_profile_body(pid), headers=_auth(owner, tid))
        assert saved.status_code == 200 and saved.json()["code"] == 0

        pub = client.post(
            f"/api/score-profiles/{pid}/visibility",
            json={"visibility": "public"},
            headers=_auth(owner, tid),
        )
        assert pub.status_code == 200 and pub.json()["data"]["visibility"] == "public"

        listed = client.get("/api/score-profiles", headers=_auth(outsider, otid))
        assert listed.status_code == 200 and listed.json()["code"] == 0
        shared = next(r for r in listed.json()["data"] if r["id"] == pid)
        assert shared["source"] == "public"
        assert shared["readonly"] is True
        assert shared["owner_label"] == "其他租户用户"
        assert shared["owner_label"] != owner
    finally:
        pg.execute("DELETE FROM score_profile WHERE owner_user_id=%s", [owner])
        pg.execute("DELETE FROM score_profile_version WHERE owner_user_id=%s", [owner])
        _rm_user(pg, owner, tid, owner_role)
        _rm_user(pg, outsider, otid, outsider_role)


def test_delete_public_profile_returns_409_not_500(client, pg):
    """P1 收口:删除仍公开的方案返回 409 业务提示,而非未捕获 ValueError→500。"""
    owner, tid, owner_role = _mk_user(
        pg, ["score-profile:view", "score-profile:save", "score-profile:publish-tenant", "score-profile:delete"])
    pid = "spv_del409_" + uuid.uuid4().hex[:6]
    try:
        client.post("/api/score-profiles", json=_profile_body(pid), headers=_auth(owner, tid))
        pub = client.post(
            f"/api/score-profiles/{pid}/visibility",
            json={"visibility": "tenant"}, headers=_auth(owner, tid))
        assert pub.status_code == 200 and pub.json()["code"] == 0
        # 公开态删除 → 409(非 500),提示先收回
        blocked = client.delete(f"/api/score-profiles/{pid}", headers=_auth(owner, tid))
        assert blocked.status_code == 200 and blocked.json()["code"] == 409
        assert "收回为私有" in blocked.json()["msg"]
        # 收回私有后可删
        client.post(
            f"/api/score-profiles/{pid}/visibility",
            json={"visibility": "private"}, headers=_auth(owner, tid))
        ok_del = client.delete(f"/api/score-profiles/{pid}", headers=_auth(owner, tid))
        assert ok_del.status_code == 200 and ok_del.json()["code"] == 0
    finally:
        pg.execute("DELETE FROM score_profile WHERE owner_user_id=%s", [owner])
        pg.execute("DELETE FROM score_profile_version WHERE owner_user_id=%s", [owner])
        _rm_user(pg, owner, tid, owner_role)


def test_list_source_validation_and_pagination_clamp(client, pg):
    """R2-P2：未知 source 返回 400（信封码）；browse 分页越界值被 clamp 且如实回显。"""
    uid, tid, rid = _mk_user(pg, ["score-profile:view", "score-profile:save"])
    try:
        # 未知 source → 信封 code 400（不静默回退 list_visible）
        bad = client.get("/api/score-profiles", params={"source": "favorite"}, headers=_auth(uid, tid))
        assert bad.status_code == 200 and bad.json()["code"] == 400
        # 合法 source=mine 正常
        mine = client.get("/api/score-profiles", params={"source": "mine"}, headers=_auth(uid, tid))
        assert mine.status_code == 200 and mine.json()["code"] == 0
        # browse 越界分页：page<1 → 1，page_size>100 → 100，且回显 clamp 后的值
        clamp = client.get(
            "/api/score-profiles",
            params={"source": "public", "page": 0, "page_size": 999},
            headers=_auth(uid, tid),
        )
        assert clamp.status_code == 200 and clamp.json()["code"] == 0
        data = clamp.json()["data"]
        assert data["page"] == 1 and data["page_size"] == 100
    finally:
        _rm_user(pg, uid, tid, rid)
