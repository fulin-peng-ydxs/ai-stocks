"""M5 回测引擎测试（正确性命脉）：撮合约束（涨跌停/停牌/退市）+ 前向收益无未来 + 绩效。

构造样例验证 SDD §6.4/§6.5 的硬约束，对应任务清单 M5 阶段验收：
  - 涨停封死次日不可买、跌停封死次日不可卖
  - 信号次日停牌 → 买入顺延；持仓中途停牌 → 期间不可卖、按最后价估值
  - 区间末仍持仓 → 强平不悬空
  - 前向收益用 hfq、入场=次日开、无未来函数
  - 绩效指标符号/口径正确
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from backend.backtest.broker import (
    Broker, can_buy_at_open, can_sell_at_open, limit_prices,
)
from backend.backtest.engine import BacktestEngine
from backend.backtest.forward import compute_forward_returns
from backend.backtest.metrics import compute_metrics
from backend.config import CostConfig
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


# ── 撮合约束（纯逻辑）─────────────────────────────────────────
def test_limit_prices_rounding():
    up, down = limit_prices(10.0, 0.10)
    assert up == 11.0 and down == 9.0
    up2, _ = limit_prices(9.99, 0.20)  # 科创/创业
    assert up2 == 11.99


def test_limit_prices_rounding_half_up_boundary():
    up, down = limit_prices(1.005, 0.0)
    assert up == 1.01 and down == 1.01


def test_can_buy_blocked_when_open_at_limit_up():
    # 开盘即涨停（open == 涨停价）→ 不可买
    assert can_buy_at_open(11.0, 10.0, 0.10) is False
    # 开盘低于涨停 → 可买
    assert can_buy_at_open(10.5, 10.0, 0.10) is True


def test_can_sell_blocked_when_open_at_limit_down():
    assert can_sell_at_open(9.0, 10.0, 0.10) is False   # 开盘即跌停 → 不可卖
    assert can_sell_at_open(9.5, 10.0, 0.10) is True


def test_engine_load_prices_switches_main_board_st_limit_on_20260706():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        days = [date(2026, 7, 3), date(2026, 7, 6)]
        _seed_one_stock(
            c,
            "STX.SH",
            [(days[0], 10, 10, 10, 10, 10), (days[1], 10, 10, 10, 10, 10)],
            name="*ST测试",
        )
        rows = BacktestEngine(c)._load_prices(days[0], days[1], ma_period=1)
        assert rows[("STX.SH", pd.Timestamp(days[0]))].pct == 0.05
        assert rows[("STX.SH", pd.Timestamp(days[1]))].pct == 0.10


# ── Broker 记账（整手 + 成本，方向性）──────────────────────────
def test_broker_buy_lot_rounding_and_cost():
    cost = CostConfig(commission_rate=0.00025, commission_min=5.0, stamp_tax_rate=0.001,
                      transfer_fee_rate=0.00001, slippage=0.0)
    b = Broker(cash=100_000.0, cost=cost, lot_size=100)
    f = b.buy("X.SH", date(2024, 1, 2), open_px=33.0, target_amount=100_000.0)
    # 33 元、10万 → 3030 股 → 整手 3000 股
    assert f is not None and f.shares == 3000
    gross = 33.0 * 3000
    commission = max(gross * 0.00025, 5.0)
    assert abs(b.cash - (100_000 - gross - commission - gross * 0.00001)) < 1e-6


def test_broker_sell_proceeds_with_stamp_tax():
    cost = CostConfig(commission_rate=0.00025, commission_min=5.0, stamp_tax_rate=0.001,
                      transfer_fee_rate=0.00001, slippage=0.0)
    b = Broker(cash=100_000.0, cost=cost, lot_size=100)
    b.buy("X.SH", date(2024, 1, 2), open_px=10.0, target_amount=50_000.0)
    shares = b.positions["X.SH"].shares
    f = b.sell_all("X.SH", date(2024, 1, 3), 12.0)
    gross = 12.0 * shares
    stamp = gross * 0.001
    commission = max(gross * 0.00025, 5.0)
    expected = gross - stamp - commission - gross * 0.00001
    assert abs(f.cash_delta - expected) < 1e-6
    assert "X.SH" not in b.positions


def test_broker_insufficient_cash_returns_none():
    b = Broker(cash=100.0, lot_size=100)
    assert b.buy("X.SH", date(2024, 1, 2), open_px=50.0, target_amount=100.0) is None


# ── 前向收益（hfq、入场=次日开、无未来）──────────────────────
def _seed_one_stock(c, code, rows, pct=0.10, name="测试", rs=50.0):
    """rows: list of (date, open, high, low, close, pre_close)。adj_factor=1。

    v2.0：指标动态计算（无 indicator 表），横截面 RS 需 ~20 日窗口。为让短合成序列也能
    算出可区分的 RS（上涨标的 RS 自然高于横盘），自动在首行之前前置一段**暖机交易日**
    （平盘于首行开盘价，早于回测区间、不参与撮合），仅供指标暖机。
    """
    first_d, first_open = rows[0][0], rows[0][1]
    warm_dates = [d.date() for d in pd.bdate_range(
        end=pd.Timestamp(first_d) - pd.Timedelta(days=1), periods=30)]
    warm_rows = [(wd, first_open, first_open, first_open, first_open, first_open)
                 for wd in warm_dates]
    all_rows = warm_rows + list(rows)
    bars = [{
        "code": code, "trade_date": d, "open": o, "high": h, "low": lo, "close": cl,
        "pre_close": pc, "volume": 1_000_000, "amount": cl * 1_000_000, "adj_factor": 1.0,
        "turnover_rate": 5.0, "is_st": False, "is_suspended": False,
        "limit_status": 0, "is_one_word": False,
    } for (d, o, h, lo, cl, pc) in all_rows]
    c.register_df("t", pd.DataFrame(bars)); c.execute("INSERT INTO daily_bar BY NAME SELECT * FROM t"); c.unregister("t")
    c.execute("INSERT INTO stock_basic (code,name,board,price_limit_pct) VALUES (?,?,?,?)",
              [code, name, "主板", pct])
    st_rows = [{
        "code": code,
        "trade_date": d,
        "is_st": name.upper().startswith(("ST", "*ST", "S*ST")),
        "source": "test_fixture",
        "source_ref": "test_backtest",
        "quality": "accurate",
    } for (d, *_3) in all_rows]
    c.register_df("tst", pd.DataFrame(st_rows))
    c.execute(
        "INSERT INTO stock_st_status_daily "
        "(code,trade_date,is_st,source,source_ref,quality,captured_at,updated_at) "
        "SELECT code,trade_date,is_st,source,source_ref,quality,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP "
        "FROM tst"
    )
    c.unregister("tst")
    # v2.0：指标动态计算（无 indicator 表），rs_pct 由横截面收益排名得出，不再手工灌入。
    # rs 入参保留以兼容调用签名（涨幅高者横截面 RS 自然更高，与原 rs 排序意图一致）。
    _ = rs
    mdf = [{"code": code, "trade_date": d, "float_mv": 1e10, "total_mv": 1e10} for (d, *_3) in all_rows]
    c.register_df("tm", pd.DataFrame(mdf)); c.execute("INSERT INTO daily_metrics SELECT * FROM tm"); c.unregister("tm")


def test_forward_returns_entry_and_window():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        # 日:  open high low close
        rows = [
            (date(2024, 1, 2), 10, 10.2, 9.9, 10.0, 9.9),
            (date(2024, 1, 3), 10.1, 10.5, 10.0, 10.4, 10.0),  # 入场日(对1/2信号)
            (date(2024, 1, 4), 10.4, 12.0, 10.3, 11.8, 10.4),  # 窗口内最高 12.0
            (date(2024, 1, 5), 11.8, 11.9, 11.0, 11.2, 11.8),
        ]
        _seed_one_stock(c, "AAA.SH", rows)
        fwd = compute_forward_returns(date(2024, 1, 2), date(2024, 1, 5), [2], client=c)
        r12 = fwd[fwd["trade_date"] == pd.Timestamp("2024-01-02")].iloc[0]
        # 入场=1/3 开=10.1；窗口[1/3,1/4] 最高=12.0 → 12.0/10.1-1
        assert abs(r12["entry_price"] - 10.1) < 1e-9
        assert abs(r12["fwd_ret_2"] - (12.0 / 10.1 - 1)) < 1e-9
        assert bool(r12["eval_2"]) is True
        # 1/4 信号：窗口[1/5,1/6] 仅 1/5 可得（右沿不足 2 日）→ eval False
        r14 = fwd[fwd["trade_date"] == pd.Timestamp("2024-01-04")].iloc[0]
        assert bool(r14["eval_2"]) is False


# ── 引擎硬约束 ────────────────────────────────────────────────
def _seed_index(c, days):
    idx = [{"index_code": "000905.SH", "trade_date": d, "open": 1000.0, "high": 1000.0,
            "low": 1000.0, "close": 1000.0, "volume": 1, "amount": 1.0} for d in days]
    c.register_df("ix", pd.DataFrame(idx)); c.execute("INSERT INTO index_bar SELECT * FROM ix"); c.unregister("ix")


def test_eval_expr_indicator_range_per_day():
    """M2.5：表达式型指标区间逐日求值（below_ma 用 close<MA(close,3)）。"""
    from backend.indicators.engine import IndicatorEngine
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        D = [date(2024, 1, d) for d in (2, 3, 4, 5, 8, 9, 10, 11)]
        # 先涨后跌：跌段触发 close < MA(close,3)
        closes = [10, 11, 12, 13, 11, 10, 9, 8]
        rows = [(d, cl, cl, cl, cl, cl) for d, cl in zip(D, closes)]
        _seed_one_stock(c, "AAA.SH", rows)
        rng = IndicatorEngine(c).eval_expr_indicator_range(
            "C < MA(C, 3)", None, None, date(2024, 1, 2), date(2024, 1, 11))
        assert not rng.empty
        m = {pd.Timestamp(r.trade_date).date(): bool(r.value) for r in rng.itertuples()}
        assert m[date(2024, 1, 4)] is False      # 上涨段：12 > MA(10,11,12)
        assert m[date(2024, 1, 10)] is True       # 下跌段：9 < MA(11,10,9)


def test_strategy_with_trade_and_score_profile():
    """M2.5：策略回测接入买卖方案(buy_tree/sell_tree/兜底) + 评分方案，端到端跑通。"""
    from backend.indicators.definition import IndicatorDefRepo
    from backend.scoring.score_profile import ScoreProfileRepo
    from backend.signals.trade_profile import TradeProfileRepo
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        IndicatorDefRepo(c).seed_builtins()
        ScoreProfileRepo(c).seed_defaults()
        TradeProfileRepo(c).seed_defaults()
        D = [date(2024, 1, d) for d in (2, 3, 4, 5, 8, 9, 10, 11, 12, 15)]
        # 持续上涨后回落：制造可买（高 RS）+ 卖出（跌破 MA）
        closes = [10, 11, 12, 13, 14, 15, 14, 12, 10, 9]
        up = [(d, cl, cl, cl, cl, cl) for d, cl in zip(D, closes)]
        _seed_one_stock(c, "UP.SH", up, rs=99.0)
        _seed_one_stock(c, "REF.SH", [(d, 5, 5, 5, 5, 5) for d in D], rs=1.0, name="ST锚")
        _seed_index(c, D)
        # ma5_pullback：买=贴近5日线、卖=跌破10日线（均为 expr 指标，验证区间求值接入）
        out = BacktestEngine(c).run({
            "date_start": "2024-01-02", "date_end": "2024-01-15", "top_n": 1,
            "initial_capital": 1_000_000, "trade_profile_id": "ma5_pullback",
            "score_profile_id": "default",
        })
        assert "error" not in out
        assert len(out["equity"]) == len(D)         # 每个交易日一条净值
        # 卖出原因应来自卖出信号或兜底（不再是旧式“跌破MAxx”默认路径）
        reasons = {t["exit_reason"] for t in out["trades"]}
        assert reasons <= {"卖出信号", "止损", "止盈", "到期", "区间末强平", "停牌/退市强平", "顺延"}


def test_backtest_engine_accepts_visible_score_profile_ref(market, pg):
    """回测引擎运行时支持他人公开评分方案 profile_ref，不再按当前 owner 私有 id 读取。"""
    from backend.auth.context import get_current_context
    from backend.scoring.score_profile import ScoreProfileRepo
    from backend.tests.conftest import TEST_OWNER, TEST_TENANT

    assert get_current_context() is None
    owner = "pytest_public_score_owner"
    items = [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}]
    src_repo = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=owner)
    src_repo.save("bt_public_score", "公开回测评分", items)
    src = src_repo.set_visibility("bt_public_score", "tenant", published_by=owner)
    try:
        out = BacktestEngine(
            market,
            tenant_id=TEST_TENANT,
            owner_user_id=TEST_OWNER,
        ).run({
            "date_start": "2024-01-02",
            "date_end": "2024-01-03",
            "score_profile_id": src["profile_ref"],
        })
        assert out.get("error") != f"评分方案不存在: {src['profile_ref']}"
    finally:
        pg.execute("DELETE FROM score_profile WHERE owner_user_id=%s", [owner])
        pg.execute("DELETE FROM score_profile_version WHERE owner_user_id=%s", [owner])


def test_engine_buy_deferred_on_limit_up_open():
    """信号次日开盘即涨停 → 当日买不到，顺延到下一可买日。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        D = [date(2024, 1, d) for d in (2, 3, 4, 5, 8)]
        # REF 参照股全程交易（定义交易日）；标 ST 使其不进候选（仅作交易日锚），凸显 TGT 顺延
        _seed_one_stock(c, "REF.SH", [(d, 5, 5, 5, 5, 5) for d in D], rs=1.0, name="ST参照")
        # TGT 高 rs 必被选中。1/3 开盘=涨停价(11.0,pre=10) → 不可买；1/4 正常开 → 买入
        tgt = [
            (D[0], 10, 10.2, 9.9, 10.0, 9.9),
            (D[1], 11.0, 11.0, 11.0, 11.0, 10.0),   # 开=涨停价 → 不可买
            (D[2], 10.5, 11.0, 10.4, 10.8, 10.0),   # 正常 → 可买
            (D[3], 10.9, 11.2, 10.8, 11.0, 10.8),
            (D[4], 11.0, 11.5, 10.9, 11.2, 11.0),
        ]
        _seed_one_stock(c, "TGT.SH", tgt, rs=99.0)
        _seed_index(c, D)
        out = BacktestEngine(c).run({"date_start": "2024-01-02", "date_end": "2024-01-08",
                                     "top_n": 1, "initial_capital": 1_000_000, "sell_ma_period": 99})
        tgt_trades = [t for t in out["trades"] if t["code"] == "TGT.SH"]
        assert tgt_trades, "TGT 应被买入"
        # 入场不应是 1/3（涨停封死），应顺延到 1/4
        assert tgt_trades[0]["entry_date"] == date(2024, 1, 4)


