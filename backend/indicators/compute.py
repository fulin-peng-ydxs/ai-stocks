"""单股指标计算（SDD §6/§7）——基于前复权日线序列，逐股算出 indicator 宽表列。

输入：单只股票、按 trade_date 升序的**前复权**日线 DataFrame，需含
      code, trade_date, high, close, volume, turnover_rate。
输出：同长度 DataFrame，含全部 indicator 列（rs_pct 留空，由横截面阶段填）。

防未来函数：全部走 operators 的后向算子；不引用 T 之后数据。
"""

from __future__ import annotations

import hashlib
import json

import pandas as pd

from backend.config import get_effective_settings
from backend.indicators.operators import (
    EMA,
    HHV,
    MA,
    REF,
    is_new_high,
    platform_breakout,
)

INDICATOR_ALGO_VERSION = "2.1-macd-v1"
_MACD_FAST = 12
_MACD_SLOW = 26
_MACD_SIGNAL = 9


def build_params(settings=None) -> dict:
    """从配置抽取指标参数（含进 param_hash，参数变即重算）。"""
    s = (settings or get_effective_settings()).indicators
    return {
        "algo_version": INDICATOR_ALGO_VERSION,
        "ma_periods": list(s.ma_periods),
        "hhv_periods": list(s.hhv_periods),
        "ma_up_lookback": s.ma_up_lookback,
        "vol_breakout_n": s.vol_breakout_n,
        "vol_breakout_x": s.vol_breakout_x,
        "vol_sustain_s": s.vol_sustain_s,
        "platform_breakout_n": s.platform_breakout_n,
        "turnover_healthy_min": s.turnover_healthy_min,
        "turnover_healthy_max": s.turnover_healthy_max,
        "rs_window": s.rs_window,
    }


