"""资产库通用批量写 + 评分快照 PG 侧机制测试（混合持久层 stage1·T2）。

聚焦本次迁移改动：AssetRepository.upsert（归属注入/冲突更新）与 ScoreSnapshotRepo 的
fresh/stale/stats（PG 侧）；快照重算的计算路径（score_day）逻辑未变，由集成测试覆盖。
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from backend.scoring.snapshot import ScoreSnapshotRepo
from backend.storage.asset_repository import AssetRepository
from backend.tests.conftest import TEST_OWNER, TEST_TENANT


def _snap_df(scores: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame({
        "trade_date": [date(2026, 1, 5)] * len(scores),
        "profile_id": ["pf1"] * len(scores),
        "profile_version": [1] * len(scores),
        "code": list(scores.keys()),
        "total_score": list(scores.values()),
        "grade": ["观察"] * len(scores),
        "rank": list(range(1, len(scores) + 1)),
        "sub_scores": [None] * len(scores),
    })


def test_asset_upsert_inject_owner_and_conflict_update(pg):
    repo = AssetRepository(pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    n = repo.upsert("score_snapshot", _snap_df({"A": 90.0, "B": 80.0}))
    assert n == 2
    df = pg.query_df(
        "SELECT code, total_score, tenant_id, owner_user_id FROM score_snapshot "
        "WHERE owner_user_id=%s ORDER BY code", [TEST_OWNER])
    assert df["code"].tolist() == ["A", "B"]
    assert df.iloc[0]["tenant_id"] == TEST_TENANT and df.iloc[0]["owner_user_id"] == TEST_OWNER

    # 冲突更新：同主键改分 → 覆盖，不新增
    repo.upsert("score_snapshot", _snap_df({"A": 95.0, "B": 80.0}))
    df2 = pg.query_df(
        "SELECT code, total_score FROM score_snapshot WHERE owner_user_id=%s ORDER BY code", [TEST_OWNER])
    assert len(df2) == 2
    assert float(df2[df2["code"] == "A"].iloc[0]["total_score"]) == 95.0


def test_asset_upsert_empty_noop(pg):
    repo = AssetRepository(pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    assert repo.upsert("score_snapshot", pd.DataFrame()) == 0


def test_snapshot_fresh_stale_stats(market, pg):
    repo = ScoreSnapshotRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    d, pid, ver = date(2026, 1, 5), "pf1", 1
    # 当前指标参数指纹（与打分口径同源）
    from backend.indicators.compute import build_params, param_hash
    ph = param_hash(build_params())
    # 手写一条 meta（stale=false + 当前指纹）
    pg.execute(
        "INSERT INTO score_snapshot_meta "
        "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,computed_at,stale,n_codes,param_hash) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        [d, pid, ver, TEST_TENANT, TEST_OWNER, datetime.now(), False, 2, ph])
    assert repo._fresh(d, pid, ver, ph) is True
    # 指纹不匹配（参数变更场景）→ 视为失效，触发重算自愈
    assert repo._fresh(d, pid, ver, "another-hash") is False
    # 失效（全局）→ 不再 fresh
    assert repo.mark_stale_dates([d]) >= 1
    assert repo._fresh(d, pid, ver, ph) is False
    s = repo.stats()
    assert s["materialized_day_profiles"] >= 1 and s["stale"] >= 1


def test_snapshot_isolation_by_owner(pg):
    """不同归属者快照互不可见（多租户隔离 R9）。"""
    AssetRepository(pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER).upsert(
        "score_snapshot", _snap_df({"A": 90.0}))
    other = pg.query_df(
        "SELECT code FROM score_snapshot WHERE owner_user_id=%s", ["pytest_other"])
    assert other.empty
