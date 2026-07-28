"""T2C：回测浏览 q 关键字过滤——回测无自身 name，按三类引用方案名 + kind 匹配（不设退化分支）。

source=tenant/public 与同步重跑（source_run_ref 审计）已由 test_stage6_backtest_visibility 覆盖，
此处专测 q 口径。用 market 内存库构造 BacktestService，避开文件 DuckDB 锁。
"""

from __future__ import annotations

from datetime import date

from backend.screening.presets import PRESET_PROFILES
from backend.screening.profile import ProfileRepo
from backend.services.backtest_service import BacktestService
from backend.tests.conftest import TEST_OWNER, TEST_TENANT

_EXPR = PRESET_PROFILES[0]["expression"]


def _mk_run(pg, run_id, kind, profile_id=None):
    pg.execute(
        "INSERT INTO backtest_run (id, tenant_id, owner_user_id, kind, profile_id, "
        "date_start, date_end, params, status, created_at, finished_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,'{}','done',now(),now())",
        [run_id, TEST_TENANT, TEST_OWNER, kind, profile_id, date(2024, 1, 1), date(2024, 1, 31)],
    )


def test_backtest_list_q_matches_profile_name_and_kind(pg, market):
    svc = BacktestService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    screen = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    try:
        screen.save("q_screen", "独特筛选名QX", _EXPR)
        _mk_run(pg, "q_run_named", "strategy", profile_id="q_screen")
        _mk_run(pg, "q_run_plain", "strategy")
        _mk_run(pg, "q_run_score", "score_check")

        # q 命中筛选方案名 → 只出引用该方案的 run
        by_name = {r["id"] for r in svc.list_runs(q="独特筛选")}
        assert "q_run_named" in by_name
        assert "q_run_plain" not in by_name and "q_run_score" not in by_name

        # q 命中 kind → 只出 score_check
        by_kind = {r["id"] for r in svc.list_runs(q="score_check")}
        assert "q_run_score" in by_kind
        assert "q_run_named" not in by_kind and "q_run_plain" not in by_kind

        # 无 q → 三条都在（不受过滤）
        all_ids = {r["id"] for r in svc.list_runs()}
        assert {"q_run_named", "q_run_plain", "q_run_score"} <= all_ids
    finally:
        for table in ("backtest_trade", "backtest_equity", "backtest_metrics", "backtest_run"):
            pg.execute(f"DELETE FROM {table} WHERE owner_user_id=%s", [TEST_OWNER])
        pg.execute("DELETE FROM screen_profile WHERE owner_user_id=%s", [TEST_OWNER])
        pg.execute("DELETE FROM screen_profile_version WHERE owner_user_id=%s", [TEST_OWNER])


def test_backtest_list_runs_nonpositive_limit_is_no_truncation(pg, market):
    """R5-P2：非正 limit（0/-1）防御性归一为「不截断」，无 q 时不触发 SQL LIMIT 负值报错、
    有 q 时不产生 matched[:-1] 反常切片。"""
    svc = BacktestService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    screen = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    try:
        screen.save("lim_screen", "边界筛选名LB", _EXPR)
        _mk_run(pg, "lim_a", "strategy", profile_id="lim_screen")
        _mk_run(pg, "lim_b", "strategy", profile_id="lim_screen")
        _mk_run(pg, "lim_c", "strategy", profile_id="lim_screen")
        # 无 q：limit=-1/0 均返回全部（不报错、不截断）
        assert len({r["id"] for r in svc.list_runs(limit=-1)}) >= 3
        assert len({r["id"] for r in svc.list_runs(limit=0)}) >= 3
        # 有 q：limit=-1 不产生 matched[:-1]（不漏最后一条匹配）
        ids = {r["id"] for r in svc.list_runs(q="边界筛选名LB", limit=-1)}
        assert {"lim_a", "lim_b", "lim_c"} <= ids
    finally:
        for table in ("backtest_trade", "backtest_equity", "backtest_metrics", "backtest_run"):
            pg.execute(f"DELETE FROM {table} WHERE owner_user_id=%s", [TEST_OWNER])
        pg.execute("DELETE FROM screen_profile WHERE owner_user_id=%s", [TEST_OWNER])
        pg.execute("DELETE FROM screen_profile_version WHERE owner_user_id=%s", [TEST_OWNER])
