"""AKShare 数据源适配器（SDD §5）。

⚠️ 实测发现（2026-05-31 探针）：
东财系接口（stock_zh_a_hist / index_zh_a_hist / stock_individual_info_em，
均走 push2his.eastmoney.com）在本环境被限流/封禁，连接直接中断；
而**新浪系接口稳定可用**。故本适配器以新浪接口为主工作路径：
- 日线：stock_zh_a_daily（不复权 + 后复权两次取数，现算复权因子）
- 指数：stock_zh_index_daily
- 列表：stock_info_a_code_name
- 日历：tool_trade_date_hist_sina
个股基础信息（list_date/industry/股本）东财接口被封，板块由代码前缀判定，
每日流通股本改用新浪日线自带的 outstanding_share（且为时变值，更准）。

字段映射到 backend.datasource.base 约定的统一 schema。
"""

from __future__ import annotations

from datetime import date

import akshare as ak
import pandas as pd

from backend.common.logging import get_logger
from backend.common.timeutil import fmt_date, to_date
from backend.config import get_settings
from backend.datasource.base import DataSource, rate_limited, with_retry

log = get_logger("datasource.akshare")

_s = get_settings().datasource
_MIN_INTERVAL = 1.0 / max(_s.rate_limit_per_sec, 0.1)


# ── 代码 / 板块工具 ─────────────────────────────────────────────


def classify_board(code6: str) -> tuple[str, str, float]:
    """由 6 位代码判定 (exchange, board, price_limit_pct)。

    用号段首位/前两位归类，覆盖新号段（如创业板 302/303）：
    - 688/689        → 科创板（沪, ±20%）
    - 30xxxx          → 创业板（深, ±20%，含 300/301/302/303…）
    - 60xxxx          → 沪市主板（±10%，含 600/601/603/605/606/607/608…）
    - 00xxxx          → 深市主板（±10%，含 000/001/002/003/004…，原中小板已并入）
    - 4/8/920         → 北交所（±30%，本期默认排除）
    - 其余            → 兜底沪市主板 + 告警（出现新号段时提醒补规则）
    """
    if code6.startswith(("688", "689")):
        return "SH", "科创板", 0.20
    if code6.startswith("30"):
        return "SZ", "创业板", 0.20
    if code6.startswith("60"):
        return "SH", "主板", 0.10
    if code6.startswith("00"):
        return "SZ", "主板", 0.10
    if code6.startswith(("4", "8", "920")):
        return "BJ", "北交所", 0.30
    log.warning("未知代码号段 %s，暂归沪市主板（请补 classify_board 规则）", code6)
    return "SH", "主板", 0.10


def to_full_code(code6: str) -> str:
    """6 位代码 -> 带后缀 600000.SH。"""
    exch, _, _ = classify_board(code6)
    return f"{code6}.{exch}"


def to_sina_symbol(code6: str) -> str:
    """6 位代码 -> 新浪格式 sh600000 / sz000001。"""
    exch, _, _ = classify_board(code6)
    prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(exch, "sh")
    return f"{prefix}{code6}"


def compute_pre_close(close: pd.Series, adj_factor: pd.Series) -> pd.Series:
    """官方前收盘（除权参考价）= 前日收盘 × 前日复权因子 / 当日复权因子。

    普通日因子不变 → 等于上一日收盘；除权除息/高送转日因子跳变 →
    得到调整后的参考价，使涨跌幅/涨跌停判定正确。序列须按日期升序。
    """
    return close.shift(1) * adj_factor.shift(1) / adj_factor


def index_to_sina_symbol(index_code: str) -> str:
    """指数代码 -> 新浪 symbol。

    指数代码统一带交易所后缀（'000905.SH'），转 'sh000905'，
    杜绝与深市个股(000xxx)冲突。兼容裸代码（默认沪市）。
    """
    if "." in index_code:
        code6, exch = index_code.split(".")
        return f"{exch.lower()}{code6}"
    if index_code[:2] in ("sh", "sz"):
        return index_code
    return f"sh{index_code}"


