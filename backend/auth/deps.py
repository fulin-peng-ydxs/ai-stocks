"""鉴权路由依赖（多租户 RBAC）：粗粒度 system 守卫（stage2·R8）+ resource code 精确守卫（stage3·R8）。

- `require_system`：系统管理页专属接口（角色/菜单/功能/租户管理 + 平台写）——非 system 一律 403。
- `require_perm(code)`：接口级细粒度授权（用户管理等可授权给 tenant_admin 的接口）——system 恒过，
  否则精确码 ∉ 上下文 resources → 403。**精确匹配、不用通配符**（Codex P0 整改）。
未认证（无上下文）一律 401。
"""

from __future__ import annotations

from collections.abc import Callable

from backend.auth.context import get_current_context
from backend.common.exceptions import AuthError, ForbiddenError


def require_system() -> None:
    """系统管理员守卫：非 system 拒绝。用作系统级路由/端点的 FastAPI 依赖。

    stage3：判 ctx.is_system（由 perm_resolver 解析，system 角色 → True）。
    """
    ctx = get_current_context()
    if ctx is None:
        raise AuthError("未登录")
    if not ctx.is_system:
        raise ForbiddenError("需要系统管理员权限")


def require_perm(code: str) -> Callable[[], None]:
    """构造 resource code 精确授权依赖：`dependencies=[Depends(require_perm("user:list"))]`。

    system 恒过；否则 code 必须在上下文解析出的 resources 集合内（精确匹配），不在 → 403。
    未认证 → 401。同一 code 复用同一依赖对象（FastAPI 按 code 缓存）。
    """
    def _dep() -> None:
        ctx = get_current_context()
        if ctx is None:
            raise AuthError("未登录")
        if ctx.is_system:
            return
        if code not in ctx.resources:
            raise ForbiddenError("无权访问该功能")

    return _dep
