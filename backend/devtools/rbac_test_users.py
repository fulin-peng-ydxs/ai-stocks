"""RBAC 调试用户维护工具。

仅用于本地开发/测试库：幂等创建固定账号、调试租户、自定义角色和授权，方便浏览器手工验收
不同权限组合。生产/共享环境请不要执行。
"""

from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from backend.auth.constants import ROLE_NORMAL, ROLE_SYSTEM, ROLE_TENANT_ADMIN
from backend.auth.perm_resolver import clear_perms_cache
from backend.auth.security import check_strength, hash_password
from backend.config import get_settings
from backend.devtools.environment_guard import require_local_test_environment
from backend.storage.pg_client import PostgresClient, get_pg_client
from backend.storage.pg_ddl import DEFAULT_TENANT_ID, init_pg_db
from backend.storage.pg_identity import pg_fingerprint

DEBUG_TENANT_ID = "debug_tenant"
DEFAULT_PASSWORD = "Test@12345"
_PG_FINGERPRINT_RE = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class RoleSpec:
    id: str
    name: str
    menus: tuple[str, ...]
    resources: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class UserSpec:
    id: str
    account: str
    tenant_id: str
    role_code: str
    role_ids: tuple[str, ...]
    purpose: str


CUSTOM_ROLES: tuple[RoleSpec, ...] = (
    RoleSpec(
        "debug_role_board_only",
        "调试-仅每日榜单",
        ("/board",),
        ("board:view",),
        "仅用于验证 board:view 最小页面权限。",
    ),
    RoleSpec(
        "debug_role_stocks_only",
        "调试-仅个股行情",
        ("/stocks",),
        ("stocks:view",),
        "仅用于验证个股页主体可用且不拉自选分组。",
    ),
    RoleSpec(
        "debug_role_sectors_only",
        "调试-仅板块行情",
        ("/sectors",),
        ("sectors:view", "sector-watchlist:view", "sector-watchlist:update"),
        "用于验证板块行情、自选及无个股查看权限的成分股禁用态。",
    ),
    RoleSpec(
        "debug_role_stocks_group",
        "调试-个股+自选分组",
        ("/stocks",),
        ("stocks:view", "stock-group:view", "stock-group:member-update"),
        "用于验证个股页分组查看与成员维护。",
    ),
    RoleSpec(
        "debug_role_backtest_view",
        "调试-仅回测只读",
        ("/backtest",),
        ("backtest:view",),
        "仅用于验证回测历史只读权限。",
    ),
    RoleSpec(
        "debug_role_trade_discipline_view",
        "调试-交易纪律只读",
        ("/trade-discipline",),
        ("trade-discipline:view", "trade-discipline:checkin-view"),
        "用于验证交易纪律规则与履约历史只读边界。",
    ),
    RoleSpec(
        "debug_role_trade_discipline_submit",
        "调试-交易纪律提交",
        ("/trade-discipline",),
        (
            "trade-discipline:view",
            "trade-discipline:checkin-view",
            "trade-discipline:checkin-submit",
        ),
        "用于验证可打卡但无规则维护、无 stocks:view 的独立提交边界。",
    ),
)


