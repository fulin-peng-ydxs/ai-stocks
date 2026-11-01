"""事件驱动策略回测（T-M5-6，SDD §6.4/§10）。

逐日循环（先卖后买）：在**执行日 D** 成交**信号日 D-1**（数据≤D-1）做出的决策——
T 日选股/卖出判定，T+1 开盘成交，杜绝未来函数。

硬约束
------
- **可成交性按板块涨跌停 + 停牌**（broker）：买/卖只在该股**执行日有 bar** 且开盘价未封死涨/跌停时成交，
  否则**顺延**到下一可交易日。可成交性在**原始价**基准判定（涨跌停 round 到分）；成交/估值在 **hfq** 基准。
- **持仓停牌**：执行日无 bar → 不可卖、按最后可得 hfq close 估值，复牌后再处理。
- **退市/区间末**：回测末日对仍持仓者按最后可得价强平（exit_reason=退市/区间末强平），不悬空。
- **退市股市值**：选股 universe 由 score_result 截面派生（含当时存活、后退市票），不因缺市值丢票。

价格口径：成交/净值/收益率统一 hfq（单调、无需 rebase）；涨跌停可成交性用原始 open/pre_close。
"""

from __future__ import annotations

import json
import math
from datetime import date
from typing import ClassVar

import pandas as pd

from backend.backtest.broker import Broker, can_buy_at_open, can_sell_at_open
from backend.common.logging import get_logger
from backend.config import get_effective_settings
from backend.market_identity import STOCK_CODE_CHANGES, filter_trading_codes, trading_code_at
from backend.market_rules import price_limit_pct_for
from backend.scoring.model import ScoreModel
from backend.storage.duckdb_client import get_client

log = get_logger("backtest.engine")


