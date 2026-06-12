"""baostock 数据源适配器（T-M1-4，需求附录 A：补退市股 + 上市/退市日）。

baostock 优势（探针实测）：
- query_stock_basic 提供 ipoDate(上市日)/outDate(退市日)/status(1上市0退市)/type ——
  补上新浪缺的上市/退市日期，且含 1125 只退市股（防幸存者偏差核心）。
- query_history_k_data_plus 可取**退市股历史日线**，含 preclose/turn/tradestatus/isST。

代码格式：baostock 用 'sh.600000' / 'sz.000001'（点分隔）。
登录态为进程级；本类惰性 login，析构/close 时 logout。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from backend.common.exceptions import DataSourceError
from backend.common.logging import get_logger
from backend.common.timeutil import fmt_date, to_date
from backend.config import get_settings
from backend.datasource.akshare_source import classify_board, to_full_code
from backend.datasource.base import DataSource, rate_limited, with_retry

log = get_logger("datasource.baostock")

_s = get_settings().datasource
_MIN_INTERVAL = 1.0 / max(_s.rate_limit_per_sec, 0.1)


def bs_to_full(bs_code: str) -> str:
    """'sh.600000' -> '600000.SH'。"""
    market, code6 = bs_code.split(".")
    return f"{code6}.{market.upper()}"


def full_to_bs(full: str) -> str:
    """'600000.SH' -> 'sh.600000'。"""
    code6, exch = full.split(".")
    return f"{exch.lower()}.{code6}"


def _collect(rs) -> pd.DataFrame:
    """把 baostock ResultData 收集为 DataFrame。"""
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    return pd.DataFrame(rows, columns=rs.fields)


class BaostockSource(DataSource):
    name = "baostock"
    # baostock：日线/指数/日历 + 退市股 + 上市退市日 + 行业
    capabilities = {"daily", "index", "calendar", "delisted", "adj_factor", "basic_dates", "industry"}

    def __init__(self):
        self._logged_in = False

    def _ensure_login(self) -> None:
        if self._logged_in:
            return
        import baostock as bs

        lg = bs.login()
        if lg.error_code != "0":
            raise DataSourceError(f"baostock 登录失败: {lg.error_msg}")
        self._logged_in = True

    def close(self) -> None:
        if self._logged_in:
            import baostock as bs

            bs.logout()
            self._logged_in = False

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass

    # ── 基础信息（上市/退市日 + 退市股清单）──
    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    def _query_basic(self) -> pd.DataFrame:
        import baostock as bs

        self._ensure_login()
        df = _collect(bs.query_stock_basic())
        # 只保留股票（type==1），排除指数/其他
        df = df[df["type"] == "1"].copy()
        df["code_full"] = df["code"].apply(bs_to_full)
        df["list_date"] = df["ipoDate"].apply(lambda x: to_date(x) if x else None)
        df["delist_date"] = df["outDate"].apply(lambda x: to_date(x) if x else None)
        df["is_delisted"] = df["status"] == "0"
        return df[["code_full", "code_name", "list_date", "delist_date", "is_delisted"]].rename(
            columns={"code_full": "code", "code_name": "name"}
        )

    def get_basic_dates(self) -> pd.DataFrame:
        """全市场（含退市）上市/退市日期表。列：code,name,list_date,delist_date,is_delisted。"""
        return self._query_basic()

    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    def get_industry(self) -> pd.DataFrame:
        """全市场行业分类（证监会行业）。列：code(带后缀), industry。"""
        import baostock as bs

        self._ensure_login()
        df = _collect(bs.query_stock_industry())
        if df.empty:
            return pd.DataFrame(columns=["code", "industry"])
        df["code"] = df["code"].apply(bs_to_full)
        df["industry"] = df["industry"].replace("", None)
        return df[["code", "industry"]]

    def get_delisted_list(self) -> pd.DataFrame:
        df = self._query_basic()
        out = df[df["is_delisted"]][["code", "name", "delist_date"]].copy()
        return out.reset_index(drop=True)

    def get_stock_list(self) -> pd.DataFrame:
        df = self._query_basic()
        live = df[~df["is_delisted"]][["code", "name"]].copy()
        live["code6"] = live["code"].apply(lambda c: c.split(".")[0])
        return live[["code", "code6", "name"]].reset_index(drop=True)

    def get_stock_info(self, code: str) -> pd.DataFrame:
        df = self._query_basic()
        row = df[df["code"] == code]
        code6 = code.split(".")[0]
        exch, board, limit = classify_board(code6)
        name = row["name"].iloc[0] if not row.empty else None
        list_date = row["list_date"].iloc[0] if not row.empty else None
        delist_date = row["delist_date"].iloc[0] if not row.empty else None
        return pd.DataFrame(
            [
                {
                    "code": code, "name": name, "exchange": exch, "board": board,
                    "list_date": list_date, "delist_date": delist_date,
                    "total_share": None, "float_share": None, "industry": None,
                    "price_limit_pct": limit,
                }
            ]
        )

    # ── 日线（退市股也可取；raw + 算复权因子）──
    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL)
    def _k_data(self, code: str, start: date, end: date, adjustflag: str) -> pd.DataFrame:
        import baostock as bs

        self._ensure_login()
        fields = "date,open,high,low,close,preclose,volume,amount,turn,tradestatus,isST"
        rs = bs.query_history_k_data_plus(
            full_to_bs(code), fields,
            start_date=fmt_date(start), end_date=fmt_date(end),
            frequency="d", adjustflag=adjustflag,
        )
        return _collect(rs)

    def get_daily_bar(self, code: str, start: date, end: date, adjust: str = "") -> pd.DataFrame:
        raw = self._k_data(code, start, end, "3")  # 3=不复权
        if raw is None or raw.empty:
            return pd.DataFrame()
        raw = raw.replace("", None)
        for col in ["open", "high", "low", "close", "preclose", "amount", "turn"]:
            raw[col] = pd.to_numeric(raw[col], errors="coerce")
        raw["volume"] = pd.to_numeric(raw["volume"], errors="coerce").fillna(0).astype("int64")
        raw["trade_date"] = raw["date"].apply(to_date)

        # 复权因子 = 后复权收盘 / 不复权收盘
        try:
            hfq = self._k_data(code, start, end, "1")  # 1=后复权
            hfq["trade_date"] = hfq["date"].apply(to_date)
            hfq["close"] = pd.to_numeric(hfq["close"], errors="coerce")
            factor = hfq.set_index("trade_date")["close"] / raw.set_index("trade_date")["close"]
            raw["adj_factor"] = raw["trade_date"].map(factor)
        except Exception as e:  # noqa: BLE001
            log.warning("%s baostock 复权因子失败，置 1.0: %s", code, e)
            raw["adj_factor"] = 1.0

        out = pd.DataFrame(
            {
                "code": code,
                "trade_date": raw["trade_date"],
                "open": raw["open"], "high": raw["high"], "low": raw["low"], "close": raw["close"],
                "pre_close": raw["preclose"],
                "volume": raw["volume"], "amount": raw["amount"],
                "adj_factor": raw["adj_factor"].fillna(1.0),
                "turnover_rate": raw["turn"],  # baostock turn 已是百分比
            }
        ).sort_values("trade_date")
        # 零成交日（退市整理/停牌）成交额、换手率应为 0，而非 NaN
        zero_vol = out["volume"] == 0
        out.loc[zero_vol, "amount"] = out.loc[zero_vol, "amount"].fillna(0.0)
        out.loc[zero_vol, "turnover_rate"] = out.loc[zero_vol, "turnover_rate"].fillna(0.0)
        return out.reset_index(drop=True)

    # ── 指数 ──
    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL)
    def get_index_bar(self, index_code: str, start: date, end: date) -> pd.DataFrame:
        import baostock as bs

        self._ensure_login()
        # 指数代码带后缀（'000905.SH'）→ baostock 'sh.000905'
        if "." in index_code:
            code6, exch = index_code.split(".")
            bs_code = f"{exch.lower()}.{code6}"
        elif index_code.startswith("000"):
            bs_code = f"sh.{index_code}"
        else:
            bs_code = index_code
        rs = bs.query_history_k_data_plus(
            bs_code, "date,open,high,low,close,volume,amount",
            start_date=fmt_date(start), end_date=fmt_date(end), frequency="d",
        )
        df = _collect(rs)
        if df.empty:
            return df
        for col in ["open", "high", "low", "close", "amount"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return pd.DataFrame(
            {
                "index_code": index_code,
                "trade_date": df["date"].apply(to_date),
                "open": df["open"], "high": df["high"], "low": df["low"], "close": df["close"],
                "volume": pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64"),
                "amount": df["amount"],
            }
        )

    # ── 交易日历 ──
    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    def get_trade_calendar(self, start: date, end: date) -> pd.DataFrame:
        import baostock as bs

        self._ensure_login()
        rs = bs.query_trade_dates(start_date=fmt_date(start), end_date=fmt_date(end))
        df = _collect(rs)
        return pd.DataFrame(
            {
                "trade_date": df["calendar_date"].apply(to_date),
                "is_open": df["is_trading_day"] == "1",
            }
        )
