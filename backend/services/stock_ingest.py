"""个股一体化采集任务的参数契约与场景定义。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from backend.services.stock_codes import normalize_stock_codes

STOCK_INGEST_RECIPES = (
    "daily_update",
    "history_backfill",
    "range_refetch",
    "share_capital_history",
    "valuation_history",
    "valuation_gaps",
    "valuation_invalid_history",
    "basic_refresh",
    "delisted_history",
    "st_status_refresh",
)

STOCK_INGEST_RECIPE_LABELS = {
    "daily_update": "日常同步",
    "history_backfill": "历史行情补全",
    "range_refetch": "日期区间重采",
    "share_capital_history": "逐日股本补采",
    "valuation_history": "市值历史补采",
    "valuation_gaps": "市值缺口修复",
    "valuation_invalid_history": "全历史异常市值修复",
    "basic_refresh": "基础资料刷新",
    "delisted_history": "退市股历史补全",
    "st_status_refresh": "ST状态刷新",
}

_COMMON_FIELDS = {
    "recipe", "codes", "date_start", "date_end", "years", "concurrency", "force_current_day", "verified_facts", "recalculate_only", "review_only",
}
_CODE_RECIPES = {
    "daily_update", "history_backfill", "range_refetch",
    "share_capital_history",
    "valuation_history", "valuation_gaps", "valuation_invalid_history",
    "st_status_refresh",
}
_YEAR_RECIPES = {"share_capital_history", "history_backfill", "valuation_history", "delisted_history"}
_CONCURRENCY_RECIPES = {
    "daily_update", "history_backfill", "range_refetch",
    "share_capital_history",
    "valuation_history", "valuation_gaps", "valuation_invalid_history",
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


def normalize_verified_share_facts(records, codes: list[str]) -> list[dict]:
    """公告核验只接受有出处、已生效且已披露的精确日期总股本，不自动外推。"""
    import re
    from urllib.parse import urlsplit

    if not codes or not isinstance(records, list) or not 1 <= len(records) <= 1000:
        raise ValueError("公告股本须指定股票及 1-1000 条核验记录")
    required = {"code", "trade_date", "effective_date", "available_date", "total_share",
                "total_mv_eligible", "notice_id", "source_ref", "reason"}
    result, seen = [], set()
    for record in records:
        if not isinstance(record, dict) or not required <= set(record) or set(record) - required - {"source_type"}:
            raise ValueError("公告股本记录字段不完整或包含未知字段")
        fact = dict(record)
        evidence_type = fact.get("source_type", "notice")
        if evidence_type not in ("notice", "exchange_daily"):
            raise ValueError("股本核验证据类型不支持")
        if fact["code"] not in codes:
            raise ValueError("公告股本股票必须在指定采集范围内")
        for key in ("trade_date", "effective_date", "available_date"):
            try:
                fact[key] = date.fromisoformat(str(fact[key])).isoformat()
            except ValueError as exc:
                raise ValueError("公告股本日期须使用 YYYY-MM-DD") from exc
        if (fact["effective_date"] > fact["trade_date"]
                or fact["available_date"] > fact["trade_date"]
                or fact["trade_date"] > date.today().isoformat()):  # noqa: DTZ011 -- 与行情采集采用本地交易日
            raise ValueError("公告股本不得用于生效前、披露前或未来交易日")
        fact["total_share"] = _strict_int(fact["total_share"], field="总股本", lo=1, hi=9_000_000_000_000_000_000)
        if not isinstance(fact["total_mv_eligible"], bool):
            raise ValueError("公告股本 A 股口径必须明确为布尔值")  # noqa: TRY004 -- API 统一映射 400
        for key in ("notice_id", "source_ref", "reason"):
            if not isinstance(fact[key], str) or not fact[key].strip() or len(fact[key]) > 2000:
                raise ValueError("公告股本必须保留有效公告编号、链接和核验说明")
            fact[key] = fact[key].strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", fact["notice_id"]):
            raise ValueError("公告编号须为 1-100 位字母、数字、下划线或连字符")
        parsed = urlsplit(fact["source_ref"])
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("公告股本证据链接须为 不含账号的 HTTPS URL")
        if evidence_type == "exchange_daily" and parsed.hostname not in ("bond.sse.com.cn", "query.sse.com.cn", "www.sse.com.cn"):
            raise ValueError("交易所逐日股本证据须来自上交所官方接口或页面")
        identity = (fact["code"], fact["trade_date"])
        if identity in seen:
            raise ValueError("公告股本不允许重复股票交易日")
        seen.add(identity)
        result.append(fact)
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

    if "force_current_day" in raw:
        force_current_day = raw["force_current_day"]
        if not isinstance(force_current_day, bool):
            raise ValueError("强制采集当日须为布尔值")
        if recipe != "daily_update":
            raise ValueError(f"{STOCK_INGEST_RECIPE_LABELS[recipe]}不支持强制采集当日")
        if force_current_day:
            out["force_current_day"] = True

    if "codes" in raw:
        if recipe not in _CODE_RECIPES:
            raise ValueError(f"{STOCK_INGEST_RECIPE_LABELS[recipe]}不支持指定股票")
        codes = raw.get("codes")
        if not isinstance(codes, (list, tuple)) or not codes:
            raise ValueError("指定股票时 codes 必须是非空数组")
        out["codes"] = normalize_stock_codes(codes)

    if recipe in {"range_refetch", "st_status_refresh"}:
        start_raw = raw.get("date_start")
        if recipe == "range_refetch" and not start_raw:
            raise ValueError("日期区间重采必须填写起始日期")
        if not start_raw:
            if raw.get("date_end") is not None:
                raise ValueError("ST状态刷新填写结束日期时也必须填写起始日期")
        else:
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

    if "verified_facts" in raw:
        if recipe != "share_capital_history":
            raise ValueError("公告核验股本仅允许逐日股本补采方案")
        out["verified_facts"] = normalize_verified_share_facts(raw["verified_facts"], out.get("codes", []))

    if "review_only" in raw:
        if recipe != "share_capital_history" or not isinstance(raw["review_only"], bool):
            raise ValueError("历史轮询仅支持逐日股本方案及布尔参数")
        if raw["review_only"]:
            if "years" in out or "verified_facts" in out or raw.get("recalculate_only"):
                raise ValueError("历史轮询不能与年份、核验导入或纯补算混用")
            out["review_only"] = True

    if "recalculate_only" in raw:
        if recipe != "share_capital_history" or not isinstance(raw["recalculate_only"], bool):
            raise ValueError("仅本地补算须用于逐日股本方案并传布尔值")
        if raw["recalculate_only"]:
            if "years" in out or "verified_facts" in out:
                raise ValueError("仅本地补算不支持年限和公告事实参数")
            out["recalculate_only"] = True
    return out