class BacktestEngine:
    def __init__(
        self,
        client=None,
        model: ScoreModel | None = None,
        ind=None,
        *,
        tenant_id: str | None = None,
        owner_user_id: str | None = None,
    ):
        self.c = client or get_client()
        self.model = model or ScoreModel()
        self.s = get_effective_settings()
        self.tenant_id = tenant_id
        self.owner_user_id = owner_user_id
        from backend.indicators.engine import IndicatorEngine
        # 可注入共享 IndicatorEngine：策略回测与分层分析复用同一实例 → 区间指标快照只算一遍
        self.ind = ind or IndicatorEngine(self.c)

    # ── 数据预载 ──────────────────────────────────────────────
    def _load_prices(self, lo: date, hi: date, ma_period: int) -> dict:
        """预载全市场行情：原始 open/pre_close（涨跌停判定）+ hfq open/close + below_ma 信号。

        返回 {(code, Timestamp): row}，row 含 open_raw/pre_close_raw/open_hfq/close_hfq/pct/below_ma。
        lo 需向前预留 ma_period 个交易日缓冲以算均线。
        """
        from backend.services.stock_st_status import StockSTStatusService

        StockSTStatusService(self.c).assert_published()
        bars = self.c.query_df(
            "SELECT b.code, b.trade_date, b.open, b.pre_close, b.close, "
            "       COALESCE(b.adj_factor_clean, b.adj_factor) AS adj_factor, "
            "       sb.price_limit_pct, st.is_st, st.quality AS st_quality, "
            "       (special.code IS NOT NULL) AS no_price_limit "
            "FROM daily_bar b JOIN stock_basic sb ON sb.code=b.code "
            "LEFT JOIN stock_st_status_daily st ON st.code=b.code AND st.trade_date=b.trade_date "
            "LEFT JOIN stock_special_trading_day special "
            "ON special.code=b.code AND special.trade_date=b.trade_date AND special.active "
            "WHERE b.trade_date BETWEEN ? AND ? ORDER BY b.code, b.trade_date",
            [lo, hi],
        )
        if bars.empty:
            return {}
        bars["trade_date"] = pd.to_datetime(bars["trade_date"])
        af = bars["adj_factor"].fillna(1.0)
        bars["open_hfq"] = bars["open"] * af
        bars["close_hfq"] = bars["close"] * af
        missing_st = bars["is_st"].isna() | (bars["st_quality"] != "accurate")
        if missing_st.any():
            bad = bars.loc[missing_st, ["code", "trade_date"]].head(5)
            raise RuntimeError(
                f"回测区间 ST 点时事实未就绪（{int(missing_st.sum())} 行），示例 "
                f"{bad.to_dict('records')}；请先运行 ST状态刷新"
            )
        # ST 涨跌幅按交易日规则切换：主板 ST 2026-07-06 起 5%→10%，创业/科创仍为20%。
        bars["pct"] = [
            price_limit_pct_for(
                None if pd.isna(t.price_limit_pct) else float(t.price_limit_pct),
                bool(t.is_st),
                t.trade_date,
                code=t.code,
            )
            for t in bars.itertuples(index=False)
        ]
        # below_ma：close_hfq < MA(close_hfq, ma_period)（后向、点时安全、基准一致）
        bars["ma"] = bars.groupby("code")["close_hfq"].transform(
            lambda x: x.rolling(ma_period, min_periods=ma_period).mean()
        )
        bars["below_ma"] = bars["close_hfq"] < bars["ma"]
        out: dict = {}
        for t in bars.itertuples(index=False):
            out[(t.code, t.trade_date)] = t
        return out

    def _load_scores(self, lo: date, hi: date) -> dict:
        """逐日全市场打分 → {Timestamp: DataFrame[code, total_score, grade] desc}。"""
        snap = self.ind.wide_snapshot(lo, hi)
        if snap.empty:
            return {}
        snap["trade_date"] = pd.to_datetime(snap["trade_date"])
        by_day: dict = {}
        for d, g in snap.groupby("trade_date", sort=False):
            from backend.services.stock_st_status import StockSTStatusService

            statuses = StockSTStatusService(self.c).status_map(
                pd.Timestamp(d).date(), g["code"].astype(str).tolist()
            )
            st = {code for code, value in statuses.items() if value}
            g = g[~g["code"].isin(st)]
            if g.empty:
                continue
            scored = self.model.score(g.set_index("code"))
            df = pd.DataFrame({"code": scored.index, "total_score": scored["total_score"].values,
                               "grade": scored["grade"].values})
            by_day[d] = df.sort_values(
                ["total_score", "code"], ascending=[False, True], kind="mergesort"
            ).reset_index(drop=True)
        return by_day

    # ── M2.5：评分方案 + 买卖方案（区间向量化）─────────────────────
    def _attach_range_exprs(self, snap: pd.DataFrame, items: list[dict], lo: date, hi: date) -> pd.DataFrame:
        """批量补齐区间表达式指标，同 key 不同参数也按独立实例求值。"""
        return self.ind.attach_range_columns(snap, items, lo, hi)

    def _tree_hits(self, snap: pd.DataFrame, tree: dict) -> dict:
        """条件树在区间快照上逐行求值 → {Timestamp: set(命中 code)}。"""
        from backend.signals.trade_profile import eval_conditions
        if not tree or ("op" in tree and not tree.get("children")):
            return {}
        hit = eval_conditions(tree, snap.set_index("code"))
        hh = pd.DataFrame({"code": snap["code"].values, "trade_date": snap["trade_date"].values,
                           "hit": hit.values})
        return {d: set(g.loc[g["hit"], "code"]) for d, g in hh.groupby("trade_date", sort=False)}

    _CMP_SYM: ClassVar[dict[str, str]] = {
        ">=": "≥", "<=": "≤", ">": ">", "<": "<", "==": "=", "!=": "≠", "between": "介于",
    }

    def _ind_name_map(self) -> dict:
        df = self.c.query_df("SELECT key, name_cn FROM indicator_def")
        return dict(zip(df["key"], df["name_cn"]))

    def _leaf_label(self, leaf: dict, name_map: dict) -> str:
        """卖出指标叶子 → 简洁中文标签，如 '跌破均线(n=10)' / 'RS强度≥80'。"""
        nm = name_map.get(leaf["indicator"], leaf["indicator"])
        ps = leaf.get("params") or {}
        pstr = ("(" + ",".join(f"{k}={v}" for k, v in ps.items()) + ")") if ps else ""
        val = leaf.get("value")
        if isinstance(val, bool):
            return f"{nm}{pstr}" if val else f"非{nm}{pstr}"
        cmp = leaf.get("cmp", "==")
        if cmp == "between" and isinstance(val, (list, tuple)):
            return f"{nm}{pstr}∈[{val[0]},{val[1]}]"
        return f"{nm}{pstr}{self._CMP_SYM.get(cmp, cmp)}{val}"

    def _sell_leaf_detail(self, snap: pd.DataFrame, tree: dict | None) -> dict:
        """拍平卖树叶子 → {labels:[标签], hits:[{date:set(命中code)}]}，供卖出时标注具体命中指标。"""
        from backend.signals.trade_profile import _eval_leaf, prune_disabled_conditions
        leaves: list[dict] = []

        def walk(n: dict | None) -> None:
            if not n:
                return
            if "op" in n:
                for ch in n.get("children", []):
                    walk(ch)
            else:
                leaves.append(n)

        walk(prune_disabled_conditions(tree))
        if not leaves:
            return {"labels": [], "hits": []}
        name_map = self._ind_name_map()
        labels = [self._leaf_label(lf, name_map) for lf in leaves]
        si = snap.set_index("code")
        codes, dates = snap["code"].values, snap["trade_date"].values
        hits = []
        for lf in leaves:
            b = _eval_leaf(lf, si).values
            hh = pd.DataFrame({"code": codes, "trade_date": dates, "hit": b})
            hits.append({d: set(g.loc[g["hit"], "code"]) for d, g in hh.groupby("trade_date", sort=False)})
        return {"labels": labels, "hits": hits}

    def _decision_data(self, lo: date, hi: date, score_profile: dict | None,
                       buy_tree: dict | None, sell_tree: dict | None) -> tuple[dict, dict, dict, dict]:
        """一次性构建：逐日评分榜 S、买树命中 buy_hits、卖树命中 sell_hits、卖树叶子明细 sell_detail。"""
        from backend.scoring.score_profile import ScoreProfileModel
        from backend.signals.trade_profile import collect_indicators
        snap = self.ind.wide_snapshot(lo, hi)
        if snap.empty:
            return {}, {}, {}, {"labels": [], "hits": []}
        snap = snap.copy()
        snap["trade_date"] = pd.to_datetime(snap["trade_date"])
        from backend.scoring.score_profile import active_score_items
        items: list[dict] = active_score_items(score_profile.get("items", [])) if score_profile else []
        items += collect_indicators(buy_tree or {}) + collect_indicators(sell_tree or {})
        snap = self._attach_range_exprs(snap, items, lo, hi)
        # 评分：有评分方案时遵循 include_st；旧固定模型兼容路径仍排除 ST。
        scorer = ScoreProfileModel(score_profile) if score_profile else self.model
        snap_idx = snap.set_index("code")
        scored = scorer.score(snap_idx)
        sc = pd.DataFrame({"code": snap_idx.index, "trade_date": snap["trade_date"].values,
                           "total_score": scored["total_score"].values, "grade": scored["grade"].values})
        kept = []
        from backend.services.stock_st_status import StockSTStatusService

        st_service = StockSTStatusService(self.c)
        for day, group in sc.groupby("trade_date", sort=False):
            statuses = st_service.status_map(
                pd.Timestamp(day).date(), group["code"].astype(str).tolist()
            )
            if score_profile and bool(score_profile.get("include_st", True)):
                kept.append(group)
            else:
                kept.append(group[~group["code"].map(statuses).astype(bool)])
        sc = pd.concat(kept, ignore_index=True) if kept else sc.iloc[0:0]
        S = {d: g.sort_values(
                ["total_score", "code"], ascending=[False, True], kind="mergesort"
            ).reset_index(drop=True)[["code", "total_score", "grade"]]
             for d, g in sc.groupby("trade_date", sort=False)}
        buy_hits = self._tree_hits(snap, buy_tree) if buy_tree else {}
        sell_hits = self._tree_hits(snap, sell_tree) if sell_tree else {}
        sell_detail = self._sell_leaf_detail(snap, sell_tree) if sell_tree else {"labels": [], "hits": []}
        return S, buy_hits, sell_hits, sell_detail

    def _trading_days(self, lo: date, hi: date) -> list[pd.Timestamp]:
        df = self.c.query_df(
            "SELECT DISTINCT trade_date FROM daily_bar WHERE trade_date BETWEEN ? AND ? "
            "ORDER BY trade_date", [lo, hi],
        )
        return [pd.Timestamp(d) for d in df["trade_date"]]

    def _benchmark(self, code: str, days: list[pd.Timestamp]) -> pd.Series:
        df = self.c.query_df(
            "SELECT trade_date, close FROM index_bar WHERE index_code = ? "
            "AND trade_date BETWEEN ? AND ? ORDER BY trade_date",
            [code, days[0].date(), days[-1].date()],
        )
        if df.empty:
            return pd.Series(dtype=float)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df.set_index("trade_date")["close"]

    # ── 主循环 ────────────────────────────────────────────────
    def run(self, params: dict) -> dict:
        bt = self.s.backtest
        d0 = date.fromisoformat(params["date_start"]) if isinstance(params["date_start"], str) else params["date_start"]
        d1 = date.fromisoformat(params["date_end"]) if isinstance(params["date_end"], str) else params["date_end"]
        top_n = int(params.get("top_n", bt.top_n))
        init_cap = float(params.get("initial_capital", bt.initial_capital))
        ma_period = int(params.get("sell_ma_period", bt.sell_ma_period))
        max_hold = params.get("max_hold_days")          # 可选：到期卖出
        take_profit = params.get("take_profit")          # 可选：止盈（如 0.30）
        stop_loss = params.get("stop_loss")              # 可选：止损（如 0.10 表示 -10%）
        rebalance_days = int(params.get("rebalance_days", 1))
        profile_id = params.get("profile_id")
        bench_code = params.get("benchmark", bt.benchmark_main)
        industry_max_pct = params.get("industry_max_pct", bt.industry_max_pct)

        # M2.5：买卖方案（买/卖/兜底）与评分方案。给定即接入，否则走旧式（评分=固定模型，卖出=跌破MA+止盈止损到期）。
        buy_tree: dict | None = None
        sell_tree: dict | None = None
        score_profile: dict | None = None
        if params.get("trade_profile_id"):
            from backend.signals.trade_profile import TradeProfileRepo
            tp = TradeProfileRepo(
                self.c,
                tenant_id=self.tenant_id,
                owner_user_id=self.owner_user_id,
            ).get_visible(params["trade_profile_id"])
            if not tp:
                return {"error": f"买卖方案不存在: {params['trade_profile_id']}"}
            buy_tree, sell_tree = tp.get("buy_tree") or {}, tp.get("sell_tree") or {}
            bs = tp.get("backstop") or {}
            if bs.get("take_profit") is not None:
                take_profit = bs["take_profit"]
            if bs.get("stop_loss") is not None:
                stop_loss = bs["stop_loss"]
            if bs.get("max_hold_days") is not None:
                max_hold = bs["max_hold_days"]
        if params.get("score_profile_id"):
            from backend.scoring.score_profile import ScoreProfileRepo
            score_profile = ScoreProfileRepo(
                self.c,
                tenant_id=self.tenant_id,
                owner_user_id=self.owner_user_id,
            ).get_visible(params["score_profile_id"])
            if not score_profile:
                return {"error": f"评分方案不存在: {params['score_profile_id']}"}
        use_profiles = bool(buy_tree or sell_tree or score_profile)

        days = self._trading_days(d0, d1)
        if len(days) < 2:
            return {"error": "区间交易日不足"}
        # 价格预载需向前缓冲 ma_period 个交易日
        buf_days = self._trading_days(date(d0.year - 1, d0.month, d0.day), d0)
        lo_price = buf_days[-(ma_period + 5)].date() if len(buf_days) > ma_period + 5 else d0
        P = self._load_prices(lo_price, d1, ma_period)
        if use_profiles:
            S, buy_hits, sell_hits, sell_detail = self._decision_data(d0, d1, score_profile, buy_tree, sell_tree)
        else:
            S, buy_hits, sell_hits = self._load_scores(d0, d1), {}, {}
            sell_detail = {"labels": [], "hits": []}
        sell_labels: list[str] = sell_detail.get("labels", [])
        sell_leaf_hits: list[dict] = sell_detail.get("hits", [])

        def sell_hit_labels(code: str, day) -> list[str]:
            """该票当日命中的卖出指标标签（部分命中时用于明示原因）。"""
            return [sell_labels[i] for i, h in enumerate(sell_leaf_hits) if code in h.get(day, set())]

        bench = self._benchmark(bench_code, days)

        # 可选：方案命中（限制候选）。用 HitPrecomputer 在全区间一次性预算（T-M5-10），
        # 避免逐调仓日逐股重算 expr。返回 {date: set(命中 code)}。
        hits_by_day: dict = {}
        if profile_id:
            from backend.backtest.precompute import HitPrecomputer
            from backend.screening.profile import ProfileRepo
            prof = ProfileRepo(
                self.c,
                tenant_id=self.tenant_id,
                owner_user_id=self.owner_user_id,
            ).get_visible(profile_id, include_owner=True)
            if not prof:
                return {"error": f"方案不存在: {profile_id}"}
            hits_by_day = HitPrecomputer(self.c).precompute(prof["expression"], d0, d1)

        # 可选单行业持仓上限（趋势龙头常扎堆，防过度集中）
        ind_map: dict = {}
        ind_cap: int | None = None
        if industry_max_pct:
            ind_df = self.c.query_df("SELECT code, industry FROM stock_basic")
            ind_map = dict(zip(ind_df["code"], ind_df["industry"]))
            ind_cap = max(1, math.ceil(float(industry_max_pct) * top_n))

        broker = Broker(cash=init_cap)
        equity_rows: list[dict] = []
        trades: list[dict] = []
        seq = 0
        peak = init_cap
        bench0 = float(bench.loc[days[0]]) if (len(bench) and days[0] in bench.index) else None
        pending_sells: set[str] = set()  # 触发卖出但因停牌/跌停顺延的持仓

        def price_row(code: str, day: pd.Timestamp):
            return P.get((code, day))

        def exit_notes(pos, reason, detail=None):
            if not pos.code_changes:
                return detail
            labels = json.loads(detail) if detail else [reason]
            return json.dumps([*labels, *pos.code_changes], ensure_ascii=False)

        def transfer_positions(day):
            # 只用切换前两代码同日的原始价/有效因子校准，绝不以跨日价格比抹去真实收益。
            for change in STOCK_CODE_CHANGES:
                if change.previous_code not in broker.positions or day.date() < change.effective_date:
                    continue
                pairs = [(stamp, old, P.get((change.current_code, stamp)))
                         for (code, stamp), old in P.items()
                         if code == change.previous_code and stamp.date() < change.effective_date]
                pairs = [(stamp, old, new) for stamp, old, new in pairs if new is not None]
                if not pairs:
                    raise ValueError(f"{change.previous_code}→{change.current_code} 缺切换前共同复权锚点")
                _, old, new = max(pairs, key=lambda item: item[0])
                factors = (old.adj_factor, new.adj_factor)
                if (not all(math.isfinite(x) and x > 0 for x in factors)
                        or not math.isfinite(old.close) or not math.isfinite(new.close)
                        or abs(old.close - new.close) > .011):
                    raise ValueError(f"{change.previous_code}→{change.current_code} 复权锚点价格或因子不一致")
                broker.transfer_code(change.previous_code, change.current_code,
                                     old.adj_factor / new.adj_factor, day.date())
                if change.previous_code in pending_sells:
                    pending_sells.remove(change.previous_code)
                    pending_sells.add(change.current_code)

        for i, D in enumerate(days):
            transfer_positions(D)
            sig = days[i - 1] if i > 0 else None  # 信号日 = 前一交易日
            sold_today: set[str] = set()  # 当日已卖出的票，禁止当日买回（防同日"卖了又买"churn）

            # ── 1. 卖出（执行信号日触发的卖出，T+1=D 开盘成交）──
            if sig is not None:
                # 评估卖出信号（基于信号日数据）
                for code in list(broker.positions.keys()):
                    pos = broker.positions[code]
                    srow = price_row(code, sig)
                    trigger = code in pending_sells
                    reason = "顺延" if trigger else None
                    exit_detail = None  # 卖树部分命中时记命中指标标签（JSON）；全命中/非卖树为空
                    if srow is not None:
                        cur = srow.close_hfq * pos.price_scale
                        ret = cur / pos.entry_price - 1.0
                        hold = i - 1 - days.index(pd.Timestamp(pos.entry_date)) if pd.Timestamp(pos.entry_date) in days else 0
                        # 卖出信号：有买卖方案则用 sell_tree 命中；否则旧式跌破 MA
                        if use_profiles:
                            sell_sig = trading_code_at(code, sig.date()) in sell_hits.get(sig, set())
                            sell_label = "卖出信号"
                        else:
                            sell_sig = bool(srow.below_ma)
                            sell_label = f"跌破MA{ma_period}"
                        if sell_sig:
                            trigger, reason = True, sell_label
                            if use_profiles and sell_labels:  # 部分命中 → 标注命中了哪些卖出指标
                                hl = sell_hit_labels(trading_code_at(code, sig.date()), sig)
                                if hl and len(hl) < len(sell_labels):
                                    exit_detail = json.dumps(hl, ensure_ascii=False)
                        elif take_profit is not None and ret >= float(take_profit):
                            trigger, reason = True, "止盈"
                        elif stop_loss is not None and ret <= -abs(float(stop_loss)):
                            trigger, reason = True, "止损"
                        elif max_hold is not None and hold >= int(max_hold):
                            trigger, reason = True, "到期"
                    if not trigger:
                        continue
                    # 执行日 D 撮合：需有 bar 且开盘未封跌停
                    drow = price_row(code, D)
                    if drow is None or not can_sell_at_open(drow.open, drow.pre_close, drow.pct,
                            no_price_limit=drow.no_price_limit):
                        pending_sells.add(code)  # 顺延
                        continue
                    pending_sells.discard(code)
                    f = broker.sell_all(code, D, drow.open_hfq)
                    if f:
                        sold_today.add(code)  # 当日不再买回
                        entry_dt = pd.Timestamp(pos.entry_date)
                        hold_days = days.index(D) - days.index(entry_dt) if entry_dt in days else 0
                        seq += 1
                        trades.append({
                            "seq": seq, "code": code, "entry_date": entry_dt.date(),
                            "entry_price": round(pos.entry_price, 4), "exit_date": D.date(),
                            "exit_price": round(f.price, 4), "exit_reason": reason,
                            "exit_detail": exit_notes(pos, reason, exit_detail),
                            "shares": f.shares,
                            "return_pct": round((f.cash_delta - pos.cost_basis) / pos.cost_basis, 6),
                            "pnl": round(f.cash_delta - pos.cost_basis, 2),
                            "hold_days": hold_days, "grade": pos.grade, "entry_score": pos.entry_score,
                            "entry_rank": pos.entry_rank,
                            "entry_pick_rank": pos.entry_pick_rank, "entry_pool": pos.entry_pool,
                        })

            # ── 2. 选股（信号日 sig 截面，排除已持仓）+ 3. 买入（D 开盘）──
            do_rebalance = (sig is not None) and (i - 1) % rebalance_days == 0
            if do_rebalance and len(broker.positions) < top_n:
                cand = S.get(sig)
                if cand is not None and not cand.empty:
                    cand = filter_trading_codes(cand.assign(trade_date=sig))
                    codes_ranked = cand["code"].tolist()
                    grade_map = dict(zip(cand["code"], cand["grade"]))
                    score_map = dict(zip(cand["code"], cand["total_score"]))
                    # 全市场评分榜名次（1-based，含未买入者；用于"每日榜单排名"）
                    rank_map = {c: i + 1 for i, c in enumerate(codes_ranked)}
                    if profile_id:
                        hitset = hits_by_day.get(sig.date(), set())
                        codes_ranked = [c for c in codes_ranked if c in hitset]
                    # 买入门槛：有买卖方案的 buy_tree 时，须同时 buy_tree 成立（筛选命中 且 buy_tree 成立才买）
                    if buy_tree:
                        bset = buy_hits.get(sig, set())
                        codes_ranked = [c for c in codes_ranked if c in bset]
                    # 方案内排名（命中票按评分排序后的优先级）+ 候选池大小（解释"为什么买它"）
                    pick_map = {c: i + 1 for i, c in enumerate(codes_ranked)}
                    pool = len(codes_ranked)
                    # 信号规则在 T 日旧代码求值；T+1 若更码，则按当天真实代码撮合。
                    execution_codes = {code: trading_code_at(code, D.date()) for code in codes_ranked}
                    grade_map = {execution_codes.get(c, c): v for c, v in grade_map.items()}
                    score_map = {execution_codes.get(c, c): v for c, v in score_map.items()}
                    rank_map = {execution_codes.get(c, c): v for c, v in rank_map.items()}
                    pick_map = {execution_codes[c]: v for c, v in pick_map.items()}
                    codes_ranked = [execution_codes[c] for c in codes_ranked]
                    slots = top_n - len(broker.positions)
                    alloc = broker.cash / max(slots, 1)
                    # 当前各行业持仓数（行业上限用）
                    ind_count: dict = {}
                    if ind_cap is not None:
                        for c2 in broker.positions:
                            ind = ind_map.get(c2)
                            ind_count[ind] = ind_count.get(ind, 0) + 1
                    for code in codes_ranked:
                        if slots <= 0:
                            break
                        if code in broker.positions or code in sold_today:
                            continue  # 已持有 / 当日刚卖出 → 不(再)买
                        if ind_cap is not None:
                            ind = ind_map.get(code)
                            if ind_count.get(ind, 0) >= ind_cap:
                                continue  # 该行业已达上限，跳过
                        drow = price_row(code, D)
                        if drow is None or not can_buy_at_open(drow.open, drow.pre_close, drow.pct,
                            no_price_limit=drow.no_price_limit):
                            continue
                        sc = score_map.get(code)
                        f = broker.buy(code, D, drow.open_hfq, alloc,
                                       grade=grade_map.get(code, ""), rank=rank_map.get(code, 0),
                                       pick_rank=pick_map.get(code, 0), pool=pool,
                                       score=round(float(sc), 2) if sc is not None else None)
                        if f:
                            slots -= 1
                            if ind_cap is not None:
                                ind = ind_map.get(code)
                                ind_count[ind] = ind_count.get(ind, 0) + 1

            # ── 4. 估值（D 收盘）──
            marks = {code: price_row(code, D).close_hfq for code in broker.positions
                     if price_row(code, D) is not None}
            broker.mark(marks)
            eq = broker.equity()
            peak = max(peak, eq)
            bench_eq = (init_cap * float(bench.loc[D]) / bench0
                        if bench0 and D in bench.index else None)
            equity_rows.append({
                "trade_date": D.date(), "equity": round(eq, 2), "cash": round(broker.cash, 2),
                "position_value": round(broker.position_value(), 2),
                "n_positions": len(broker.positions),
                "drawdown": round(eq / peak - 1.0, 6),
                "benchmark_equity": round(bench_eq, 2) if bench_eq is not None else None,
            })

        # ── 区间末强平（按最后估值价，退市/停牌均归入）──
        last_day = days[-1]
        for code in list(broker.positions.keys()):
            pos = broker.positions[code]
            drow = price_row(code, last_day)
            exit_px = drow.open_hfq if drow is not None else pos.last_price / pos.price_scale
            reason = "区间末强平" if drow is not None else "停牌/退市强平"
            f = broker.sell_all(code, last_day, exit_px)
            if f:
                entry_dt = pd.Timestamp(pos.entry_date)
                seq += 1
                trades.append({
                    "seq": seq, "code": code, "entry_date": entry_dt.date(),
                    "entry_price": round(pos.entry_price, 4), "exit_date": last_day.date(),
                    "exit_price": round(f.price, 4), "exit_reason": reason,
                    "exit_detail": exit_notes(pos, reason),
                    "shares": f.shares,
                    "return_pct": round((f.cash_delta - pos.cost_basis) / pos.cost_basis, 6),
                    "pnl": round(f.cash_delta - pos.cost_basis, 2),
                    "hold_days": days.index(last_day) - days.index(entry_dt) if entry_dt in days else 0,
                    "grade": pos.grade, "entry_score": pos.entry_score, "entry_rank": pos.entry_rank,
                    "entry_pick_rank": pos.entry_pick_rank, "entry_pool": pos.entry_pool,
                })

        equity_df = pd.DataFrame(equity_rows)
        return {
            "params": params, "initial_capital": init_cap,
            "days": [d.date().isoformat() for d in days],
            "equity": equity_df, "trades": trades,
            "benchmark_code": bench_code,
        }
