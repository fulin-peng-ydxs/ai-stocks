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
