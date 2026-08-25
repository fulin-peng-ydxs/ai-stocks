"""个股一体化采集任务的参数契约与场景定义。"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

STOCK_INGEST_RECIPES = (
    "daily_update",
    "history_backfill",
    "range_refetch",
    "valuation_history",
    "valuation_gaps",
    "basic_refresh",
    "delisted_history",
)

STOCK_INGEST_RECIPE_LABELS = {
    "daily_update": "日常同步",
    "history_backfill": "历史行情补全",
    "range_refetch": "日期区间重采",
    "valuation_history": "市值历史补采",
    "valuation_gaps": "市值缺口修复",
    "basic_refresh": "基础资料刷新",
    "delisted_history": "退市股历史补全",
}

_CODE_RE = re.compile(r"^\d{6}\.(?:SH|SZ)$")
_COMMON_FIELDS = {"recipe", "codes", "date_start", "date_end", "years", "concurrency"}
_CODE_RECIPES = {
    "daily_update", "history_backfill", "range_refetch",
    "valuation_history", "valuation_gaps",
}
_YEAR_RECIPES = {"history_backfill", "valuation_history", "delisted_history"}
_CONCURRENCY_RECIPES = {
    "daily_update", "history_backfill", "range_refetch",
    "valuation_history", "valuation_gaps",
}


def _strict_int(value, *, field: str, lo: int, hi: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field}须为 {lo}-{hi} 的整数")  # noqa: TRY004  API 统一映射 400
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field}须为 {lo}-{hi} 的整数") from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError(f"{field}须为 {lo}-{hi} 的整数")
    result = int(number)
    if not lo <= result <= hi:
        raise ValueError(f"{field}须为 {lo}-{hi} 的整数")
    return result


def normalize_stock_ingest_params(params: dict | None) -> dict:
    """校验并规范化统一采集参数，拒绝场景不支持的字段组合。"""
    raw = dict(params or {})
    unknown = sorted(set(raw) - _COMMON_FIELDS)
    if unknown:
        raise ValueError(f"个股采集包含不支持的参数: {unknown}")

    recipe = str(raw.get("recipe") or "").strip()
    if recipe not in STOCK_INGEST_RECIPES:
        raise ValueError(f"个股采集方案非法（可选 {STOCK_INGEST_RECIPES}）")
    out: dict = {"recipe": recipe}

    if "codes" in raw:
        if recipe not in _CODE_RECIPES:
            raise ValueError(f"{STOCK_INGEST_RECIPE_LABELS[recipe]}不支持指定股票")
        codes = raw.get("codes")
        if not isinstance(codes, (list, tuple)) or not codes:
            raise ValueError("指定股票时 codes 必须是非空数组")
        normalized_codes = []
        for item in codes:
            code = str(item).strip().upper()
            if not _CODE_RE.fullmatch(code):
                raise ValueError(f"股票代码格式非法: {item}")
            if code not in normalized_codes:
                normalized_codes.append(code)
        out["codes"] = normalized_codes

    if recipe == "range_refetch":
        start_raw = raw.get("date_start")
        if not start_raw:
            raise ValueError("日期区间重采必须填写起始日期")
        try:
            start = date.fromisoformat(str(start_raw))
            end = date.fromisoformat(str(raw.get("date_end") or start_raw))
        except ValueError as exc:
            raise ValueError("采集日期须使用 YYYY-MM-DD 格式") from exc
        if end < start:
            raise ValueError("结束日期不得早于起始日期")
        out["date_start"] = start.isoformat()
        out["date_end"] = end.isoformat()
    elif raw.get("date_start") is not None or raw.get("date_end") is not None:
        raise ValueError(f"{STOCK_INGEST_RECIPE_LABELS[recipe]}不支持日期区间参数")

    if raw.get("years") not in (None, ""):
        if recipe not in _YEAR_RECIPES:
            raise ValueError(f"{STOCK_INGEST_RECIPE_LABELS[recipe]}不支持历史年数参数")
        out["years"] = _strict_int(raw["years"], field="历史年数", lo=1, hi=30)

    if raw.get("concurrency") not in (None, ""):
        if recipe not in _CONCURRENCY_RECIPES:
            raise ValueError(f"{STOCK_INGEST_RECIPE_LABELS[recipe]}不支持并发数参数")
        out["concurrency"] = _strict_int(raw["concurrency"], field="采集并发数", lo=1, hi=16)

    return out
