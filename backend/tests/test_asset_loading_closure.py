"""资产加载闭环统一修复回归：可见性级联与指定历史版本复制。"""

from __future__ import annotations

from datetime import UTC, date, datetime

from backend.scoring.score_profile import ScoreProfileRepo
from backend.screening.presets import PRESET_PROFILES
from backend.screening.profile import ProfileRepo
from backend.signals.trade_profile import TradeProfileRepo
from backend.tests.conftest import TEST_OWNER, TEST_TENANT


def _insert_run(pg, run_id: str, owner: str, score_ref: str, visibility: str = "public") -> None:
    pg.execute(
        "INSERT INTO backtest_run (id,tenant_id,owner_user_id,kind,score_profile_id,visibility,"
        "date_start,date_end,params,status,created_at,finished_at) "
        "VALUES (%s,%s,%s,'strategy',%s,%s,%s,%s,'{}','done',%s,%s)",
        [run_id, TEST_TENANT, owner, score_ref, visibility, date(2024, 1, 1),
         date(2024, 12, 31), datetime(2025, 1, 1, tzinfo=UTC),
         datetime(2025, 1, 1, tzinfo=UTC)],
    )


def test_retract_profile_cascades_all_published_runs_without_deleting_results(market, pg):
    repo = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    pid = "closure_retract_score"
    own_run = "closure_retract_own"
    other_run = "closure_retract_other"
    items = [{
        "indicator": "rs_pct",
        "weight": 1.0,
        "scoring": {"type": "linear", "min": 0, "max": 100},
    }]
    try:
        repo.save(pid, "待收回评分", items)
        published = repo.set_visibility(pid, "public", published_by=TEST_OWNER)
        assert published is not None
        ref = published["profile_ref"]
        _insert_run(pg, own_run, TEST_OWNER, ref)
        _insert_run(pg, other_run, "closure_other", ref)

        retracted = repo.set_visibility(pid, "private")

        assert retracted is not None
        assert retracted["visibility"] == "private"
        assert retracted["affected_run_count"] == 2
        rows = pg.query_df(
            "SELECT id, visibility, published_at, published_by FROM backtest_run "
            "WHERE id IN (%s,%s) ORDER BY id",
            [own_run, other_run],
        )
        assert len(rows) == 2
        assert set(rows["visibility"]) == {"private"}
        assert rows["published_at"].isna().all()
        assert rows["published_by"].isna().all()
    finally:
        pg.execute("DELETE FROM backtest_run WHERE id IN (%s,%s)", [own_run, other_run])
        pg.execute(
            "DELETE FROM score_profile_version WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [TEST_TENANT, TEST_OWNER, pid],
        )
        pg.execute(
            "DELETE FROM score_profile WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [TEST_TENANT, TEST_OWNER, pid],
        )


def test_copy_specific_visible_version_for_all_profile_types(market, pg):
    source_owner = "closure_version_source"
    viewer = "closure_version_viewer"
    score = ScoreProfileRepo(
        market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=source_owner
    )
    score_view = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=viewer)
    screen = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=source_owner)
    screen_view = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=viewer)
    trade = TradeProfileRepo(
        market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=source_owner
    )
    trade_view = TradeProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=viewer)
    score_id, screen_id, trade_id = "closure_score_v", "closure_screen_v", "closure_trade_v"
    score_v1 = [
        {"indicator": "rs_pct", "weight": 1.0,
         "scoring": {"type": "linear", "min": 1, "max": 9}}
    ]
    score_v2 = [
        {"indicator": "rs_pct", "weight": 1.0,
         "scoring": {"type": "linear", "min": 2, "max": 10}}
    ]
    screen_v1 = PRESET_PROFILES[0]["expression"]
    screen_v2 = PRESET_PROFILES[1]["expression"]
    buy_v1 = {"op": "AND", "children": [{"indicator": "bull_arrange", "cmp": "==", "value": True}]}
    buy_v2 = {"op": "AND", "children": [{"indicator": "rs_pct", "cmp": ">=", "value": 5}]}
    try:
        score.save(score_id, "评分历史一", score_v1)
        score.save(score_id, "评分历史二", score_v2)
        score_ref = score.set_visibility(
            score_id, "public", published_by=source_owner
        )["profile_ref"]
        score_copy = score_view.copy_visible(score_ref, version=1)
        assert score_view.get(score_copy["id"])["items"] == score_v1

        screen.save(screen_id, "筛选历史一", screen_v1)
        screen.save(screen_id, "筛选历史二", screen_v2)
        screen_ref = screen.set_visibility(
            screen_id, "public", published_by=source_owner
        )["profile_ref"]
        screen_copy = screen_view.copy_visible(screen_ref, version=1)
        assert screen_view.get(screen_copy["id"])["expression"] == screen_v1

        backstop = {"max_hold_days": 20}
        trade.save(trade_id, "买卖历史一", buy_v1, {}, backstop)
        trade.save(trade_id, "买卖历史二", buy_v2, {}, backstop)
        trade_ref = trade.set_visibility(
            trade_id, "public", published_by=source_owner
        )["profile_ref"]
        trade_copy = trade_view.copy_visible(trade_ref, version=1)
        assert trade_view.get(trade_copy["id"])["buy_tree"] == buy_v1
    finally:
        for table in ("score_profile", "screen_profile", "trade_profile"):
            pg.execute(
                f"DELETE FROM {table}_version WHERE tenant_id=%s AND owner_user_id IN (%s,%s)",
                [TEST_TENANT, source_owner, viewer],
            )
            pg.execute(
                f"DELETE FROM {table} WHERE tenant_id=%s AND owner_user_id IN (%s,%s)",
                [TEST_TENANT, source_owner, viewer],
            )
