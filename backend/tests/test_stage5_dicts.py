"""阶段五 T6：数据字典后端闭环。"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth.security import hash_password
from backend.services.dict_service import DictService
from backend.storage.user_repository import UserRepository

_SECRET = "unit-test-stage5-dicts-0123456789-abcdef"


@pytest.fixture()
def client(monkeypatch, pg, redis_cli):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.main import create_app

    return TestClient(create_app())


def _token(pg, user_id: str, tenant_id: str) -> str:
    from backend.auth.jwt_tokens import issue_access

    pv = int(
        pg.query_df("SELECT perm_ver FROM sys_user WHERE id=%s", [user_id]).iloc[0]["perm_ver"]
    )
    return "Bearer " + issue_access(user_id, tenant_id, pv)


def _admin_headers(pg) -> dict:
    return {"Authorization": _token(pg, "admin", "default")}


def _new_tenant_admin(pg) -> dict:
    account = f"stage5_dict_{uuid.uuid4().hex[:10]}"
    return UserRepository(pg).register_tenant_and_admin(
        account,
        f"{account}@ex.com",
        hash_password("GoodPass1"),
    )


def _cleanup_type(pg, type_code: str) -> None:
    pg.execute("DELETE FROM dict_item WHERE type_code=%s", [type_code])
    pg.execute("DELETE FROM dict_type WHERE code=%s", [type_code])
    pg.execute("DELETE FROM audit_log WHERE target_id LIKE %s", [f"{type_code}%"])


def test_stage5_dict_crud_code_immutable_delete_guard_and_audit(client, pg):
    type_code = f"stage5_dict_{uuid.uuid4().hex[:8]}"
    item_code = "alpha"
    _cleanup_type(pg, type_code)

    create_type = client.post(
        "/api/dict/types",
        headers=_admin_headers(pg),
        json={"code": type_code, "name": "阶段五字典", "sort": 9},
    )
    assert create_type.status_code == 200
    assert create_type.json()["data"]["code"] == type_code

    duplicate = client.post(
        "/api/dict/types",
        headers=_admin_headers(pg),
        json={"code": type_code, "name": "重复"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["code"] == 4000

    change_code = client.put(
        f"/api/dict/types/{type_code}",
        headers=_admin_headers(pg),
        json={"code": f"{type_code}_new", "name": "阶段五字典", "enabled": True, "sort": 10},
    )
    assert change_code.status_code == 200
    assert change_code.json()["code"] == 4000

    create_item = client.post(
        "/api/dict/items",
        headers=_admin_headers(pg),
        json={"type_code": type_code, "code": item_code, "label": "Alpha", "sort": 1},
    )
    assert create_item.status_code == 200
    assert create_item.json()["data"]["code"] == item_code

    item_change_code = client.put(
        f"/api/dict/items/{type_code}/{item_code}",
        headers=_admin_headers(pg),
        json={
            "type_code": type_code,
            "code": "beta",
            "label": "Alpha",
            "enabled": True,
            "sort": 2,
        },
    )
    assert item_change_code.status_code == 200
    assert item_change_code.json()["code"] == 4000

    delete_type_with_item = client.delete(
        f"/api/dict/types/{type_code}", headers=_admin_headers(pg)
    )
    assert delete_type_with_item.status_code == 200
    assert delete_type_with_item.json()["code"] == 4000

    delete_item = client.delete(
        f"/api/dict/items/{type_code}/{item_code}",
        headers=_admin_headers(pg),
    )
    assert delete_item.status_code == 200
    assert delete_item.json()["code"] == 0

    delete_type = client.delete(f"/api/dict/types/{type_code}", headers=_admin_headers(pg))
    assert delete_type.status_code == 200
    assert delete_type.json()["code"] == 0

    audits = pg.query_df(
        "SELECT action FROM audit_log WHERE event_category='dict' "
        "AND target_id LIKE %s ORDER BY event_time",
        [f"{type_code}%"],
    )["action"].tolist()
    assert {"type_create", "item_create", "item_delete", "type_delete"} <= set(audits)


def test_stage5_dict_public_read_baseline_and_disabled_filter(client, pg):
    type_code = f"stage5_public_{uuid.uuid4().hex[:8]}"
    _cleanup_type(pg, type_code)
    tenant_admin = _new_tenant_admin(pg)
    try:
        headers = _admin_headers(pg)
        client.post(
            "/api/dict/types",
            headers=headers,
            json={"code": type_code, "name": "公开消费字典"},
        )
        client.post(
            "/api/dict/items",
            headers=headers,
            json={
                "type_code": type_code,
                "code": "enabled_item",
                "label": "启用项",
                "enabled": True,
            },
        )
        client.post(
            "/api/dict/items",
            headers=headers,
            json={
                "type_code": type_code,
                "code": "disabled_item",
                "label": "停用项",
                "enabled": False,
            },
        )

        public = client.get(
            "/api/dict/items/public",
            headers={"Authorization": _token(pg, tenant_admin["id"], tenant_admin["tenant_id"])},
            params={"type_code": type_code},
        )
        assert public.status_code == 200
        data = public.json()["data"]
        assert data["fallback"] is False
        assert [item["code"] for item in data["items"]] == ["enabled_item"]
    finally:
        _cleanup_type(pg, type_code)
        pg.execute("DELETE FROM sys_user WHERE id=%s", [tenant_admin["id"]])
        pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tenant_admin["tenant_id"]])


def test_stage5_dict_fallback_builtin_when_repo_fails():
    class BrokenRepo:
        def get_type(self, type_code):  # noqa: ARG002
            raise RuntimeError("dict storage down")

    data = DictService(BrokenRepo()).get_enabled_items("audit_result")  # type: ignore[arg-type]
    assert data["fallback"] is True
    assert [item["code"] for item in data["items"]] == ["success", "failed", "denied"]
