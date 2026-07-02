"""鉴权路由依赖（多租户 RBAC stage2·T5）：粗粒度角色守卫（R8 最小切片）。

叠加在系统级 / 全市场写接口上：非 system 角色 → 403，未认证 → 401。
完整 resource code 细粒度授权留阶段三。
"""

from __future__ import annotations

from backend.auth.context import get_current_context
from backend.common.exceptions import AuthError, ForbiddenError


def require_system() -> None:
    """系统管理员守卫：非 system 拒绝。用作系统级路由/端点的 FastAPI 依赖。

    stage3：判 ctx.is_system（由 perm_resolver 解析，system 角色 → True）。require_perm 见下（T4）。
    """
    ctx = get_current_context()
    if ctx is None:
        raise AuthError("未登录")
    if not ctx.is_system:
        raise ForbiddenError("需要系统管理员权限")
