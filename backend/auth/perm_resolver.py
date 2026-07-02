"""权限解析 + 失效编排（多租户 RBAC stage3·T2）。

`resolve(user_id)` 把 user_id 解析为有效权限集（角色码 / is_system / 菜单码 / 功能码 / perm_ver）：
- system 角色（code=system 或 kind=system）→ **全量**菜单+功能（不看 role_menu 授权）；
- 其余角色 → 各自 role_menu / role_resource 的并集。
权威在 PG；Redis 缓存 `auth:perms:{user_id}` 的读写由中间件(T3)编排，本模块提供 resolve() 供回填。

失效编排（bump_*）：任何改变用户有效权限的操作 → 相关用户 perm_ver+1(PG) + 清 perms/pv 缓存。
因 stage2「token.perm_ver ≠ 当前 → 401 重登」，受影响用户下次请求 401、重登后拿新权限
（= R11「perm_ver 自增、即时生效」口径）。PG 耦合在本模块（session_store 保持纯 Redis）。
"""

from __future__ import annotations

from collections.abc import Iterable

from backend.auth import session_store
from backend.auth.constants import ROLE_SYSTEM
from backend.common.logging import get_logger
from backend.storage.pg_client import PostgresClient, get_pg_client

log = get_logger("auth.perm_resolver")


def resolve(user_id: str, client: PostgresClient | None = None) -> dict:
    """解析用户有效权限。返回 {roles, is_system, menus, resources, perm_ver}。"""
    client = client or get_pg_client()
    roles_df = client.query_df(
        "SELECT ur.role_id, r.code, r.kind FROM sys_user_role ur "
        "JOIN sys_role r ON r.id = ur.role_id WHERE ur.user_id = %s", [user_id])
    role_ids = roles_df["role_id"].tolist() if not roles_df.empty else []
    role_codes = roles_df["code"].tolist() if not roles_df.empty else []
    is_system = (ROLE_SYSTEM in role_codes) or (
        not roles_df.empty and bool((roles_df["kind"] == "system").any()))

    pv_df = client.query_df("SELECT perm_ver FROM sys_user WHERE id = %s", [user_id])
    perm_ver = int(pv_df.iloc[0]["perm_ver"]) if not pv_df.empty else 0

    if is_system:   # 超管看全量，不受 role_menu 授权约束
        menus = client.query_df("SELECT code FROM sys_menu")["code"].tolist()
        resources = client.query_df("SELECT code FROM sys_resource")["code"].tolist()
    elif role_ids:
        menus = client.query_df(
            "SELECT DISTINCT m.code FROM sys_role_menu rm "
            "JOIN sys_menu m ON m.id = rm.menu_id WHERE rm.role_id = ANY(%s)",
            [role_ids])["code"].tolist()
        resources = client.query_df(
            "SELECT DISTINCT r.code FROM sys_role_resource rr "
            "JOIN sys_resource r ON r.id = rr.resource_id WHERE rr.role_id = ANY(%s)",
            [role_ids])["code"].tolist()
    else:           # 无角色：空权限（fail-closed）
        menus, resources = [], []

    return {
        "roles": role_codes,
        "is_system": bool(is_system),
        "menus": menus,
        "resources": resources,
        "perm_ver": perm_ver,
    }


# ── 失效编排 ──────────────────────────────────────────────────────────────────

def bump_and_invalidate(user_ids: Iterable[str], client: PostgresClient | None = None) -> int:
    """相关用户 perm_ver+1(PG) + 清 perms/pv 缓存。返回受影响用户数。

    缓存清理走 session_store（_critical fail-closed）：Redis 不可用则抛 503——此时中间件同样
    fail-closed（读不到 pv/perms），全站拒绝，语义一致；调用方（写接口）拿到 503 可重试。
    """
    uids = [u for u in dict.fromkeys(user_ids) if u]   # 去重去空、保序
    if not uids:
        return 0
    client = client or get_pg_client()
    client.execute("UPDATE sys_user SET perm_ver = perm_ver + 1 WHERE id = ANY(%s)", [uids])
    for uid in uids:
        session_store.clear_perms(uid)
        session_store.invalidate_perm_ver(uid)
    log.info("perm bump: %d 个用户权限失效（下次请求需重登）", len(uids))
    return len(uids)


def bump_users_of_roles(role_ids: Iterable[str], client: PostgresClient | None = None) -> int:
    """角色授权/删除变更 → 拥有这些角色的全部用户失效。"""
    rids = [r for r in dict.fromkeys(role_ids) if r]
    if not rids:
        return 0
    client = client or get_pg_client()
    df = client.query_df(
        "SELECT DISTINCT user_id FROM sys_user_role WHERE role_id = ANY(%s)", [rids])
    return bump_and_invalidate(df["user_id"].tolist() if not df.empty else [], client)


def bump_users_of_menu(menu_id: str, client: PostgresClient | None = None) -> int:
    """菜单删除/可见性变更 → 引用它的角色的用户 ∪ 全部 system 用户（超管看全量菜单，结构变更也影响）。"""
    client = client or get_pg_client()
    df = client.query_df(
        "SELECT DISTINCT ur.user_id FROM sys_role_menu rm "
        "JOIN sys_user_role ur ON ur.role_id = rm.role_id WHERE rm.menu_id = %s", [menu_id])
    uids = set(df["user_id"].tolist()) if not df.empty else set()
    uids |= set(_system_user_ids(client))
    return bump_and_invalidate(uids, client)


def bump_users_of_resource(resource_id: str, client: PostgresClient | None = None) -> int:
    """功能点删除/改绑 → 引用它的角色的用户 ∪ 全部 system 用户。"""
    client = client or get_pg_client()
    df = client.query_df(
        "SELECT DISTINCT ur.user_id FROM sys_role_resource rr "
        "JOIN sys_user_role ur ON ur.role_id = rr.role_id WHERE rr.resource_id = %s", [resource_id])
    uids = set(df["user_id"].tolist()) if not df.empty else set()
    uids |= set(_system_user_ids(client))
    return bump_and_invalidate(uids, client)


def bump_users_of_tenant(tenant_id: str, client: PostgresClient | None = None) -> int:
    """租户停用 → 该租户全部用户失效（下次请求 401，重登被 status 校验拒绝）。"""
    client = client or get_pg_client()
    df = client.query_df("SELECT id FROM sys_user WHERE tenant_id = %s", [tenant_id])
    return bump_and_invalidate(df["id"].tolist() if not df.empty else [], client)


def _system_user_ids(client: PostgresClient) -> list[str]:
    """全部拥有 system 角色的用户 id（菜单/功能结构变更影响其全量视图）。"""
    df = client.query_df(
        "SELECT DISTINCT ur.user_id FROM sys_user_role ur JOIN sys_role r ON r.id = ur.role_id "
        "WHERE r.code = %s OR r.kind = 'system'", [ROLE_SYSTEM])
    return df["user_id"].tolist() if not df.empty else []