class AKShareSource(DataSource):
    name = "akshare"
    # 新浪日线/指数/日历/列表 + 东财市值（valuation）
    capabilities = {"daily", "index", "calendar", "stock_list", "valuation"}

    # ── 股票列表 ──
    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL)
    def get_stock_list(self) -> pd.DataFrame:
        df = ak.stock_info_a_code_name()  # columns: code, name
        df = df.rename(columns={"code": "code6"})
        df["code"] = df["code6"].apply(to_full_code)
        return df[["code", "code6", "name"]]

    # ── 个股基础信息（板块由代码判定；其余尽力而为）──
    def get_stock_info(self, code: str) -> pd.DataFrame:
        code6 = code.split(".")[0]
        exch, board, limit = classify_board(code6)
        return pd.DataFrame(
            [
                {
                    "code": to_full_code(code6),
                    "name": None,
                    "exchange": exch,
                    "board": board,
                    "list_date": None,
                    "delist_date": None,
                    "total_share": None,
                    "float_share": None,
                    "industry": None,
                    "price_limit_pct": limit,
                }
            ]
        )

    # ── 日线（新浪：不复权 + 后复权 → 现算复权因子）──
    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL)
    def _sina_daily(self, code6: str, start: date, end: date, adjust: str) -> pd.DataFrame:
        return ak.stock_zh_a_daily(
            symbol=to_sina_symbol(code6),
            start_date=fmt_date(start, compact=True),
            end_date=fmt_date(end, compact=True),
            adjust=adjust,
        )

    def get_daily_bar(
        self, code: str, start: date, end: date, adjust: str = ""
    ) -> pd.DataFrame:
        code6 = code.split(".")[0]
        raw = self._sina_daily(code6, start, end, "")
        # 空数据或返回结构异常（无 date 列，如无效 symbol）→ 视为无数据，不重试
        if raw is None or raw.empty or "date" not in raw.columns:
            return pd.DataFrame()

        raw = raw.copy()
        raw["trade_date"] = pd.to_datetime(raw["date"]).dt.date

        # 复权因子 = 后复权收盘 / 不复权收盘（比例，前复权计算时再按最新因子归一）
        try:
            hfq = self._sina_daily(code6, start, end, "hfq")
            hfq = hfq.copy()
            hfq["trade_date"] = pd.to_datetime(hfq["date"]).dt.date
            factor = hfq.set_index("trade_date")["close"] / raw.set_index("trade_date")["close"]
            raw["adj_factor"] = raw["trade_date"].map(factor)
        except Exception as e:  # noqa: BLE001
            log.warning("%s 复权因子获取失败，置 1.0: %s", code, e)
            raw["adj_factor"] = 1.0

        out = pd.DataFrame(
            {
                "code": to_full_code(code6),
                "trade_date": raw["trade_date"],
                "open": raw["open"].astype(float),
                "high": raw["high"].astype(float),
                "low": raw["low"].astype(float),
                "close": raw["close"].astype(float),
                "volume": raw["volume"].astype("int64"),
                "amount": raw["amount"].astype(float),
                "adj_factor": raw["adj_factor"].astype(float),
                # 新浪 turnover 为小数（流通占比），换算成百分比
                "turnover_rate": (raw["turnover"].astype(float) * 100.0),
                # 新浪自带每日流通股本（时变，用于历史市值）
                "float_share": raw["outstanding_share"].astype("int64"),
            }
        ).sort_values("trade_date")

        # 前收盘 = 官方除权参考价（除权除息/高送转日需按复权因子调整）：
        #   pre_close_t = close_{t-1} × adj_factor_{t-1} / adj_factor_t
        # 普通日因子不变 → 等于上一日收盘；除权日则得到调整后的参考价，
        # 保证涨跌幅/涨跌停判定正确（新浪不直接给 preclose，故由因子推算）。
        out["pre_close"] = compute_pre_close(out["close"], out["adj_factor"])
        return out.reset_index(drop=True)

    # ── 每日估值/市值（东财 stock_value_em，含总市值/总股本）──
    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL)
    def get_valuation(self, code: str, start: date, end: date) -> pd.DataFrame:
        """每日总市值/总股本/流通市值/流通股本。

        列：code, trade_date, total_mv, float_mv, total_share, float_share。
        来源 stock_value_em（东财，与被封的 push2his 不同 endpoint，可用）。
        """
        code6 = code.split(".")[0]
        df = ak.stock_value_em(symbol=code6)
        if df is None or df.empty or "数据日期" not in df.columns:
            return pd.DataFrame()
        df = df.copy()
        df["trade_date"] = pd.to_datetime(df["数据日期"]).dt.date
        mask = (df["trade_date"] >= start) & (df["trade_date"] <= end)
        df = df[mask]
        return pd.DataFrame(
            {
                "code": to_full_code(code6),
                "trade_date": df["trade_date"],
                "total_mv": pd.to_numeric(df["总市值"], errors="coerce"),
                "float_mv": pd.to_numeric(df["流通市值"], errors="coerce"),
                "total_share": pd.to_numeric(df["总股本"], errors="coerce"),
                "float_share": pd.to_numeric(df["流通股本"], errors="coerce"),
            }
        ).reset_index(drop=True)

    # ── 指数日线（新浪）──
    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL)
    def get_index_bar(self, index_code: str, start: date, end: date) -> pd.DataFrame:
        # 指数代码带后缀（'000905.SH'）→ 新浪 symbol 'sh000905'
        symbol = index_to_sina_symbol(index_code)
        df = ak.stock_zh_index_daily(symbol=symbol)
        if df is None or df.empty or "date" not in df.columns:
            return pd.DataFrame()
        df = df.copy()
        df["trade_date"] = pd.to_datetime(df["date"]).dt.date
        mask = (df["trade_date"] >= start) & (df["trade_date"] <= end)
        df = df[mask]
        out = pd.DataFrame(
            {
                "index_code": index_code,  # 保留带后缀的完整代码
                "trade_date": df["trade_date"],
                "open": df["open"].astype(float),
                "high": df["high"].astype(float),
                "low": df["low"].astype(float),
                "close": df["close"].astype(float),
                "volume": df["volume"].astype("int64"),
                "amount": df["amount"].astype(float) if "amount" in df.columns else None,
            }
        )
        return out.reset_index(drop=True)

    # ── 交易日历（新浪：仅列交易日 → is_open=True）──
    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL)
    def get_trade_calendar(self, start: date, end: date) -> pd.DataFrame:
        df = ak.tool_trade_date_hist_sina()
        df = df.copy()
        df["trade_date"] = df["trade_date"].apply(to_date)
        mask = (df["trade_date"] >= start) & (df["trade_date"] <= end)
        out = df[mask][["trade_date"]].copy()
        out["is_open"] = True
        return out.reset_index(drop=True)