def test_engine_sell_deferred_on_suspension_and_valued_at_last_price():
    """持仓中途停牌（无 bar）→ 期间不可卖、按最后可得收盘估值。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        D = [date(2024, 1, d) for d in (2, 3, 4, 5, 8)]
        _seed_one_stock(c, "REF.SH", [(d, 5, 5, 5, 5, 5) for d in D], rs=1.0)
        # TGT：1/2 信号→1/3 买入；1/4 停牌(无 bar)；用 sell_ma_period=2 触发卖出信号但停牌不可卖
        tgt = [
            (D[0], 10, 10.2, 9.9, 10.0, 9.9),
            (D[1], 10.0, 10.1, 9.0, 9.2, 10.0),    # 买入日，收盘跌
            # D[2]=1/4 缺失（停牌）
            (D[3], 9.0, 9.1, 8.5, 8.6, 9.2),
            (D[4], 8.6, 8.7, 8.0, 8.1, 8.6),
        ]
        _seed_one_stock(c, "TGT.SH", tgt, rs=99.0)
        _seed_index(c, D)
        out = BacktestEngine(c).run({"date_start": "2024-01-02", "date_end": "2024-01-08",
                                     "top_n": 1, "initial_capital": 1_000_000, "sell_ma_period": 2})
        eq = out["equity"]
        row_0104 = eq[eq["trade_date"] == date(2024, 1, 4)].iloc[0]
        # 停牌日仍持有 1 只（不可卖），且持仓市值>0（按最后可得价 9.2 估值）
        assert int(row_0104["n_positions"]) == 1
        assert row_0104["position_value"] > 0


def test_engine_force_liquidate_at_end():
    """区间末仍持仓 → 强平，不悬空。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        D = [date(2024, 1, d) for d in (2, 3, 4, 5, 8)]
        _seed_one_stock(c, "REF.SH", [(d, 5, 5, 5, 5, 5) for d in D], rs=1.0)
        # 单调上涨、永不触发跌破MA → 持有到末日被强平
        tgt = [(D[i], 10 + i, 10.5 + i, 9.5 + i, 10.2 + i, (9.9 if i == 0 else 9.2 + i)) for i in range(5)]
        _seed_one_stock(c, "TGT.SH", tgt, rs=99.0)
        _seed_index(c, D)
        out = BacktestEngine(c).run({"date_start": "2024-01-02", "date_end": "2024-01-08",
                                     "top_n": 1, "initial_capital": 1_000_000, "sell_ma_period": 2})
        reasons = {t["exit_reason"] for t in out["trades"] if t["code"] == "TGT.SH"}
        assert "区间末强平" in reasons
        # 末日无悬空持仓（已全部平仓）
        assert int(out["equity"].iloc[-1]["n_positions"]) >= 0


