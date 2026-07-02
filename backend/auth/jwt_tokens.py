"""JWT 令牌签发与校验（多租户 RBAC stage2·T2）。

- access（短期）+ refresh（长期），HS256，密钥走 AI_STOCKS_JWT_SECRET（无弱默认）。
- claims：sub(user_id) / tenant_id / perm_ver / typ(access|refresh) / jti / iat / exp。
  **stage3 瘦令牌**：去 `role` claim——角色/权限一律服务端按 user_id 实时解析（perm_resolver）+
  Redis 缓存，令牌只留身份 + perm_ver（防前端伪造角色、且角色变更经 perm_ver 即时失效）。
- 校验失败（过期/篡改/类型不符/密钥缺失）统一抛 AuthError(401)，不泄露内部细节。
- jti（token 唯一 id）供黑名单按需吊销；perm_ver 供权限变更即时失效比对。

时间基准：统一用 UTC 时间戳（PyJWT 的 exp/iat 语义即 UTC）。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import jwt

from backend.common.exceptions import AuthError
from backend.config import get_settings

TOKEN_ACCESS = "access"
TOKEN_REFRESH = "refresh"


def _issue(user_id: str, tenant_id: str, perm_ver: int,
           typ: str, ttl_seconds: int) -> str:
    s = get_settings()
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "perm_ver": perm_ver,
        "typ": typ,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, s.jwt_secret(), algorithm=s.auth.algorithm)


def issue_access(user_id: str, tenant_id: str, perm_ver: int) -> str:
    """签发 access token（短期）。角色/权限不入令牌，由服务端解析（瘦令牌）。"""
    ttl = get_settings().auth.access_ttl_min * 60
    return _issue(user_id, tenant_id, perm_ver, TOKEN_ACCESS, ttl)


def issue_refresh(user_id: str, tenant_id: str, perm_ver: int) -> str:
    """签发 refresh token（长期，用于换发 access）。"""
    ttl = get_settings().auth.refresh_ttl_days * 86400
    return _issue(user_id, tenant_id, perm_ver, TOKEN_REFRESH, ttl)


def decode(token: str, *, expect_typ: str | None = None) -> dict[str, Any]:
    """校验并解出 claims；过期/篡改/密钥缺失/类型不符一律抛 AuthError(401)。

    expect_typ：限定 token 类型（access/refresh），不符即拒（防 refresh 当 access 用）。
    """
    s = get_settings()
    try:
        claims = jwt.decode(token, s.jwt_secret(), algorithms=[s.auth.algorithm])
    except jwt.ExpiredSignatureError as e:
        raise AuthError("token 已过期") from e
    except jwt.InvalidTokenError as e:
        raise AuthError("token 无效") from e
    if expect_typ is not None and claims.get("typ") != expect_typ:
        raise AuthError("token 类型不符")
    return claims
