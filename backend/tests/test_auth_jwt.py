"""JWT 令牌测试（多租户 RBAC stage2·T2）：签发/解码/过期/篡改/类型/密钥缺失。"""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest

from backend.auth.jwt_tokens import (
    TOKEN_ACCESS,
    TOKEN_REFRESH,
    decode,
    issue_access,
    issue_refresh,
)
from backend.common.exceptions import AuthError, ConfigError
from backend.config import get_settings

_SECRET = "unit-test-jwt-secret-0123456789-abcdefghij"   # ≥32 字节（避免 HS256 弱密钥告警）


@pytest.fixture()
def jwt_secret(monkeypatch):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    return _SECRET


def test_issue_and_decode_access(jwt_secret):
    tok = issue_access("u1", "t1", 3)
    c = decode(tok, expect_typ=TOKEN_ACCESS)
    assert c["sub"] == "u1" and c["tenant_id"] == "t1"
    assert "role" not in c and c["perm_ver"] == 3   # 瘦令牌：无 role claim
    assert c["typ"] == TOKEN_ACCESS and c["jti"]


def test_refresh_type_gate(jwt_secret):
    rt = issue_refresh("u1", "t1", 0)
    assert decode(rt, expect_typ=TOKEN_REFRESH)["typ"] == TOKEN_REFRESH
    # refresh 不能当 access 用
    with pytest.raises(AuthError):
        decode(rt, expect_typ=TOKEN_ACCESS)


def test_tampered_token_rejected(jwt_secret):
    tok = issue_access("u1", "t1", 0)
    tampered = tok[:-3] + ("abc" if tok[-3:] != "abc" else "xyz")
    with pytest.raises(AuthError):
        decode(tampered)


def test_expired_token_rejected(jwt_secret):
    algo = get_settings().auth.algorithm
    expired = pyjwt.encode(
        {"sub": "u1", "typ": TOKEN_ACCESS, "exp": int(time.time()) - 10},
        _SECRET, algorithm=algo)
    with pytest.raises(AuthError):
        decode(expired)


def test_wrong_secret_rejected(jwt_secret):
    algo = get_settings().auth.algorithm
    forged = pyjwt.encode(
        {"sub": "hacker", "typ": TOKEN_ACCESS, "exp": int(time.time()) + 60},
        "attacker-secret-0123456789-abcdefghijklmnop", algorithm=algo)
    with pytest.raises(AuthError):
        decode(forged)


def test_missing_secret_is_config_error(monkeypatch):
    monkeypatch.delenv("AI_STOCKS_JWT_SECRET", raising=False)
    # 无弱默认：缺密钥属服务配置错误（非客户端 401）
    with pytest.raises(ConfigError):
        issue_access("u1", "t1", 0)
