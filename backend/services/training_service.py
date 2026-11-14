"""盘感训练服务（agent-works/market-sense-training/）。

手动交易训练：盲测 + 逐日揭示 + 真实撮合（买 T+0 / 卖 T+1）。
- 一局 session = N 个回合 round；每回合 = 一只随机股 + 区间内随机起点 + 连续 window_days 个交易日窗口。
- 回合内独立资金账户（初始资金相同），按手分批买卖。
- 买入 T+0：用户在 cursor 日（看到的最后一根 K，含当日收盘）尾盘决策买入，按当日收盘价即时成交。
- 卖出 T+1：当日登记 pending → 揭示下一日时按次日开盘价成交（当日买入的仓位最早次日才能卖，天然满足 T+1）。
- 真实约束：收盘封涨停买不到 / 次日开盘涨跌停买不到卖不出（按原始价 half-up 到分判定，复用 broker）。
- 价格口径：回合内统一以 start_date 的 adj_factor_clean 为基准做前复权（base_factor 固定），
  显示与记账价位一致，且只用 <= start_date 的因子（点时安全、不引未来）。
- 防作弊：running 态接口绝不返回未揭示的未来 K 线，也不返回真实 code/name/真实日期。
"""

from __future__ import annotations

import json
import random
from datetime import date, datetime

import pandas as pd

from backend.auth.context import get_current_owner
from backend.backtest.broker import can_buy_at_open, can_sell_at_open
from backend.common.logging import get_logger
from backend.common.timeutil import shanghai_now_naive
from backend.config import get_effective_settings
from backend.indicators.compute import compute_macd
from backend.market_rules import price_limit_pct_for
from backend.price_adjustment import adjust_price_columns, effective_factors, price_scale
from backend.storage.duckdb_client import get_client
from backend.storage.pg_client import get_pg_client

log = get_logger("services.training")

MIN_HISTORY = 60          # 起点前最少历史交易日（开局抽样校验门槛）
VIEW_HISTORY = 480        # 起点前展示的历史交易日上限（≈2 年，支持 K 线全范围选择）
MAX_PICK_RETRY = 80       # 随机抽样最大重试次数
GRADE_BANDS = [(90, "S"), (80, "A"), (70, "B"), (60, "C")]


def _now() -> datetime:
    return shanghai_now_naive()


def _to_date(v) -> date:
    return pd.Timestamp(v).date()


def _grade_of(score: float) -> str:
    for thr, g in GRADE_BANDS:
        if score >= thr:
            return g
    return "D"


