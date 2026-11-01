"""仅对已触发价量冲突的 BaoStock 行取得独立价格证据，不扩大正常采集请求。"""

from __future__ import annotations

import math
from datetime import timedelta

import pandas as pd
import requests

from backend.common.exceptions import DataSourceError
from backend.datasource.base import check_thread_cancel
from backend.services.eod_dates import cap_end

TENCENT_DAILY_URL = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"


def fetch_tencent_prices(code, start, end, *, timeout=15):
    """原始日 K 只提供 OHLC/手数；不据此补造成交额、精确股数或复权因子。"""
    symbol = code.split(".")[1].lower() + code.split(".")[0]
    check_thread_cancel()
    response = requests.get(
        TENCENT_DAILY_URL,
        params={"param": f"{symbol},day,{start},{end},640,"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise DataSourceError(f"{code} 腾讯历史价格响应异常")
    rows = payload.get("data", {}).get(symbol, {}).get("day", [])
    if not rows or len(rows) >= 640:
        raise DataSourceError(f"{code} 腾讯历史价格为空或可能截断")
    try:
        out = pd.DataFrame(
            [row[:6] for row in rows],
            columns=["date", "open", "close", "high", "low", "lots"],
        )
        out["date"] = pd.to_datetime(out.date, errors="raise").dt.date
        for column in ["open", "close", "high", "low", "lots"]:
            out[column] = pd.to_numeric(out[column], errors="raise")
        if (
            out.date.duplicated().any()
            or not out.date.between(start, end).all()
            or not out[["open", "close", "high", "low", "lots"]].map(math.isfinite).all().all()
            or not out[["open", "close", "high", "low"]].gt(0).all().all()
            or (out.high < out[["open", "close", "low"]].max(axis=1)).any()
            or (out.low > out[["open", "close", "high"]].min(axis=1)).any()
            or out.lots.lt(0).any()
        ):
            raise ValueError("日期、唯一性或价格非法")
    except (ValueError, TypeError, IndexError) as exc:
        raise DataSourceError(f"{code} 腾讯价格字段非法: {exc}") from exc
    return out.sort_values("date").set_index("date")


def repair_baostock_price_conflicts(code, frame, fetch_raw, *, timeout=15):
    """独立 OHLC、相邻真实收盘/参考价及同基准因子同时通过才修正。

    不接受跨除权/因子切换的收盘修正；保留 BaoStock 精确量额和源因子。
    无独立证据则抛错，调用链保留旧事实和质量台账，不按均价反推 OHLC。
    """
    average = frame.amount / frame.volume.where(frame.volume > 0)
    bad = (frame.volume > 0) & (frame.low > 0) & (frame.high >= frame.low)
    bad &= (average < frame.low * 0.99) | (average > frame.high * 1.01)
    if not bad.any():
        return frame
    result = frame.copy()
    for index in frame.index[bad]:
        check_thread_cancel()
        row = frame.loc[index]
        day = pd.Timestamp(row.trade_date).date()
        lo, hi = day - timedelta(days=20), cap_end(day + timedelta(days=20))
        prices = fetch_tencent_prices(code, lo, hi, timeout=timeout)
        if day not in prices.index:
            raise DataSourceError(f"{code} {day} 腾讯缺少冲突日")
        verified = prices.loc[day]
        # 腾讯历史成交量按整数手截断，不能拿其粗粒度数值覆盖精确股数。
        if not 0 <= float(row.volume) - float(verified.lots) * 100 < 100:
            raise DataSourceError(f"{code} {day} 独立成交量不匹配")
        if not verified.low <= float(average.loc[index]) <= verified.high:
            raise DataSourceError(f"{code} {day} 独立价格仍与成交均价冲突")
        close_changed = abs(float(verified.close) - float(row.close)) > 0.011
        if close_changed:
            raw = fetch_raw(code, lo, hi, "3").copy()
            raw = raw[raw.tradestatus.astype(str).eq("1")]
            raw["date"] = pd.to_datetime(raw.date).dt.date
            raw = raw.sort_values("date").set_index("date")
            before, after = raw.loc[raw.index < day], raw.loc[raw.index > day]
            if before.empty or after.empty:
                raise DataSourceError(f"{code} {day} 收盘修正缺少前后真实交易锚点")
            prev_day, next_day = before.index[-1], after.index[0]
            if prev_day not in prices.index or next_day not in prices.index:
                raise DataSourceError(f"{code} {day} 独立价格缺少邻日")
            hfq = fetch_raw(code, lo, hi, "1").copy()
            hfq["date"] = pd.to_datetime(hfq.date).dt.date
            hfq = hfq.set_index("date")
            factors = [float(hfq.loc[d, "close"]) / float(raw.loc[d, "close"])
                       for d in (prev_day, day, next_day)]
            if (
                any(not math.isfinite(value) or value <= 0 for value in factors)
                or max(factors) / min(factors) - 1 > 1e-6
                or abs(float(row.adj_factor) / factors[1] - 1) > 1e-6
                or abs(float(raw.loc[prev_day, "close"]) - prices.loc[prev_day, "close"]) > 0.011
                or abs(float(raw.loc[next_day, "close"]) - prices.loc[next_day, "close"]) > 0.011
                or abs(float(raw.loc[next_day, "preclose"]) - verified.close) > 0.011
                or abs(float(row.pre_close) - prices.loc[prev_day, "close"]) > 0.011
            ):
                raise DataSourceError(f"{code} {day} 收盘/邻日参考价/因子基准未通过交叉核验")
        for column in ("open", "high", "low", "close"):
            result.loc[index, column] = verified[column]
        result.loc[index, "reference_close"] = verified.close
        symbol = code.split(".")[1].lower() + code.split(".")[0]
        result.loc[index, "_price_repair_evidence"] = (
            f"{TENCENT_DAILY_URL}?param={symbol},day,{lo},{hi},640,;"
            f"original_ohlc={row.open},{row.high},{row.low},{row.close};"
            f"verified_ohlc={verified.open},{verified.high},{verified.low},{verified.close};"
            f"volume_amount_factor=baostock;adjacent_reference_verified={str(close_changed).lower()}"
        )
    return result
