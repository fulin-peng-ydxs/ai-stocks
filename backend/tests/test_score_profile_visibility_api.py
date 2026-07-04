"""评分方案可见性 API 回归：保存、租户公开、只读引用与复制。"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

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
    pg.execute(
        "INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
        "VALUES (%s,%s,'spv','custom',FALSE,FALSE)",
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
    copy_id = "spv_copy_" + uuid.uuid4().hex[:6]
    try:
        saved = client.post("/api/score-profiles", json=_profile_body(pid), headers=_auth(owner, tid))
        assert saved.status_code == 200 and saved.json()["code"] == 0

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
            json={"id": copy_id, "name": "我的副本"},
            headers=_auth(viewer, tid),
        )
        assert copied.status_code == 200 and copied.json()["data"]["version"] == 1

        out = client.get("/api/score-profiles", headers=_auth(outsider, otid))
        assert pid not in {r["id"] for r in out.json()["data"]}
    finally:
        for owner_id in (owner, viewer):
            pg.execute("DELETE FROM score_profile WHERE owner_user_id=%s", [owner_id])
            pg.execute("DELETE FROM score_profile_version WHERE owner_user_id=%s", [owner_id])
        _rm_user(pg, owner, tid, owner_role)
        _rm_user(pg, viewer, tid, viewer_role)
        _rm_user(pg, outsider, otid, outsider_role)
