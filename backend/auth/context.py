"""请求认证上下文（ContextVar）+ 归属解析——多租户 RBAC stage2·T5。

鉴权中间件在请求入口 set 当前用户上下文；资产仓库经 get_current_owner() 取归属。
- 有上下文（认证请求）→ 用 token 归属：tenant_id + user_id（作 owner_user_id）。
- 无上下文（CLI/后台/迁移/测试/白名单）→ 回落默认 default/admin（保持阶段一行为，向后兼容）。
  说明（评审 P1）：受控 HTTP 请求**必经中间件 set 上下文**，故请求链不会静默回落 admin；
  回落只发生在非请求代码路径，那里 default/admin 正是期望值。
- system_context()：CLI/后台任务显式声明系统上下文（可选；不用也会回落 default/admin）。
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from backend.common.exceptions import AuthError
from backend.storage.pg_ddl import DEFAULT_OWNER_USER_ID, DEFAULT_TENANT_ID


@dataclass(frozen=True)
class AuthContext:
    """请求认证上下文（stage3 瘦令牌）：身份 + 解析后的有效权限。

    role 单列已去除；改为 roles(多角色) + is_system(超管短路) + menus/resources(权限码集)。
    权限由中间件经 perm_resolver 解析（缓存优先）后注入，供 require_perm/require_system 判定。
    """
    user_id: str        # 作 owner_user_id（资产归属键）
    tenant_id: str
    roles: tuple[str, ...] = ()
    is_system: bool = False
    menus: frozenset[str] = frozenset()
    resources: frozenset[str] = frozenset()


_ctx: contextvars.ContextVar[AuthContext | None] = contextvars.ContextVar(
    "auth_ctx", default=None)
# 由鉴权中间件对每个 HTTP 请求置 True：标记"当前在请求链内"，用于区分请求路径与 CLI/后台/测试。
_in_request: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "auth_in_request", default=False)
_resource_code: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "auth_resource_code", default=None)


def set_context(ctx: AuthContext) -> contextvars.Token:
    return _ctx.set(ctx)


def reset_context(token: contextvars.Token) -> None:
    _ctx.reset(token)


def enter_request() -> contextvars.Token:
    return _in_request.set(True)


def exit_request(token: contextvars.Token) -> None:
    _in_request.reset(token)


def get_current_context() -> AuthContext | None:
    return _ctx.get()


def set_current_resource_code(code: str | None) -> None:
    _resource_code.set(code)


def get_current_resource_code() -> str | None:
    return _resource_code.get()


def clear_current_resource_code() -> None:
    _resource_code.set(None)


def get_current_owner() -> tuple[str, str]:
    """返回 (tenant_id, owner_user_id)。

    - 有认证上下文 → token 归属（tenant_id + user_id）。
    - **请求链内却无上下文 → 报错**（防中间件注入失败/白名单误配/调用路径错误被静默掩盖成 admin，评审 P0）。
    - 非请求路径（CLI/后台/迁移/测试，无中间件）→ 回落默认 default/admin。
    """
    ctx = _ctx.get()
    if ctx is not None:
        return ctx.tenant_id, ctx.user_id
    if _in_request.get():
        raise AuthError("请求缺少认证上下文")
    return DEFAULT_TENANT_ID, DEFAULT_OWNER_USER_ID


def get_current_roles() -> tuple[str, ...]:
    ctx = _ctx.get()
    return ctx.roles if ctx else ()


def is_current_system() -> bool:
    """当前上下文是否 system（无上下文=False）。"""
    ctx = _ctx.get()
    return bool(ctx and ctx.is_system)


@contextmanager
def system_context() -> Iterator[None]:
    """显式系统上下文（CLI/后台/迁移用）：归属 default/admin、is_system=True（全权）。"""
    from backend.auth.constants import ROLE_SYSTEM

    token = _ctx.set(AuthContext(
        user_id=DEFAULT_OWNER_USER_ID, tenant_id=DEFAULT_TENANT_ID,
        roles=(ROLE_SYSTEM,), is_system=True))
    try:
        yield
    finally:
        _ctx.reset(token)
