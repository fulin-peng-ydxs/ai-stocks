"""内部身份与人工业务编码的公共规则。"""

from __future__ import annotations

import re
import uuid

BUSINESS_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_:-]{0,79}$")


def uuid_hex_id() -> str:
    """生成不可读的 128-bit UUIDv4 标识，统一使用 32 位小写十六进制格式。"""
    return uuid.uuid4().hex


def is_business_code(value: str) -> bool:
    """业务编码须由管理员显式填写，并符合全平台统一格式。"""
    return BUSINESS_CODE_PATTERN.fullmatch(value) is not None
