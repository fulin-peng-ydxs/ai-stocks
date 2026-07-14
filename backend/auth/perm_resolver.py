"""权限解析 + 失效编排（多租户 RBAC stage3·T2）。

`resolve(user_id)` 把 user_id 解析为有效权限集（角色码 / is_system / 菜单码 / 功能码 / perm_ver）：
- system 角色（code=system 或 kind=system）→ **全量**菜单+功能（不看 role_menu 授权）；
- 其余角色 → 各自 role_menu / role_resource 的并集。
权威在 PG；Redis 缓存 `auth:perms:{user_id}` 的读写由中间件(T3)编排，本模块提供 resolve() 供回填。

失效编排（bump_*）：任何改变用户有效权限的操作 → 相关用户 perm_ver+1(PG) + 清 perms 缓存。
因「token.perm_ver ≠ 当前 → 401 重登」，受影响用户下次请求 401、重登后拿新权限（= R11「即时生效」）。
**权威源在 PG（Codex 四轮 P1）**：鉴权闸门 `claims_from_bearer` 每请求以 PG 的 perm_ver + status 为准、
**不信任 Redis 缓存的 auth:pv**——故 Redis 清理失败/并发回填旧值都不会造成 fail-open；perms 缓存也由
`load_perms` 按权威 perm_ver 校验新鲜度。Redis 清缓存退化为"减少重解析"的优化，不再是正确性关键。
PG 耦合在本模块（session_store 保持纯 Redis）。

**调用契约（Codex 五轮 P1 整改，原子化）：业务写入与 `perm_ver` 自增在**同一 PG 事务**里原子提交。**
每个改权限/状态的服务操作三步走：
- ① `affected = affected_users_of_*(...)`：业务写入**前**一次性算定受影响用户（读），避免删除的级联
  （role_menu/role_resource/sys_user_role CASCADE）在写入后使集合缩水、漏掉本应失效的用户。
- ② 在一个 PG 事务内：`repo.业务写入(..., conn=conn)` + `bump_perm_ver(affected, conn)` → **原子提交**。
  权威失效（PG perm_ver 自增）与业务写入同生共死：要么都提交、要么都回滚，中间无"业务已变、版本未进"
  或"版本已进、业务未变"的窗口，也**不被 Redis 可用性左右**。
- ③ 提交后 `clear_perms_cache(affected)`：best-effort 清 Redis perms 缓存（纯优化，失败仅告警——权威在
  PG，鉴权闸门每请求以 PG perm_ver + status 为准，`load_perms` 再按 perm_ver 校验缓存新鲜度自愈）。
历史教训（前四轮都栽在非原子上）：把失效拆成"清 Redis / bump PG / 业务写入"多个独立步骤，任何两步之间
都有并发窗口或某步失败即脱钩——要么旧 token 蒙混（fail-open）、要么 Redis 故障挡住 PG 权威失效。原子化
一次性消除该类窗口。`bump_and_invalidate`（清→bump→best-effort）保留给测试/无需同事务的一次性场景。
"""

from __future__ import annotations

from collections.abc import Iterable

import redis

from backend.auth import session_store
from backend.auth.constants import ROLE_SYSTEM, SHARED_RESOURCE_CODES
from backend.common.exceptions import ServiceUnavailableError, StorageError
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
        # baseline 登录基线（共享读 + 当前用户自持久化偏好）：非 system 且有角色的业务用户**强制并入**，与 role_resource
        # 授权无关、角色页不可反选（运行时权威防线）。无角色分支不注入 → 仍 fail-closed。dedup 保序。
        resources = list(dict.fromkeys(resources + list(SHARED_RESOURCE_CODES)))
    else:           # 无角色：空权限（fail-closed，不注入 baseline）
        menus, resources = [], []

    return {
        "roles": role_codes,
        "is_system": bool(is_system),
        "menus": menus,
        "resources": resources,
        "perm_ver": perm_ver,
    }


# ── 失效编排 ──────────────────────────────────────────────────────────────────