class TrainingService:
    """盘感训练服务（混合持久层 stage1·T2）。

    训练 session/round/trade 属用户资产（→PG，self.pg）；行情读走 DuckDB（self.c）。
    归属：training_session 按 tenant_id+owner_user_id 过滤(所有权闸门)；round/trade 经
    session 已鉴权，按 session_id 过滤。auth 未落地前默认 default/admin。
    第一位参保留为 market(DuckDB) 兼容历史 TrainingService(c) 调用。
    """

    def __init__(self, client=None, *, tenant_id: str | None = None,
                 owner_user_id: str | None = None):
        self.c = client or get_client()
        from backend.storage.ddl import init_db
        init_db(self.c)
        self.pg = get_pg_client()
        _ctx_t, _ctx_o = get_current_owner()
        self.tenant_id = tenant_id or _ctx_t
        self.owner_user_id = owner_user_id or _ctx_o
        bt = get_effective_settings().backtest
        self.cost = bt.cost
        self.lot = bt.lot_size

    @property
    def _op(self) -> list:
        return [self.tenant_id, self.owner_user_id]

    # ════════════════════════════════════════════════════════════
    # 费用
    # ════════════════════════════════════════════════════════════
    def _buy_fee(self, gross: float, fee_enabled: bool) -> float:
        if not fee_enabled:
            return 0.0
        commission = max(gross * self.cost.commission_rate, self.cost.commission_min)
        return commission + gross * self.cost.transfer_fee_rate

    def _sell_fee(self, gross: float, fee_enabled: bool) -> float:
        if not fee_enabled:
            return 0.0
        commission = max(gross * self.cost.commission_rate, self.cost.commission_min)
        return commission + gross * self.cost.stamp_tax_rate + gross * self.cost.transfer_fee_rate

    def _slip(self, fee_enabled: bool) -> float:
        return self.cost.slippage if fee_enabled else 0.0

    # ════════════════════════════════════════════════════════════
    # 行情访问（点时安全 + 回合固定复权基准）
    # ════════════════════════════════════════════════════════════
    def _latest_trade_date(self) -> date | None:
        d = self.c.query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]
        return None if d is None or pd.isna(d) else _to_date(d)

    def _earliest_trade_date(self) -> date | None:
        d = self.c.query_df("SELECT min(trade_date) AS d FROM daily_bar").iloc[0]["d"]
        return None if d is None or pd.isna(d) else _to_date(d)

    def _raw_bar(self, code: str, d: date) -> dict | None:
        """某股某日原始（不复权）行情行 + 干净因子；无行（停牌/无数据）→ None。"""
        df = self.c.query_df(
            "SELECT open, high, low, close, pre_close, volume, amount, turnover_rate, "
            "COALESCE(adj_factor_clean, adj_factor) AS f "
            "FROM daily_bar WHERE code = ? AND trade_date = ?",
            [code, d],
        )
        if df.empty:
            return None
        effective_factors(df, factor_column="f")
        r = df.iloc[0]
        return {k: (None if pd.isna(r[k]) else float(r[k])) for k in
                ("open", "high", "low", "close", "pre_close", "volume", "amount", "turnover_rate", "f")}

    def _forward_dates(self, code: str, start: date, n: int) -> list[date]:
        """从 start（含）起该股的前 n 个实际交易日（停牌日自然跳过）。"""
        df = self.c.query_df(
            "SELECT trade_date FROM daily_bar WHERE code = ? AND trade_date >= ? "
            "ORDER BY trade_date LIMIT ?",
            [code, start, n],
        )
        return [_to_date(x) for x in df["trade_date"]]

    def _next_trade_date(self, code: str, after: date) -> date | None:
        df = self.c.query_df(
            "SELECT min(trade_date) AS d FROM daily_bar WHERE code = ? AND trade_date > ?",
            [code, after],
        )
        d = df.iloc[0]["d"]
        return None if d is None or pd.isna(d) else _to_date(d)

    def _bars_for_view(self, rnd: dict, upto: date, reveal_dates: bool) -> tuple[list[dict], dict]:
        """构造展示用 K 线：起点前 MIN_HISTORY 历史 + 起点至 upto 的揭示区间，按 base_factor 复权。

        返回 (bars, date_map)；bars 每根含相对日 rel_day（起点=0，历史为负）。
        reveal_dates=False（盲测）时不返回真实日期，date 字段用相对日标签。
        """
        code, start, base = rnd["code"], rnd["start_date"], rnd["base_factor"]
        df = self.c.query_df(
            "SELECT trade_date, open, high, low, close, pre_close, volume, amount, turnover_rate, "
            "COALESCE(adj_factor_clean, adj_factor) AS f "
            "FROM daily_bar WHERE code = ? AND trade_date <= ? ORDER BY trade_date",
            [code, upto],
        )
        if df.empty:
            return [], {}
        dates = [_to_date(x) for x in df["trade_date"]]
        try:
            idx0 = dates.index(start)
        except ValueError:
            idx0 = 0
        lo = max(0, idx0 - VIEW_HISTORY)
        scale = price_scale(df.iloc[lo:], "qfq", base_factor=float(base), factor_column="f")
        bars, date_map = [], {}
        for i in range(lo, len(df)):
            r = df.iloc[i]
            rel = i - idx0
            factor_scale = float(scale.iloc[i - lo])
            label = dates[i].isoformat() if reveal_dates else f"D{rel:+d}"
            date_map[rel] = label
            bars.append({
                "date": label,
                "rel_day": rel,
                "open": float(r["open"]) * factor_scale,
                "high": float(r["high"]) * factor_scale,
                "low": float(r["low"]) * factor_scale,
                "close": float(r["close"]) * factor_scale,
                "pre_close": None if pd.isna(r["pre_close"]) else float(r["pre_close"]) * factor_scale,
                "volume": None if pd.isna(r["volume"]) else int(r["volume"]),
                "amount": None if pd.isna(r["amount"]) else float(r["amount"]),
                "turnover_rate": None if pd.isna(r["turnover_rate"]) else float(r["turnover_rate"]),
            })
        # 训练 K 线附带 MACD：复用后端原子指标（12/26/9，严格后向），由脱敏前复权 close 算出，
        # 训练中/结算回看共用，且不引用真实代码（防作弊）。暖机不足的行保留 null。
        if bars:
            closes = pd.Series([b["close"] for b in bars])
            macd = compute_macd(closes)
            for b, row in zip(bars, macd.to_dict("records")):
                for key in ("macd_diff", "macd_dea", "macd_hist"):
                    v = row.get(key)
                    b[key] = None if v is None or pd.isna(v) else round(float(v), 3)
                for key in ("macd_golden_cross", "macd_dead_cross"):
                    v = row.get(key)
                    b[key] = None if v is None or pd.isna(v) else bool(v)
        return bars, date_map

    def _disp_price(self, raw_price: float, factor: float, base: float) -> float:
        frame = pd.DataFrame({"close": [raw_price], "adj_factor": [factor]})
        return float(adjust_price_columns(frame, "qfq", base_factor=base).iloc[0]["close"])

    # ════════════════════════════════════════════════════════════
    # 开局与随机抽样
    # ════════════════════════════════════════════════════════════
    def create_session(self, params: dict) -> dict:
        mode = params.get("mode", "single")
        window_days = int(params.get("window_days", 20))
        n_rounds = 1 if mode == "single" else int(params.get("n_rounds", 5))
        initial_capital = float(params.get("initial_capital", 100_000))
        fee_enabled = bool(params.get("fee_enabled", True))
        filters = params.get("filters") or {}

        if window_days < 5 or window_days > 60:
            raise ValueError("连续交易日窗口需在 5~60 之间")
        if n_rounds < 1 or n_rounds > 20:
            raise ValueError("回合数需在 1~20 之间")
        if initial_capital < 10_000:
            raise ValueError("初始资金过小（≥10000）")

        emin, emax = self._earliest_trade_date(), self._latest_trade_date()
        if emin is None:
            raise ValueError("行情库为空，请先在数据管理补充行情")
        range_start = _to_date(params["range_start"]) if params.get("range_start") else emin
        range_end = _to_date(params["range_end"]) if params.get("range_end") else emax
        # 起点须留出 window_days 的后续空间；用日历交易日近似（实际按个股交易日校验）
        cal = self.c.query_df(
            "SELECT trade_date FROM trade_calendar "
            "WHERE is_open AND trade_date BETWEEN ? AND ? ORDER BY trade_date",
            [range_start, range_end],
        )
        cal_dates = [_to_date(x) for x in cal["trade_date"]]
        if len(cal_dates) < window_days + 1:
            raise ValueError("所选交易日范围过窄，放不下一个完整窗口")
        pickable = cal_dates[: max(1, len(cal_dates) - window_days)]  # 末尾留窗口空间

        rounds: list[dict] = []
        used_codes: set[str] = set()
        for _ in range(MAX_PICK_RETRY):
            if len(rounds) >= n_rounds:
                break
            start = random.choice(pickable)
            pool = self.c_universe(start, filters)
            pool = [c for c in pool if c not in used_codes]
            if not pool:
                continue
            code = random.choice(pool)
            fwd = self._forward_dates(code, start, window_days)
            if len(fwd) < window_days:
                continue  # 退市/数据不足，窗口排不满
            hist = self.c.query_df(
                "SELECT count(*) AS n FROM daily_bar WHERE code = ? AND trade_date < ?",
                [code, start],
            ).iloc[0]["n"]
            if int(hist) < MIN_HISTORY:
                continue
            srow = self._raw_bar(code, start)
            if not srow or not srow.get("f"):
                continue
            limit_pct = self._price_limit_pct(code)
            used_codes.add(code)
            rounds.append({
                "code": code, "start_date": start, "end_date": fwd[-1],
                "base_factor": srow["f"], "price_limit_pct": limit_pct,
            })
        if len(rounds) < n_rounds:
            raise ValueError("满足条件的可用样本不足，请放宽交易日范围或过滤条件")

        sid = "train_" + _now().strftime("%Y%m%d%H%M%S%f")
        now = _now()
        self.pg.execute(
            "INSERT INTO training_session (id,tenant_id,owner_user_id,mode,range_start,range_end,n_rounds,"
            "window_days,initial_capital,filters,fee_enabled,status,cur_round,created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [sid, self.tenant_id, self.owner_user_id, mode, range_start, range_end, n_rounds,
             window_days, initial_capital,
             json.dumps(filters, ensure_ascii=False), fee_enabled, "running", 0, now],
        )
        for seq, rd in enumerate(rounds):
            self.pg.execute(
                "INSERT INTO training_round (session_id,tenant_id,owner_user_id,seq,code,start_date,"
                "end_date,window_days,base_factor,price_limit_pct,cursor_date,cursor_idx,status,cash,"
                "pos_shares,pos_cost,pos_avg_price,pending,realized_pnl) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [sid, self.tenant_id, self.owner_user_id, seq, rd["code"], rd["start_date"],
                 rd["end_date"], window_days,
                 rd["base_factor"], rd["price_limit_pct"], rd["start_date"], 0,
                 "running" if seq == 0 else "pending", initial_capital, 0, 0.0, 0.0, None, 0.0],
            )
        log.info("盘感训练开局 %s mode=%s rounds=%d window=%d", sid, mode, n_rounds, window_days)
        return self.get_view(sid)

    def c_universe(self, asof: date, filters: dict) -> list[str]:
        from backend.storage.repository import MarketRepository
        return MarketRepository(self.c).get_universe_asof(asof, filters)

    def _price_limit_pct(self, code: str) -> float:
        df = self.c.query_df("SELECT price_limit_pct FROM stock_basic WHERE code = ?", [code])
        if df.empty or pd.isna(df.iloc[0]["price_limit_pct"]):
            return 0.10
        return float(df.iloc[0]["price_limit_pct"])

    def _effective_price_limit_pct(self, code: str, trade_date: date, board_pct: float) -> float:
        from backend.services.stock_st_status import StockSTStatusService

        is_st = StockSTStatusService(self.c).status_map(trade_date, [code])[code]
        return price_limit_pct_for(board_pct, is_st, trade_date, code=code)

    # ════════════════════════════════════════════════════════════
    # 读取与视图
    # ════════════════════════════════════════════════════════════
    def _session_row(self, sid: str) -> dict | None:
        # 所有权闸门：训练存取统一先过此处的归属过滤，下游 round/trade 按 session_id 即可
        df = self.pg.query_df(
            "SELECT * FROM training_session WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
            [sid, *self._op])
        return None if df.empty else df.iloc[0].to_dict()

    def _round_rows(self, sid: str) -> list[dict]:
        # 归属过滤不可省：session_id 在不同 owner 间可碰撞（复合主键允许），仅按 session_id 会串读
        df = self.pg.query_df(
            "SELECT * FROM training_round WHERE session_id=%s AND tenant_id=%s AND owner_user_id=%s "
            "ORDER BY seq", [sid, *self._op])
        return [r.to_dict() for _, r in df.iterrows()]

    def _round_trades(self, sid: str, seq: int) -> list[dict]:
        df = self.pg.query_df(
            "SELECT * FROM training_trade WHERE session_id=%s AND round_seq=%s "
            "AND tenant_id=%s AND owner_user_id=%s ORDER BY seq", [sid, seq, *self._op])
        return [r.to_dict() for _, r in df.iterrows()]

    def _norm_round(self, rnd: dict) -> dict:
        """统一类型（pandas/numpy → python）。"""
        out = dict(rnd)
        for k in ("start_date", "end_date", "cursor_date"):
            if out.get(k) is not None and not pd.isna(out[k]):
                out[k] = _to_date(out[k])
        for k in ("base_factor", "price_limit_pct", "cash", "pos_cost", "pos_avg_price",
                  "realized_pnl", "round_return", "benchmark_return", "final_equity"):
            out[k] = None if out.get(k) is None or pd.isna(out.get(k)) else float(out[k])
        for k in ("seq", "window_days", "cursor_idx", "pos_shares"):
            out[k] = None if out.get(k) is None or pd.isna(out.get(k)) else int(out[k])
        out["pending"] = json.loads(out["pending"]) if out.get("pending") else None
        return out

    def get_view(self, sid: str) -> dict:
        """开局/训练中视图（盲测脱敏）；completed 时转交 get_detail。"""
        s = self._session_row(sid)
        if not s:
            raise ValueError("训练不存在")
        if s["status"] == "completed":
            return self.get_detail(sid)
        cur = int(s["cur_round"])
        rounds = [self._norm_round(r) for r in self._round_rows(sid)]
        rnd = rounds[cur]
        bars, date_map = self._bars_for_view(rnd, rnd["cursor_date"], reveal_dates=False)
        cur_close = bars[-1]["close"] if bars else 0.0
        pos_value = rnd["pos_shares"] * cur_close
        equity = rnd["cash"] + pos_value
        trades = self._mask_trades(self._round_trades(sid, cur))
        markers = [{"date": date_map.get(t["rel_day"], f"D{t['rel_day']:+d}"),
                    "rel_day": t["rel_day"], "kind": t["side"],
                    "label": ("买" if t["side"] == "buy" else "卖")} for t in trades]
        return {
            "id": sid, "status": s["status"], "mode": s["mode"],
            "n_rounds": int(s["n_rounds"]), "window_days": int(s["window_days"]),
            "initial_capital": float(s["initial_capital"]), "fee_enabled": bool(s["fee_enabled"]),
            "cur_round": cur,
            "round": {
                "seq": cur, "cursor_idx": rnd["cursor_idx"], "window_days": rnd["window_days"],
                "status": rnd["status"], "is_last_day": rnd["cursor_idx"] >= rnd["window_days"] - 1,
                "cash": round(rnd["cash"], 2), "pos_shares": rnd["pos_shares"],
                "pos_hands": rnd["pos_shares"] // self.lot,
                "pos_avg_price": round(rnd["pos_avg_price"], 3),
                "cur_close": round(cur_close, 3),
                "pos_value": round(pos_value, 2), "equity": round(equity, 2),
                "unrealized_pnl": round(pos_value - rnd["pos_cost"], 2) if rnd["pos_shares"] else 0.0,
                "realized_pnl": round(rnd["realized_pnl"], 2),
                "pending": rnd["pending"],
                "bars": bars, "markers": markers, "trades": trades,
                "lot_size": self.lot,
                # 板块（主板/创业板/科创板）为宽泛分类，与训练选股过滤同口径，
                # 不指向具体个股，盲测阶段同样返回供前端标注。
                "board": self._stock_board(rnd["code"]),
            },
        }

    def _mask_trades(self, trades: list[dict]) -> list[dict]:
        out = []
        for t in trades:
            out.append({
                "seq": int(t["seq"]), "side": t["side"], "rel_day": int(t["rel_day"]),
                "price": round(float(t["price"]), 3), "hands": int(t["hands"]),
                "shares": int(t["shares"]), "fee": round(float(t["fee"]), 2),
                "pnl": None if pd.isna(t["pnl"]) else round(float(t["pnl"]), 2),
                "return_pct": None if pd.isna(t["return_pct"]) else round(float(t["return_pct"]), 4),
                "reason": t.get("reason") or "",
                "auto_close": bool(t.get("auto_close")),
            })
        return out

    # ════════════════════════════════════════════════════════════
    # 下单：买入 T+0 即时成交 / 卖出 T+1 登记 pending
    # ════════════════════════════════════════════════════════════
    def place_intent(self, sid: str, side: str, hands: int, reason: str = "") -> dict:
        s = self._session_row(sid)
        if not s or s["status"] != "running":
            raise ValueError("训练不在进行中")
        if side not in ("buy", "sell"):
            raise ValueError("方向非法")
        hands = int(hands)
        if hands < 1:
            raise ValueError("手数需为正整数")
        cur = int(s["cur_round"])
        rnd = self._norm_round(self._round_rows(sid)[cur])
        if rnd["status"] != "running":
            raise ValueError("当前回合不可操作")
        if rnd["cursor_idx"] >= rnd["window_days"] - 1:
            raise ValueError("已到窗口末日，无法再下单，请结算回合")
        if side == "buy":
            # T+0：买入当日按收盘价即时成交（尾盘决策买入），不进入 pending
            msg = self._execute_buy_now(s, rnd, hands, reason)
            if msg:
                raise ValueError(msg)
            return self.get_view(sid)
        # T+1：卖出登记意图，揭示下一日时按次日开盘价成交
        if hands * self.lot > rnd["pos_shares"]:
            raise ValueError("卖出手数超过持仓")
        pending = {"side": side, "hands": hands, "reason": reason or ""}
        self.pg.execute(
            "UPDATE training_round SET pending=%s WHERE session_id=%s AND seq=%s "
            "AND tenant_id=%s AND owner_user_id=%s",
            [json.dumps(pending, ensure_ascii=False), sid, cur, *self._op])
        return self.get_view(sid)

    def _execute_buy_now(self, s: dict, rnd: dict, hands: int, reason: str) -> str | None:
        """T+0 买入：以当日（cursor）收盘价即时成交。返回失败文案或 None（成功）。"""
        sid, cur = s["id"], int(rnd["seq"])
        fee_on = bool(s["fee_enabled"])
        srow = self._raw_bar(rnd["code"], rnd["cursor_date"])
        if not srow or srow["close"] is None:
            return "当日停牌，买入未成交"
        pct = self._effective_price_limit_pct(
            rnd["code"], rnd["cursor_date"], rnd["price_limit_pct"]
        )
        raw_close, raw_pre = srow["close"], srow["pre_close"]
        # 收盘封涨停则买不到（按原始价 half-up 到分判定，复用 broker 涨停口径）
        if raw_pre and not can_buy_at_open(raw_close, raw_pre, pct):
            return "收盘封涨停，买入未成交"
        price = self._disp_price(raw_close, srow["f"], rnd["base_factor"]) * (1 + self._slip(fee_on))
        shares = hands * self.lot
        gross = price * shares
        fee = self._buy_fee(gross, fee_on)
        total = gross + fee
        if total > rnd["cash"] + 1e-6:
            return "可用资金不足以买入该手数"
        new_shares = rnd["pos_shares"] + shares
        new_cost = rnd["pos_cost"] + total
        self.pg.execute(
            "UPDATE training_round SET cash=%s, pos_shares=%s, pos_cost=%s, pos_avg_price=%s "
            "WHERE session_id=%s AND seq=%s AND tenant_id=%s AND owner_user_id=%s",
            [rnd["cash"] - total, new_shares, new_cost, new_cost / new_shares, sid, cur, *self._op])
        # 当日成交：决策日 = 成交日 = cursor_date，相对日 = cursor_idx
        self._insert_trade(sid, cur, "buy", rnd["cursor_date"], rnd["cursor_date"], rnd["cursor_idx"],
                           price, hands, shares, gross, fee, None, None, reason, False)
        return None

    def cancel_intent(self, sid: str) -> dict:
        s = self._session_row(sid)
        if not s:
            raise ValueError("训练不存在")
        cur = int(s["cur_round"])
        self.pg.execute(
            "UPDATE training_round SET pending=NULL WHERE session_id=%s AND seq=%s "
            "AND tenant_id=%s AND owner_user_id=%s", [sid, cur, *self._op])
        return self.get_view(sid)

    # ════════════════════════════════════════════════════════════
    # 揭示下一日 + T+1 成交结算
    # ════════════════════════════════════════════════════════════
    def reveal(self, sid: str, known_cursor_idx: int | None = None) -> dict:
        s = self._session_row(sid)
        if not s or s["status"] != "running":
            raise ValueError("训练不在进行中")
        cur = int(s["cur_round"])
        rnd = self._norm_round(self._round_rows(sid)[cur])
        if known_cursor_idx is not None and int(known_cursor_idx) != rnd["cursor_idx"]:
            raise ValueError("训练进度已变化，请刷新后重试")
        if rnd["status"] != "running":
            raise ValueError("当前回合不可推进")
        if rnd["cursor_idx"] >= rnd["window_days"] - 1:
            raise ValueError("已到窗口末日，请结算回合")
        next_date = self._next_trade_date(rnd["code"], rnd["cursor_date"])
        if next_date is None:
            raise ValueError("无更多行情，请结算回合")
        fill_msg = self._settle_pending(s, rnd, next_date)
        new_idx = rnd["cursor_idx"] + 1
        self.pg.execute(
            "UPDATE training_round SET cursor_date=%s, cursor_idx=%s WHERE session_id=%s AND seq=%s "
            "AND tenant_id=%s AND owner_user_id=%s",
            [next_date, new_idx, sid, cur, *self._op])
        view = self.get_view(sid)
        view["fill_msg"] = fill_msg
        return view

    def _settle_pending(self, s: dict, rnd: dict, fill_date: date) -> str | None:
        """以 fill_date 开盘价结算 pending 卖出意图（T+1）。返回提示文案或 None。

        买入已在下单当日即时成交（见 _execute_buy_now），正常不再走此处；
        下面的 buy 分支仅兼容历史遗留的 buy pending（按次日开盘价结算）。
        """
        pending = rnd["pending"]
        if not pending:
            return None
        sid, cur = s["id"], int(rnd["seq"])
        fee_on = bool(s["fee_enabled"])
        frow = self._raw_bar(rnd["code"], fill_date)
        disp_open = self._disp_price(frow["open"], frow["f"], rnd["base_factor"]) if frow else None
        # 因子未就绪必须在资产状态写入前失败，保留订单以便修复后重试。
        self.pg.execute(
            "UPDATE training_round SET pending=NULL WHERE session_id=%s AND seq=%s "
            "AND tenant_id=%s AND owner_user_id=%s", [sid, cur, *self._op])
        if not frow:
            return "次日停牌，订单未成交"
        pct = self._effective_price_limit_pct(
            rnd["code"], fill_date, rnd["price_limit_pct"]
        )
        raw_open, raw_pre = frow["open"], frow["pre_close"]
        side, hands = pending["side"], int(pending["hands"])
        reason = pending.get("reason", "")
        if side == "buy":
            if raw_pre and not can_buy_at_open(raw_open, raw_pre, pct):
                return "次日开盘涨停，买入未成交"
            price = disp_open * (1 + self._slip(fee_on))
            shares = hands * self.lot
            gross = price * shares
            fee = self._buy_fee(gross, fee_on)
            total = gross + fee
            # 隔夜价格变动可能超出现金 → 缩减到买得起的手数
            while shares > 0 and total > rnd["cash"] + 1e-6:
                hands -= 1
                shares = hands * self.lot
                gross = price * shares
                fee = self._buy_fee(gross, fee_on)
                total = gross + fee
            if shares <= 0:
                return "次日开盘价超出可用资金，买入未成交"
            new_shares = rnd["pos_shares"] + shares
            new_cost = rnd["pos_cost"] + total
            self.pg.execute(
                "UPDATE training_round SET cash=%s, pos_shares=%s, pos_cost=%s, pos_avg_price=%s "
                "WHERE session_id=%s AND seq=%s AND tenant_id=%s AND owner_user_id=%s",
                [rnd["cash"] - total, new_shares, new_cost, new_cost / new_shares, sid, cur, *self._op])
            self._insert_trade(sid, cur, "buy", rnd["cursor_date"], fill_date, rnd["cursor_idx"] + 1,
                               price, hands, shares, gross, fee, None, None, reason, False)
            return None
        else:
            shares = min(hands * self.lot, rnd["pos_shares"])
            if shares <= 0:
                return "无持仓可卖"
            if raw_pre and not can_sell_at_open(raw_open, raw_pre, pct):
                return "次日开盘跌停，卖出未成交"
            price = disp_open * (1 - self._slip(fee_on))
            gross = price * shares
            fee = self._sell_fee(gross, fee_on)
            proceeds = gross - fee
            cost_portion = rnd["pos_cost"] * (shares / rnd["pos_shares"])
            pnl = proceeds - cost_portion
            ret = pnl / cost_portion if cost_portion else 0.0
            rem_shares = rnd["pos_shares"] - shares
            rem_cost = rnd["pos_cost"] - cost_portion
            self.pg.execute(
                "UPDATE training_round SET cash=%s, pos_shares=%s, pos_cost=%s, pos_avg_price=%s, "
                "realized_pnl=%s WHERE session_id=%s AND seq=%s AND tenant_id=%s AND owner_user_id=%s",
                [rnd["cash"] + proceeds, rem_shares, rem_cost,
                 (rem_cost / rem_shares) if rem_shares else 0.0,
                 rnd["realized_pnl"] + pnl, sid, cur, *self._op])
            self._insert_trade(sid, cur, "sell", rnd["cursor_date"], fill_date, rnd["cursor_idx"] + 1,
                               price, shares // self.lot, shares, gross, fee, pnl, ret, reason, False)
            return None

    def _insert_trade(self, sid, cur, side, decide_date, fill_date, rel_day, price, hands,
                      shares, amount, fee, pnl, ret, reason, auto_close):
        seq = self.pg.query_df(
            "SELECT COALESCE(max(seq), -1) + 1 AS n FROM training_trade "
            "WHERE session_id=%s AND round_seq=%s AND tenant_id=%s AND owner_user_id=%s",
            [sid, cur, *self._op]).iloc[0]["n"]
        self.pg.execute(
            "INSERT INTO training_trade (session_id,tenant_id,owner_user_id,round_seq,seq,side,"
            "decide_date,fill_date,rel_day,price,hands,shares,amount,fee,pnl,return_pct,reason,auto_close) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [sid, self.tenant_id, self.owner_user_id, cur, int(seq), side, decide_date, fill_date,
             int(rel_day), float(price), int(hands),
             int(shares), float(amount), float(fee), pnl, ret, reason, auto_close])

    # ════════════════════════════════════════════════════════════
    # 回合结算 / 整局结算
    # ════════════════════════════════════════════════════════════
    def settle_round(self, sid: str) -> dict:
        s = self._session_row(sid)
        if not s or s["status"] != "running":
            raise ValueError("训练不在进行中")
        cur = int(s["cur_round"])
        rnd = self._norm_round(self._round_rows(sid)[cur])
        if rnd["status"] != "running":
            raise ValueError("回合已结算")
        fee_on = bool(s["fee_enabled"])
        init_cap = float(s["initial_capital"])
        # 末日强制清算（按 cursor 日，即末日收盘价）
        end_bar = self._raw_bar(rnd["code"], rnd["cursor_date"])
        end_close = self._disp_price(end_bar["close"], end_bar["f"], rnd["base_factor"]) if end_bar else rnd["pos_avg_price"]
        cash, realized = rnd["cash"], rnd["realized_pnl"]
        if rnd["pos_shares"] > 0:
            shares = rnd["pos_shares"]
            price = end_close * (1 - self._slip(fee_on))
            gross = price * shares
            fee = self._sell_fee(gross, fee_on)
            proceeds = gross - fee
            pnl = proceeds - rnd["pos_cost"]
            ret = pnl / rnd["pos_cost"] if rnd["pos_cost"] else 0.0
            cash += proceeds
            realized += pnl
            self._insert_trade(sid, cur, "sell", rnd["cursor_date"], rnd["cursor_date"],
                               rnd["cursor_idx"], price, shares // self.lot, shares, gross, fee,
                               pnl, ret, "到期清算", True)
        final_equity = cash
        round_return = final_equity / init_cap - 1 if init_cap else 0.0
        bench = self._benchmark_return(rnd)
        self.pg.execute(
            "UPDATE training_round SET status='done', cash=%s, pos_shares=0, pos_cost=0, "
            "pos_avg_price=0, realized_pnl=%s, round_return=%s, benchmark_return=%s, final_equity=%s "
            "WHERE session_id=%s AND seq=%s AND tenant_id=%s AND owner_user_id=%s",
            [cash, realized, round_return, bench, final_equity, sid, cur, *self._op])
        # 推进或整局结算
        if cur + 1 < int(s["n_rounds"]):
            self.pg.execute("UPDATE training_session SET cur_round=%s WHERE id=%s "
                            "AND tenant_id=%s AND owner_user_id=%s", [cur + 1, sid, *self._op])
            self.pg.execute(
                "UPDATE training_round SET status='running' WHERE session_id=%s AND seq=%s "
                "AND tenant_id=%s AND owner_user_id=%s", [sid, cur + 1, *self._op])
            return self.get_view(sid)
        self._settle_session(sid)
        return self.get_detail(sid)

    def _benchmark_return(self, rnd: dict) -> float:
        """满仓持有基准：首日开盘买入 → 末日收盘卖出（比值与复权基准无关）。"""
        sb = self._raw_bar(rnd["code"], rnd["start_date"])
        eb = self._raw_bar(rnd["code"], rnd["end_date"])
        if not sb or not eb or not sb["open"]:
            return 0.0
        # 用后复权口径（raw×factor）保证跨除权一致
        start_hfq = self._disp_price(sb["open"], sb["f"], 1.0)
        end_hfq = self._disp_price(eb["close"], eb["f"], 1.0)
        return end_hfq / start_hfq - 1 if start_hfq else 0.0

    def _round_equity_curve(self, sid: str, rnd: dict, init_cap: float) -> list[float]:
        """回放回合资金曲线（每个交易日收盘市值），用于回撤与展示。"""
        trades = self._round_trades(sid, int(rnd["seq"]))
        df = self.c.query_df(
            "SELECT trade_date, close, COALESCE(adj_factor_clean, adj_factor) AS f "
            "FROM daily_bar WHERE code=? AND trade_date BETWEEN ? AND ? ORDER BY trade_date",
            [rnd["code"], rnd["start_date"], rnd["cursor_date"]])
        scale = price_scale(df, "qfq", base_factor=float(rnd["base_factor"]), factor_column="f")
        fills: dict[date, list[dict]] = {}
        for t in trades:
            fills.setdefault(_to_date(t["fill_date"]), []).append(t)
        cash, shares = init_cap, 0
        curve = []
        for i, r in df.iterrows():
            d = _to_date(r["trade_date"])
            for t in fills.get(d, []):
                if t["side"] == "buy":
                    cash -= (float(t["amount"]) + float(t["fee"]))
                    shares += int(t["shares"])
                else:
                    cash += (float(t["amount"]) - float(t["fee"]))
                    shares -= int(t["shares"])
            close = float(r["close"]) * float(scale.loc[i])
            curve.append(round(cash + shares * close, 2))
        return curve

    @staticmethod
    def _max_drawdown(curve: list[float]) -> float:
        peak, mdd = -1e18, 0.0
        for v in curve:
            peak = max(peak, v)
            if peak > 0:
                mdd = min(mdd, v / peak - 1)
        return mdd

    def _settle_session(self, sid: str) -> None:
        s = self._session_row(sid)
        init_cap = float(s["initial_capital"])
        rounds = [self._norm_round(r) for r in self._round_rows(sid)]
        rets = [r["round_return"] for r in rounds if r["round_return"] is not None]
        benches = [r["benchmark_return"] for r in rounds if r["benchmark_return"] is not None]
        total_return = sum(rets) / len(rets) if rets else 0.0
        bench_avg = sum(benches) / len(benches) if benches else 0.0
        # 胜率/笔数（按卖出笔）
        sells = self.pg.query_df(
            "SELECT pnl FROM training_trade WHERE session_id=%s AND side='sell' "
            "AND tenant_id=%s AND owner_user_id=%s", [sid, *self._op])
        n_sells = len(sells)
        wins = int((sells["pnl"] > 0).sum()) if n_sells else 0
        win_rate = wins / n_sells if n_sells else 0.0
        n_trades = self.pg.query_df(
            "SELECT count(*) AS n FROM training_trade WHERE session_id=%s "
            "AND tenant_id=%s AND owner_user_id=%s", [sid, *self._op]).iloc[0]["n"]
        worst_dd = 0.0
        for r in rounds:
            worst_dd = min(worst_dd, self._max_drawdown(self._round_equity_curve(sid, r, init_cap)))
        # 综合评分：超额40% + 绝对25% + 回撤20% + 胜率15%
        def clamp01(x):
            return max(0.0, min(1.0, x))
        excess_s = clamp01((total_return - bench_avg + 0.10) / 0.20) * 100
        abs_s = clamp01((total_return + 0.20) / 0.40) * 100
        dd_s = clamp01((worst_dd + 0.25) / 0.25) * 100
        win_s = win_rate * 100
        score = round(0.40 * excess_s + 0.25 * abs_s + 0.20 * dd_s + 0.15 * win_s, 1)
        grade = _grade_of(score)
        self.pg.execute(
            "UPDATE training_session SET status='completed', cur_round=%s, total_return=%s, score=%s, "
            "grade=%s, win_rate=%s, max_drawdown=%s, n_trades=%s, completed_at=%s "
            "WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
            [int(s["n_rounds"]) - 1, total_return, score, grade, win_rate, worst_dd,
             int(n_trades), _now(), sid, *self._op])
        log.info("盘感训练结算 %s score=%.1f grade=%s ret=%.4f", sid, score, grade, total_return)

    # ════════════════════════════════════════════════════════════
    # 复盘 / 详情 / 历史 / 成长
    # ════════════════════════════════════════════════════════════
    def update_review(self, sid: str, note: str) -> None:
        if not self._session_row(sid):
            raise ValueError("训练不存在")
        self.pg.execute(
            "UPDATE training_session SET review_note=%s WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
            [note or "", sid, *self._op])

    def get_detail(self, sid: str) -> dict:
        """完整详情（completed 揭晓真实身份；running 复用脱敏视图的字段）。"""
        s = self._session_row(sid)
        if not s:
            raise ValueError("训练不存在")
        completed = s["status"] == "completed"
        init_cap = float(s["initial_capital"])
        rounds_out = []
        for r in self._round_rows(sid):
            rnd = self._norm_round(r)
            name = self._stock_name(rnd["code"]) if completed else None
            upto = rnd["end_date"] if completed else rnd["cursor_date"]
            bars, date_map = self._bars_for_view(rnd, upto, reveal_dates=completed)
            trades = self._round_trades(sid, int(rnd["seq"]))
            markers = [{"date": date_map.get(int(t["rel_day"]), f"D{int(t['rel_day']):+d}"),
                        "rel_day": int(t["rel_day"]), "kind": t["side"],
                        "label": ("买" if t["side"] == "buy" else "卖")} for t in trades]
            curve = self._round_equity_curve(sid, rnd, init_cap)
            rounds_out.append({
                "seq": rnd["seq"], "status": rnd["status"],
                "code": rnd["code"] if completed else None,
                "name": name,
                "board": self._stock_board(rnd["code"]) if completed else None,
                "start_date": rnd["start_date"].isoformat() if completed and rnd["start_date"] else None,
                "end_date": rnd["end_date"].isoformat() if completed and rnd["end_date"] else None,
                "window_days": rnd["window_days"], "cursor_idx": rnd["cursor_idx"],
                "round_return": rnd["round_return"], "benchmark_return": rnd["benchmark_return"],
                "final_equity": rnd["final_equity"],
                "max_drawdown": round(self._max_drawdown(curve), 4) if curve else 0.0,
                "bars": bars, "markers": markers,
                "trades": self._mask_trades(trades) if not completed else self._full_trades(trades),
                "equity_curve": curve,
            })
        return {
            "id": sid, "status": s["status"], "mode": s["mode"],
            "n_rounds": int(s["n_rounds"]), "window_days": int(s["window_days"]),
            "initial_capital": init_cap, "fee_enabled": bool(s["fee_enabled"]),
            "total_return": None if pd.isna(s["total_return"]) else float(s["total_return"]),
            "score": None if pd.isna(s["score"]) else float(s["score"]),
            "grade": None if not s["grade"] or (isinstance(s["grade"], float) and pd.isna(s["grade"])) else s["grade"],
            "win_rate": None if pd.isna(s["win_rate"]) else float(s["win_rate"]),
            "max_drawdown": None if pd.isna(s["max_drawdown"]) else float(s["max_drawdown"]),
            "n_trades": None if pd.isna(s["n_trades"]) else int(s["n_trades"]),
            "review_note": s["review_note"] if s["review_note"] and not (isinstance(s["review_note"], float) and pd.isna(s["review_note"])) else "",
            "created_at": str(s["created_at"]),
            "completed_at": None if pd.isna(s["completed_at"]) else str(s["completed_at"]),
            "lot_size": self.lot,
            "rounds": rounds_out,
        }

    def _full_trades(self, trades: list[dict]) -> list[dict]:
        out = self._mask_trades(trades)
        for o, t in zip(out, trades):
            o["decide_date"] = _to_date(t["decide_date"]).isoformat() if t.get("decide_date") is not None else None
            o["fill_date"] = _to_date(t["fill_date"]).isoformat() if t.get("fill_date") is not None else None
        return out

    def _stock_name(self, code: str) -> str:
        df = self.c.query_df("SELECT name FROM stock_basic WHERE code = ?", [code])
        return "" if df.empty else str(df.iloc[0]["name"])

    def _stock_board(self, code: str) -> str | None:
        """所属板块（主板/创业板/科创板），与训练选股过滤 sb.board 同口径。"""
        df = self.c.query_df("SELECT board FROM stock_basic WHERE code = ?", [code])
        if df.empty or pd.isna(df.iloc[0]["board"]):
            return None
        return str(df.iloc[0]["board"])

    def list_sessions(self, page: int = 1, size: int = 20, status: str | None = None,
                      sort_by: str = "created_at", sort_order: str = "desc") -> dict:
        where = ["tenant_id=%s", "owner_user_id=%s"]
        params: list = [*self._op]
        if status:
            where.append("status = %s")
            params.append(status)
        wsql = "WHERE " + " AND ".join(where)
        total = self.pg.query_df(
            f"SELECT count(*) AS n FROM training_session {wsql}", params).iloc[0]["n"]
        allow = {"created_at", "completed_at", "total_return", "score", "win_rate"}
        sb = sort_by if sort_by in allow else "created_at"
        so = "ASC" if sort_order.lower() == "asc" else "DESC"
        df = self.pg.query_df(
            f"SELECT id,mode,n_rounds,window_days,status,total_return,score,grade,win_rate,"
            f"max_drawdown,n_trades,created_at,completed_at FROM training_session {wsql} "
            f"ORDER BY {sb} {so} NULLS LAST LIMIT %s OFFSET %s",
            params + [size, (page - 1) * size])
        rows = []
        for _, r in df.iterrows():
            rows.append({
                "id": r["id"], "mode": r["mode"], "n_rounds": int(r["n_rounds"]),
                "window_days": int(r["window_days"]), "status": r["status"],
                "total_return": None if pd.isna(r["total_return"]) else float(r["total_return"]),
                "score": None if pd.isna(r["score"]) else float(r["score"]),
                "grade": None if not r["grade"] or (isinstance(r["grade"], float) and pd.isna(r["grade"])) else r["grade"],
                "win_rate": None if pd.isna(r["win_rate"]) else float(r["win_rate"]),
                "max_drawdown": None if pd.isna(r["max_drawdown"]) else float(r["max_drawdown"]),
                "n_trades": None if pd.isna(r["n_trades"]) else int(r["n_trades"]),
                "created_at": str(r["created_at"]),
                "completed_at": None if pd.isna(r["completed_at"]) else str(r["completed_at"]),
            })
        return {"total": int(total), "page": page, "size": size, "list": rows}

    def growth(self) -> list[dict]:
        df = self.pg.query_df(
            "SELECT id,score,total_return,win_rate,grade,completed_at FROM training_session "
            "WHERE status='completed' AND tenant_id=%s AND owner_user_id=%s ORDER BY completed_at ASC",
            self._op)
        out = []
        for _, r in df.iterrows():
            out.append({
                "id": r["id"], "score": None if pd.isna(r["score"]) else float(r["score"]),
                "total_return": None if pd.isna(r["total_return"]) else float(r["total_return"]),
                "win_rate": None if pd.isna(r["win_rate"]) else float(r["win_rate"]),
                "grade": r["grade"] if r["grade"] and not (isinstance(r["grade"], float) and pd.isna(r["grade"])) else None,
                "completed_at": None if pd.isna(r["completed_at"]) else str(r["completed_at"]),
            })
        return out

    def delete(self, sid: str) -> None:
        if not self._session_row(sid):   # 归属闸门：非本人 session 不删
            return
        self.pg.execute("DELETE FROM training_trade WHERE session_id=%s "
                        "AND tenant_id=%s AND owner_user_id=%s", [sid, *self._op])
        self.pg.execute("DELETE FROM training_round WHERE session_id=%s "
                        "AND tenant_id=%s AND owner_user_id=%s", [sid, *self._op])
        self.pg.execute(
            "DELETE FROM training_session WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
            [sid, *self._op])

    def abort(self, sid: str) -> None:
        self.pg.execute(
            "UPDATE training_session SET status='aborted' "
            "WHERE id=%s AND status='running' AND tenant_id=%s AND owner_user_id=%s", [sid, *self._op])
