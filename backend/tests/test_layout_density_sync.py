"""密度批量补丁：真实 PG、随机归属、精确清理，不重置任何平台配置。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.common.exceptions import ValidationError
from backend.storage.layout_config import LayoutConfigRepo
from backend.tests.test_stage4_resource_codes import _auth, _mk_user, _rm_user


@pytest.fixture()
def density_env(pg, monkeypatch):
    from backend.api import layout
    from backend.main import create_app

    users = []
    try:
        for _ in range(3):
            users.append(_mk_user(pg, []))
        pg.execute("DELETE FROM sys_user_role WHERE user_id=%s AND role_id=%s",
                   [users[2][0], users[2][2]])
        repo = object.__new__(LayoutConfigRepo)
        repo.pg = pg
        repo._tenant_id = users[0][1]
        monkeypatch.setattr(layout, "LayoutConfigRepo", lambda: repo)
        yield pg, repo, users, TestClient(create_app())
    finally:
        for owner, tenant, role in users:
            pg.execute(
                "DELETE FROM layout_user_config WHERE tenant_id=%s AND owner_user_id=%s",
                [tenant, owner],
            )
            _rm_user(pg, owner, tenant, role)


def _insert(pg, owner, tenant, page, values, version=1):
    pg.execute(
        "INSERT INTO layout_user_config "
        "(user_id,tenant_id,owner_user_id,page_key,config,schema_version) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        [owner, tenant, owner, page, json.dumps(values), version],
    )


def test_density_bulk_preserves_fields_and_other_accounts_at_limit(density_env):
    pg, repo, users, _ = density_env
    uid, tid, _ = users[0]
    other, other_tid, _ = users[1]
    values = {"density": "standard", "slots.table.config.hiddenColumns": ["name"],
              "slots.table.config.pageSize": 50}
    _insert(pg, uid, tid, "page_0", values)
    _insert(pg, other, other_tid, "page_0", {"density": "comfortable"})
    keys = [f"page_{index}" for index in range(100)]
    result = repo.sync_user_density(keys, "compact", user_id=uid)
    assert len(result["pageKeys"]) == 100
    rows = pg.query_df(
        "SELECT config FROM layout_user_config WHERE tenant_id=%s AND owner_user_id=%s",
        [tid, uid],
    )
    assert len(rows) == 100
    assert all(json.loads(value)["density"] == "compact" for value in rows["config"])
    assert repo.get_user_config("page_0", uid)["config"]["values"] == {
        **values, "density": "compact",
    }
    assert repo.get_user_config("page_0", other)["config"]["values"] == {
        "density": "comfortable",
    }
    assert repo.sync_user_density(["page_0", "page_0"], "compact", user_id=uid)[
        "pageKeys"
    ] == ["page_0"]


@pytest.mark.parametrize("bad_values,version", [({"density": "standard"}, 999), ([], 1)])
def test_density_bulk_rolls_back_all_pages_for_incompatible_row(density_env, bad_values, version):
    pg, repo, users, _ = density_env
    uid, tid, _ = users[0]
    _insert(pg, uid, tid, "z_incompatible", bad_values, version)
    with pytest.raises(ValidationError, match="未应用密度"):
        repo.sync_user_density(["a_new", "z_incompatible"], "compact", user_id=uid)
    assert repo.get_user_config("a_new", uid)["config"]["values"] == {}
    assert repo.get_user_config("z_incompatible", uid)["config"]["values"] == bad_values


def test_density_bulk_rejects_wrong_tenant_even_with_conflicting_user_id(density_env):
    pg, repo, users, _ = density_env
    uid, tid, _ = users[0]
    _insert(pg, uid, tid, "board", {"density": "standard"})
    repo._tenant_id = users[1][1]
    with pytest.raises(ValidationError):
        repo.sync_user_density(["board"], "compact", user_id=uid)
    repo._tenant_id = tid
    assert repo.get_user_config("board", uid)["config"]["values"]["density"] == "standard"


def test_density_api_uses_current_owner_and_allows_later_page_edit(density_env):
    _, repo, users, client = density_env
    uid, tid, _ = users[0]
    headers = _auth(uid, tid)
    result = client.post("/api/layout/user-density", headers=headers, json={
        "density": "compact", "pageKeys": ["board", "stocks"],
        "userId": users[1][0], "tenantId": users[1][1],
    })
    assert result.status_code == 200 and result.json()["code"] == 0
    assert repo.get_user_config("board", users[1][0])["config"]["values"] == {}
    edited = client.post("/api/layout/users/board", headers=headers, json={
        "config": {"values": {"density": "comfortable"}},
    })
    assert edited.status_code == 200 and edited.json()["code"] == 0
    assert repo.get_user_config("board", uid)["config"]["values"]["density"] == "comfortable"
    assert repo.get_user_config("stocks", uid)["config"]["values"]["density"] == "compact"


@pytest.mark.parametrize("payload,status", [
    ({"density": "huge", "pageKeys": ["board"]}, 422),
    ({"density": "standard", "pageKeys": []}, 422),
    ({"density": "compact", "pageKeys": ["invalid/page"]}, 200),
    ({"density": "standard", "pageKeys": [f"p_{i}" for i in range(101)]}, 422),
])
def test_density_api_validates_entire_payload(density_env, payload, status):
    _, repo, users, client = density_env
    uid, tid, _ = users[0]
    result = client.post("/api/layout/user-density", headers=_auth(uid, tid), json=payload)
    assert result.status_code == status
    assert result.json()["code"] != 0
    assert repo.get_user_config("board", uid)["config"]["values"] == {}


def test_density_api_no_role_and_anonymous_fail_closed(density_env):
    _, _, users, client = density_env
    uid, tid, _ = users[2]
    body = {"density": "compact", "pageKeys": ["board"]}
    assert client.post("/api/layout/user-density", headers=_auth(uid, tid), json=body).status_code == 403
    assert client.post("/api/layout/user-density", json=body).status_code == 401