def param_hash(params: dict) -> str:
    """参数与算法版本哈希（短）。任一语义变化 → hash 变 → 重算。"""
    blob = json.dumps(params, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(blob.encode("utf-8")).hexdigest()[:12]


def _macd_cross_events(
    diff: pd.Series,
    dea: pd.Series,
    groups: pd.Series | None = None,
) -> tuple[pd.Series, pd.Series]:
    """按紧邻交易行计算金叉/死叉；缺失行和股票边界均保持可空语义。"""
    if groups is None:
        prev_diff, prev_dea = diff.shift(1), dea.shift(1)
    else:
        prev_diff = diff.groupby(groups, sort=False).shift(1)
        prev_dea = dea.groupby(groups, sort=False).shift(1)
    valid = diff.notna() & dea.notna() & prev_diff.notna() & prev_dea.notna()
    golden = ((diff > dea) & (prev_diff <= prev_dea)).where(valid, other=pd.NA)
    dead = ((diff < dea) & (prev_diff >= prev_dea)).where(valid, other=pd.NA)
    return golden.astype("boolean"), dead.astype("boolean")


def compute_macd(close: pd.Series) -> pd.DataFrame:
    """按交易日升序收盘价计算统一 MACD 原子指标（12/26/9，严格后向）。"""
    numeric_close = pd.to_numeric(close, errors="coerce").astype("float64")
    ema_fast = EMA(numeric_close, _MACD_FAST)
    ema_slow = EMA(numeric_close, _MACD_SLOW)
    diff = ema_fast - ema_slow
    dea = EMA(diff, _MACD_SIGNAL)
    golden, dead = _macd_cross_events(diff, dea)
    return pd.DataFrame({
        "macd_diff": diff,
        "macd_dea": dea,
        "macd_hist": 2.0 * (diff - dea),
        "macd_golden_cross": golden,
        "macd_dead_cross": dead,
    })


def compute_stock_indicators(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    """对单只股票（升序前复权日线）计算全部指标列。"""
    params = params or build_params()
    df = df.sort_values("trade_date").reset_index(drop=True)
    close, high, vol, turn = df["close"], df["high"], df["volume"], df["turnover_rate"]
    k = params["ma_up_lookback"]

    out = pd.DataFrame({"code": df["code"], "trade_date": df["trade_date"]})

    # ── 均线 ──
    ma = {n: MA(close, n) for n in (5, 10, 20, 60, 250)}
    for n in (5, 10, 20, 60, 250):
        out[f"ma{n}"] = ma[n]

    # ── MACD（固定 12/26/9，全部严格后向）──
    macd = compute_macd(close)
    for column in macd.columns:
        out[column] = macd[column]

    # ── 新高（位置）──
    hhv = {n: HHV(high, n) for n in (60, 120, 240, 480)}
    out["hhv60"], out["hhv120"], out["hhv240"], out["hhv480"] = (
        hhv[60], hhv[120], hhv[240], hhv[480],
    )
    out["is_high_60"] = is_new_high(close, high, 60)
    out["is_high_120"] = is_new_high(close, high, 120)
    out["is_high_1y"] = is_new_high(close, high, 240)
    out["is_high_2y"] = is_new_high(close, high, 480)
    out["dist_to_high_2y"] = (hhv[480] - close) / hhv[480]

    # ── 趋势 ──
    out["is_bull_arrange"] = (
        (ma[5] > ma[10]) & (ma[10] > ma[20]) & (ma[20] > ma[60])
    ).fillna(False)
    out["ma20_up"] = (ma[20] > REF(ma[20], k)).fillna(False)
    out["ma60_up"] = (ma[60] > REF(ma[60], k)).fillna(False)
    out["above_ma250"] = (close > ma[250]).fillna(False)

    # ── 量 ──
    out["vol_ma5"] = MA(vol, params["vol_sustain_s"])
    vol_ma_n = MA(vol, params["vol_breakout_n"])
    out["vol_ma20"] = vol_ma_n
    out["is_vol_breakout"] = (vol > vol_ma_n * params["vol_breakout_x"]).fillna(False)

    # ── 突破（平台突破用 shift(1) 防自指）──
    out["is_platform_breakout"] = platform_breakout(
        close, high, params["platform_breakout_n"]
    ).fillna(False).astype(bool)

    # ── 换手健康区间 ──
    out["is_turnover_healthy"] = (
        (turn >= params["turnover_healthy_min"]) & (turn <= params["turnover_healthy_max"])
    ).fillna(False)

    # ── RS 横截面：单股阶段留空，由 engine 跨股填 ──
    out["rs_pct"] = pd.NA
    out["param_hash"] = param_hash(params)

    # 可空布尔列转成 object（保留 <NA>），其余布尔转 bool
    for col in (
        "is_high_60",
        "is_high_120",
        "is_high_1y",
        "is_high_2y",
        "macd_golden_cross",
        "macd_dead_cross",
    ):
        out[col] = out[col].astype("boolean")
    return out


def compute_market_indicators(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    """全市场向量化算指标（v2.0 性能路径，结果与逐股 compute_stock_indicators 一致）。

    入参：多股**前复权**日线（含 code, trade_date, high, close, volume, turnover_rate），
    用 groupby.rolling（C 实现）一次性算完所有股票，避免逐股 Python 循环（全市场 ~3.5× 提速）。
    输出列同 compute_stock_indicators（rs_pct 留空，由 engine 横截面填）。
    """
    params = params or build_params()
    df = df.sort_values(["code", "trade_date"]).reset_index(drop=True)
    code, close = df["code"], df["close"]
    vol, turn = df["volume"].astype(float), df["turnover_rate"]
    k = params["ma_up_lookback"]
    g = df.groupby("code", sort=False)

    def rmean(col: str, n: int) -> pd.Series:
        return g[col].rolling(n, min_periods=n).mean().reset_index(level=0, drop=True)

    def rmax(col: str, n: int) -> pd.Series:
        return g[col].rolling(n, min_periods=n).max().reset_index(level=0, drop=True)

    out = pd.DataFrame({"code": code.values, "trade_date": df["trade_date"].values})
    ma = {n: rmean("close", n) for n in (5, 10, 20, 60, 250)}
    for n in (5, 10, 20, 60, 250):
        out[f"ma{n}"] = ma[n].values

    def rema(series: pd.Series, n: int) -> pd.Series:
        clean = pd.to_numeric(series, errors="coerce").astype("float64")
        clean = clean.replace([float("inf"), float("-inf")], float("nan"))
        result = (
            clean.groupby(code, sort=False)
            .ewm(span=n, adjust=False, min_periods=n)
            .mean()
            .reset_index(level=0, drop=True)
            .reindex(clean.index)
        )
        return result.where(clean.notna())

    ema_fast = rema(close, _MACD_FAST)
    ema_slow = rema(close, _MACD_SLOW)
    macd_diff = ema_fast - ema_slow
    macd_dea = rema(macd_diff, _MACD_SIGNAL)
    out["macd_diff"] = macd_diff.values
    out["macd_dea"] = macd_dea.values
    out["macd_hist"] = (2.0 * (macd_diff - macd_dea)).values
    golden, dead = _macd_cross_events(macd_diff, macd_dea, code)
    out["macd_golden_cross"] = golden.values
    out["macd_dead_cross"] = dead.values

    hhv = {n: rmax("high", n) for n in (60, 120, 240, 480)}
    for n in (60, 120, 240, 480):
        out[f"hhv{n}"] = hhv[n].values

    def new_high(n: int) -> pd.Series:
        hv = hhv[n]
        return (close >= hv).where(hv.notna(), other=pd.NA).astype("boolean")

    out["is_high_60"] = new_high(60).values
    out["is_high_120"] = new_high(120).values
    out["is_high_1y"] = new_high(240).values
    out["is_high_2y"] = new_high(480).values
    out["dist_to_high_2y"] = ((hhv[480] - close) / hhv[480]).values
    out["is_bull_arrange"] = (
        (ma[5] > ma[10]) & (ma[10] > ma[20]) & (ma[20] > ma[60])
    ).fillna(False).values
    out["ma20_up"] = (ma[20] > ma[20].groupby(code).shift(k)).fillna(False).values
    out["ma60_up"] = (ma[60] > ma[60].groupby(code).shift(k)).fillna(False).values
    out["above_ma250"] = (close > ma[250]).fillna(False).values
    out["vol_ma5"] = rmean("volume", params["vol_sustain_s"]).values
    vm = rmean("volume", params["vol_breakout_n"])
    out["vol_ma20"] = vm.values
    out["is_vol_breakout"] = (vol > vm * params["vol_breakout_x"]).fillna(False).values
    plat = rmax("high", params["platform_breakout_n"]).groupby(code).shift(1)
    out["is_platform_breakout"] = (
        (close > plat).where(plat.notna(), other=False).fillna(False).astype(bool).values
    )
    out["is_turnover_healthy"] = (
        (turn >= params["turnover_healthy_min"]) & (turn <= params["turnover_healthy_max"])
    ).fillna(False).values
    out["rs_pct"] = pd.NA
    out["param_hash"] = param_hash(params)
    for col in (
        "is_high_60",
        "is_high_120",
        "is_high_1y",
        "is_high_2y",
        "macd_golden_cross",
        "macd_dead_cross",
    ):
        out[col] = out[col].astype("boolean")
    return out
