"""认证短状态（Redis）测试（多租户 RBAC stage2·T3）：
黑名单 / perm_ver 缓存 / 登录失败计数+锁定 / 验证码（图形·邮箱）/ 限流令牌桶。

用 uuid 化标识避免跨用例/重跑碰撞；键均带 TTL，测试后自动过期。
"""

from __future__ import annotations

import uuid

from backend.auth import session_store as ss


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def test_token_blacklist(redis_cli):
    jti = _uid()
    assert ss.is_jti_revoked(jti) is False
    ss.revoke_jti(jti, 60)
    assert ss.is_jti_revoked(jti) is True
    # ttl<=0 视为已过期，不拉黑
    jti2 = _uid()
    ss.revoke_jti(jti2, 0)
    assert ss.is_jti_revoked(jti2) is False


def test_perm_ver_cache(redis_cli):
    uid = _uid()
    assert ss.get_cached_perm_ver(uid) is None
    ss.cache_perm_ver(uid, 7, ttl_seconds=60)
    assert ss.get_cached_perm_ver(uid) == 7
    ss.invalidate_perm_ver(uid)
    assert ss.get_cached_perm_ver(uid) is None


def test_login_failure_and_lock(redis_cli):
    acc = _uid()
    assert ss.login_failure_count(acc) == 0
    assert [ss.record_login_failure(acc, 300) for _ in range(3)] == [1, 2, 3]
    assert ss.login_failure_count(acc) == 3
    assert ss.is_locked(acc) is False
    ss.lock_account(acc, 120)
    assert ss.is_locked(acc) is True
    assert 0 < ss.lock_remaining(acc) <= 120
    ss.clear_login_failures(acc)
    assert ss.login_failure_count(acc) == 0


def test_captcha_one_time(redis_cli):
    cid = _uid()
    ss.save_captcha(cid, "Ab12", 60)
    # 大小写不敏感命中，且一次性消费
    assert ss.take_captcha(cid, "aB12") is True
    assert ss.take_captcha(cid, "aB12") is False   # 已消费
    # 错误也消费（防爆破）
    cid2 = _uid()
    ss.save_captcha(cid2, "XY99", 60)
    assert ss.take_captcha(cid2, "zzzz") is False
    assert ss.take_captcha(cid2, "XY99") is False   # 上一步已删


def test_email_code(redis_cli):
    email = f"{_uid()}@ex.com"
    ss.save_email_code(email, "135790", 300)
    assert ss.verify_email_code(email, "000000") is False   # 错误不消费
    assert ss.verify_email_code(email, "135790") is True    # 正确消费
    assert ss.verify_email_code(email, "135790") is False   # 已消费


def test_rate_limit_window(redis_cli):
    key = _uid()
    # limit=3：前 3 次放行，第 4 次拒
    assert [ss.rate_limit_ok("login", key, 3, 60) for _ in range(4)] == [True, True, True, False]