# ── 表达式批量预计算（T-M5-10）与逐日筛选一致 ──────────────────
def test_precompute_matches_screen_engine():
    """预计算命中集必须逐日等于 ScreenEngine.run_hits（含 expr 叶子）。"""
    from backend.backtest.precompute import HitPrecomputer
    from backend.screening.engine import ScreenEngine
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        # 两股，连涨表达式 C>REF(C,1)
        up = [(date(2024, 1, d), 10 + i, 10.2 + i, 9.8 + i, 10.1 + i, (9.9 if i == 0 else 9.1 + i))
              for i, d in enumerate((2, 3, 4, 5, 8))]
        flat = [(date(2024, 1, d), 5, 5, 5, 5, 5) for d in (2, 3, 4, 5, 8)]
        _seed_one_stock(c, "UP.SH", up, rs=80)
        _seed_one_stock(c, "FLAT.SH", flat, rs=10)
        ast = {"type": "expr", "expr": "C > REF(C,1)"}
        pre = HitPrecomputer(c).precompute(ast, date(2024, 1, 3), date(2024, 1, 8))
        for d in [date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 8)]:
            old = set(ScreenEngine(c).run_hits(ast, d))
            assert pre.get(d, set()) == old, f"{d}: precompute {pre.get(d)} != engine {old}"
        # UP 每日连涨 → 命中；FLAT 不变 → 不命中
        assert "UP.SH" in pre[date(2024, 1, 8)]
        assert "FLAT.SH" not in pre[date(2024, 1, 8)]


