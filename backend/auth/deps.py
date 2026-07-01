"""鉴权路由依赖（多租户 RBAC stage2·T5）：粗粒度角色守卫（R8 最小切片）。

叠加在系统级 / 全市场写接口上：非 system 角色 → 403，未认证 → 401。
完整 resource code 细粒度授权留阶段三。
"""

from __future__ import annotations

from backend.auth.constants import ROLE_SYSTEM
from backend.auth.context import get_current_context
from backend.common.exceptions import AuthError, ForbiddenError


def require_system() -> None:
    """系统管理员守卫：非 system 角色拒绝。用作系统级路由/端点的 FastAPI 依赖。"""
    ctx = get_current_context()
    if ctx is None:
        raise AuthError("未登录")
    if ctx.role != ROLE_SYSTEM:
        raise ForbiddenError("需要系统管理员权限")
