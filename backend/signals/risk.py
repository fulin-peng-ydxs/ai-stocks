"""风险识别（T-M6-2，SDD §11）。

基于单只股票的**前复权**指标+行情序列（升序），逐日输出风险标签列表：
  - 追高：连续 ≥N 根大阳线（实体涨幅 ≥ big_pct）。
  - 量价背离：创两年新高当日但量能未配合（volume < vol_ma20）。
  - 破位：跌破 MA10 / MA20 / MA60（分别标记）。
  - 过热：换手率 > turnover_risk_high（默认 35%）。

点时安全：仅用当日及之前数据（追高的连阳计数为后向滚动）。
"""

from __future__ import annotations

import math

import pandas as pd

from backend.config import get_effective_settings


def _na(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


class RiskDetector:
    def __init__(self, big_pct: float = 0.05, chase_n: int = 3, settings=None):
        """big_pct: 大阳线实体涨幅阈值；chase_n: 连续大阳线根数阈值。"""
        s = (settings or get_effective_settings()).indicators
        self.turnover_high = s.turnover_risk_high
        self.big_pct = big_pct
        self.chase_n = chase_n

    def detect(self, df: pd.DataFrame) -> pd.Series:
        """df 升序，需含 open, close, volume, turnover_rate, ma10, ma20, ma60,
        vol_ma20, is_high_2y。返回逐行风险标签 list[str] 的 Series。"""
        n = len(df)
        if n == 0:
            return pd.Series([[] for _ in range(n)], index=df.index, dtype=object)

        op = df["open"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        vol = df["volume"].to_numpy(dtype=float)
        turn = df["turnover_rate"].to_numpy()
        ma10 = df["ma10"].to_numpy()
        ma20 = df["ma20"].to_numpy()
        ma60 = df["ma60"].to_numpy()
        vma20 = df["vol_ma20"].to_numpy()
        hi2y = df["is_high_2y"].astype("boolean").fillna(False).astype(bool).to_numpy()

        # 大阳线：实体涨幅 (close-open)/open >= big_pct
        big_up = [(not _na(op[i]) and op[i] > 0 and (close[i] - op[i]) / op[i] >= self.big_pct)
                  for i in range(n)]
        # 连续大阳线根数（含当日）
        run = 0
        chase = [False] * n
        for i in range(n):
            run = run + 1 if big_up[i] else 0
            chase[i] = run >= self.chase_n

        out: list[list[str]] = []
        for i in range(n):
            flags: list[str] = []
            if chase[i]:
                flags.append("连阳追高")
            if hi2y[i] and not _na(vma20[i]) and vol[i] < vma20[i]:
                flags.append("量价背离")
            if not _na(ma10[i]) and close[i] < ma10[i]:
                flags.append("跌破MA10")
            if not _na(ma20[i]) and close[i] < ma20[i]:
                flags.append("跌破MA20")
            if not _na(ma60[i]) and close[i] < ma60[i]:
                flags.append("跌破MA60")
            if not _na(turn[i]) and turn[i] > self.turnover_high:
                flags.append("换手过热")
            out.append(flags)

        return pd.Series(out, index=df.index, dtype=object)
