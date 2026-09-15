"""筛选+评分编排服务（T-M3-4/7）——对某交易日：跑筛选→打分→排序→出 Top N 榜单，并落库。

- run_profile：对方案在指定（含历史任意）交易日运行筛选 → 写 screen_result（点时回溯）。
- rank_board：对当日全市场打分排序、分档、写 score_result，返回 Top N 榜单。
点时安全：均以 run_date 当日截面 + ≤run_date 序列，无未来函数。
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from backend.common.logging import get_logger
from backend.config import get_effective_settings
from backend.scoring.model import ScoreModel
from backend.screening.engine import ScreenEngine
from backend.screening.profile import ProfileRepo
from backend.services.stock_board_correlation import StockBoardCorrelationService
from backend.storage.duckdb_client import get_client
from backend.storage.repository import MarketRepository

log = get_logger("services.screen_score")


class ScreenScoreService:
    def __init__(self, client=None, *, tenant_id: str | None = None,
                 owner_user_id: str | None = None):
        self.c = client or get_client()
        from backend.auth.context import get_current_owner
        from backend.storage.asset_repository import AssetRepository
        from backend.storage.ddl import init_db
        init_db(self.c)
        _ctx_t, _ctx_o = get_current_owner()
        self.tenant_id = tenant_id or _ctx_t
        self.owner_user_id = owner_user_id or _ctx_o
        self.repo = MarketRepository(self.c)                 # 行情库（DuckDB）
        self.assets = AssetRepository(tenant_id=self.tenant_id,
                                      owner_user_id=self.owner_user_id)  # 结果库（PG）
        self.engine = ScreenEngine(self.c)
        self.profiles = ProfileRepo(market=self.c, tenant_id=self.tenant_id,
                                    owner_user_id=self.owner_user_id)
        self.model = ScoreModel()
        self.s = get_effective_settings()

    # ── 筛选并落库（支持任意历史交易日）──
    def run_profile(self, profile_id: str, run_date: date, persist: bool = True) -> list[str]:
        prof = self.profiles.get_visible(profile_id, include_owner=True)
        if not prof:
            raise ValueError(f"方案不存在: {profile_id}")
        res = self.engine.run_ast(prof["expression"], run_date)
        hits = res[res["hit"]]["code"].tolist()
        if persist and hits:
            rows = pd.DataFrame({
                "run_date": run_date, "profile_id": prof["id"], "code": hits,
                "hit": True, "matched": json.dumps({"profile": prof["name"]}, ensure_ascii=False),
                "snapshot": None,
            })
            self.assets.upsert("screen_result", rows)
        log.info("方案[%s] %s 命中 %d 只", prof["name"], run_date, len(hits))
        return hits

    def _st_codes(self, run_date: date, codes: list[str]) -> set[str]:
        """ST codes from the canonical point-in-time fact table; missing facts block use."""
        from backend.services.stock_st_status import StockSTStatusService

        status = StockSTStatusService(self.c).status_map(run_date, codes)
        return {code for code, is_st in status.items() if is_st}

    # ── 筛选 + 对命中打分排序（供筛选页：列表化、ST 标记、可排除 ST）──
    def screen_scored(
        self,
        run_date: date,
        profile_id: str | None = None,
        expression: dict | None = None,
        exclude_st: bool = True,
    ) -> list[dict]:
        """运行筛选 → 对命中股票用榜单同款评分模型打分 → 按综合分降序。

        返回 [{code, name, total_score, grade, is_st}]；exclude_st 时剔除 ST。
        """
        if profile_id:
            hits = self.run_profile(profile_id, run_date)
        elif expression is not None:
            res = self.engine.run_ast(expression, run_date)
            hits = res[res["hit"]]["code"].tolist()
        else:
            raise ValueError("需提供 profile_id 或 expression")
        if not hits:
            return []

        st_codes = self._st_codes(run_date, hits)
        # 复用筛选时已计算的全市场指标帧，再切命中集。不能以 hits 重新计算：那会把
        # rs_pct 从全市场百分位错误改成命中集内部百分位，也会产生一次重复指标计算。
        full_snap = self.engine._snapshot(run_date, None)
        snap = full_snap.reindex(hits).dropna(how="all") if not full_snap.empty else full_snap
        scored = self.model.score(snap) if not snap.empty else None
        name_df = self.c.query_df(
            f"SELECT code, name FROM stock_basic WHERE code IN ({','.join('?' * len(hits))})", hits
        )
        name_map = dict(zip(name_df["code"], name_df["name"]))

        out = []
        for code in hits:
            is_st = code in st_codes
            if exclude_st and is_st:
                continue
            ts = float(scored.loc[code, "total_score"]) if scored is not None and code in scored.index else None
            grade = str(scored.loc[code, "grade"]) if scored is not None and code in scored.index else ""
            out.append({"code": code, "name": name_map.get(code), "total_score": ts,
                        "grade": grade, "is_st": is_st})
        # 按综合分降序（None 排最后）
        out.sort(key=lambda r: (r["total_score"] is not None, r["total_score"] or 0), reverse=True)
        StockBoardCorrelationService(self.c).attach_related_boards(out, run_date)
        return out

    # ── 买点/风险信号（T-M6-3）：批量、hfq 基准一致 ──
    def compute_signals(self, run_date: date, codes: list[str], lookback_days: int = 140) -> dict:
        """对 codes 计算 run_date 当日的买点 + 技术风险标签。

        返回 {code: {"buy_point": str|None, "risk_flags": [str]}}。
        正确性：close 与 MA 统一用 **hfq**（raw×adj_factor）基准（与回测引擎一致），
        避免快照里"原始 close vs 前复权 MA"口径错配；is_* 布尔取自 indicator（尺度无关）。
        """
        if not codes:
            return {}
        from datetime import timedelta

        from backend.signals.buypoint import BuyPointDetector
        from backend.signals.risk import RiskDetector

        lo = run_date - timedelta(days=lookback_days)
        ph = ",".join("?" * len(codes))
        df = self.c.query_df(
            "SELECT b.code, b.trade_date, b.open, b.high, b.close, b.volume, b.turnover_rate, "
            "       COALESCE(b.adj_factor_clean, b.adj_factor) AS adj_factor "
            "FROM daily_bar b "
            f"WHERE b.code IN ({ph}) AND b.trade_date BETWEEN ? AND ? "
            "ORDER BY b.code, b.trade_date",
            [*codes, lo, run_date],
        )
        if df.empty:
            return {}
        bp_det, rk_det = BuyPointDetector(), RiskDetector()
        out: dict = {}
        for code, g in df.groupby("code", sort=False):
            gd = self._signal_frame(g)
            bp = bp_det.detect(gd).iloc[-1]
            rk = list(rk_det.detect(gd).iloc[-1])
            out[code] = {"buy_point": bp or None, "risk_flags": rk}
        return out

    def _signal_frame(self, g: pd.DataFrame) -> pd.DataFrame:
        """由单股日线（含 high）构建买点/风险检测所需的 hfq 帧。

        is_*（新高/放量/平台突破）为尺度无关布尔，直接由 hfq 序列用算子内联计算
        （v2.0 取消 indicator 落库表，改为动态计算，结果与旧表一致）。
        """
        from backend.indicators.operators import MA, is_new_high, platform_breakout

        s = self.s.indicators
        af = g["adj_factor"].fillna(1.0)
        c_hfq = (g["close"] * af).reset_index(drop=True)
        o_hfq = (g["open"] * af).reset_index(drop=True)
        h_hfq = (g["high"] * af).reset_index(drop=True)
        v = g["volume"].astype(float).reset_index(drop=True)
        vol_ma_n = MA(v, s.vol_breakout_n)
        return pd.DataFrame({
            "close": c_hfq, "open": o_hfq, "volume": v,
            "turnover_rate": g["turnover_rate"].reset_index(drop=True),
            "ma10": c_hfq.rolling(10).mean(), "ma20": c_hfq.rolling(20).mean(),
            "ma60": c_hfq.rolling(60).mean(),
            "vol_ma5": v.rolling(s.vol_sustain_s).mean(), "vol_ma20": vol_ma_n,
            "is_platform_breakout": platform_breakout(c_hfq, h_hfq, s.platform_breakout_n).fillna(False),
            "is_vol_breakout": (v > vol_ma_n * s.vol_breakout_x).fillna(False),
            "is_high_2y": is_new_high(c_hfq, h_hfq, 480).fillna(False),
        })

    def buypoint_markers(self, code: str, end_date: date, lookback: int = 250) -> list[dict]:
        """个股近 lookback 日的历史买点标记（T-M4-5），供 K 线叠加。

        返回 [{date, label}]，label 如 "第一买点"。hfq 基准一致，与榜单买点同口径。
        """
        from datetime import timedelta

        from backend.signals.buypoint import BuyPointDetector
        lo = end_date - timedelta(days=lookback * 2 + 200)  # 日历日宽松下界，覆盖 lookback 交易日 + 状态机窗口
        df = self.c.query_df(
            "SELECT b.trade_date, b.open, b.high, b.close, b.volume, b.turnover_rate, "
            "       COALESCE(b.adj_factor_clean, b.adj_factor) AS adj_factor "
            "FROM daily_bar b "
            "WHERE b.code=? AND b.trade_date BETWEEN ? AND ? ORDER BY b.trade_date",
            [code, lo, end_date],
        )
        if df.empty:
            return []
        gd = self._signal_frame(df)
        labels = BuyPointDetector().detect(gd)
        dates = df["trade_date"].reset_index(drop=True)
        return [{"date": str(pd.Timestamp(dates[i]).date()), "label": labels.iloc[i]}
                for i in range(len(labels)) if labels.iloc[i]]

    # ── 打分排序出榜单 ──
    def rank_board(self, run_date: date, model_id: str = "default",
                   top_n: int | None = None, persist: bool = True,
                   with_signals: bool = False) -> pd.DataFrame:
        top_n = top_n or self.s.scoring.top_n
        snap = self.engine._snapshot(run_date, None)
        if snap.empty:
            log.warning("%s 无截面数据", run_date)
            return pd.DataFrame()
        # ST 不参与趋势龙头榜单；历史日期严格读取当日 ST 事实，缺失则门禁失败。
        st_codes = self._st_codes(run_date, snap.index.astype(str).tolist())
        n_st = int(snap.index.isin(st_codes).sum())
        snap = snap[~snap.index.isin(st_codes)]
        if n_st:
            log.info("%s 榜单排除 ST 股 %d 只", run_date, n_st)
        scored = self.model.score(snap)  # index=code
        risk = self._risk_flags(snap)  # code -> [可成交性标记：涨停/跌停/一字板/ST]
        scored = scored.sort_values("total_score", ascending=False)
        scored["rank"] = range(1, len(scored) + 1)
        scored = scored.reset_index().rename(columns={"index": "code"})
        if "code" not in scored.columns:  # 兼容 index 名
            scored = scored.rename(columns={scored.columns[0]: "code"})

        # 技术买点/风险（T-M6-3）：可选，逐股序列计算后并入
        sig: dict = {}
        if with_signals:
            sig = self.compute_signals(run_date, scored["code"].tolist())

        if persist:
            # 历史遗留：score_result 公共读端点（/scores、/scores/top）已废弃（前端无调用方，
            # 产品已切到评分快照层 score_snapshot）。此分支仅 CLI cmd_rank 调试用，写当前 owner
            # 槽，不再作为任何公共读的数据源。勿复用为生产榜单路径。
            dims = list(self.model.weights.keys())

            def _merged_risk(code: str) -> list[str]:
                flags = list(risk.get(code, []))  # 可成交性（涨停/一字板/ST）
                for f in sig.get(code, {}).get("risk_flags", []):  # 技术（跌破MA/追高/背离/过热）
                    if f not in flags:
                        flags.append(f)
                return flags

            rows = pd.DataFrame({
                "trade_date": run_date, "model_id": model_id, "code": scored["code"],
                "total_score": scored["total_score"],
                "sub_scores": [json.dumps({d: float(r[d]) for d in dims}, ensure_ascii=False)
                               for _, r in scored.iterrows()],
                "rank": scored["rank"], "grade": scored["grade"],
                "buy_point": [sig.get(c, {}).get("buy_point") for c in scored["code"]],
                "risk_flags": [json.dumps(_merged_risk(c), ensure_ascii=False)
                               for c in scored["code"]],
            })
            # 整日全量替换：先清当日旧榜单，避免被排除/退榜的股票残留旧行（按归属，PG）
            self.assets.pg.execute(
                "DELETE FROM score_result WHERE trade_date=%s AND model_id=%s "
                "AND tenant_id=%s AND owner_user_id=%s",
                [run_date, model_id, self.tenant_id, self.owner_user_id],
            )
            self.assets.upsert("score_result", rows)
        log.info("%s 打分排序 %d 只（已排除 ST），Top%d 已出", run_date, len(scored), top_n)
        return scored.head(top_n)

    @staticmethod
    def _risk_flags(snap: pd.DataFrame) -> dict[str, list[str]]:
        """从截面派生每只股票的风险标记（次日能否买入/风险提示）。

        - 涨停/跌停：limit_status ±1；一字板：is_one_word（次日难以原价买入）。
        - ST：理论上榜单已排除，仍兜底标记。

        注：这是 M6 风险识别（T-M6-2/3）的**提前部分交付**——仅覆盖"可成交性"
        类标记（涨跌停/一字板/ST）；量价背离、跌破均线等完整 RiskDetector 仍属 M6。
        """
        out: dict[str, list[str]] = {}
        for code, r in snap.iterrows():
            flags: list[str] = []
            if bool(r.get("is_st")) if "is_st" in snap else False:
                flags.append("ST")
            ls = r.get("limit_status")
            if ls == 1:
                flags.append("涨停")
            elif ls == -1:
                flags.append("跌停")
            if bool(r.get("is_one_word")) if "is_one_word" in snap else False:
                flags.append("一字板")
            if flags:
                out[code] = flags
        return out
