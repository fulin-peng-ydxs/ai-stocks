"""权限解析 + 失效编排（多租户 RBAC stage3·T2）。

`resolve(user_id)` 把 user_id 解析为有效权限集（角色码 / is_system / 菜单码 / 功能码 / perm_ver）：
- system 角色（code=system 或 kind=system）→ **全量**菜单+功能（不看 role_menu 授权）；
- 其余角色 → 各自 role_menu / role_resource 的并集。
权威在 PG；Redis 缓存 `auth:perms:{user_id}` 的读写由中间件(T3)编排，本模块提供 resolve() 供回填。

失效编排（bump_*）：任何改变用户有效权限的操作 → 相关用户 perm_ver+1(PG) + 清 perms/pv 缓存。
因 stage2「token.perm_ver ≠ 当前 → 401 重登」，受影响用户下次请求 401、重登后拿新权限
（= R11「perm_ver 自增、即时生效」口径）。PG 耦合在本模块（session_store 保持纯 Redis）。

**调用契约（Codex P1 整改）：bump_* 必须在业务写入之**前**调用。** 内部顺序为「清 Redis 缓存
(fail-closed)→自增 PG perm_ver→**再清一次 Redis 缓存**」（延迟双删）：
- 首清 fail-closed：Redis 不可用则在改动任何持久状态前即抛 503，调用方业务写入随之中止，绝不出现
  「DB 已改但 Redis 清理失败、旧 auth:pv 残留继续放行旧 token」的 fail-open。
- 自增 PG（权威）后**再清一次**：关闭「首清与自增之间的并发窗口」——该窗口内别的请求可能因缓存 miss
  回查到**尚未自增**的旧 perm_ver 并回填 Redis；二次清理抹掉此回填，使下一次读必回查已自增的 PG →
  旧 token perm_ver 失配 → 401（Codex 第二轮 P1）。即便自增后二次清理失败（503），业务写入仍中止、
  仅 perm_ver 已+1（over-invalidate，用户被迫重登，非 fail-open），且极窄残留由缓存 TTL 收敛。
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
    """相关用户 **清 perms/pv 缓存(Redis)→perm_ver+1(PG)→再清一次缓存**（延迟双删）。返回受影响用户数。

    顺序刻意为「Redis 首清 → PG 自增 → Redis 二次清理」（Codex 两轮 P1 整改）：
    - ① 首清走 session_store（_critical fail-closed）：Redis 不可用则抛 503，此时 **PG perm_ver 尚未
      自增**；因调用方在业务写入前调用本函数，业务写入也随之中止 → 无任何持久状态被改，不产生 fail-open。
    - ② Redis 清成功后再自增 PG（权威）。
    - ③ 自增后**再清一次**：关闭①与②之间的并发回填窗口——该窗口内并发请求可能因缓存 miss 回查到尚未
      自增的旧 perm_ver 并回填 Redis，二次清理抹掉它，使下次读必回查已自增的 PG → 旧 token 401。
    """
    uids = [u for u in dict.fromkeys(user_ids) if u]   # 去重去空、保序
    if not uids:
        return 0
    client = client or get_pg_client()
    _clear_user_caches(uids)       # ① 首清（fail-closed）：Redis 不可用即抛，尚未动 PG
    # ② 缓存清理成功后再自增 PG perm_ver（权威）
    client.execute("UPDATE sys_user SET perm_ver = perm_ver + 1 WHERE id = ANY(%s)", [uids])
    _clear_user_caches(uids)       # ③ 二次清理：抹掉①与②窗口内并发回填的旧值（关闭回填竞态）
    log.info("perm bump: %d 个用户权限失效（下次请求需重登）", len(uids))
    return len(uids)


def _clear_user_caches(uids: Iterable[str]) -> None:
    """清若干用户的有效权限缓存 + perm_ver 缓存（_critical fail-closed，Redis 不可用即抛 503）。"""
    for uid in uids:
        session_store.clear_perms(uid)
        session_store.invalidate_perm_ver(uid)


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
    """菜单删除/可见性变更/移动 → 引用「该菜单**及其全部子孙**」的角色的用户 ∪ 全部 system 用户。

    子树纳入（Codex 第二轮 P2-c）：`/me` 可见性由**祖先链**决定（父分组 visible=system 或被移动跨可见域
    → 整棵子树对非 system 用户隐藏）。角色可能只授到**子孙叶子**、未授父节点，只 bump 当前节点会漏掉
    这些用户、其缓存菜单残留到 TTL。故用递归 CTE 收「当前节点 + 全部后代」被引用的角色用户一并失效。
    （叶子无后代时 CTE 只返回自身，等价旧行为；删除仅发生在无子节点菜单上，子树亦仅自身。）
    """
    client = client or get_pg_client()
    df = client.query_df(
        "WITH RECURSIVE sub AS ("
        "  SELECT id FROM sys_menu WHERE id = %s "
        "  UNION ALL "
        "  SELECT m.id FROM sys_menu m JOIN sub ON m.parent_id = sub.id) "
        "SELECT DISTINCT ur.user_id FROM sys_role_menu rm "
        "JOIN sub ON sub.id = rm.menu_id "
        "JOIN sys_user_role ur ON ur.role_id = rm.role_id", [menu_id])
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
