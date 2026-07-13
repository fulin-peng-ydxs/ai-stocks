"""鉴权中间件（多租户 RBAC stage2·T5）：应用级机制性默认 deny + 上下文注入。

**纯 ASGI 中间件**（非 BaseHTTPMiddleware）——在同一执行上下文 set ContextVar，可靠传播到
下游同步端点（Starlette 把当前上下文复制进 threadpool）；BaseHTTPMiddleware 的 dispatch 另起
上下文会导致 ContextVar 不传播，故不用。

规则：
- 非 /api、OPTIONS 预检、白名单（/api/health、/api/auth/*）→ 直接放行，不注上下文。
- 其余 /api/** → 必须携带有效 access token：解析+校验（签名/过期/黑名单/perm_ver）→
  set AuthContext → 处理 → 请求结束 reset。缺/无效 → 401；Redis/存储不可用（鉴权关键）→ 503（fail-closed）。
默认 deny 是**机制**：新增受控路由无需记得挂依赖即被保护（另有路由扫描测试兜底）。
"""

from __future__ import annotations

import time

import anyio
import redis
from starlette.responses import JSONResponse

from backend.auth import session_store as ss
from backend.auth.context import (
    AuthContext,
    clear_current_resource_code,
    enter_request,
    exit_request,
    get_current_resource_code,
    reset_context,
    set_context,
)
from backend.common.exceptions import AuthError, ServiceUnavailableError, StorageError
from backend.common.logging import get_logger
from backend.config import get_settings
from backend.services.audit_service import AuditService
from backend.services.auth_service import AuthService

log = get_logger("auth.middleware")

# 公开前缀：健康检查 + 认证端点（登录/注册/刷新/验证码/公开配置/oauth 占位；me/logout 自校验 token）
_WHITELIST_PREFIXES = ("/api/health", "/api/auth/")

# 安全响应头（R15；HSTS/CSP 留反代层，见 deploy-reverse-proxy.md，避免开发态 HTTP/内联脚本被误伤）
_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"SAMEORIGIN"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
]


def is_public(path: str) -> bool:
    if not path.startswith("/api/"):
        return True   # 非 API（SPA 静态 / 文档）不在鉴权范围
    return any(path.startswith(p) for p in _WHITELIST_PREFIXES)


def _scope_ip(scope) -> str:
    """取客户端 IP 作为全局 /api 限流键（与认证端点 _client_ip 同口径）。

    默认用不可伪造的连接地址；仅 server.trust_forwarded_for=true（后端在可信反代之后、
    反代会覆盖 XFF）时才取 X-Forwarded-For 首段。直连公网时信任 XFF 会被伪造头绕过全局限流。
    """
    if get_settings().server.trust_forwarded_for:
        for k, v in scope.get("headers", []):
            if k == b"x-forwarded-for":
                return v.decode("latin-1").split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


async def _run_audit_write(func, *args, **kwargs) -> None:
    """Run best-effort audit writes outside the event loop thread."""
    try:
        await anyio.to_thread.run_sync(lambda: func(*args, **kwargs))
    except Exception as e:  # noqa: BLE001
        log.warning("审计后台写入失败，已降级忽略: %s", e)


def _record_security_event(**kwargs) -> None:
    AuditService().record_security_event(**kwargs)


