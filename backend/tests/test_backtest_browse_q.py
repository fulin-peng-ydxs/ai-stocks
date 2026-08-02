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

        # 中文页面文案同样可检索，不要求用户知道内部枚举。
        by_kind_cn = {r["id"] for r in svc.list_runs(q="评分验证")}
        assert "q_run_score" in by_kind_cn
        assert "q_run_named" not in by_kind_cn and "q_run_plain" not in by_kind_cn

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


def test_backtest_pagination_offset_and_total(pg, market):
    """T5 分页契约：offset 切片 + count_runs 真 total，无 q（SQL LIMIT/OFFSET/COUNT）与有 q
    （Python 切片 + len(matched)）两路径口径一致。"""
    svc = BacktestService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    screen = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    try:
        screen.save("pg_screen", "分页筛选名PG", _EXPR)
        # 5 条引用 pg_screen 的 strategy run（id 字典序即 created_at 排序基准——同 now() 时靠稳定键兜底，
        # 故断言按「切片后的集合关系」而非具体次序，避免与 created_at 秒级精度耦合）
        for rid in ("pg_r1", "pg_r2", "pg_r3", "pg_r4", "pg_r5"):
            _mk_run(pg, rid, "strategy", profile_id="pg_screen")

        # 有 q 路径：total=len(matched)=5；offset 切片不漏不重
        assert svc.count_runs(q="分页筛选名PG") == 5
        p1 = {r["id"] for r in svc.list_runs(q="分页筛选名PG", limit=2, offset=0)}
        p2 = {r["id"] for r in svc.list_runs(q="分页筛选名PG", limit=2, offset=2)}
        p3 = {r["id"] for r in svc.list_runs(q="分页筛选名PG", limit=2, offset=4)}
        assert len(p1) == 2 and len(p2) == 2 and len(p3) == 1
        assert p1.isdisjoint(p2) and p2.isdisjoint(p3) and p1.isdisjoint(p3)
        assert p1 | p2 | p3 == {"pg_r1", "pg_r2", "pg_r3", "pg_r4", "pg_r5"}

        # 无 q 路径：total=COUNT(*)（含本测试 5 条，可能含库中其他 run，故只校验 ≥5 与 offset 不漏不重）
        assert svc.count_runs() >= 5
        assert svc.count_runs(kind="strategy") >= 5
        # 无 q 全列 vs 分页拼接一致（对 strategy + 本 owner 可见集）
        all_ids = [r["id"] for r in svc.list_runs(kind="strategy")]
        step = 3
        stitched: list[str] = []
        off = 0
        while True:
            page = [r["id"] for r in svc.list_runs(kind="strategy", limit=step, offset=off)]
            if not page:
                break
            stitched.extend(page)
            off += step
        assert stitched == all_ids  # 顺序一致、不漏不重
    finally:
        for table in ("backtest_trade", "backtest_equity", "backtest_metrics", "backtest_run"):
            pg.execute(f"DELETE FROM {table} WHERE owner_user_id=%s", [TEST_OWNER])
        pg.execute("DELETE FROM screen_profile WHERE owner_user_id=%s", [TEST_OWNER])
        pg.execute("DELETE FROM screen_profile_version WHERE owner_user_id=%s", [TEST_OWNER])


def test_backtest_q_page_decorates_visible_rows_only_once(pg, market, monkeypatch):
    """分页 q 同时返回 items/total，不得为 list 与 count 重复做两次全量装饰。"""
    svc = BacktestService(market, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    screen = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    calls = 0
    original = svc._query_runs_decorated  # noqa: SLF001

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(svc, "_query_runs_decorated", counted)
    try:
        screen.save("one_scan", "一次扫描方案", _EXPR)
        for rid in ("one_scan_1", "one_scan_2", "one_scan_3"):
            _mk_run(pg, rid, "strategy", profile_id="one_scan")
        items, total = svc.list_runs_page(limit=2, q="一次扫描")
        assert len(items) == 2
        assert total == 3
        assert calls == 1
    finally:
        for table in ("backtest_trade", "backtest_equity", "backtest_metrics", "backtest_run"):
            pg.execute(f"DELETE FROM {table} WHERE owner_user_id=%s", [TEST_OWNER])
        pg.execute("DELETE FROM screen_profile WHERE owner_user_id=%s", [TEST_OWNER])
        pg.execute("DELETE FROM screen_profile_version WHERE owner_user_id=%s", [TEST_OWNER])
