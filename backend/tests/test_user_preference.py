"""用户偏好 PG 存储与 API（config-storage-pg-migration T4）。"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.storage.user_preference import UserPreferenceRepo, UserPreferenceValidationError

_SECRET = "test-secret-user-pref-0123456789abcdef"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.main import create_app

    return TestClient(create_app())


def _auth(uid: str, tid: str, pv: int = 0) -> dict:
    from backend.auth.jwt_tokens import issue_access

    return {"Authorization": "Bearer " + issue_access(uid, tid, pv)}


def _mk_user(pg, *, with_role: bool = True) -> tuple[str, str, str | None]:
    tid = "pref_t_" + uuid.uuid4().hex[:8]
    uid = "pref_u_" + uuid.uuid4().hex[:8]
    rid = "pref_r_" + uuid.uuid4().hex[:8] if with_role else None
    pg.execute("INSERT INTO sys_tenant (id,name,status) VALUES (%s,'t','active') ON CONFLICT DO NOTHING", [tid])
    pg.execute(
        "INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
        "VALUES (%s,%s,%s,'normal',0,'active')",
        [uid, tid, uid],
    )
    if rid:
        pg.execute(
            "INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
            "VALUES (%s,%s,'pref','custom',FALSE,FALSE)",
            [rid, rid],
        )
        pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)", [uid, rid])
    return uid, tid, rid


def _rm_user(pg, uid: str, tid: str, rid: str | None) -> None:
    pg.execute("DELETE FROM user_preference WHERE owner_user_id=%s", [uid])
    pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    if rid:
        pg.execute("DELETE FROM sys_role WHERE id=%s", [rid])
    pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])


def test_user_preference_repo_roundtrip_and_isolation(pg):
    a = UserPreferenceRepo(pg, tenant_id="pref_t", owner_user_id="owner_a")
    b = UserPreferenceRepo(pg, tenant_id="pref_t", owner_user_id="owner_b")
    try:
        saved = a.set(
            scope="global",
            pref_key="settings-drawer",
            value={"size": "lg", "defaultCollapsed": ["layout"]},
        )
        assert saved["value"]["size"] == "lg"
        assert a.get(scope="global", pref_key="settings-drawer")["value"]["defaultCollapsed"] == ["layout"]
        assert b.get(scope="global", pref_key="settings-drawer") is None
    finally:
        pg.execute("DELETE FROM user_preference WHERE owner_user_id IN (%s,%s)", ["owner_a", "owner_b"])


def test_user_preference_repo_validation(pg):
    repo = UserPreferenceRepo(pg, tenant_id="pref_t", owner_user_id="owner_v")
    with pytest.raises(UserPreferenceValidationError, match="scope"):
        repo.set(scope="tenant", pref_key="x", value={})
    with pytest.raises(UserPreferenceValidationError, match="pref_key"):
        repo.set(scope="global", pref_key="../x", value={})
    with pytest.raises(UserPreferenceValidationError, match="对象或标量"):
        repo.set(scope="global", pref_key="x", value=[1, 2])
    with pytest.raises(UserPreferenceValidationError, match="标准 JSON"):
        repo.set(scope="global", pref_key="x", value={"ratio": float("nan")})
    with pytest.raises(UserPreferenceValidationError, match="大小限制"):
        repo.set(scope="global", pref_key="x", value={"blob": "x" * (64 * 1024)})


def test_stock_detail_chart_preference_is_additive_and_tenant_owner_isolated(pg):
    owner = "pref_shared_owner"
    tenant_a = UserPreferenceRepo(pg, tenant_id="pref_tenant_a", owner_user_id=owner)
    tenant_b = UserPreferenceRepo(pg, tenant_id="pref_tenant_b", owner_user_id=owner)
    other_owner = UserPreferenceRepo(
        pg,
        tenant_id="pref_tenant_a",
        owner_user_id="pref_other_owner",
    )
    key = {"scope": "page", "page_key": "stock-detail", "pref_key": "settings"}
    try:
        tenant_a.set(
            **key,
            value={
                "adjust": "qfq",
                "range": "120",
                "legacyPanel": {"collapsed": True},
            },
        )
        previous = tenant_a.get(**key)
        assert previous is not None
        merged = {
            **previous["value"],
            "charts": {
                "slot2": "volume",
                "slot3": "macd",
                "heightRatios": {
                    "kline|volume|macd": [0.6, 0.2, 0.2],
                },
            },
        }
        saved = tenant_a.set(**key, value=merged)

        assert saved["value"] == merged
        assert saved["value"]["adjust"] == "qfq"
        assert saved["value"]["legacyPanel"] == {"collapsed": True}
        assert tenant_b.get(**key) is None
        assert other_owner.get(**key) is None
    finally:
        pg.execute(
            "DELETE FROM user_preference WHERE owner_user_id IN (%s,%s)",
            [owner, "pref_other_owner"],
        )


def test_user_preference_api_allowed_by_baseline_and_ignores_owner_fields(client, pg):
    uid, tid, rid = _mk_user(pg)
    try:
        headers = _auth(uid, tid)
        resp = client.post(
            "/api/user-preferences",
            json={
                "scope": "global",
                "prefKey": "theme",
                "value": {"mode": "dark"},
                "ownerUserId": "attacker",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        df = pg.query_df(
            "SELECT owner_user_id, value FROM user_preference "
            "WHERE pref_key=%s AND owner_user_id IN (%s,%s)",
            ["theme", uid, "attacker"],
        )
        assert df["owner_user_id"].tolist() == [uid]

        listed = client.get(
            "/api/user-preferences?scope=global&prefKey=theme",
            headers=headers,
        ).json()
        assert listed["code"] == 0
        assert listed["data"]["items"][0]["value"] == {"mode": "dark"}
    finally:
        _rm_user(pg, uid, tid, rid)


def test_user_preference_api_bulk_and_page_scope(client, pg):
    uid, tid, rid = _mk_user(pg)
    try:
        resp = client.post(
            "/api/user-preferences/bulk",
            json={
                "items": [
                    {"scope": "page", "pageKey": "board", "prefKey": "settings", "value": {"dense": True}},
                    {"scope": "feature", "pageKey": "backtest", "prefKey": "params", "value": {"cash": 100000}},
                ]
            },
            headers=_auth(uid, tid),
        )
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]["items"]) == 2
        listed = client.get("/api/user-preferences?scope=page&pageKey=board", headers=_auth(uid, tid)).json()
        assert listed["data"]["items"][0]["prefKey"] == "settings"
    finally:
        _rm_user(pg, uid, tid, rid)


def test_user_preference_client_migration_bulk_writes_audit(client, pg):
    uid, tid, rid = _mk_user(pg)
    try:
        pg.execute(
            "DELETE FROM audit_log WHERE actor_user_id=%s AND event_type=%s",
            [uid, "client_preference_migration"],
        )
        resp = client.post(
            "/api/user-preferences/bulk",
            json={
                "migrationSource": "config-storage-pg-v1",
                "items": [
                    {"scope": "page", "pageKey": "board", "prefKey": "settings", "value": {"dense": True}},
                    {"scope": "global", "prefKey": "theme", "value": {"mode": "dark"}},
                ],
            },
            headers=_auth(uid, tid),
        )

        body = resp.json()
        assert body["code"] == 0
        audits = pg.query_df(
            "SELECT event_category, event_type, action, result, status, target_type, target_id, context "
            "FROM audit_log WHERE actor_user_id=%s AND event_type=%s",
            [uid, "client_preference_migration"],
        )
        assert len(audits) == 1
        row = audits.iloc[0]
        assert row["event_category"] == "migration"
        assert row["action"] == "bulk_save"
        assert row["result"] == "success"
        assert row["status"] == "completed"
        assert row["target_type"] == "user_preference"
        assert row["target_id"] == "config-storage-pg-v1"
        assert row["context"]["item_count"] == 2
        assert row["context"]["saved_count"] == 2
    finally:
        pg.execute(
            "DELETE FROM audit_log WHERE actor_user_id=%s AND event_type=%s",
            [uid, "client_preference_migration"],
        )
        _rm_user(pg, uid, tid, rid)


def test_user_preference_api_without_role_fail_closed(client, pg):
    uid, tid, rid = _mk_user(pg, with_role=False)
    try:
        resp = client.get("/api/user-preferences", headers=_auth(uid, tid))
        assert resp.status_code == 403 and resp.json()["code"] == 4030
    finally:
        _rm_user(pg, uid, tid, rid)


def test_user_preference_api_rejects_invalid_payload(client, pg):
    uid, tid, rid = _mk_user(pg)
    try:
        resp = client.post(
            "/api/user-preferences",
            json={"scope": "global", "prefKey": "bad", "value": [1, 2]},
            headers=_auth(uid, tid),
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 400
    finally:
        _rm_user(pg, uid, tid, rid)
