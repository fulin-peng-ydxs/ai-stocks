"""身份字段规范化规则。

邮箱作为全平台登录身份使用，所有写入口必须采用同一份去空白、转小写与格式校验规则，
避免自助注册和后台用户管理产生不同口径。
"""

from __future__ import annotations

import re

from backend.common.exceptions import ValidationError

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_account(account: str | None) -> str:
    """账号去首尾空白并转小写，作为登录、查重、限流和锁定的统一键。"""
    return (account or "").strip().lower()


def normalize_email(email: str | None) -> str | None:
    """返回规范化邮箱；空字符串按未填写处理，非法格式抛业务校验错误。"""
    normalized = (email or "").strip().lower()
    if not normalized:
        return None
    if not _EMAIL_RE.match(normalized):
        raise ValidationError("邮箱格式不正确")
    return normalized