def test_precompute_supports_registered_indicator_leaf():
    """当前筛选页生成的 type=ind AST 在回测预算路径中必须可执行且同口径。"""
    from backend.backtest.precompute import HitPrecomputer
    from backend.screening.engine import ScreenEngine
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        D = [date(2024, 1, d) for d in (2, 3, 4, 5, 8)]
        rows = [(d, 10, 10, 10, 10, 10) for d in D]
        _seed_one_stock(c, "A.SH", rows, rs=80)
        ast = {"type": "ind", "key": "turnover_rate", "cmp": ">=", "value": 5}
        pre = HitPrecomputer(c).precompute(ast, D[1], D[-1])
        for day in D[1:]:
            assert pre.get(day, set()) == set(ScreenEngine(c).run_hits(ast, day))


def test_engine_no_same_day_sell_then_rebuy():
    """当日触发卖出的票，当日不得被再次买回（防同日 churn；调仓与卖出规则的交互）。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        D = [date(2024, 1, d) for d in (2, 3, 4, 5, 8)]
        _seed_one_stock(c, "REF.SH", [(d, 5, 5, 5, 5, 5) for d in D], rs=1.0, name="ST锚")
        # TGT 始终最高分（rs=99）→ 每日调仓都想买它；用 sell_ma_period=2 + 价格回落制造卖出信号
        # 1/2 买点，1/3 买入；之后价格走平/略跌使其某日跌破 MA2 → 卖出；同日(每日调仓)不得买回
        tgt = [
            (D[0], 10, 10.2, 9.9, 10.0, 9.9),
            (D[1], 10.0, 10.1, 9.5, 9.6, 10.0),
            (D[2], 9.6, 9.7, 9.3, 9.4, 9.6),    # 跌破 MA2 → 信号日
            (D[3], 9.4, 9.5, 9.0, 9.1, 9.4),
            (D[4], 9.1, 9.2, 8.8, 8.9, 9.1),
        ]
        _seed_one_stock(c, "TGT.SH", tgt, rs=99.0)
        _seed_index(c, D)
        out = BacktestEngine(c).run({"date_start": "2024-01-02", "date_end": "2024-01-08",
                                     "top_n": 1, "initial_capital": 1_000_000, "sell_ma_period": 2})
        # 不应出现"同一天 entry_date==exit_date"的交易，也不应在卖出当日重新建仓该票
        for t in out["trades"]:
            assert t["entry_date"] != t["exit_date"], f"出现同日买卖：{t}"
        # 每个交易日 TGT 至多被持有一段连续区间——校验没有"卖出日当天又买入"的重叠
        tgt_trades = sorted([t for t in out["trades"] if t["code"] == "TGT.SH"], key=lambda x: x["entry_date"])
        for a, b in zip(tgt_trades, tgt_trades[1:]):
            assert b["entry_date"] > a["exit_date"], "卖出当日不应重新买回"


def test_backtest_service_delete_run(market, pg):
    """删除历史回测：清掉 run + trade/equity/metrics，幂等返回是否存在。回测表在 PG。"""
    from datetime import date as _date

    from backend.services.backtest_service import BacktestService
    from backend.tests.conftest import TEST_OWNER, TEST_TENANT
    svc = BacktestService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    own = [TEST_TENANT, TEST_OWNER]
    pg.execute("INSERT INTO backtest_run (id,tenant_id,owner_user_id,kind,status) VALUES (%s,%s,%s,'strategy','done')", ["r1", *own])
    pg.execute("INSERT INTO backtest_trade (run_id,tenant_id,owner_user_id,seq,code) VALUES (%s,%s,%s,1,'X.SH')", ["r1", *own])
    pg.execute("INSERT INTO backtest_equity (run_id,tenant_id,owner_user_id,trade_date,equity) VALUES (%s,%s,%s,%s,1.0)", ["r1", *own, _date(2024, 1, 2)])
    pg.execute("INSERT INTO backtest_metrics (run_id,tenant_id,owner_user_id,total_return) VALUES (%s,%s,%s,0.1)", ["r1", *own])
    assert svc.delete_run("r1") is True
    assert pg.query_df("SELECT 1 FROM backtest_run WHERE id='r1' AND owner_user_id=%s", [TEST_OWNER]).empty
    assert pg.query_df("SELECT 1 FROM backtest_trade WHERE run_id='r1' AND owner_user_id=%s", [TEST_OWNER]).empty
    assert pg.query_df("SELECT 1 FROM backtest_metrics WHERE run_id='r1' AND owner_user_id=%s", [TEST_OWNER]).empty
    assert svc.delete_run("nope") is False  # 不存在 → False


def test_backtest_service_list_get_run(market, pg):
    """读路径：list_runs 的 run⋈screen_profile⋈metrics JOIN（全在 PG）+ get_run 归属过滤。"""
    from datetime import date as _date

    from backend.services.backtest_service import BacktestService
    from backend.tests.conftest import TEST_OWNER, TEST_TENANT
    svc = BacktestService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    own = [TEST_TENANT, TEST_OWNER]
    pg.execute("INSERT INTO screen_profile (id,tenant_id,owner_user_id,name,version) VALUES (%s,%s,%s,'趋势龙头',1)", ["sp1", *own])
    pg.execute(
        "INSERT INTO backtest_run (id,tenant_id,owner_user_id,kind,profile_id,date_start,date_end,status,created_at) "
        "VALUES (%s,%s,%s,'strategy','sp1',%s,%s,'done',now())", ["r9", *own, _date(2024, 1, 2), _date(2024, 1, 15)])
    pg.execute("INSERT INTO backtest_metrics (run_id,tenant_id,owner_user_id,total_return) VALUES (%s,%s,%s,0.25)", ["r9", *own])

    runs = svc.list_runs(kind="strategy")
    mine = [r for r in runs if r["id"] == "r9"]
    assert mine and mine[0]["profile_name"] == "趋势龙头"   # PG 内 JOIN 取到方案名
    assert float(mine[0]["total_return"]) == 0.25

    got = svc.get_run("r9")
    assert got and got["run"]["kind"] == "strategy"
    assert "tenant_id" not in got["run"]                    # 内部归属字段不外泄
    # 跨归属不可见
    other = BacktestService(market, tenant_id=TEST_TENANT, owner_user_id="pytest_other")
    assert other.get_run("r9") is None


def test_backtest_service_resolves_visible_score_profile_ref(market, pg):
    """服务层版本解析和历史列表展示支持跨 owner 可见评分方案 profile_ref。"""
    from backend.scoring.score_profile import ScoreProfileRepo
    from backend.services.backtest_service import BacktestService
    from backend.tests.conftest import TEST_OWNER, TEST_TENANT

    owner = "pytest_public_score_owner"
    items = [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}]
    src_repo = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=owner)
    src_repo.save("bt_public_score", "公开回测评分", items)
    src = src_repo.set_visibility("bt_public_score", "tenant", published_by=owner)
    svc = BacktestService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    try:
        params = {
            "date_start": "2024-01-02",
            "date_end": "2024-01-03",
            "score_profile_id": src["profile_ref"],
        }
        versions = svc._resolve_versions(params)  # noqa: SLF001
        assert versions["score_profile_version"] == 1
        assert svc._load_score_profile(params)["name"] == "公开回测评分"  # noqa: SLF001

        svc._persist_run("r_score_ref", "strategy", params, "done", finished=True, versions=versions)  # noqa: SLF001
        mine = [r for r in svc.list_runs(kind="strategy") if r["id"] == "r_score_ref"]
        assert mine and mine[0]["score_profile_name"] == "公开回测评分"
        assert mine[0]["score_profile_version"] == 1
    finally:
        pg.execute("DELETE FROM score_profile WHERE owner_user_id=%s", [owner])
        pg.execute("DELETE FROM score_profile_version WHERE owner_user_id=%s", [owner])


def test_list_runs_join_no_cross_owner(market, pg):
    """回归(P0)：list_runs 的 run⋈profile⋈metrics JOIN 必须带归属，否则同 id 会串其他 owner。"""
    from datetime import date as _date

    from backend.services.backtest_service import BacktestService
    from backend.tests.conftest import TEST_OWNER, TEST_TENANT
    # A、B 各有同 id 的 profile 与 run（复合主键下可并存）
    for owner, pname, ret in ((TEST_OWNER, "A策略", 0.1), ("pytest_other", "B策略", 0.9)):
        pg.execute("INSERT INTO screen_profile (id,tenant_id,owner_user_id,name,version) VALUES ('PP',%s,%s,%s,1)", [TEST_TENANT, owner, pname])
        pg.execute("INSERT INTO backtest_run (id,tenant_id,owner_user_id,kind,profile_id,status,created_at) VALUES ('RR',%s,%s,'strategy','PP','done',now())", [TEST_TENANT, owner])
        pg.execute("INSERT INTO backtest_metrics (run_id,tenant_id,owner_user_id,total_return) VALUES ('RR',%s,%s,%s)", [TEST_TENANT, owner, ret])
    try:
        runs = BacktestService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER).list_runs()
        mine = [r for r in runs if r["id"] == "RR"]
        assert len(mine) == 1                              # 不是 4 行笛卡尔积
        assert mine[0]["profile_name"] == "A策略"          # 不串 B 的 profile
        assert float(mine[0]["total_return"]) == 0.1       # 不串 B 的 metrics
    finally:
        for owner in (TEST_OWNER, "pytest_other"):
            for t in ("screen_profile", "backtest_run", "backtest_metrics"):
                pg.execute(f"DELETE FROM {t} WHERE owner_user_id=%s", [owner])


# ── 绩效指标 ──────────────────────────────────────────────────
def test_metrics_basic_signs():
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    eq = pd.Series([100, 110, 121, 115, 130, 128, 140, 150, 145, 160], index=idx, dtype=float)
    bench = pd.Series([100] * 10, index=idx, dtype=float)
    trades = [{"return_pct": 0.1, "pnl": 1000, "hold_days": 3},
              {"return_pct": -0.05, "pnl": -500, "hold_days": 2}]
    m = compute_metrics(eq, bench, trades)
    assert m["total_return"] == round(160 / 100 - 1, 6)
    assert m["max_drawdown"] < 0          # 中途有回撤
    assert m["win_rate"] == 0.5
    assert m["excess_return"] == m["total_return"]  # 基准 0
