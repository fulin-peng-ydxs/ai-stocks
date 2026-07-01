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

import redis
from starlette.responses import JSONResponse

from backend.auth.context import (
    AuthContext,
    enter_request,
    exit_request,
    reset_context,
    set_context,
)
from backend.common.exceptions import AuthError, StorageError
from backend.common.logging import get_logger
from backend.services.auth_service import AuthService

log = get_logger("auth.middleware")

# 公开前缀：健康检查 + 认证端点（登录/注册/刷新/验证码/公开配置/oauth 占位；me/logout 自校验 token）
_WHITELIST_PREFIXES = ("/api/health", "/api/auth/")


def is_public(path: str) -> bool:
    if not path.startswith("/api/"):
        return True   # 非 API（SPA 静态 / 文档）不在鉴权范围
    return any(path.startswith(p) for p in _WHITELIST_PREFIXES)


class AuthMiddleware:
    """应用级鉴权：路径白名单外强制有效 token + 注入上下文。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # 标记"在请求链内"：使受控端点若因 bug/白名单误配缺上下文取归属时报错而非静默回落 admin（评审 P0）
        req_token = enter_request()
        try:
            if scope.get("method") == "OPTIONS" or is_public(scope.get("path", "")):
                return await self.app(scope, receive, send)

            authorization = None
            for k, v in scope.get("headers", []):
                if k == b"authorization":
                    authorization = v.decode("latin-1")
                    break

            try:
                claims = AuthService().claims_from_bearer(authorization)
            except AuthError as e:
                return await self._deny(scope, receive, send, e.http_status, e.code, e.msg)
            except (StorageError, redis.RedisError):
                # 鉴权关键依赖（Redis 黑名单/perm_ver、PG）不可用 → fail-closed 503（保吊销/失效语义）
                log.warning("鉴权链存储不可用，fail-closed 拒绝 path=%s", scope.get("path"))
                return await self._deny(
                    scope, receive, send, 503, 5003, "服务暂时不可用（鉴权依赖），请稍后重试")

            token = set_context(AuthContext(
                user_id=claims["sub"], tenant_id=claims["tenant_id"], role=claims["role"]))
            try:
                await self.app(scope, receive, send)
            finally:
                reset_context(token)
        finally:
            exit_request(req_token)

    @staticmethod
    async def _deny(scope, receive, send, status: int, code: int, msg: str):
        resp = JSONResponse({"code": code, "msg": msg, "data": None}, status_code=status)
        await resp(scope, receive, send)
