"""认证短状态存取（Redis）——多租户 RBAC stage2·T3。

覆盖：token 黑名单 / perm_ver 缓存 / 登录失败计数+锁定 / 验证码（图形·邮箱）/ 接口限流。
键前缀统一 `auth:*`、`rl:*`，**一律设 TTL** 防无限增长。

降级语义（评审 P1，见 plan §10.2）：
- **鉴权关键**（黑名单、perm_ver 缓存读取）Redis 不可用 → 异常上抛（redis.RedisError/StorageError），
  由上层（中间件）**fail-closed 拒绝**（保 token 吊销 / 权限失效语义），绝不静默放行。
- **限流** `rate_limit_ok` Redis 不可用 → **fail-open 放行 + 告警**（防滥用非安全闸，避免抖动锁死全站）。

perm_ver 权威在 PG（sys_user.perm_ver）；本模块只做缓存 get/set/invalidate，
「未命中回查 PG 并回填」的编排由 T5 中间件/T4 服务持有（避免本层耦合 PG）。
"""

from __future__ import annotations

import json
from functools import wraps

import redis

from backend.common.exceptions import ServiceUnavailableError, StorageError
from backend.common.logging import get_logger
from backend.storage.redis_client import get_redis_client

log = get_logger("auth.session_store")


def _r() -> redis.Redis:
    return get_redis_client().client


def _critical(fn):
    """鉴权关键 Redis 操作：故障翻译为 ServiceUnavailableError(503)，让上层 fail-closed。

    区别于 rate_limit_ok（fail-open）：黑名单/perm_ver/失败计数/验证码等一旦 Redis 不可用，
    宁可整体拒绝(503)也不放行，保 token 吊销 / 权限失效 / 防爆破语义。
    无论调用方是中间件还是白名单 auth 端点（/me·/refresh·/logout），出码都统一为 503。
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (redis.RedisError, StorageError) as e:
            raise ServiceUnavailableError(f"鉴权依赖(Redis)不可用: {e}") from e
    return wrapper


# ── key 构造 ──
def _bl(jti: str) -> str: return f"auth:bl:{jti}"
def _pv(user_id: str) -> str: return f"auth:pv:{user_id}"
def _fail(account: str) -> str: return f"auth:fail:{account}"
def _lock(account: str) -> str: return f"auth:lock:{account}"
def _perms(user_id: str) -> str: return f"auth:perms:{user_id}"
def _captcha(cid: str) -> str: return f"auth:captcha:{cid}"
def _emailcode(email: str) -> str: return f"auth:emailcode:{email}"
def _rl(scope: str, key: str) -> str: return f"rl:{scope}:{key}"


# ── token 黑名单（登出 / 吊销）──
@_critical
def revoke_jti(jti: str, ttl_seconds: int) -> None:
    """把 token 的 jti 拉黑，TTL 取该 token 剩余寿命（过期即无需再占用 Redis）。"""
    if ttl_seconds <= 0:
        return
    _r().set(_bl(jti), "1", ex=ttl_seconds)


@_critical
def is_jti_revoked(jti: str) -> bool:
    """黑名单命中判定。**Redis 故障时异常上抛**（上层 fail-closed 拒绝）。"""
    return bool(_r().exists(_bl(jti)))


# ── perm_ver 缓存（权威在 PG，权限/状态变更后 invalidate + 自增）──
@_critical
def cache_perm_ver(user_id: str, ver: int, ttl_seconds: int = 3600) -> None:
    _r().set(_pv(user_id), str(ver), ex=ttl_seconds)


@_critical
def get_cached_perm_ver(user_id: str) -> int | None:
    """读缓存的 perm_ver；未命中返回 None（由上层回查 PG 并回填）。故障时异常上抛。"""
    v = _r().get(_pv(user_id))
    return int(v) if v is not None else None


@_critical
def invalidate_perm_ver(user_id: str) -> None:
    _r().delete(_pv(user_id))


# ── 有效权限缓存（stage3：解析结果 roles/is_system/menus/resources/perm_ver）──
# 纯缓存读写；解析(回查 PG)与失效编排(bump)在 perm_resolver.py（避免本层耦合 PG，同 perm_ver）。
@_critical
def cache_perms(user_id: str, perms: dict, ttl_seconds: int = 3600) -> None:
    _r().set(_perms(user_id), json.dumps(perms), ex=ttl_seconds)


@_critical
def get_cached_perms(user_id: str) -> dict | None:
    """读缓存的有效权限；未命中返回 None（由上层实时解析回填）。故障时异常上抛(fail-closed)。"""
    v = _r().get(_perms(user_id))
    return json.loads(v) if v is not None else None


@_critical
def clear_perms(user_id: str) -> None:
    _r().delete(_perms(user_id))


# ── 登录失败计数 + 账号锁定 ──
@_critical
def record_login_failure(account: str, window_seconds: int) -> int:
    """失败计数 +1，首次失败设窗口 TTL；返回当前窗口内失败次数。"""
    r = _r()
    k = _fail(account)
    n = int(r.incr(k))
    if n == 1:
        r.expire(k, window_seconds)
    return n


@_critical
def login_failure_count(account: str) -> int:
    v = _r().get(_fail(account))
    return int(v) if v is not None else 0


@_critical
def clear_login_failures(account: str) -> None:
    """登录成功时清零。"""
    _r().delete(_fail(account))


@_critical
def lock_account(account: str, ttl_seconds: int) -> None:
    _r().set(_lock(account), "1", ex=ttl_seconds)


@_critical
def is_locked(account: str) -> bool:
    return bool(_r().exists(_lock(account)))


@_critical
def lock_remaining(account: str) -> int:
    """剩余锁定秒数（0=未锁）；用于向用户展示剩余时间。"""
    t = _r().ttl(_lock(account))
    return t if t and t > 0 else 0


# ── 验证码：图形（一次性）/ 邮箱 ──
@_critical
def save_captcha(cid: str, code: str, ttl_seconds: int) -> None:
    """存图形验证码（大小写不敏感，统一小写存）。"""
    _r().set(_captcha(cid), code.strip().lower(), ex=ttl_seconds)


@_critical
def take_captcha(cid: str, code: str) -> bool:
    """一次性校验图形验证码：命中键即删（无论对错都消费，防重放/爆破）。"""
    r = _r()
    k = _captcha(cid)
    stored = r.get(k)
    if stored is None:
        return False
    r.delete(k)
    return stored == code.strip().lower()


@_critical
def save_email_code(email: str, code: str, ttl_seconds: int) -> None:
    _r().set(_emailcode(email), code.strip(), ex=ttl_seconds)


@_critical
def verify_email_code(email: str, code: str) -> bool:
    """校验邮箱验证码：正确才消费（错误保留，允许在有效期内重试）。"""
    r = _r()
    k = _emailcode(email)
    stored = r.get(k)
    if stored is not None and stored == code.strip():
        r.delete(k)
        return True
    return False


# ── 接口限流（固定窗口计数；fail-open）──
def rate_limit_ok(scope: str, key: str, limit: int, window_seconds: int) -> bool:
    """窗口内计数是否未超限；超限返回 False（上层 429）。Redis 故障 fail-open 放行 + 告警。"""
    try:
        r = _r()
        k = _rl(scope, key)
        n = int(r.incr(k))
        if n == 1:
            r.expire(k, window_seconds)
        return n <= limit
    except (redis.RedisError, StorageError) as e:
        log.warning("限流 Redis 不可用，fail-open 放行 scope=%s key=%s: %s", scope, key, e)
        return True
