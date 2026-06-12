"""指标计算引擎（v2.0 §5）——动态实时计算，无 indicator 落库表（决策 D1）。

v2.0 变更：删除 indicator 预计算值表。指标改为**按需实时计算 + 单次运行内存缓存**：
  - `range_frame(codes, lo, hi)`：逐股取前复权序列 → compute_stock_indicators → 切片到 [lo,hi]，
    再按 trade_date 横截面对 W 日收益排名得 rs_pct（防未来 + 防幸存者偏差，口径同旧实现）。
  - `wide_snapshot(lo, hi, codes)`：把动态指标帧注册为临时视图，与 daily_bar/daily_metrics
    JOIN 出宽快照（列与旧 `indicator⋈daily_bar⋈daily_metrics` 完全一致），供筛选/评分/回测复用。
  - `compute_series(code, end)`：单股指标序列，供个股查询（rs_pct 为横截面量，单股不填）。

单次运行（一次筛选/榜单/回测）内对相同 (codes, lo, hi) 复用缓存，避免重复计算。
纯本地、点时安全：序列只取 ≤hi，算子全后向。
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import date

import pandas as pd

from backend.common.logging import get_logger
from backend.config import get_settings
from backend.indicators.compute import (
    build_params,
    compute_market_indicators,
    compute_stock_indicators,
    param_hash,
)
from backend.storage.duckdb_client import get_client
from backend.storage.repository import MarketRepository

log = get_logger("indicators.engine")

# 动态指标帧的列（与旧 indicator 表一致，供下游 SQL 的 i.* 取用）
_IND_COLS = [
    "code", "trade_date",
    "ma5", "ma10", "ma20", "ma60", "ma250",
    "hhv60", "hhv120", "hhv240", "hhv480",
    "is_high_60", "is_high_120", "is_high_1y", "is_high_2y", "dist_to_high_2y",
    "is_bull_arrange", "ma20_up", "ma60_up", "above_ma250",
    "vol_ma5", "vol_ma20", "is_vol_breakout",
    "is_platform_breakout", "is_turnover_healthy",
    "rs_pct", "param_hash",
]

_CACHE_MAX = 6


def _as_date(d) -> date:
    if isinstance(d, date) and not isinstance(d, pd.Timestamp):
        return d
    return pd.Timestamp(d).date()


class IndicatorEngine:
    def __init__(self, client=None):
        self.c = client or get_client()
        self.repo = MarketRepository(self.c)
        self.s = get_settings()
        self.params = build_params(self.s)
        self.phash = param_hash(self.params)
        self.rs_window = self.s.indicators.rs_window
        # 单次运行缓存：(codes_key, lo, hi) -> 指标帧
        self._cache: "OrderedDict[tuple, pd.DataFrame]" = OrderedDict()

    # 覆盖最长指标 lookback（MA250/HHV480）+ RS 窗口 + buffer
    @property
    def _max_lb(self) -> int:
        return max(480, self.rs_window) + 20

    def _all_codes(self) -> list[str]:
        df = self.c.query_df("SELECT DISTINCT code FROM daily_bar ORDER BY code")
        return df["code"].tolist()

    def _latest_date(self) -> date:
        d = self.c.query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]
        return pd.Timestamp(d).date()

    def _bulk_qfq_bars(self, codes: list[str] | None, hi: date, lookback: int) -> pd.DataFrame:
        """一次查询取每股末段 lookback 行（≤hi）并按股前复权（base=各股末日因子）。

        以单条窗口查询替代逐股 get_bars（5000+ 次 SQL → 1 次），大幅降低全市场算指标耗时。
        """
        where = "trade_date <= ?"
        params: list = [hi]
        if codes is not None:
            where += f" AND code IN ({','.join('?' * len(codes))})"
            params += list(codes)
        params.append(lookback)
        df = self.c.query_df(
            "SELECT code, trade_date, open, high, low, close, pre_close, volume, turnover_rate, adj_factor "
            "FROM (SELECT *, row_number() OVER (PARTITION BY code ORDER BY trade_date DESC) AS _rn "
            f"      FROM daily_bar WHERE {where}) WHERE _rn <= ? ORDER BY code, trade_date",
            params,
        )
        if df.empty:
            return df
        af = df["adj_factor"].fillna(1.0)
        # 各股 base = 该股末日（最大 trade_date）的 adj_factor；qfq = raw*af/base
        base = df.groupby("code")["adj_factor"].transform("last").fillna(1.0)
        for col in ("open", "high", "low", "close", "pre_close"):
            df[col] = df[col] * af / base
        return df

    def compute_series(self, code: str, end_date: date | None = None,
                       lookback: int | None = None) -> pd.DataFrame:
        """单股指标序列（供个股查询）。rs_pct 为横截面量，单股不填（留空）。"""
        end_date = _as_date(end_date or self._latest_date())
        bars = self.repo.get_bars(code, end_date, lookback=lookback, adjust="qfq")
        if bars.empty:
            return pd.DataFrame()
        return compute_stock_indicators(bars, self.params)

    @staticmethod
    def _cross_sectional_rs(rets: list[pd.DataFrame]) -> pd.DataFrame:
        """按 trade_date 对 W 日收益做横截面百分位（0~100）。"""
        if not rets:
            return pd.DataFrame(columns=["code", "trade_date", "rs_pct"])
        allret = pd.concat(rets, ignore_index=True).dropna(subset=["ret_w"])
        if allret.empty:
            return pd.DataFrame(columns=["code", "trade_date", "rs_pct"])
        allret["rs_pct"] = allret.groupby("trade_date")["ret_w"].rank(pct=True) * 100.0
        return allret[["code", "trade_date", "rs_pct"]]

    def _cache_put(self, key: tuple, frame: pd.DataFrame) -> None:
        self._cache[key] = frame
        while len(self._cache) > _CACHE_MAX:
            self._cache.popitem(last=False)

    def range_frame(self, codes: list[str] | None, lo, hi) -> pd.DataFrame:
        """[lo,hi] 区间全市场（或子集）动态指标帧（含横截面 rs_pct）。"""
        lo, hi = _as_date(lo), _as_date(hi)
        codes_key = None if codes is None else frozenset(codes)
        ck = (codes_key, lo, hi, self.phash)
        if ck in self._cache:
            self._cache.move_to_end(ck)
            return self._cache[ck]

        n_days = int(self.c.query_df(
            "SELECT count(DISTINCT trade_date) AS n FROM daily_bar WHERE trade_date BETWEEN ? AND ?",
            [lo, hi]).iloc[0]["n"])
        lookback = n_days + self._max_lb
        lo_ts, hi_ts = pd.Timestamp(lo), pd.Timestamp(hi)

        bars_all = self._bulk_qfq_bars(codes, hi, lookback)
        n_codes = 0 if bars_all.empty else bars_all["code"].nunique()
        if bars_all.empty:
            frame = pd.DataFrame(columns=_IND_COLS)
        else:
            bars_all = bars_all.sort_values(["code", "trade_date"]).reset_index(drop=True)
            ind = compute_market_indicators(bars_all, self.params)
            ind = ind.drop(columns=["rs_pct"])  # 占位列；rs_pct 由下方横截面 merge 填入
            # W 日收益（同股内 shift，跨股不串）→ 横截面 RS
            ret = pd.DataFrame({
                "code": bars_all["code"].values,
                "trade_date": bars_all["trade_date"].values,
                "ret_w": (bars_all["close"]
                          / bars_all.groupby("code")["close"].shift(self.rs_window) - 1).values,
            })
            ind_td = pd.to_datetime(ind["trade_date"])
            m = (ind_td >= lo_ts) & (ind_td <= hi_ts)
            ind = ind[m.values]
            ret = ret[((pd.to_datetime(ret["trade_date"]) >= lo_ts)
                       & (pd.to_datetime(ret["trade_date"]) <= hi_ts)).values]
            if ind.empty:
                frame = pd.DataFrame(columns=_IND_COLS)
            else:
                rs = self._cross_sectional_rs([ret])
                frame = ind.merge(rs, on=["code", "trade_date"], how="left")
                frame = frame.reindex(columns=_IND_COLS)
                frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
        self._cache_put(ck, frame)
        log.info("指标动态计算：%d 只 [%s~%s] → %d 行", n_codes, lo, hi, len(frame))
        return frame

    def wide_snapshot(self, lo, hi, codes: list[str] | None = None) -> pd.DataFrame:
        """宽快照（指标⋈行情⋈市值），列与旧 indicator⋈daily_bar⋈daily_metrics 一致。"""
        frame = self.range_frame(codes, lo, hi)
        if frame.empty:
            return pd.DataFrame()
        with self.c.temp_view(frame, prefix="ind_wide") as name:
            df = self.c.query_df(
                f"SELECT i.*, b.open, b.high, b.low, b.close, b.pre_close, b.volume, "
                f"       b.amount, b.turnover_rate, b.is_st, b.limit_status, b.is_one_word, "
                f"       m.float_mv, m.total_mv "
                f"FROM {name} i "
                f"JOIN daily_bar b ON b.code=i.code AND b.trade_date=i.trade_date "
                f"LEFT JOIN daily_metrics m ON m.code=i.code AND m.trade_date=i.trade_date"
            )
        return df

    # ── 表达式型指标（M2.1b）：渲染参数 → 逐股点时求值（批量加载提速）──
    def _eval_expr_indicator(self, template: str, params: dict | None,
                             param_defs: list[dict] | None, asof, codes: list[str] | None) -> pd.Series:
        from backend.indicators.definition import render_expression
        from backend.screening.expression import eval_expr

        expr = render_expression(template, params, param_defs)
        asof = _as_date(asof)
        bars_all = self._bulk_qfq_bars(codes, asof, self._max_lb)
        if bars_all.empty:
            return pd.Series(dtype="float64")
        out: dict = {}
        for code, g in bars_all.groupby("code", sort=False):
            g = g.reset_index(drop=True)
            ctx = {
                "C": g["close"], "O": g["open"], "H": g["high"], "L": g["low"],
                "V": g["volume"].astype(float), "TURN": g["turnover_rate"].astype(float),
            }
            try:
                val = eval_expr(expr, ctx)
                out[code] = val.iloc[-1] if hasattr(val, "iloc") else val
            except Exception:  # noqa: BLE001
                out[code] = None
        return pd.Series(out)

    def eval_expr_indicator_range(self, template: str, params: dict | None, param_defs: list[dict] | None,
                                  lo, hi, codes: list[str] | None = None) -> pd.DataFrame:
        """表达式型指标在 [lo,hi] 区间**逐日逐股**求值 → DataFrame[code, trade_date, value]。

        一次批量取序列、整段求值后切片到区间（供回测买卖树/评分项跨区间向量化，避免逐日 attach）。
        """
        from backend.indicators.definition import render_expression
        from backend.screening.expression import eval_expr

        lo, hi = _as_date(lo), _as_date(hi)
        expr = render_expression(template, params, param_defs)
        n_days = int(self.c.query_df(
            "SELECT count(DISTINCT trade_date) AS n FROM daily_bar WHERE trade_date BETWEEN ? AND ?",
            [lo, hi]).iloc[0]["n"])
        bars_all = self._bulk_qfq_bars(codes, hi, n_days + self._max_lb)
        if bars_all.empty:
            return pd.DataFrame(columns=["code", "trade_date", "value"])
        lo_ts, hi_ts = pd.Timestamp(lo), pd.Timestamp(hi)
        parts = []
        for code, g in bars_all.groupby("code", sort=False):
            g = g.reset_index(drop=True)
            ctx = {
                "C": g["close"], "O": g["open"], "H": g["high"], "L": g["low"],
                "V": g["volume"].astype(float), "TURN": g["turnover_rate"].astype(float),
            }
            try:
                val = eval_expr(expr, ctx)
            except Exception:  # noqa: BLE001
                continue
            vals = val.values if hasattr(val, "values") else val
            td = pd.to_datetime(g["trade_date"])
            m = ((td >= lo_ts) & (td <= hi_ts)).values
            if m.any():
                parts.append(pd.DataFrame({"code": code, "trade_date": g["trade_date"].values[m],
                                           "value": pd.Series(vals).values[m]}))
        if not parts:
            return pd.DataFrame(columns=["code", "trade_date", "value"])
        return pd.concat(parts, ignore_index=True)

    def eval_named(self, key: str, params: dict | None, asof, codes: list[str] | None = None) -> pd.Series:
        """按指标 key 取值（index=code）：内置→快照列；表达式型→渲染参数后逐股求值。"""
        from backend.indicators.definition import IndicatorDefRepo
        d = IndicatorDefRepo(self.c).get(key)
        if d and d["kind"] == "expr":
            return self._eval_expr_indicator(d["expression"], params, d.get("params"), asof, codes)
        from backend.scoring.score_profile import resolve_indicator
        snap = self.wide_snapshot(asof, asof, codes)
        if snap.empty:
            return pd.Series(dtype="float64")
        return resolve_indicator(key, params, snap.set_index("code"))

    def attach_columns(self, snap: pd.DataFrame, items: list[dict], asof) -> pd.DataFrame:
        """为 snap（index=code）补齐表达式型指标列（列名=指标 key），供评分/筛选按列读取。"""
        from backend.indicators.definition import IndicatorDefRepo
        repo = IndicatorDefRepo(self.c)
        codes = list(snap.index)
        for it in items:
            key = it.get("indicator")
            if not key or key in snap.columns:
                continue
            d = repo.get(key)
            if d and d["kind"] == "expr":
                s = self._eval_expr_indicator(d["expression"], it.get("params"), d.get("params"), asof, codes)
                snap[key] = s.reindex(snap.index)
        return snap
