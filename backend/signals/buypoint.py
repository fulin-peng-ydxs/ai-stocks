"""买点识别（T-M6-1，SDD §11）。

基于单只股票的**前复权**指标+行情序列（升序），逐日给出买点标签：
  - 第一买点：平台突破成立后 → 缩量回踩 MA10/MA20 且不破 → 重新放量上涨确认（状态机）。
  - 第二买点：放量突破平台当日（is_platform_breakout 且 is_vol_breakout）。
  - 第三买点：创两年新高当日（is_high_2y）。

优先级（单标签）：第一买点 > 第二买点 > 第三买点。
点时安全：只用当日及之前数据；状态机逐日前推，不引用未来。
"""

from __future__ import annotations

import math

import pandas as pd


def _na(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


class BuyPointDetector:
    def __init__(self, window: int = 20, pullback_tol: float = 0.02,
                 break_tol: float = 0.05):
        """window: 突破后等待回踩确认的最大交易日数；
        pullback_tol: 回踩贴近均线的容差（≤MA×(1+tol)）；
        break_tol: 跌破 MA20 视为回踩失败的幅度（< MA20×(1-tol)）。
        """
        self.window = window
        self.pull_tol = pullback_tol
        self.break_tol = break_tol

    def detect(self, df: pd.DataFrame) -> pd.Series:
        """df 升序，需含 close, ma10, ma20, volume, vol_ma5, vol_ma20,
        is_platform_breakout, is_vol_breakout, is_high_2y。返回逐行买点标签 Series。"""
        n = len(df)
        labels = [""] * n
        if n == 0:
            return pd.Series(labels, index=df.index, dtype=object)

        close = df["close"].to_numpy()
        ma10 = df["ma10"].to_numpy()
        ma20 = df["ma20"].to_numpy()
        vol = df["volume"].to_numpy(dtype=float)
        vma5 = df["vol_ma5"].to_numpy()
        vma20 = df["vol_ma20"].to_numpy()
        pb = df["is_platform_breakout"].fillna(False).astype(bool).to_numpy()
        vb = df["is_vol_breakout"].fillna(False).astype(bool).to_numpy()
        hi2y = df["is_high_2y"].astype("boolean").fillna(False).astype(bool).to_numpy()

        state = "IDLE"  # IDLE → BROKEN → PULLBACK →(确认)→ IDLE
        broke_at = -1

        for i in range(n):
            # ── 第一买点状态机 ──
            if state == "IDLE":
                if pb[i]:
                    state, broke_at = "BROKEN", i
            else:  # BROKEN / PULLBACK
                if i - broke_at > self.window:
                    state = "IDLE"
                elif not _na(ma20[i]) and close[i] < ma20[i] * (1 - self.break_tol):
                    state = "IDLE"  # 回踩跌破 MA20 → 形态失败
                else:
                    if state == "PULLBACK" and i > 0:
                        # 确认：放量上涨 + 站上 MA10
                        confirm = (
                            close[i] > close[i - 1]
                            and not _na(vma5[i]) and vol[i] > vma5[i]
                            and not _na(ma10[i]) and close[i] > ma10[i]
                        )
                        if confirm:
                            labels[i] = "第一买点"
                            state = "IDLE"
                    if state == "BROKEN":
                        # 回踩：缩量 + 贴近 MA10/MA20 且不破
                        shrink = not _na(vma20[i]) and vol[i] < vma20[i]
                        near = (
                            (not _na(ma10[i]) and close[i] <= ma10[i] * (1 + self.pull_tol))
                            or (not _na(ma20[i]) and close[i] <= ma20[i] * (1 + self.pull_tol))
                        )
                        hold = not _na(ma20[i]) and close[i] >= ma20[i] * (1 - self.break_tol)
                        if shrink and near and hold:
                            state = "PULLBACK"

            # ── 第二/第三买点（不覆盖已判定的第一买点）──
            if not labels[i]:
                if pb[i] and vb[i]:
                    labels[i] = "第二买点"
                elif hi2y[i]:
                    labels[i] = "第三买点"

        return pd.Series(labels, index=df.index, dtype=object)
