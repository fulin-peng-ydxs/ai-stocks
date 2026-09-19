"""信号质量分析（T-M5-2/3，SDD §6.5/§10.2 路径A）。

回答需求**核心概率口径**：分越高，N 日内摸到 X% 涨幅的概率是否越高？

做法（纯向量化，与卖出规则解耦）：
  1. 区间内逐交易日给全市场打分 → 分档 grade（观察/龙头候选/主升浪核心）。
  2. 对每个 (code, 信号日) 算前向最大涨幅（forward.compute_forward_returns，hfq、无未来函数）。
  3. base rate(N,X) = 同期**全部已评分票**无条件命中率（基线）。
  4. 各分档命中率 - base rate = **超额命中率**（评分真实能力），附**样本量**。

要点：base rate 必算（SDD §6.5）——否则牛市里随便选都高命中，无从判断模型好坏；
样本过小（< min_samples）标注但不采信。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from backend.backtest.forward import compute_forward_returns
from backend.common.logging import get_logger
from backend.scoring.model import ScoreModel
from backend.storage.duckdb_client import get_client

log = get_logger("backtest.signal")

_GRADES = ["主升浪核心", "龙头候选", "观察"]  # 由强到弱


class SignalAnalyzer:
    def __init__(self, client=None, model: ScoreModel | None = None, ind=None):
        self.c = client or get_client()
        self.model = model or ScoreModel()
        from backend.indicators.engine import IndicatorEngine
        self.ind = ind or IndicatorEngine(self.c)  # 可注入共享实例，复用区间快照缓存

    def _score_range(self, date_start: date, date_end: date, score_profile: dict | None = None) -> pd.DataFrame:
        """区间内逐日全市场打分 → DataFrame[code, trade_date, total_score, grade]。

        一次性取区间宽快照（动态指标⋈daily_bar⋈daily_metrics）。给定评分方案则用方案打分
        （表达式型指标跨区间向量化补列），否则用旧固定模型。
        """
        snap = self.ind.wide_snapshot(date_start, date_end)
        if snap.empty:
            return pd.DataFrame(columns=["code", "trade_date", "total_score", "grade"])
        snap = snap.copy()
        snap["trade_date"] = pd.to_datetime(snap["trade_date"])
        if score_profile:
            from backend.scoring.score_profile import ScoreProfileModel, active_score_items
            snap = self.ind.attach_range_columns(
                snap, active_score_items(score_profile.get("items", [])), date_start, date_end
            )
            scorer: object = ScoreProfileModel(score_profile)
        else:
            scorer = self.model
        snap_idx = snap.set_index("code")
        scored = scorer.score(snap_idx)
        return pd.DataFrame({
            "code": snap_idx.index, "trade_date": snap["trade_date"].values,
            "total_score": scored["total_score"].values, "grade": scored["grade"].values,
        })

    def analyze(
        self,
        date_start: date,
        date_end: date,
        horizons: list[int] | None = None,
        thresholds: list[float] | None = None,
        min_samples: int = 30,
        score_profile: dict | None = None,
    ) -> dict:
        from backend.config import get_effective_settings
        bt = get_effective_settings().backtest
        horizons = horizons or bt.hit_horizons
        thresholds = thresholds or bt.hit_thresholds

        scores = self._score_range(date_start, date_end, score_profile)
        if scores.empty:
            return {"error": "区间内无评分数据", "date_start": str(date_start), "date_end": str(date_end)}

        fwd = compute_forward_returns(date_start, date_end, horizons, client=self.c)
        df = scores.merge(fwd, on=["code", "trade_date"], how="inner")

        def cell(sub: pd.DataFrame, n: int, x: float) -> dict:
            ev = sub[sub[f"eval_{n}"]]
            nn = len(ev)
            if nn == 0:
                return {"hit_rate": None, "n": 0}
            return {"hit_rate": round(float((ev[f"fwd_ret_{n}"] >= x).mean()), 4), "n": nn}

        # base rate：全部已评分票
        base: dict[str, dict] = {}
        for n in horizons:
            for x in thresholds:
                base[f"N{n}_X{int(x*100)}"] = cell(df, n, x)

        # 分档
        by_grade: dict[str, dict] = {}
        for grade in _GRADES:
            sub = df[df["grade"] == grade]
            entry: dict = {"n_signals": len(sub)}
            for n in horizons:
                ev_n = sub[sub[f"eval_{n}"]]
                entry[f"avg_fwd_ret_{n}"] = (
                    round(float(ev_n[f"fwd_ret_{n}"].mean()), 4) if len(ev_n) else None
                )
                for x in thresholds:
                    key = f"N{n}_X{int(x*100)}"
                    c = cell(sub, n, x)
                    b = base[key]["hit_rate"]
                    c["base_rate"] = b
                    c["excess"] = (round(c["hit_rate"] - b, 4)
                                   if c["hit_rate"] is not None and b is not None else None)
                    c["reliable"] = c["n"] >= min_samples
                    entry[key] = c
            by_grade[grade] = entry

        return {
            "date_start": str(date_start), "date_end": str(date_end),
            "model_id": "default", "horizons": horizons,
            "thresholds": [round(x, 4) for x in thresholds],
            "min_samples": min_samples,
            "total_signals": len(df),
            "base_rate": base,
            "by_grade": by_grade,
            "grades_order": _GRADES,
        }
