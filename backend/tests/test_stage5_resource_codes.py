"""阶段五 T11：审计/字典资源码、菜单授权和前端路由对齐回归。"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.auth.constants import (
    ROLE_NORMAL,
    ROLE_PAID,
    ROLE_TENANT_ADMIN,
    SHARED_RESOURCE_CODES,
)
from backend.storage.resource_repository import ResourceRepository

_SECRET = "unit-test-stage5-resource-codes-0123456789"
_HTTP_VERBS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def client(monkeypatch, pg, redis_cli):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.main import create_app

    return TestClient(create_app())


@pytest.fixture()
def users(pg):
    made: list[dict] = []

    def mk(role_code: str = ROLE_NORMAL, *, with_role: bool = True) -> dict:
        tid = "s5rc_t_" + uuid.uuid4().hex[:8]
        uid = "s5rc_u_" + uuid.uuid4().hex[:8]
        pg.execute(
            "INSERT INTO sys_tenant (id,name,status) VALUES (%s,'stage5-rc','active')",
            [tid],
        )
        pg.execute(
            "INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
            "VALUES (%s,%s,%s,%s,0,'active')",
            [uid, tid, uid, role_code],
        )
        if with_role:
            pg.execute(
                "INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)",
                [uid, role_code],
            )
        user = {"id": uid, "tenant_id": tid, "role_code": role_code}
        made.append(user)
        return user

    yield mk

    for u in made:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [u["id"]])
        pg.execute("DELETE FROM sys_tenant WHERE id=%s", [u["tenant_id"]])


def _auth(pg, user_id: str, tenant_id: str) -> dict:
    from backend.auth.jwt_tokens import issue_access

    pv = int(
        pg.query_df(
            "SELECT perm_ver FROM sys_user WHERE id=%s",
            [user_id],
        ).iloc[0]["perm_ver"]
    )
    return {"Authorization": "Bearer " + issue_access(user_id, tenant_id, pv)}


def _admin_auth(pg) -> dict:
    return _auth(pg, "admin", "default")


def _route_dep_calls(route) -> list:
    return [d.call for d in route.dependant.dependencies if getattr(d, "call", None)]


def _resource_codes(route) -> set[str]:
    return {
        getattr(call, "resource_code")
        for call in _route_dep_calls(route)
        if hasattr(call, "resource_code")
    }


def _has_system_perm(route, code: str) -> bool:
    return any(
        getattr(call, "resource_code", None) == code
        and getattr(call, "require_system_perm", False) is True
        for call in _route_dep_calls(route)
    )


def _iter_api_routes(app):
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = (getattr(route, "methods", None) or set()) & _HTTP_VERBS
        if path.startswith("/api/") and methods:
            yield path, methods, route


def _menu_indexes(nodes: list[dict]) -> set[str]:
    indexes: set[str] = set()
    for node in nodes:
        indexes.add(node["index"])
        indexes |= _menu_indexes(node.get("children", []))
    return indexes


def test_stage5_audit_and_dict_routes_have_precise_resource_codes(client):
    expected = [
        ("GET", "/api/audit", "audit:view", False),
        ("GET", "/api/audit/summary", "audit:view", False),
        ("GET", "/api/audit/{audit_id}", "audit:view", False),
        ("GET", "/api/dict/types", "dict:view", True),
        ("POST", "/api/dict/types", "dict:type-manage", True),
        ("PUT", "/api/dict/types/{code}", "dict:type-manage", True),
        ("DELETE", "/api/dict/types/{code}", "dict:type-manage", True),
        ("GET", "/api/dict/items", "dict:view", True),
        ("POST", "/api/dict/items", "dict:item-manage", True),
        ("GET", "/api/dict/items/public", "dict:read", False),
        ("PUT", "/api/dict/items/{type_code}/{code}", "dict:item-manage", True),
        ("DELETE", "/api/dict/items/{type_code}/{code}", "dict:item-manage", True),
    ]
    routes = list(_iter_api_routes(client.app))

    for method, path, code, system_only in expected:
        matches = [route for p, methods, route in routes if p == path and method in methods]
        assert matches, f"{method} {path} 路由未注册"
        assert any(
            code in _resource_codes(route) for route in matches
        ), f"{method} {path} 缺 {code}"
        if system_only:
            assert any(
                _has_system_perm(route, code) for route in matches
            ), f"{method} {path} 未保持 system-only 元数据"

    naked = [
        f"{','.join(sorted(methods))} {path}"
        for path, methods, route in routes
        if path.startswith(("/api/audit", "/api/dict")) and not _resource_codes(route)
    ]
    assert not naked, f"阶段五新增端点缺精确资源码: {naked}"


def test_stage5_default_roles_me_menus_and_permissions(client, pg, users):
    tenant_admin = users(ROLE_TENANT_ADMIN)
    normal = users(ROLE_NORMAL)
    paid = users(ROLE_PAID)

    tenant_admin_me = client.get(
        "/api/auth/me",
        headers=_auth(pg, tenant_admin["id"], tenant_admin["tenant_id"]),
    )
    assert tenant_admin_me.status_code == 200
    ta_data = tenant_admin_me.json()["data"]
    ta_menus = _menu_indexes(ta_data["menus"])
    ta_perms = set(ta_data["permissions"])
    assert "/system/audit" in ta_menus
    assert "/system/dicts" not in ta_menus
    assert "audit:view" in ta_perms
    assert "dict:read" in ta_perms
    assert not {"dict:view", "dict:type-manage", "dict:item-manage"} & ta_perms

    for user in (normal, paid):
        resp = client.get("/api/auth/me", headers=_auth(pg, user["id"], user["tenant_id"]))
        assert resp.status_code == 200
        data = resp.json()["data"]
        menus = _menu_indexes(data["menus"])
        perms = set(data["permissions"])
        assert "/system/audit" not in menus
        assert "/system/dicts" not in menus
        assert "audit:view" not in perms
        assert "dict:read" in perms
        assert not {"dict:view", "dict:type-manage", "dict:item-manage"} & perms


def test_stage5_runtime_authorization_for_audit_and_dict(client, pg, users):
    tenant_admin = users(ROLE_TENANT_ADMIN)
    normal = users(ROLE_NORMAL)
    no_role = users(ROLE_NORMAL, with_role=False)

    assert client.get(
        "/api/audit",
        headers=_auth(pg, tenant_admin["id"], tenant_admin["tenant_id"]),
        params={"page": 1, "page_size": 1},
    ).status_code == 200
    assert client.get(
        "/api/audit",
        headers=_auth(pg, normal["id"], normal["tenant_id"]),
        params={"page": 1, "page_size": 1},
    ).status_code == 403

    public_dict = client.get(
        "/api/dict/items/public",
        headers=_auth(pg, normal["id"], normal["tenant_id"]),
        params={"type_code": "audit_result"},
    )
    assert public_dict.status_code == 200
    assert public_dict.json()["code"] == 0

    assert client.get(
        "/api/dict/items/public",
        headers=_auth(pg, no_role["id"], no_role["tenant_id"]),
        params={"type_code": "audit_result"},
    ).status_code == 403
    assert client.get(
        "/api/dict/types",
        headers=_auth(pg, tenant_admin["id"], tenant_admin["tenant_id"]),
    ).status_code == 403
    assert client.get(
        "/api/dict/types",
        headers=_auth(pg, normal["id"], normal["tenant_id"]),
    ).status_code == 403

    system_dicts = client.get("/api/dict/types", headers=_admin_auth(pg))
    assert system_dicts.status_code == 200
    assert system_dicts.json()["code"] == 0


def test_stage5_dict_read_baseline_anchor_locked_and_fail_closed(pg, users):
    from backend.auth.perm_resolver import resolve

    with_role = users(ROLE_NORMAL)
    no_role = users(ROLE_NORMAL, with_role=False)

    assert "dict:read" in SHARED_RESOURCE_CODES
    row = pg.query_df(
        "SELECT r.code, r.menu_id, m.visible FROM sys_resource r "
        "JOIN sys_menu m ON m.id = r.menu_id WHERE r.code=%s",
        ["dict:read"],
    ).iloc[0]
    assert row["menu_id"] == "/board"
    assert row["visible"] == "login"

    repo_row = {r["code"]: r for r in ResourceRepository(pg).list_all()}["dict:read"]
    assert repo_row["baseline_locked"] is True
    assert "dict:read" in set(resolve(with_role["id"], pg)["resources"])
    assert "dict:read" not in set(resolve(no_role["id"], pg)["resources"])


def test_stage5_menu_paths_align_frontend_routes_and_registry(pg):
    menus = {
        r["id"]: r["route_path"]
        for _, r in pg.query_df(
            "SELECT id, route_path FROM sys_menu WHERE id = ANY(%s)",
            [["/system/audit", "/system/dicts"]],
        ).iterrows()
    }
    assert menus == {
        "/system/audit": "/system/audit",
        "/system/dicts": "/system/dicts",
    }

    router_text = (_ROOT / "frontend/src/router/index.ts").read_text()
    registry_text = (_ROOT / "frontend/src/layout/pageRegistry.ts").read_text()
    for path in menus.values():
        assert f"path: '{path}'" in router_text
        assert f"path: '{path}'" in registry_text
