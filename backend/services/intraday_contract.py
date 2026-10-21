"""分时查询、归档与体检共用的分钟契约；不补造任何价格或成交。"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from backend.services.stock_codes import normalize_stock_codes

EXPECTED_TIMES = frozenset(
    pd.date_range("2000-01-01 09:31", periods=120, freq="min").strftime("%H:%M")
) | frozenset(pd.date_range("2000-01-01 13:01", periods=120, freq="min").strftime("%H:%M"))
# 沪深股票收盘集合竞价在 15:00 一次撮合；14:58/14:59 不要求独立成交柱。
# 仍接收源端返回的这些分钟及额外开盘点，不能用点数阈值替代必需时点集合。
REQUIRED_TIMES = EXPECTED_TIMES - {"14:58", "14:59"}
ALLOWED_TIMES = EXPECTED_TIMES | {"09:30", "13:00"}
BAR_FIELDS = ["timestamp", "open", "high", "low", "close", "volume", "amount"]
INTRADAY_ISSUE_TYPES = ("intraday_gap", "intraday_partial", "intraday_invalid")
INTRADAY_PROVIDERS = ("sina", "ths", "eastmoney")
PROVIDER_LABELS = {"sina": "新浪", "eastmoney": "东财", "ths": "同花顺"}


def normalize_intraday_params(params: dict | None) -> dict:
    raw = dict(params or {})
    if set(raw) - {"mode", "codes", "date_start", "date_end"}:
        raise ValueError("分时采集包含不支持的参数")
    mode = raw.get("mode", "update")
    if mode not in ("update", "refetch"):
        raise ValueError("分时采集模式须为 update 或 refetch")
    out = {"mode": mode}
    if "codes" in raw:
        if not isinstance(raw["codes"], (list, tuple)) or not raw["codes"]:
            raise ValueError("指定股票时 codes 必须是非空数组")
        out["codes"] = normalize_stock_codes(raw["codes"])
    if mode == "refetch":
        try:
            start = date.fromisoformat(str(raw.get("date_start", "")))
            end = date.fromisoformat(str(raw.get("date_end") or start))
        except ValueError as exc:
            raise ValueError("分时重采须填写有效的起始日期 YYYY-MM-DD") from exc
        if start > end:
            raise ValueError("结束日期不得早于起始日期")
        out.update(date_start=str(start), date_end=str(end))
    elif raw.get("date_start") or raw.get("date_end"):
        raise ValueError("近期增量补采不接受固定日期区间")
    return out


def sanitize_minutes(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """开盘占位只置空；其余坏行拒用。诊断随逐日覆盖保存，不能被空响应清除。"""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=BAR_FIELDS), {}
    out = frame[BAR_FIELDS].copy()
    out["timestamp"] = pd.to_datetime(out.timestamp, errors="coerce")
    for field in BAR_FIELDS[1:]:
        out[field] = pd.to_numeric(out[field], errors="coerce")
    out.loc[out.open.eq(0), "open"] = np.nan
    clock = out.timestamp.dt.strftime("%H:%M")
    time_bad = ~clock.isin(ALLOWED_TIMES) | out.timestamp.dt.second.ne(0)
    numeric = out[["high", "low", "close", "volume", "amount"]]
    invalid = (
        ~np.isfinite(numeric).all(axis=1)
        | out.high.lt(out.low)
        | out.low.le(0)
        | out.close.lt(out.low)
        | out.close.gt(out.high)
        | out.volume.lt(0)
        | out.amount.lt(0)
        | (
            out.open.notna()
            & (
                ~np.isfinite(out.open)
                | out.open.le(0)
                | out.open.lt(out.low)
                | out.open.gt(out.high)
            )
        )
    )
    diagnostics = {
        "invalid_rows": int(invalid.sum()),
        "off_session_rows": int(time_bad.sum()),
        "duplicate_rows": int(out.timestamp.duplicated().sum()),
    }
    out = out.loc[~(invalid | time_bad)].sort_values("timestamp")
    return out.drop_duplicates("timestamp", keep="last").reset_index(drop=True), diagnostics


def complete_times(times) -> bool:
    return REQUIRED_TIMES.issubset(set(times))


def candidate_rank(rows: list, provider: str) -> tuple:
    times = {str(row[0])[11:16] for row in rows}
    return (complete_times(times), len(times & REQUIRED_TIMES), len(times), provider == "sina")
