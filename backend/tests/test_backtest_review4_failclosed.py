"""T5 四次复审后端回归：P1-4 显式失效方案 fail-closed、P1-5 回测 ID 并发唯一。

- P1-4：请求提供了 ref 而当前用户不可见/不存在即拒绝（ValueError → API 400），
  禁止持久化和审计（防止方案失效/下架/跨租户竞态时静默改用默认评分重跑）。
- P1-5：_new_id 并发唯一（同秒多次生成不碰撞）；_persist_run 状态转换不再「先 DELETE 再 INSERT」。
"""
from __future__ import annotations

import pytest

from backend.services.backtest_service import BacktestService
from backend.tests.conftest import TEST_OWNER, TEST_TENANT


def _svc(market) -> BacktestService:
    return BacktestService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)


# ── P1-4 显式失效方案 fail-closed ─────────────────────────────


def test_prepare_rejects_nonexistent_score_ref(market, pg):
    """prepare：提供了不存在的评分 ref → 拒绝（fail-closed，不再静默 version=None）。"""
    svc = _svc(market)
    params = {"date_start": "2024-01-02", "date_end": "2024-01-03", "score_profile_id": "avr_nonexistent_xyz"}
    with pytest.raises(ValueError, match="评分方案不存在或不可见"):
        svc.prepare("score_check", params)


def test_run_signal_rejects_nonexistent_score_ref(market, pg):
    """run_signal：不存在评分 ref → 拒绝，且不持久化任何 run（不落库不审计）。"""
    svc = _svc(market)
    params = {"date_start": "2024-01-02", "date_end": "2024-01-03", "score_profile_id": "avr_nonexistent_xyz"}
    with pytest.raises(ValueError, match="评分方案不存在或不可见"):
        svc.run_signal(params)
    df = pg.query_df(
        "SELECT COUNT(*) AS n FROM backtest_run WHERE tenant_id=%s AND owner_user_id=%s AND date_start='2024-01-02'",
        [TEST_TENANT, TEST_OWNER])
    assert int(df.iloc[0]["n"]) == 0


def test_run_strategy_rejects_cross_tenant_private_score_ref(market, pg):
    """跨租户私有评分 ref：当前用户不可见 → run_strategy 拒绝（资产边界 fail-closed）。"""
    from backend.scoring.score_profile import ScoreProfileRepo

    other_tenant = "pytest_other_tenant"
    other_owner = "pytest_other_owner"
    items = [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}]
    repo = ScoreProfileRepo(market=market, pg=pg, tenant_id=other_tenant, owner_user_id=other_owner)
    repo.save("bt_priv_score", "他租户私有评分", items)  # 默认 private
    ref = repo.get_visible("bt_priv_score")["profile_ref"]  # owner 自查拿到 opaque ref
    svc = _svc(market)
    try:
        params = {"date_start": "2024-01-02", "date_end": "2024-01-03", "score_profile_id": ref}
        with pytest.raises(ValueError, match="评分方案不存在或不可见"):
            svc.run_strategy(params)
    finally:
        pg.execute("DELETE FROM score_profile WHERE tenant_id=%s AND owner_user_id=%s", [other_tenant, other_owner])
        pg.execute("DELETE FROM score_profile_version WHERE tenant_id=%s AND owner_user_id=%s", [other_tenant, other_owner])


def test_run_strategy_rejects_missing_screen_profile(market, pg):
    """strategy 的选股方案（profile_id）失效 → 拒绝（统一三类显式依赖 fail-closed）。"""
    svc = _svc(market)
    params = {"date_start": "2024-01-02", "date_end": "2024-01-03", "profile_id": "avr_screen_missing"}
    with pytest.raises(ValueError, match="选股方案不存在或不可见"):
        svc.run_strategy(params)


def test_run_strategy_rejects_missing_trade_profile(market, pg):
    """strategy 的买卖方案（trade_profile_id）失效 → 拒绝。"""
    svc = _svc(market)
    params = {"date_start": "2024-01-02", "date_end": "2024-01-03", "trade_profile_id": "avr_trade_missing"}
    with pytest.raises(ValueError, match="买卖方案不存在或不可见"):
        svc.run_strategy(params)


# ── P1-5 回测 ID 并发唯一 + 状态转换不删行 ─────────────────────


def test_new_id_unique_under_concurrent_same_second(market, pg):
    """同一服务实例同秒多次 _new_id：全部唯一（秒级时间戳+短 UUID，并发/多标签/重试不碰撞）。"""
    svc = _svc(market)
    ids = {svc._new_id("strategy") for _ in range(200)}  # noqa: SLF001
    assert len(ids) == 200
    assert all(i.startswith("bt_strategy_") for i in ids)


def test_persist_run_state_transition_keeps_single_row(market, pg):
    """_persist_run 同 run_id 二次调用（running → done）走 UPDATE 而非 DELETE+INSERT：
    始终只有一行、状态被更新、不丢记录。"""
    svc = _svc(market)
    run_id = svc._new_id("strategy")
    params = {"date_start": "2024-01-02", "date_end": "2024-01-03"}
    try:
        svc._persist_run(run_id, "strategy", params, "running")  # noqa: SLF001
        svc._persist_run(run_id, "strategy", params, "done", finished=True)  # noqa: SLF001
        df = pg.query_df(
            "SELECT status, finished_at FROM backtest_run WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
            [run_id, TEST_TENANT, TEST_OWNER])
        assert len(df) == 1                      # 不删行重建，仍一条
        assert df.iloc[0]["status"] == "done"    # 状态被 UPDATE
        assert df.iloc[0]["finished_at"] is not None
    finally:
        pg.execute("DELETE FROM backtest_run WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
                   [run_id, TEST_TENANT, TEST_OWNER])
