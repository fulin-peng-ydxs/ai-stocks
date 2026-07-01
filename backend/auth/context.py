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
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from backend.storage.pg_ddl import DEFAULT_OWNER_USER_ID, DEFAULT_TENANT_ID


@dataclass(frozen=True)
class AuthContext:
    user_id: str        # 作 owner_user_id（资产归属键）
    tenant_id: str
    role: str


_ctx: contextvars.ContextVar[AuthContext | None] = contextvars.ContextVar(
    "auth_ctx", default=None)


def set_context(ctx: AuthContext) -> contextvars.Token:
    return _ctx.set(ctx)


def reset_context(token: contextvars.Token) -> None:
    _ctx.reset(token)


def get_current_context() -> AuthContext | None:
    return _ctx.get()


def get_current_owner() -> tuple[str, str]:
    """返回 (tenant_id, owner_user_id)；无上下文回落 (default, admin)。"""
    ctx = _ctx.get()
    if ctx is None:
        return DEFAULT_TENANT_ID, DEFAULT_OWNER_USER_ID
    return ctx.tenant_id, ctx.user_id


def get_current_role() -> str | None:
    ctx = _ctx.get()
    return ctx.role if ctx else None


@contextmanager
def system_context() -> Iterator[None]:
    """显式系统上下文（CLI/后台/迁移用）：归属 default/admin、role=system。"""
    from backend.auth.constants import ROLE_SYSTEM

    token = _ctx.set(AuthContext(
        user_id=DEFAULT_OWNER_USER_ID, tenant_id=DEFAULT_TENANT_ID, role=ROLE_SYSTEM))
    try:
        yield
    finally:
        _ctx.reset(token)