class SecurityMiddleware:
    """安全加固中间件（stage2·T6）：全局 per-IP 限流（backstop）+ 安全响应头。

    - 限流：对 /api/** 按 IP 固定窗口计数，超限 429；Redis 故障 fail-open（rate_limit_ok 内部处理）。
      应用层粗粒度 backstop，主限流由反代承担（deploy-reverse-proxy.md）。
    - 安全头：所有响应追加 nosniff / X-Frame-Options / Referrer-Policy。
    置于 CORS 内层、Auth 外层：限流在鉴权前拦（早卸载），头对所有响应（含 401/403/429）生效。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        if path.startswith("/api/") and scope.get("method") != "OPTIONS":
            limit = get_settings().auth.api_rate_per_min
            if not ss.rate_limit_ok("api", _scope_ip(scope), limit, 60):
                await _run_audit_write(
                    _record_security_event,
                    event_type="rate_limit",
                    action="api_rate_limit",
                    result="failed",
                    status="blocked",
                    ip=_scope_ip(scope),
                    method=scope.get("method"),
                    path=path,
                    error_summary="请求过于频繁",
                    context={"route": path, "rate_limit_rule": f"{limit}/min"},
                )
                resp = JSONResponse(
                    {"code": 4290, "msg": "请求过于频繁，请稍后再试", "data": None},
                    status_code=429, headers={k.decode(): v.decode() for k, v in _SECURITY_HEADERS})
                return await resp(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + _SECURITY_HEADERS
            await send(message)

        await self.app(scope, receive, send_wrapper)


class AuthMiddleware:
    """应用级鉴权：路径白名单外强制有效 token + 注入上下文。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        method = scope.get("method", "")
        # 标记"在请求链内"：使受控端点若因 bug/白名单误配缺上下文取归属时报错而非静默回落 admin（评审 P0）
        req_token = enter_request()
        try:
            if method == "OPTIONS" or is_public(path):
                return await self.app(scope, receive, send)

            authorization = None
            for k, v in scope.get("headers", []):
                if k == b"authorization":
                    authorization = v.decode("latin-1")
                    break

            svc = AuthService()
            try:
                claims = svc.claims_from_bearer(authorization)
                # 瘦令牌：角色/权限不在 token，按 user_id 解析后注入上下文。传入权威 perm_ver
                # （claims 已与 PG 一致，见 claims_from_bearer）令 load_perms 按其校验缓存新鲜度，
                # 防陈旧 perms 内容被采信（Codex 四轮 P1）。
                perms = svc.load_perms(claims["sub"], perm_ver=int(claims["perm_ver"]))
            except AuthError as e:
                await _run_audit_write(
                    self._record_auth_reject, scope, e.http_status, e.msg)
                return await self._deny(scope, receive, send, e.http_status, e.code, e.msg)
            except (ServiceUnavailableError, StorageError, redis.RedisError):
                # 鉴权关键依赖（Redis 黑名单/perm_ver/perms 缓存、PG）不可用 → fail-closed 503
                log.warning("鉴权链存储不可用，fail-closed 拒绝 path=%s", scope.get("path"))
                await _run_audit_write(
                    self._record_auth_reject, scope, 503, "鉴权依赖不可用")
                return await self._deny(
                    scope, receive, send, 503, 5003, "服务暂时不可用（鉴权依赖），请稍后重试")

            token = set_context(AuthContext(
                user_id=claims["sub"], tenant_id=claims["tenant_id"],
                roles=tuple(perms["roles"]), is_system=bool(perms["is_system"]),
                menus=frozenset(perms["menus"]), resources=frozenset(perms["resources"])))
            started = time.monotonic()
            status_code: int | None = None

            async def send_wrapper(message):
                nonlocal status_code
                if message["type"] == "http.response.start":
                    status_code = int(message.get("status", 200))
                await send(message)

            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                await _run_audit_write(
                    self._record_request_end,
                    scope,
                    tenant_id=claims.get("tenant_id"),
                    actor_user_id=claims.get("sub"),
                    status_code=status_code or 500,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
                clear_current_resource_code()
                reset_context(token)
        finally:
            exit_request(req_token)

    @staticmethod
    async def _deny(scope, receive, send, status: int, code: int, msg: str):
        resp = JSONResponse({"code": code, "msg": msg, "data": None}, status_code=status)
        await resp(scope, receive, send)

    @staticmethod
    def _record_request_end(
        scope,
        *,
        tenant_id: str | None,
        actor_user_id: str | None,
        status_code: int,
        duration_ms: int,
    ) -> None:
        path = scope.get("path", "")
        if path.startswith("/api/audit"):
            return
        method = scope.get("method", "")
        state = scope.get("state") or {}
        resource_code = getattr(state, "resource_code", None)
        if resource_code is None and isinstance(state, dict):
            resource_code = state.get("resource_code")
        resource_code = resource_code or get_current_resource_code()
        audit = AuditService()
        audit.record_api_event(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            resource_code=resource_code,
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            ip=_scope_ip(scope),
        )
        if status_code == 403:
            audit.record_security_event(
                event_type="forbidden",
                action="permission_denied",
                result="failed",
                status="blocked",
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                resource_code=resource_code,
                target_type="api",
                target_id=f"{method} {path}",
                target_label=path,
                ip=_scope_ip(scope),
                method=method,
                path=path,
                error_summary="无权访问该功能",
                context={
                    "route": path,
                    "permission_code": resource_code,
                } if resource_code else {"route": path},
            )

    @staticmethod
    def _record_auth_reject(scope, status_code: int, message: str) -> None:
        path = scope.get("path", "")
        if path.startswith("/api/audit"):
            return
        event_type = "auth_required" if status_code == 401 else "auth_dependency"
        AuditService().record_security_event(
            event_type=event_type,
            action="authenticate",
            result="failed",
            status="blocked",
            ip=_scope_ip(scope),
            method=scope.get("method"),
            path=path,
            error_summary=message,
            context={"route": path},
        )