def bump_perm_ver(user_ids: Iterable[str], conn) -> int:
    """在给定 PG 连接（调用方事务）内自增 perm_ver。**仅 PG、不碰 Redis**——供与业务写入**同事务原子提交**。

    权威失效：鉴权闸门每请求以 PG perm_ver 为准（`claims_from_bearer`），故此自增一旦随业务写入同事务
    提交，旧 token 下次请求即因 perm_ver 失配被拒，与 Redis 可用性无关；若事务回滚则一并回滚、业务亦不落库。
    返回受影响用户数（去重去空后）。
    """
    uids = [u for u in dict.fromkeys(user_ids) if u]
    if not uids:
        return 0
    conn.execute("UPDATE sys_user SET perm_ver = perm_ver + 1 WHERE id = ANY(%s)", [uids])
    return len(uids)


def clear_perms_cache(user_ids: Iterable[str]) -> None:
    """业务+bump 提交后 **best-effort** 清 Redis perms 缓存（纯优化）。

    失败仅告警、不抛——权威在 PG：闸门每请求校验 PG perm_ver + status，`load_perms` 再按 perm_ver 校验
    缓存新鲜度、拒采信陈旧内容。故 Redis 清理失败绝不影响正确性（区别于旧实现"清失败即 fail-open/挡住失效"）。
    """
    try:
        _clear_user_caches(user_ids)
    except (ServiceUnavailableError, StorageError, redis.RedisError) as e:
        log.warning("清 perms 缓存失败（best-effort，PG perm_ver 已权威失效，不影响正确性）: %s", e)


def bump_and_invalidate(user_ids: Iterable[str], client: PostgresClient | None = None) -> int:
    """一次性失效（非同事务路径）：**先自增 PG perm_ver（权威）再 best-effort 清 Redis**。返回受影响用户数。

    PG 自增优先且**不被 Redis 阻断**（Codex 五轮 P1）：先 bump PG（权威失效落定），再 best-effort 清缓存。
    供测试与"无业务写入需同事务"的场景；改状态/授权的写入路径请走 `bump_perm_ver(conn)` 与业务写入同事务
    （见模块 docstring 调用契约），以消除跨事务窗口。
    """
    uids = [u for u in dict.fromkeys(user_ids) if u]   # 去重去空、保序
    if not uids:
        return 0
    client = client or get_pg_client()
    client.execute("UPDATE sys_user SET perm_ver = perm_ver + 1 WHERE id = ANY(%s)", [uids])
    clear_perms_cache(uids)
    log.info("perm bump: %d 个用户权限失效（下次请求需重登）", len(uids))
    return len(uids)


def _clear_user_caches(uids: Iterable[str]) -> None:
    """清若干用户的有效权限缓存（+ 历史 perm_ver 缓存键，已不再读取，清之无害）。_critical：Redis 故障抛 503。"""
    for uid in uids:
        session_store.clear_perms(uid)
        session_store.invalidate_perm_ver(uid)


# ── affected 用户集计算（业务写入前算定，供同事务 bump_perm_ver + 提交后 clear_perms_cache 共用）──
# 删除类操作的级联（role_menu/role_resource/sys_user_role CASCADE）会在写入后使集合缩水，故必须在
# 业务写入**前**算定并复用同一集合，否则重算会漏掉被级联摘除关联的用户（Codex 三轮 P1）。

def affected_users_of_roles(role_ids: Iterable[str],
                            client: PostgresClient | None = None) -> list[str]:
    """拥有这些角色的全部用户。"""
    rids = [r for r in dict.fromkeys(role_ids) if r]
    if not rids:
        return []
    client = client or get_pg_client()
    df = client.query_df(
        "SELECT DISTINCT user_id FROM sys_user_role WHERE role_id = ANY(%s)", [rids])
    return df["user_id"].tolist() if not df.empty else []


