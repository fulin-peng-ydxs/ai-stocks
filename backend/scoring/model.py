"""评分模型（SDD §9）——对截面快照向量化打 0~100 综合分 + 分项分。

维度与默认权重（config.scoring.weights，可配）：位置30/趋势20/量20/换手10/RS10/资金流0。
每维原始分 ∈[0,1]，加权求和后按"有效权重和"归一到 100（资金流权重0自动排除，SDD §9.2）。
输出分项分（可解释）+ 分档 grade（≥80观察/≥90龙头候选/≥95主升浪核心，阈值可配）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.config import get_settings


class ScoreModel:
    def __init__(self, settings=None):
        self.s = (settings or get_settings()).scoring
        self.weights = dict(self.s.weights)
        self.grades = self.s.grade_thresholds

    def _raw_dimensions(self, snap: pd.DataFrame) -> pd.DataFrame:
        """各维度原始分 ∈[0,1]（向量化，NaN 安全）。"""
        def b(col):  # 布尔列 → 0/1，NaN→0
            return snap[col].astype("boolean").fillna(False).astype(float) if col in snap else 0.0

        # 位置：两年新高满分；否则按距新高幅度递减（越近越高）
        dist = snap.get("dist_to_high_2y")
        if dist is None:
            pos = pd.Series(0.0, index=snap.index)
        else:
            pos = (1.0 - dist.astype(float)).clip(0, 1).fillna(0.0)
        pos = np.where(b("is_high_2y") > 0, 1.0, pos)

        # 趋势：多头排列(0.6)+均线向上(0.4)
        trend = 0.6 * b("is_bull_arrange") + 0.4 * b("ma20_up")
        # 量：启动放量(0.5)+持续放量(0.5，vol_ma5>vol_ma20)
        sustain = ((snap.get("vol_ma5", np.nan) > snap.get("vol_ma20", np.nan))
                   .fillna(False).astype(float) if "vol_ma5" in snap else 0.0)
        volume = 0.5 * b("is_vol_breakout") + 0.5 * sustain
        # 换手：健康区间满分，否则给基础分 0.3
        turnover = np.where(b("is_turnover_healthy") > 0, 1.0, 0.3)
        # RS：百分位/100
        rs = (snap["rs_pct"].astype(float) / 100.0).clip(0, 1).fillna(0.0) if "rs_pct" in snap else 0.0
        fund_flow = pd.Series(0.0, index=snap.index)  # MVP 置 0

        return pd.DataFrame({
            "position": pos, "trend": trend, "volume": volume,
            "turnover": turnover, "rs": rs, "fund_flow": fund_flow,
        }, index=snap.index)

    def score(self, snap: pd.DataFrame) -> pd.DataFrame:
        """返回 DataFrame[code, total_score, <各维度加权分>, grade]（index=code）。"""
        raw = self._raw_dimensions(snap)
        active = {k: w for k, w in self.weights.items() if w > 0}
        total_w = sum(active.values()) or 1.0
        sub = {}  # 各维度加权得分（满分=权重）
        total = pd.Series(0.0, index=snap.index)
        for dim, w in self.weights.items():
            pts = raw[dim] * w
            sub[dim] = pts
            if w > 0:
                total = total + pts
        total_score = (total / total_w * 100.0).round(2)

        out = pd.DataFrame({"total_score": total_score}, index=snap.index)
        for dim in self.weights:
            out[dim] = (sub[dim]).round(2)
        out["grade"] = self._grade(total_score)
        return out

    def _grade(self, score: pd.Series) -> pd.Series:
        g = pd.Series("", index=score.index, dtype=object)
        g[score >= self.grades.watch] = "观察"
        g[score >= self.grades.leader] = "龙头候选"
        g[score >= self.grades.core] = "主升浪核心"
        return g
