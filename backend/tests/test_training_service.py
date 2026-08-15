"""盘感训练 PG 持久层测试（混合持久层 stage1·T2）。

聚焦本次迁移改动：训练 session/round/trade 落 PG 的归属闸门、list/growth 归属过滤、
delete/abort、跨归属隔离。完整开局→交易→结算的计算流逻辑未变，由实时冒烟覆盖。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from backend.indicators.compute import compute_macd
from backend.services.training_service import TrainingService
from backend.tests.conftest import TEST_OWNER, TEST_TENANT


def _mk_session(pg, sid, owner=TEST_OWNER, status="completed", score=80.0):
    pg.execute(
        "INSERT INTO training_session (id,tenant_id,owner_user_id,mode,n_rounds,window_days,"
        "initial_capital,status,cur_round,total_return,score,grade,win_rate,created_at,completed_at) "
        "VALUES (%s,%s,%s,'single',1,20,100000,%s,0,0.1,%s,'A',0.6,%s,%s)",
        [sid, TEST_TENANT, owner, status, score, datetime.now(), datetime.now()])


def _mk_round(pg, sid, code, start, end, owner=TEST_OWNER, status="completed"):
    """构造一个 completed 回合（无成交，仅用于 bars/board 视图断言）。"""
    pg.execute(
        "INSERT INTO training_round (session_id,tenant_id,owner_user_id,seq,code,start_date,end_date,"
        "window_days,base_factor,price_limit_pct,cursor_date,cursor_idx,status,cash,pos_shares,"
        "pos_cost,pos_avg_price,pending,realized_pnl,round_return,benchmark_return,final_equity) "
        "VALUES (%s,%s,%s,0,%s,%s,%s,5,1.0,0.10,%s,4,'completed',100000,0,0,0,NULL,0,0.1,0.1,100000)",
        [sid, TEST_TENANT, owner, code, start, end, end])


def _insert_bars(market, code, n=40):
    """插入 n 个交易日的行情（升序，不复权 + 干净因子=1），返回首末日。"""
    start = date(2026, 1, 5)
    for i in range(n):
        d = start + timedelta(days=i)
        close = 10.0 + i * 0.1
        market.execute(
            "INSERT INTO daily_bar (code,trade_date,open,high,low,close,pre_close,volume,amount,"
            "adj_factor,adj_factor_clean,turnover_rate) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [code, d, close - 0.2, close + 0.4, close - 0.5, close, close - 0.1, 100000, 1000000,
             1.0, 1.0, 1.0])
    return start, start + timedelta(days=n - 1)


def test_session_owner_gate(market, pg):
    _mk_session(pg, "ts1")
    svc = TrainingService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    assert svc._session_row("ts1") is not None
    # 他人看不到
    other = TrainingService(market, tenant_id=TEST_TENANT, owner_user_id="pytest_other")
    assert other._session_row("ts1") is None


def test_training_effective_price_limit_switches_main_board_st(market, pg):
    market.execute(
        "INSERT INTO stock_basic (code, name, price_limit_pct) VALUES "
        "('STX.SH','*ST测试',0.10)"
    )
    svc = TrainingService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    assert svc._effective_price_limit_pct("STX.SH", date(2026, 7, 3), 0.10) == 0.05
    assert svc._effective_price_limit_pct("STX.SH", date(2026, 7, 6), 0.10) == 0.10


def test_list_and_growth_owner_filter(market, pg):
    _mk_session(pg, "ts_done", status="completed")
    _mk_session(pg, "ts_run", status="running")
    svc = TrainingService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    ids = {r["id"] for r in svc.list_sessions()["list"]}
    assert {"ts_done", "ts_run"} <= ids
    assert svc.list_sessions(status="completed")["total"] >= 1
    assert any(g["id"] == "ts_done" for g in svc.growth())   # growth 仅 completed
    # 他人列表为空
    other = TrainingService(market, tenant_id=TEST_TENANT, owner_user_id="pytest_other")
    assert all(r["id"] not in {"ts_done", "ts_run"} for r in other.list_sessions()["list"])


def test_delete_and_abort_owner_scoped(market, pg):
    _mk_session(pg, "ts_del", status="running")
    pg.execute(
        "INSERT INTO training_round (session_id,tenant_id,owner_user_id,seq,code,window_days,"
        "cursor_idx,status,cash,pos_shares,pos_cost,pos_avg_price,realized_pnl) "
        "VALUES ('ts_del',%s,%s,0,'X.SH',20,0,'running',100000,0,0,0,0)", [TEST_TENANT, TEST_OWNER])
    svc = TrainingService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    svc.abort("ts_del")
    assert svc._session_row("ts_del")["status"] == "aborted"
    svc.delete("ts_del")
    assert svc._session_row("ts_del") is None
    assert pg.query_df("SELECT 1 FROM training_round WHERE session_id='ts_del'").empty

    # 他人不能删本人 session
    _mk_session(pg, "ts_keep", status="running")
    other = TrainingService(market, tenant_id=TEST_TENANT, owner_user_id="pytest_other")
    other.delete("ts_keep")
    assert svc._session_row("ts_keep") is not None
    pg.execute("DELETE FROM training_session WHERE owner_user_id=%s", ["pytest_other"])


def test_same_session_id_different_owner_no_crossread(market, pg):
    """回归(P0)：同 session_id 不同 owner，round/trade 读写互不串（归属过滤，非靠 session 唯一）。"""
    own = "pytest_other"

    def _clean_ss():   # training_session 按 id，round/trade 按 session_id
        for o in (TEST_OWNER, own):
            pg.execute("DELETE FROM training_round WHERE session_id='SS' AND owner_user_id=%s", [o])
            pg.execute("DELETE FROM training_trade WHERE session_id='SS' AND owner_user_id=%s", [o])
            pg.execute("DELETE FROM training_session WHERE id='SS' AND owner_user_id=%s", [o])

    _clean_ss()   # 前置清理，避免上次失败残留导致主键冲突
    for o in (TEST_OWNER, own):
        _mk_session(pg, "SS", owner=o, status="running")
        pg.execute(
            "INSERT INTO training_round (session_id,tenant_id,owner_user_id,seq,code,window_days,"
            "cursor_idx,status,cash,pos_shares,pos_cost,pos_avg_price,realized_pnl,pending) "
            "VALUES ('SS',%s,%s,0,'X',5,0,'running',100000,0,0,0,0,NULL)", [TEST_TENANT, o])
    A = TrainingService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    try:
        assert len(A._round_rows("SS")) == 1          # 只读到自己的回合，不是 2
        # A 改自己的 pending，不应影响他人
        A.pg.execute("UPDATE training_round SET pending='MINE' WHERE session_id='SS' AND seq=0 "
                     "AND tenant_id=%s AND owner_user_id=%s", [TEST_TENANT, TEST_OWNER])
        other_pending = pg.query_df(
            "SELECT pending FROM training_round WHERE session_id='SS' AND owner_user_id=%s", [own]
        ).iloc[0]["pending"]
        assert other_pending is None                  # 他人的 pending 未被串改
    finally:
        _clean_ss()


def test_bars_attach_macd_from_desensitized_close(market, pg):
    """训练/回看 bars 附带 MACD：由脱敏前复权 close 计算，与 compute_macd 一致，暖机不足为 null。"""
    code = "600000.SH"
    n = 60
    start, end = _insert_bars(market, code, n=n)
    market.execute(
        "INSERT INTO stock_basic (code, name, board) VALUES (?,?,?)", [code, "测试股", "主板"])
    _mk_session(pg, "ts_macd", status="completed")
    _mk_round(pg, "ts_macd", code, start, end)
    svc = TrainingService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)

    detail = svc.get_detail("ts_macd")
    bars = detail["rounds"][0]["bars"]
    assert len(bars) == n
    closes = pd.Series([b["close"] for b in bars])
    expected = compute_macd(closes)
    for bar, row in zip(bars, expected.to_dict("records")):
        for key in ("macd_diff", "macd_dea", "macd_hist"):
            value = row[key]
            assert bar[key] == (None if value is None or pd.isna(value) else round(float(value), 3))
        for key in ("macd_golden_cross", "macd_dead_cross"):
            value = row[key]
            assert bar[key] == (None if value is None or pd.isna(value) else bool(value))
    # 暖机期（DEA 需 diff 有效后 9 根，即 EMA26 起 +9）前为 null，其后为数值
    assert bars[0]["macd_hist"] is None
    assert bars[25]["macd_hist"] is None
    assert bars[33]["macd_hist"] is not None
    # 盲测视图（reveal_dates=False）同样附带 MACD，date 为相对日
    running = TrainingService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    running.pg.execute(
        "UPDATE training_session SET status='running', cur_round=0 WHERE id='ts_macd'")
    running.pg.execute(
        "UPDATE training_round SET status='running', cursor_date=%s, cursor_idx=3 "
        "WHERE session_id='ts_macd'", [start + timedelta(days=3)])
    run_view = running.get_view("ts_macd")
    run_bars = run_view["round"]["bars"]
    assert run_bars[0]["date"].startswith("D")
    assert all("macd_hist" in b for b in run_bars)
    assert all("macd_golden_cross" in b and "macd_dead_cross" in b for b in run_bars)


def test_detail_round_carries_board(market, pg):
    """结算详情每回合附 board（主板/创业板/科创板，与选股过滤同口径）；无 board 时 None。"""
    code = "300001.SZ"
    _insert_bars(market, code, n=40)
    market.execute(
        "INSERT INTO stock_basic (code, name, board) VALUES (?,?,?)", [code, "创业股", "创业板"])
    _mk_session(pg, "ts_board", status="completed")
    _mk_round(pg, "ts_board", code, date(2026, 1, 5), date(2026, 1, 30))
    svc = TrainingService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)

    detail = svc.get_detail("ts_board")
    assert detail["rounds"][0]["board"] == "创业板"
    assert detail["rounds"][0]["code"] == code
    assert detail["rounds"][0]["name"] == "创业股"

    # 板块缺失 → None（不报错）
    _mk_session(pg, "ts_noboard", status="completed")
    _mk_round(pg, "ts_noboard", code, date(2026, 1, 5), date(2026, 1, 30))
    market.execute("UPDATE stock_basic SET board=NULL WHERE code=?", [code])
    svc2 = TrainingService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    assert svc2.get_detail("ts_noboard")["rounds"][0]["board"] is None

    # running 态返回板块（宽泛分类，防作弊不泄露具体身份）：主板/创业板/科创板
    market.execute("UPDATE stock_basic SET board=? WHERE code=?", ["创业板", code])
    _mk_session(pg, "ts_run_board", status="running")
    _mk_round(pg, "ts_run_board", code, date(2026, 1, 5), date(2026, 1, 30), status="running")
    running = TrainingService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    run_view = running.get_view("ts_run_board")
    assert run_view["round"]["board"] == "创业板"
