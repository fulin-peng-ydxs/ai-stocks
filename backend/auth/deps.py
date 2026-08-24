"""鉴权路由依赖（多租户 RBAC）：粗粒度 system 守卫（stage2·R8）+ resource code 精确守卫（stage3·R8）。

- `require_system`：系统管理页专属接口（角色/菜单/功能/租户管理 + 平台写）——非 system 一律 403。
- `require_perm(code)` / `require_any_perm(*codes)`：接口级细粒度授权（用户管理等可授权给
  tenant_admin 的接口）——system 恒过，
  否则精确码 ∉ 上下文 resources → 403。**精确匹配、不用通配符**（Codex P0 整改）。
- `require_system_perm(code)`（stage4·R21）：system-only 端点在 `require_system` 硬守卫外**挂精确资源码
  元数据**，供路由扫描（T8）与审计识别，运行时仍由 system 硬守卫兜底（非 system 一律 403，不因资源码授权放行）。
未认证（无上下文）一律 401。

**扫描契约（stage4·T8）**：`require_perm` / `require_system_perm` 返回的依赖函数均带 `resource_code` 属性；
路由扫描据此判定「该端点已接精确码」。`require_system_perm` 另带 `require_system_perm=True` 标记其为 system-only。
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request

from backend.auth.context import get_current_context, set_current_resource_code
from backend.common.exceptions import AuthError, ForbiddenError
from backend.services.asset_visibility import normalize_visibility


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
    def _dep(request: Request = None) -> None:
        set_current_resource_code(code)
        if request is not None:
            request.state.resource_code = code
        ctx = get_current_context()
        if ctx is None:
            raise AuthError("未登录")
        if ctx.is_system:
            return
        if code not in ctx.resources:
            raise ForbiddenError("无权访问该功能")

    _dep.resource_code = code   # type: ignore[attr-defined]  # 供 T8 路由扫描识别
    return _dep


def require_any_perm(*codes: str) -> Callable[[], None]:
    """要求至少拥有一个精确功能码，并暴露完整候选集供路由扫描与审计识别。"""
    unique_codes = tuple(dict.fromkeys(code for code in codes if code))
    if not unique_codes:
        raise ValueError("require_any_perm 至少需要一个功能码")
    code_set = frozenset(unique_codes)

    def _dep(request: Request = None) -> None:
        set_current_resource_code(unique_codes[0])
        if request is not None:
            request.state.resource_code = unique_codes[0]
        ctx = get_current_context()
        if ctx is None:
            raise AuthError("未登录")
        matched = unique_codes[0] if ctx.is_system else next(
            (code for code in unique_codes if code in ctx.resources),
            None,
        )
        if matched is None:
            raise ForbiddenError("无权访问该功能")
        set_current_resource_code(matched)
        if request is not None:
            request.state.resource_code = matched

    # 单码属性保持既有守卫扫描兼容，resource_codes 表达真实的任一权限契约。
    _dep.resource_code = unique_codes[0]  # type: ignore[attr-defined]
    _dep.resource_codes = code_set  # type: ignore[attr-defined]
    return _dep


def require_visibility_perm(
    view_code: str,
    publish_tenant_code: str,
    publish_public_code: str,
) -> Callable[..., None]:
    """资产可见性切换守卫：按请求体 visibility 选择精确资源码。

    依赖只守住查看基线并把实际资源码写入 request.state.resource_code，供 API 横切审计记录；
    owner-only 和 publish 权限仍在接口函数内返回既有 ApiResponse 错误结构。
    """
    codes = frozenset({view_code, publish_tenant_code, publish_public_code})

    async def _dep(request: Request = None) -> None:
        visibility = None
        if request is not None:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    visibility = normalize_visibility(body.get("visibility"))
            except Exception:  # noqa: BLE001
                visibility = None
        code = (
            publish_tenant_code if visibility == "tenant"
            else publish_public_code if visibility == "public"
            else view_code
        )
        set_current_resource_code(code)
        if request is not None:
            request.state.resource_code = code
        ctx = get_current_context()
        if ctx is None:
            raise AuthError("未登录")
        if ctx.is_system:
            return
        if view_code not in ctx.resources:
            raise ForbiddenError("无权访问该功能")

    _dep.resource_code = publish_tenant_code   # type: ignore[attr-defined]
    _dep.resource_codes = codes                # type: ignore[attr-defined]
    return _dep


def require_system_perm(code: str) -> Callable[[], None]:
    """system-only 端点守卫 + 精确资源码元数据（stage4·R21）。

    运行时 = `require_system()`（非 system 一律 403，**不因资源码被授权而放行**——system-only 边界不降级）。
    `resource_code` 属性供 T8 路由扫描识别；`require_system_perm=True` 标记其为 system-only（区别于可授权的
    `require_perm`）。system-only 资源码经其归属菜单 `visible='system'` 由 `system_only_resource_ids()` 拦截，
    不会被误授予非 system 角色。
    """
    def _dep(request: Request = None) -> None:
        set_current_resource_code(code)
        if request is not None:
            request.state.resource_code = code
        require_system()

    _dep.resource_code = code               # type: ignore[attr-defined]
    _dep.require_system_perm = True         # type: ignore[attr-defined]
    return _dep
