"""密码安全原语（多租户 RBAC stage2·T1）：bcrypt 哈希与校验。

密码一律 bcrypt 存储，禁明文/弱哈希（R15）。本模块零业务依赖，供 seed/认证服务复用。
T2 在此基础上补密码强度校验 check_strength 与 jwt_tokens（独立文件）。
"""

from __future__ import annotations

import bcrypt

from backend.common.exceptions import ValidationError

# bcrypt 单次哈希仅取前 72 字节；显式截断，避免不同 bcrypt 版本对超长密码的静默/抛错差异
_BCRYPT_MAX_BYTES = 72


def hash_password(plain: str) -> str:
    """生成 bcrypt 哈希（含随机盐），返回 ascii 字符串以入库。"""
    pw = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str | None) -> bool:
    """校验明文与哈希是否匹配；哈希为空或格式非法时一律不通过（不抛异常）。"""
    if not hashed:
        return False
    pw = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(pw, hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def check_strength(password: str, min_len: int = 8) -> None:
    """密码强度校验（注册/改密用），不达标抛 ValidationError（映射业务错误）。

    规则：长度 ≥ min_len，且同时包含字母与数字。策略参数（min_len）由 auth 配置传入，
    可经系统设置调整（R16 之外的基础项）。
    """
    if len(password) < min_len:
        raise ValidationError(f"密码至少 {min_len} 位")
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        raise ValidationError("密码需同时包含字母和数字")
