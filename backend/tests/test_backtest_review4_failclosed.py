"""T5 四次复审后端回归：P1-4 显式失效方案 fail-closed、P1-5 回测 ID 并发唯一。

- P1-4：请求提供了 ref 而当前用户不可见/不存在即拒绝（ValueError → API 400），
  禁止持久化和审计（防止方案失效/下架/跨租户竞态时静默改用默认评分重跑）。
- P1-5：_new_id 并发唯一（同秒多次生成不碰撞）；_persist_run 状态转换不再「先 DELETE 再 INSERT」。
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from backend.services.backtest_service import BacktestService
from backend.storage.asset_repository import AssetRepository
from backend.storage.pg_client import PostgresClient
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


def test_run_signal_rejects_invalid_source_run_ref_without_persisting(market, pg):
    """复用来源不存在/不可见时必须在计算与落库前拒绝，不能留下无审计的伪复用记录。"""
    svc = _svc(market)
    params = {
        "date_start": "2024-02-01",
        "date_end": "2024-02-02",
        "source_run_ref": "avr1:backtest_run:missing:missing:missing",
    }
    with pytest.raises(ValueError, match="来源回测不存在、不可复用或不可见"):
        svc.run_signal(params)
    df = pg.query_df(
        "SELECT COUNT(*) AS n FROM backtest_run WHERE tenant_id=%s AND owner_user_id=%s "
        "AND date_start='2024-02-01'",
        [TEST_TENANT, TEST_OWNER],
    )
    assert int(df.iloc[0]["n"]) == 0


@pytest.mark.parametrize(
    "source_row",
    [
        {"run_ref": "own", "readonly": False, "visibility": "public", "status": "done"},
        {"run_ref": "running", "readonly": True, "visibility": "public", "status": "running"},
        {"run_ref": "private", "readonly": True, "visibility": "private", "status": "done"},
    ],
    ids=("own-run", "unfinished-run", "private-run"),
)
def test_prepare_rejects_source_that_is_not_external_completed_public(
    market,
    pg,
    monkeypatch,
    source_row,
):
    """本人、未完成或 private 来源均不属于 R6 的外部公开回测复用范围。"""
    svc = _svc(market)
    monkeypatch.setattr(svc, "_visible_run_row", lambda *args, **kwargs: source_row)
    with pytest.raises(ValueError, match="来源回测不存在、不可复用或不可见"):
        svc.prepare(
            "score_check",
            {
                "date_start": "2024-02-01",
                "date_end": "2024-02-02",
                "source_run_ref": source_row["run_ref"],
            },
        )


def test_reuse_audit_failure_marks_run_failed_and_compensates_results(market, pg, monkeypatch):
    """复用审计是 R6 成功条件：写入失败不得返回成功，且清理已写结果子表。"""
    svc = _svc(market)
    monkeypatch.setattr(
        svc,
        "_ensure_explicit_deps_visible",
        lambda params: {"run_ref": params["source_run_ref"], "readonly": True},
    )
    monkeypatch.setattr(
        "backend.backtest.signal.SignalAnalyzer.analyze",
        lambda *args, **kwargs: {
            "date_start": "2024-02-03", "date_end": "2024-02-04",
            "horizons": [10], "thresholds": [0.1], "min_samples": 1,
            "total_signals": 0, "base_rate": {}, "by_grade": {}, "grades_order": [],
        },
    )
    monkeypatch.setattr("backend.services.backtest_service.record_backtest_reuse_audit", lambda *args: False)
    params = {
        "date_start": "2024-02-03",
        "date_end": "2024-02-04",
        "source_run_ref": "source_ref",
    }
    try:
        with pytest.raises(RuntimeError, match="回测复用审计写入失败"):
            svc.run_signal(params)
        runs = pg.query_df(
            "SELECT id, status, detail FROM backtest_run WHERE tenant_id=%s AND owner_user_id=%s "
            "AND date_start='2024-02-03'",
            [TEST_TENANT, TEST_OWNER],
        )
        assert len(runs) == 1
        assert runs.iloc[0]["status"] == "failed"
        assert "审计写入失败" in runs.iloc[0]["detail"]
        metrics = pg.query_df(
            "SELECT run_id FROM backtest_metrics WHERE tenant_id=%s AND owner_user_id=%s AND run_id=%s",
            [TEST_TENANT, TEST_OWNER, runs.iloc[0]["id"]],
        )
        assert metrics.empty
    finally:
        pg.execute(
            "DELETE FROM backtest_run WHERE tenant_id=%s AND owner_user_id=%s AND date_start='2024-02-03'",
            [TEST_TENANT, TEST_OWNER],
        )


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


def test_same_signature_runs_reject_concurrent_duplicate_and_leave_one_record(market, pg, monkeypatch):
    """两个同 owner、同签名回测真并发时，重复请求快速失败；之后重试仍按覆盖语义唯一落库。"""
    entered = 0
    entered_lock = threading.Lock()
    first_entered = threading.Event()
    second_entered = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()

    def fake_analyze(self, *args, **kwargs):  # noqa: ARG001
        nonlocal entered
        with entered_lock:
            entered += 1
            call_no = entered
        if call_no == 1:
            first_entered.set()
            assert release_first.wait(timeout=5)
        else:
            second_entered.set()
        return {
            "date_start": "2024-03-01",
            "date_end": "2024-03-02",
            "horizons": [10],
            "thresholds": [0.1],
            "min_samples": 1,
            "total_signals": 0,
            "base_rate": {},
            "by_grade": {},
            "grades_order": [],
        }

    monkeypatch.setattr("backend.backtest.signal.SignalAnalyzer.analyze", fake_analyze)
    params = {"date_start": "2024-03-01", "date_end": "2024-03-02"}
    svc1 = _svc(market)
    svc2 = _svc(market)

    def second_run():
        second_started.set()
        return svc2.run_signal(dict(params))

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(svc1.run_signal, dict(params))
            assert first_entered.wait(timeout=5)
            second = pool.submit(second_run)
            assert second_started.wait(timeout=2)
            assert not second_entered.wait(timeout=0.25)
            with entered_lock:
                assert entered == 1, "第二个同签名请求应被 advisory lock 拒绝，而非进入计算"
            release_first.set()
            with pytest.raises(ValueError, match="相同条件的回测正在运行"):
                second.result(timeout=10)
            first_result = first.result(timeout=10)

        # 首轮释放锁后允许再次运行；后一次覆盖前一次，最终仍只有一套结果。
        second_result = svc2.run_signal(dict(params))

        assert first_result["run_id"] != second_result["run_id"]
        rows = pg.query_df(
            "SELECT id, status FROM backtest_run WHERE tenant_id=%s AND owner_user_id=%s "
            "AND kind='score_check' AND date_start='2024-03-01' AND date_end='2024-03-02'",
            [TEST_TENANT, TEST_OWNER],
        )
        assert rows.to_dict("records") == [{"id": second_result["run_id"], "status": "done"}]
        metrics = pg.query_df(
            "SELECT run_id FROM backtest_metrics WHERE tenant_id=%s AND owner_user_id=%s "
            "AND run_id IN (%s,%s)",
            [TEST_TENANT, TEST_OWNER, first_result["run_id"], second_result["run_id"]],
        )
        assert metrics["run_id"].tolist() == [second_result["run_id"]]
    finally:
        release_first.set()
        for table in ("backtest_trade", "backtest_equity", "backtest_metrics", "backtest_run"):
            pg.execute(
                f"DELETE FROM {table} WHERE tenant_id=%s AND owner_user_id=%s",
                [TEST_TENANT, TEST_OWNER],
            )


def test_signature_lock_does_not_consume_the_only_business_pool_connection(market, pg, monkeypatch):
    """pool_max=1 时仍可在持锁期间写 running/results，防止锁连接与业务连接互等。"""
    single_pool = PostgresClient(max_size=1)
    svc = _svc(market)
    svc.pg = single_pool
    svc.assets = AssetRepository(
        single_pool,
        tenant_id=TEST_TENANT,
        owner_user_id=TEST_OWNER,
    )
    monkeypatch.setattr(
        "backend.backtest.signal.SignalAnalyzer.analyze",
        lambda *args, **kwargs: {
            "date_start": "2024-03-05",
            "date_end": "2024-03-06",
            "horizons": [10],
            "thresholds": [0.1],
            "min_samples": 1,
            "total_signals": 0,
            "base_rate": {},
            "by_grade": {},
            "grades_order": [],
        },
    )
    try:
        result = svc.run_signal({"date_start": "2024-03-05", "date_end": "2024-03-06"})
        row = pg.query_df(
            "SELECT status FROM backtest_run WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [TEST_TENANT, TEST_OWNER, result["run_id"]],
        )
        assert row.to_dict("records") == [{"status": "done"}]
    finally:
        single_pool.close()
        for table in ("backtest_trade", "backtest_equity", "backtest_metrics", "backtest_run"):
            pg.execute(
                f"DELETE FROM {table} WHERE tenant_id=%s AND owner_user_id=%s",
                [TEST_TENANT, TEST_OWNER],
            )


def test_signature_lock_connection_error_uses_safe_public_message(market, monkeypatch):
    """底层连接异常不得把 DSN/驱动原文透给 API 错误详情。"""
    svc = _svc(market)

    def fail_connect(*args, **kwargs):
        raise psycopg.OperationalError("internal connection details")

    monkeypatch.setattr("backend.services.backtest_service.psycopg.connect", fail_connect)
    with pytest.raises(RuntimeError, match="回测并发锁连接失败，请稍后重试") as exc_info:
        with svc._signature_run_lock("safe-error-test"):  # noqa: SLF001
            pass
    assert "internal connection details" not in str(exc_info.value)
