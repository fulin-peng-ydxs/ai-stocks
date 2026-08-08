"""阶段四 T8：资源码全接入路由扫描 + 基线共享读 + 动态 scope + 跨账号隔离（后端权限总回归）。

证明「无漏接、无越权、无误伤」：
- **路由扫描**：① 所有非白名单 /api 路由都有守卫（精确资源码依赖 或 require_system 硬守卫）——无裸露端点；
  ② 13 个 stage4 业务/数据模块的每个端点都挂了**精确资源码**（require_perm / require_system_perm），
  唯一豁免是登记过的动态 scope 自守卫端点 `POST /api/layout/reset`。
- **基线共享读**：自定义角色未授任何业务码，仍能读全站基线（交易日历 / 指标目录 / 布局预设·页面·生效）。
- **基线不可反选**：role_resource 不含基线码，`/me.permissions` 仍强制含基线三码。
- **动态 scope**：`POST /api/layout/reset` system 两种 scope 均通过。
- **跨账号隔离**：用户级布局配置不能互读（归属取自上下文）。

真实 PG/Redis + JWT。TestClient（不进 lifespan）。临时租户/用户/角色清理。
其余权限样例（system-only tenant_admin 403 / 硬守卫不降级 / 榜单公共读私有隔离 / reset 非 system 403）见
test_stage4_systemonly、test_stage4_board、test_stage4_layout、test_stage4_menu_guard、test_auth_middleware。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

_SECRET = "test-secret-stage4-rescodes-0123456789abcdef"   # ≥32B 免 HMAC 长度告警

# 白名单：无需精确资源码的 /api 路由前缀。
_PUBLIC_PREFIXES = ("/api/health", "/api/auth/")
# stage3 平台管理模块（整 router require_system 或逐端点 require_perm；不在 stage4 13 模块的"须有精确码"约束内）。
_MANAGE_PREFIXES = ("/api/users", "/api/roles", "/api/menus", "/api/resources", "/api/tenants")
# stage4 13 存量业务/数据模块前缀（每端点须有精确资源码）。
_STAGE4_PREFIXES = (
    "/api/stocks", "/api/board", "/api/profiles", "/api/screen",
    "/api/score-profiles", "/api/trade-profiles", "/api/stock-groups", "/api/backtest",
    "/api/training", "/api/layout", "/api/config", "/api/indicators", "/api/data",
)
# 动态 scope 自守卫端点（函数体内按 payload scope 分流守卫，无静态资源码依赖；扫描白名单登记，见 layout.py）。
_DYNAMIC_SCOPE_ROUTES = {"/api/layout/reset"}
_HTTP_VERBS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


@pytest.fixture()
def client(monkeypatch, pg, redis_cli):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.main import create_app
    return TestClient(create_app())


def _auth(uid: str, tid: str, pv: int = 0) -> dict:
    from backend.auth.jwt_tokens import issue_access
    return {"Authorization": "Bearer " + issue_access(uid, tid, pv)}


def _admin_auth(pg) -> dict:
    pv = int(pg.query_df("SELECT perm_ver FROM sys_user WHERE id='admin'").iloc[0]["perm_ver"])
    return _auth("admin", "default", pv)


def _mk_user(pg, codes: list[str]) -> tuple[str, str, str]:
    """建租户 + 非 system 用户 + 自定义角色（授予 codes）+ 关联，返回 (uid, tid, rid)。"""
    tid = "s4rc_t_" + uuid.uuid4().hex[:8]
    uid = "s4rc_u_" + uuid.uuid4().hex[:8]
    rid = "s4rc_r_" + uuid.uuid4().hex[:8]
    pg.execute("INSERT INTO sys_tenant (id,name,status) VALUES (%s,'t','active') ON CONFLICT DO NOTHING", [tid])
    pg.execute("INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
               "VALUES (%s,%s,%s,'normal',0,'active')", [uid, tid, uid])
    pg.execute("INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
               "VALUES (%s,%s,'t8','custom',FALSE,FALSE)", [rid, rid])
    pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)", [uid, rid])
    for c in codes:
        pg.execute("INSERT INTO sys_role_resource (role_id,resource_id) VALUES (%s,%s) "
                   "ON CONFLICT DO NOTHING", [rid, c])
    return uid, tid, rid


def _rm_user(pg, uid, tid, rid) -> None:
    pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    pg.execute("DELETE FROM sys_role WHERE id=%s", [rid])
    pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])


def _route_dep_calls(route) -> list:
    """该路由全部依赖的可调用对象（含 include_router 注入的 router 级依赖）。"""
    return [d.call for d in route.dependant.dependencies if getattr(d, "call", None) is not None]


def _has_resource_code(route) -> bool:
    return any(hasattr(c, "resource_code") for c in _route_dep_calls(route))


def _has_system_guard(route) -> bool:
    from backend.auth.deps import require_system
    return any(c is require_system or getattr(c, "__name__", "") == "require_system"
               for c in _route_dep_calls(route))


def _iter_api_routes(app):
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = (getattr(route, "methods", None) or set()) & _HTTP_VERBS
        if path.startswith("/api/") and methods:
            yield path, methods, route


# ── ① 路由扫描：无裸露端点 + stage4 精确码全接入 ──────────────────────────────

def test_no_unguarded_api_route(client):
    """所有非白名单 /api 路由都有守卫（精确码 或 require_system 硬守卫）——无裸露端点。"""
    naked = []
    for path, _methods, route in _iter_api_routes(client.app):
        if path.startswith(_PUBLIC_PREFIXES) or path in _DYNAMIC_SCOPE_ROUTES:
            continue
        if not (_has_resource_code(route) or _has_system_guard(route)):
            naked.append(path)
    assert not naked, f"存在无守卫的 /api 端点: {sorted(set(naked))}"


def test_stage4_business_routes_have_precise_code(client):
    """13 个 stage4 业务/数据模块的每个端点都挂精确资源码（唯一豁免：动态 scope /api/layout/reset）。"""
    missing = []
    for path, _methods, route in _iter_api_routes(client.app):
        if path in _DYNAMIC_SCOPE_ROUTES:
            continue
        # 属 stage4 前缀但排除平台管理模块（/api/users 等；注意 /api/data 属 stage4）
        if path.startswith(_STAGE4_PREFIXES) and not path.startswith(_MANAGE_PREFIXES):
            if not _has_resource_code(route):
                missing.append(path)
    assert not missing, f"stage4 端点缺精确资源码: {sorted(set(missing))}"


# ── ② 基线共享读：自定义角色未授业务码，仍能读全站基线 ──────────────────────

_BASELINE_READS = [
    ("GET", "/api/data/trade-dates"),               # trade-calendar:view
    ("GET", "/api/indicators/registry"),            # indicator:registry
    ("GET", "/api/layout/presets"),                 # layout:view
    ("GET", "/api/layout/pages/board"),             # layout:view
    ("GET", "/api/layout/effective/board"),         # layout:view
]


@pytest.mark.parametrize("method,path", _BASELINE_READS)
def test_baseline_shared_read_ok_without_business_code(client, pg, method, path):
    """自定义角色 role_resource 为空（仅 baseline 注入）→ 基线读接口非 401/403。"""
    uid, tid, rid = _mk_user(pg, codes=[])
    try:
        r = client.request(method, path, headers=_auth(uid, tid))
        assert r.status_code not in (401, 403), f"{path} 基线读被误挡（baseline 未生效）"
    finally:
        _rm_user(pg, uid, tid, rid)


def test_business_code_absent_blocks_non_baseline_read(client, pg):
    """对比：非基线业务读（个股行情 stocks:view）无码 → 403（证明上面的放行来自 baseline 而非全放行）。"""
    uid, tid, rid = _mk_user(pg, codes=[])
    try:
        r = client.get("/api/stocks", headers=_auth(uid, tid))
        assert r.status_code == 403 and r.json()["code"] == 4030
    finally:
        _rm_user(pg, uid, tid, rid)


# ── ③ 基线不可反选：/me.permissions 恒含全部基线码 ──────────────────────────

def test_me_permissions_force_include_baseline(client, pg):
    """自定义角色只授业务码、role_resource 不含基线 → GET /api/auth/me 的 permissions 仍强制含基线码。"""
    from backend.auth.constants import SHARED_RESOURCE_CODES
    uid, tid, rid = _mk_user(pg, codes=["backtest:view"])
    try:
        r = client.get("/api/auth/me", headers=_auth(uid, tid))
        assert r.status_code == 200
        perms = set(r.json()["data"]["permissions"])
        assert set(SHARED_RESOURCE_CODES) <= perms
        assert "backtest:view" in perms
    finally:
        _rm_user(pg, uid, tid, rid)


# ── ④ 权限样例：无码写 403 / 有码进业务层 ───────────────────────────────────

def test_business_write_requires_code(client, pg):
    body = {"id": "p_" + uuid.uuid4().hex[:6], "name": "t", "expression": {"op": "AND", "children": []}}
    no_uid, no_tid, no_rid = _mk_user(pg, codes=[])
    ok_uid, ok_tid, ok_rid = _mk_user(pg, codes=["screen-profile:save"])
    try:
        assert client.post("/api/profiles", json=body, headers=_auth(no_uid, no_tid)).status_code == 403
        # 有码 → 过守卫进业务层（业务成功 200 或校验失败 400，均非 401/403）
        assert client.post("/api/profiles", json=body,
                           headers=_auth(ok_uid, ok_tid)).status_code not in (401, 403)
    finally:
        _rm_user(pg, no_uid, no_tid, no_rid)
        _rm_user(pg, ok_uid, ok_tid, ok_rid)


# ── ⑤ 动态 scope：system 两 scope 均通过 ───────────────────────────────────

@pytest.mark.parametrize("scope", ["page", "user"])
def test_reset_system_passes_both_scopes(client, pg, scope):
    r = client.post("/api/layout/reset", json={"scope": scope, "pageKey": "board"}, headers=_admin_auth(pg))
    assert r.status_code not in (401, 403)


# ── ⑥ 跨账号隔离：用户级布局配置不能互读（归属取自上下文）──────────────────

def test_layout_user_config_cross_account_isolated(client, pg):
    a_uid, a_tid, a_rid = _mk_user(pg, codes=["layout:user-config"])
    b_uid, b_tid, b_rid = _mk_user(pg, codes=["layout:user-config"])
    pk = "iso" + uuid.uuid4().hex[:6]
    try:
        # A 写入个人偏好
        r = client.post(f"/api/layout/users/{pk}",
                        json={"config": {"values": {"density": "compact"}}}, headers=_auth(a_uid, a_tid))
        assert r.status_code == 200
        # B 读同一 pageKey → 拿不到 A 的值（各自归属；B 为空/默认，不含 A 的 density=compact）
        rb = client.get(f"/api/layout/users/{pk}", headers=_auth(b_uid, b_tid))
        assert rb.status_code == 200
        b_values = (rb.json()["data"] or {}).get("config", {}).get("values", {})
        assert b_values.get("density") != "compact", "B 读到了 A 的用户级配置（跨账号串数据）"
    finally:
        pg.execute("DELETE FROM layout_user_config WHERE page_key=%s", [pk])
        _rm_user(pg, a_uid, a_tid, a_rid)
        _rm_user(pg, b_uid, b_tid, b_rid)