DEBUG_USERS: tuple[UserSpec, ...] = (
    UserSpec("debug_system", "debug_system", DEFAULT_TENANT_ID, ROLE_SYSTEM,
             (ROLE_SYSTEM,), "系统管理员全量回归。"),
    UserSpec("debug_tenant_admin", "debug_tenant_admin", DEBUG_TENANT_ID, ROLE_TENANT_ADMIN,
             (ROLE_TENANT_ADMIN,), "租户管理员调试。"),
    UserSpec("debug_normal", "debug_normal", DEBUG_TENANT_ID, ROLE_NORMAL,
             (ROLE_NORMAL,), "普通默认业务用户。"),
    UserSpec("debug_board_only", "debug_board_only", DEBUG_TENANT_ID, ROLE_NORMAL,
             ("debug_role_board_only",), "每日榜单最小权限。"),
    UserSpec("debug_stocks_only", "debug_stocks_only", DEBUG_TENANT_ID, ROLE_NORMAL,
             ("debug_role_stocks_only",), "个股页无分组权限回归。"),
    UserSpec("debug_sectors_only", "debug_sectors_only", DEBUG_TENANT_ID, ROLE_NORMAL,
             ("debug_role_sectors_only",), "板块页无个股查看权限回归。"),
    UserSpec("debug_stocks_group", "debug_stocks_group", DEBUG_TENANT_ID, ROLE_NORMAL,
             ("debug_role_stocks_group",), "个股页分组链路调试。"),
    UserSpec("debug_backtest_view", "debug_backtest_view", DEBUG_TENANT_ID, ROLE_NORMAL,
             ("debug_role_backtest_view",), "回测历史只读调试。"),
    UserSpec(
        "debug_trade_discipline_view",
        "debug_trade_discipline_view",
        DEBUG_TENANT_ID,
        ROLE_NORMAL,
        ("debug_role_trade_discipline_view",),
        "交易纪律规则与履约历史只读调试。",
    ),
    UserSpec(
        "debug_trade_discipline_submit",
        "debug_trade_discipline_submit",
        DEBUG_TENANT_ID,
        ROLE_NORMAL,
        ("debug_role_trade_discipline_submit",),
        "交易纪律可提交但不可维护规则、不可查看个股页调试。",
    ),
)


def resolve_debug_password() -> tuple[str, str]:
    """返回 (password, source)。本地默认密码只服务开发调试。"""
    pwd = os.environ.get("AI_STOCKS_TEST_USER_PASSWORD")
    source = "AI_STOCKS_TEST_USER_PASSWORD"
    if not pwd:
        pwd = DEFAULT_PASSWORD
        source = "local-default"
    check_strength(pwd, get_settings().auth.min_password_len)
    return pwd, source


def _guard_local_test_environment() -> None:
    require_local_test_environment()


def _ensure_tenant(cur) -> None:
    now = datetime.now(UTC)
    cur.execute(
        "INSERT INTO sys_tenant (id,name,status,created_at,updated_at) "
        "VALUES (%s,%s,'active',%s,%s) "
        "ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name,status='active',updated_at=EXCLUDED.updated_at",
        [DEBUG_TENANT_ID, "RBAC 调试租户", now, now],
    )


def _ensure_custom_roles(cur) -> None:
    now = datetime.now(UTC)
    for role in CUSTOM_ROLES:
        cur.execute(
            "INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked,description,created_at,updated_at) "
            "VALUES (%s,%s,%s,'custom',FALSE,FALSE,%s,%s,%s) "
            "ON CONFLICT (id) DO UPDATE SET "
            "name=EXCLUDED.name,kind='custom',is_builtin=FALSE,is_locked=FALSE,"
            "description=EXCLUDED.description,updated_at=EXCLUDED.updated_at",
            [role.id, role.id, role.name, role.description, now, now],
        )
        cur.execute("DELETE FROM sys_role_menu WHERE role_id=%s", [role.id])
        cur.execute("DELETE FROM sys_role_resource WHERE role_id=%s", [role.id])
        for menu_id in role.menus:
            cur.execute(
                "INSERT INTO sys_role_menu (role_id,menu_id) VALUES (%s,%s) "
                "ON CONFLICT DO NOTHING",
                [role.id, menu_id],
            )
        for resource_id in role.resources:
            cur.execute(
                "INSERT INTO sys_role_resource (role_id,resource_id) VALUES (%s,%s) "
                "ON CONFLICT DO NOTHING",
                [role.id, resource_id],
            )