def affected_users_of_menu(menu_id: str, client: PostgresClient | None = None) -> list[str]:
    """引用「该菜单**及其全部子孙**」的非 system 角色用户。

    子树纳入（Codex 第二轮 P2-c）：`/me` 可见性由**祖先链**决定（父分组 visible=system 或被移动跨可见域
    → 整棵子树对非 system 用户隐藏）。角色可能只授到**子孙叶子**、未授父节点，只算当前节点会漏掉这些
    用户、其缓存菜单残留到 TTL。故用递归 CTE 收「当前节点 + 全部后代」被引用的角色用户。
    （叶子无后代时 CTE 只返回自身，等价旧行为；删除仅发生在无子节点菜单上，子树亦仅自身。）

    system 用户拥有全量菜单，菜单可见性或层级变化不会改变其安全边界；不 bump system 用户的
    perm_ver，避免系统管理员维护菜单后被旧 token 失配踢回登录页。
    """
    client = client or get_pg_client()
    df = client.query_df(
        "WITH RECURSIVE sub AS ("
        "  SELECT id FROM sys_menu WHERE id = %s "
        "  UNION ALL "
        "  SELECT m.id FROM sys_menu m JOIN sub ON m.parent_id = sub.id) "
        "SELECT DISTINCT ur.user_id FROM sys_role_menu rm "
        "JOIN sub ON sub.id = rm.menu_id "
        "JOIN sys_user_role ur ON ur.role_id = rm.role_id "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM sys_user_role sur JOIN sys_role sr ON sr.id = sur.role_id "
        "  WHERE sur.user_id = ur.user_id AND (sr.code = %s OR sr.kind = 'system'))",
        [menu_id, ROLE_SYSTEM])
    return df["user_id"].tolist() if not df.empty else []


def affected_users_of_resource(resource_id: str,
                               client: PostgresClient | None = None) -> list[str]:
    """引用该功能点的角色的用户 ∪ 全部 system 用户。"""
    client = client or get_pg_client()
    df = client.query_df(
        "SELECT DISTINCT ur.user_id FROM sys_role_resource rr "
        "JOIN sys_user_role ur ON ur.role_id = rr.role_id WHERE rr.resource_id = %s", [resource_id])
    uids = set(df["user_id"].tolist()) if not df.empty else set()
    uids |= set(_system_user_ids(client))
    return list(uids)


def affected_users_of_tenant(tenant_id: str, client: PostgresClient | None = None) -> list[str]:
    """该租户全部用户。"""
    client = client or get_pg_client()
    df = client.query_df("SELECT id FROM sys_user WHERE tenant_id = %s", [tenant_id])
    return df["id"].tolist() if not df.empty else []


# ── 一次性失效（compute+bump 合体；供测试/无需同事务的场景直用。改状态/授权的写入路径请改用同事务
#    bump_perm_ver(conn) + 提交后 clear_perms_cache，见模块 docstring 调用契约）──

def bump_users_of_roles(role_ids: Iterable[str], client: PostgresClient | None = None) -> int:
    """角色授权/删除变更 → 拥有这些角色的全部用户失效（一次性）。"""
    client = client or get_pg_client()
    return bump_and_invalidate(affected_users_of_roles(role_ids, client), client)


def bump_users_of_menu(menu_id: str, client: PostgresClient | None = None) -> int:
    """菜单删除/可见性变更/移动 → 引用该菜单及其子孙的非 system 角色用户失效（一次性）。"""
    client = client or get_pg_client()
    return bump_and_invalidate(affected_users_of_menu(menu_id, client), client)


def bump_users_of_resource(resource_id: str, client: PostgresClient | None = None) -> int:
    """功能点删除/改绑 → 引用它的角色用户 ∪ system 用户失效（一次性）。"""
    client = client or get_pg_client()
    return bump_and_invalidate(affected_users_of_resource(resource_id, client), client)


def bump_users_of_tenant(tenant_id: str, client: PostgresClient | None = None) -> int:
    """租户停用 → 该租户全部用户失效（一次性）。"""
    client = client or get_pg_client()
    return bump_and_invalidate(affected_users_of_tenant(tenant_id, client), client)


def _system_user_ids(client: PostgresClient) -> list[str]:
    """全部拥有 system 角色的用户 id（菜单/功能结构变更影响其全量视图）。"""
    df = client.query_df(
        "SELECT DISTINCT ur.user_id FROM sys_user_role ur JOIN sys_role r ON r.id = ur.role_id "
        "WHERE r.code = %s OR r.kind = 'system'", [ROLE_SYSTEM])
    return df["user_id"].tolist() if not df.empty else []
