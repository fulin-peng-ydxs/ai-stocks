"""稳定业务标识生成工具。"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid

_CN_TERMS = {
    "数据": "data",
    "分析": "analysis",
    "分析员": "analyst",
    "管理员": "admin",
    "管理": "manage",
    "租户": "tenant",
    "角色": "role",
    "菜单": "menu",
    "用户": "user",
    "系统": "system",
    "报表": "report",
    "报告": "report",
    "中心": "center",
    "配置": "config",
    "权限": "permission",
    "功能": "feature",
    "股票": "stock",
    "行情": "quote",
    "趋势": "trend",
    "评分": "score",
    "规则": "rule",
    "买卖": "trade",
    "指标": "indicator",
    "策略": "strategy",
    "回测": "backtest",
    "训练": "training",
}


def uuid_hex_id() -> str:
    """生成不可读的 128-bit UUIDv4 标识，统一使用 32 位小写十六进制格式。"""
    return uuid.uuid4().hex


def _translate_known_cn(text: str) -> str:
    out = text
    for zh in sorted(_CN_TERMS, key=len, reverse=True):
        out = out.replace(zh, f" {_CN_TERMS[zh]} ")
    return out


def readable_id(text: str, *, prefix: str, max_len: int = 48) -> str:
    """从用户可见名称生成简短英文标识；非 ASCII 名称用稳定短哈希兜底。"""
    raw = (text or "").strip()
    ascii_text = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    if not slug:
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
        slug = f"{prefix}-{digest}"
    if slug[0].isdigit():
        slug = f"{prefix}-{slug}"
    return slug[:max_len].strip("-") or prefix


def prefixed_readable_id(text: str, *, prefix: str, max_len: int = 80) -> str:
    """生成带业务前缀的稳定标识。

    英文输入直接转 snake_case；常见中文业务词用内置词典映射；未命中中文用 hash 兜底。
    """
    raw = (text or "").strip()
    translated = _translate_known_cn(raw)
    ascii_text = unicodedata.normalize("NFKD", translated).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_text).strip("_").lower()
    if not slug:
        slug = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    prefix_key = prefix.rstrip("_-")
    if slug == prefix_key:
        slug = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    if slug.startswith(f"{prefix_key}_"):
        out = slug
    else:
        if slug[0].isdigit():
            slug = f"{prefix_key}_{slug}"
        out = f"{prefix}{slug}"
    return out[:max_len].strip("_") or f"{prefix}{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:8]}"
