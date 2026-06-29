"""盘感训练 PG 持久层测试（混合持久层 stage1·T2）。

聚焦本次迁移改动：训练 session/round/trade 落 PG 的归属闸门、list/growth 归属过滤、
delete/abort、跨归属隔离。完整开局→交易→结算的计算流逻辑未变，由实时冒烟覆盖。
"""

from __future__ import annotations

from datetime import date, datetime

from backend.services.training_service import TrainingService
from backend.tests.conftest import TEST_OWNER, TEST_TENANT


def _mk_session(pg, sid, owner=TEST_OWNER, status="completed", score=80.0):
    pg.execute(
        "INSERT INTO training_session (id,tenant_id,owner_user_id,mode,n_rounds,window_days,"
        "initial_capital,status,cur_round,total_return,score,grade,win_rate,created_at,completed_at) "
        "VALUES (%s,%s,%s,'single',1,20,100000,%s,0,0.1,%s,'A',0.6,%s,%s)",
        [sid, TEST_TENANT, owner, status, score, datetime.now(), datetime.now()])


def test_session_owner_gate(market, pg):
    _mk_session(pg, "ts1")
    svc = TrainingService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    assert svc._session_row("ts1") is not None
    # 他人看不到
    other = TrainingService(market, tenant_id=TEST_TENANT, owner_user_id="pytest_other")
    assert other._session_row("ts1") is None


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
