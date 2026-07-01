"""密码安全原语测试（多租户 RBAC stage2·T2）：bcrypt 哈希/校验 + 强度校验。"""

from __future__ import annotations

import pytest

from backend.auth.security import check_strength, hash_password, verify_password
from backend.common.exceptions import ValidationError


def test_hash_verify_roundtrip():
    h = hash_password("SmokeTest#123")
    assert h and h != "SmokeTest#123"          # 非明文
    assert verify_password("SmokeTest#123", h) is True
    assert verify_password("wrong", h) is False


def test_hash_random_salt():
    # 相同明文两次哈希不同（含随机盐），但都可校验通过
    h1, h2 = hash_password("abc12345"), hash_password("abc12345")
    assert h1 != h2
    assert verify_password("abc12345", h1) and verify_password("abc12345", h2)


def test_verify_empty_or_bad_hash():
    assert verify_password("x", None) is False
    assert verify_password("x", "") is False
    assert verify_password("x", "not-a-bcrypt-hash") is False


def test_check_strength_ok():
    check_strength("abc12345")   # 8 位 + 字母 + 数字 → 通过（无异常）


@pytest.mark.parametrize("pwd", ["short1", "abc123", "12345678", "abcdefgh"])
def test_check_strength_reject(pwd):
    # 太短 / 纯数字 / 纯字母 均拒
    with pytest.raises(ValidationError):
        check_strength(pwd)