def _ensure_users(
    cur,
    *,
    password_hash: str,
    reset_password: bool,
    users: tuple[UserSpec, ...] = DEBUG_USERS,
) -> None:
    now = datetime.now(UTC)
    for user in users:
        cur.execute(
            "SELECT id FROM sys_user WHERE account=%s AND id<>%s",
            [user.account, user.id],
        )
        if cur.fetchone():
            raise RuntimeError(f"账号 {user.account} 已被非调试用户占用，拒绝覆盖")

        cur.execute(
            "INSERT INTO sys_user "
            "(id,tenant_id,account,email,password_hash,role_code,perm_ver,status,created_at,updated_at) "
            "VALUES (%s,%s,%s,NULL,%s,%s,0,'active',%s,%s) "
            "ON CONFLICT (id) DO UPDATE SET "
            "tenant_id=EXCLUDED.tenant_id,account=EXCLUDED.account,email=NULL,"
            "role_code=EXCLUDED.role_code,status='active',deleted_at=NULL,"
            "updated_at=EXCLUDED.updated_at",
            [user.id, user.tenant_id, user.account, password_hash, user.role_code, now, now],
        )
        if reset_password:
            cur.execute(
                "UPDATE sys_user SET password_hash=%s,updated_at=%s WHERE id=%s",
                [password_hash, now, user.id],
            )
        else:
            cur.execute(
                "UPDATE sys_user SET password_hash=COALESCE(password_hash,%s),updated_at=%s WHERE id=%s",
                [password_hash, now, user.id],
            )
        cur.execute("DELETE FROM sys_user_role WHERE user_id=%s", [user.id])
        for role_id in user.role_ids:
            cur.execute(
                "INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s) "
                "ON CONFLICT DO NOTHING",
                [user.id, role_id],
            )


def _bump_user_permissions(cur, users: tuple[UserSpec, ...] = DEBUG_USERS) -> None:
    """让本次被校准用户的既有 token 失效；须与用户/角色校准处于同一事务。"""
    user_ids = [user.id for user in users]
    cur.execute(
        "UPDATE sys_user SET perm_ver=perm_ver+1 WHERE id=ANY(%s)",
        [user_ids],
    )


def ensure_debug_users(
    *,
    reset_password: bool = True,
    expected_pg_fingerprint: str | None = None,
    pg: PostgresClient | None = None,
) -> dict:
    """幂等创建/校准调试租户、角色、用户。返回摘要。"""
    _guard_local_test_environment()
    pg = pg or get_pg_client()
    if expected_pg_fingerprint is not None:
        if not _PG_FINGERPRINT_RE.fullmatch(expected_pg_fingerprint):
            raise RuntimeError("缺少合法的 64 位 PostgreSQL 指纹，拒绝校准调试账号")
        actual_fingerprint = pg_fingerprint(pg)
        if not secrets.compare_digest(actual_fingerprint, expected_pg_fingerprint):
            raise RuntimeError("调试账号 PostgreSQL 与被测后端不一致，拒绝执行数据写入")
    init_pg_db(pg)
    password, source = resolve_debug_password()
    pwd_hash = hash_password(password)

    with pg.transaction() as conn, conn.cursor() as cur:
        _ensure_tenant(cur)
        _ensure_custom_roles(cur)
        _ensure_users(cur, password_hash=pwd_hash, reset_password=reset_password)
        cur.execute(
            "UPDATE sys_tenant SET admin_user_id=%s WHERE id=%s",
            ["debug_tenant_admin", DEBUG_TENANT_ID],
        )
        _bump_user_permissions(cur)
    clear_perms_cache([user.id for user in DEBUG_USERS])
    return {
        "tenant_id": DEBUG_TENANT_ID,
        "users": [u.account for u in DEBUG_USERS],
        "password_source": source,
        "password": password,
        "reset_password": reset_password,
    }


def list_debug_users(pg: PostgresClient | None = None) -> list[dict]:
    """列出调试用户；读取入口同样只允许明确的本地或测试环境。"""
    _guard_local_test_environment()
    pg = pg or get_pg_client()
    accounts = [u.account for u in DEBUG_USERS]
    df = pg.query_df(
        "SELECT u.id,u.account,u.tenant_id,u.role_code,u.status,u.perm_ver,"
        "COALESCE(array_agg(r.code ORDER BY r.code) FILTER (WHERE r.code IS NOT NULL),'{}') AS roles "
        "FROM sys_user u LEFT JOIN sys_user_role ur ON ur.user_id=u.id "
        "LEFT JOIN sys_role r ON r.id=ur.role_id "
        "WHERE u.account=ANY(%s) GROUP BY u.id ORDER BY u.account",
        [accounts],
    )
    if df.empty:
        return []
    return [row.to_dict() for _, row in df.iterrows()]


def user_specs() -> tuple[UserSpec, ...]:
    return DEBUG_USERS
