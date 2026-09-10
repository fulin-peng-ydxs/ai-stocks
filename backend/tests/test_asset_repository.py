"""资产库通用批量写 + 评分快照 PG 侧机制测试（混合持久层 stage1·T2）。

聚焦本次迁移改动：AssetRepository.upsert（归属注入/冲突更新）与 ScoreSnapshotRepo 的
fresh/stale/stats（PG 侧）；快照重算的计算路径（score_day）逻辑未变，由集成测试覆盖。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pandas as pd
import pytest

from backend.limit_ladder.rules import PointInTimeSTStatus, STStatusQuality
from backend.scoring.snapshot import ScoreSnapshotRepo
from backend.services.stock_st_status import (
    StockSTStatusFact,
    StockSTStatusService,
    STStatusNotReadyError,
)
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
    st_version = repo._st_input_version(d)
    # 手写一条 meta（stale=false + 当前指纹）
    pg.execute(
        "INSERT INTO score_snapshot_meta "
        "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,computed_at,stale,"
        "n_codes,param_hash,st_input_version) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        [d, pid, ver, TEST_TENANT, TEST_OWNER, datetime.now(UTC), False, 2, ph, st_version])
    assert repo._fresh(d, pid, ver, ph, st_version) is True
    # 指纹不匹配（参数变更场景）→ 视为失效，触发重算自愈
    assert repo._fresh(d, pid, ver, "another-hash", st_version) is False
    assert repo._fresh(d, pid, ver, ph, "different-st-version") is False
    # 失效（全局）→ 不再 fresh
    assert repo.mark_stale_dates([d]) >= 1
    assert repo._fresh(d, pid, ver, ph, st_version) is False
    s = repo.stats()
    assert s["materialized_day_profiles"] >= 1 and s["stale"] >= 1


def test_snapshot_isolation_by_owner(pg):
    """不同归属者快照互不可见（多租户隔离 R9）。"""
    AssetRepository(pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER).upsert(
        "score_snapshot", _snap_df({"A": 90.0}))
    other = pg.query_df(
        "SELECT code FROM score_snapshot WHERE owner_user_id=%s", ["pytest_other"])
    assert other.empty


def test_cached_score_board_rejects_changed_st_input_without_writing(market, pg):
    repo = ScoreSnapshotRepo(
        market=market,
        pg=pg,
        tenant_id=TEST_TENANT,
        owner_user_id=TEST_OWNER,
    )
    day = date(2026, 1, 5)
    profile = {"id": "pf-st-version", "version": 1, "items": []}
    market.execute(
        "INSERT INTO daily_bar (code,trade_date,close,pre_close) "
        "VALUES ('600001.SH',?,10,9.5)",
        [day],
    )
    st_service = StockSTStatusService(market)
    st_service.upsert_facts(
        [
            StockSTStatusFact(
                code="600001.SH",
                trade_date=day,
                status=PointInTimeSTStatus(
                    is_st=False,
                    source="test_fixture",
                    source_ref="score_cache",
                    quality=STStatusQuality.ACCURATE,
                ),
            )
        ],
        change_reason="seed",
    )
    st_version = st_service.input_version_for_date(day)
    from backend.indicators.compute import build_params, param_hash

    ph = param_hash(build_params())
    pg.execute(
        "INSERT INTO score_snapshot_meta "
        "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,computed_at,stale,"
        "n_codes,param_hash,st_input_version) VALUES (%s,%s,1,%s,%s,%s,FALSE,1,%s,%s)",
        [day, profile["id"], TEST_TENANT, TEST_OWNER, datetime.now(UTC), ph, st_version],
    )
    pg.execute(
        "INSERT INTO score_snapshot "
        "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,code,total_score,"
        "grade,rank,sub_scores) VALUES (%s,%s,1,%s,%s,'600001.SH',90,'A',1,'{}')",
        [day, profile["id"], TEST_TENANT, TEST_OWNER],
    )
    assert repo.get_board_cached(day, profile["id"], profile=profile)["code"].tolist() == [
        "600001.SH"
    ]

    st_service.upsert_facts(
        [
            StockSTStatusFact(
                code="600001.SH",
                trade_date=day,
                status=PointInTimeSTStatus(
                    is_st=True,
                    source="test_fixture",
                    source_ref="score_cache_correction",
                    quality=STStatusQuality.ACCURATE,
                ),
            )
        ],
        change_reason="correction",
    )
    assert repo.get_board_cached(day, profile["id"], profile=profile).empty
    meta = pg.query_df(
        "SELECT stale,st_input_version FROM score_snapshot_meta WHERE profile_id=%s "
        "AND tenant_id=%s AND owner_user_id=%s",
        [profile["id"], TEST_TENANT, TEST_OWNER],
    ).iloc[0]
    assert bool(meta["stale"]) is False
    assert meta["st_input_version"] == st_version


def test_score_materialization_keeps_old_snapshot_when_st_keeps_changing(
    market, pg, monkeypatch
):
    repo = ScoreSnapshotRepo(
        market=market,
        pg=pg,
        tenant_id=TEST_TENANT,
        owner_user_id=TEST_OWNER,
    )
    day = date(2026, 1, 7)
    profile_id = "pf-st-race"
    pg.execute(
        "INSERT INTO score_snapshot_meta "
        "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,computed_at,stale,"
        "n_codes,param_hash,st_input_version) VALUES (%s,%s,1,%s,%s,%s,TRUE,1,'ph','old')",
        [day, profile_id, TEST_TENANT, TEST_OWNER, datetime.now(UTC)],
    )
    pg.execute(
        "INSERT INTO score_snapshot "
        "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,code,total_score,"
        "grade,rank,sub_scores) VALUES (%s,%s,1,%s,%s,'OLD.SZ',80,'B',1,'{}')",
        [day, profile_id, TEST_TENANT, TEST_OWNER],
    )
    versions = iter(["v1", "v1", "v2", "v2", "v3"])
    monkeypatch.setattr(repo, "_st_input_version", lambda _day: next(versions))
    monkeypatch.setattr(
        "backend.scoring.snapshot.score_day",
        lambda *_args, **_kwargs: pd.DataFrame(
            [{"code": "NEW.SZ", "total_score": 90, "grade": "A", "rank": 1}]
        ),
    )

    with pytest.raises(STStatusNotReadyError, match="ST 输入在评分快照计算期间持续变化"):
        repo._materialize_locked(day, profile_id, 1, {"id": profile_id, "items": []}, "ph")

    rows = pg.query_df(
        "SELECT code FROM score_snapshot WHERE trade_date=%s AND profile_id=%s "
        "AND tenant_id=%s AND owner_user_id=%s",
        [day, profile_id, TEST_TENANT, TEST_OWNER],
    )
    meta = pg.query_df(
        "SELECT stale,st_input_version FROM score_snapshot_meta WHERE trade_date=%s "
        "AND profile_id=%s AND tenant_id=%s AND owner_user_id=%s",
        [day, profile_id, TEST_TENANT, TEST_OWNER],
    ).iloc[0]
    assert rows["code"].tolist() == ["OLD.SZ"]
    assert bool(meta["stale"]) is True
    assert meta["st_input_version"] == "old"


def test_latest_public_snapshot_date_skips_stale_st_version(market, pg):
    """概览/默认日期不能把仅 stale=false、但 ST 版本已过期的 PG 元数据报成 fresh。"""
    from backend.indicators.compute import build_params, param_hash
    from backend.services.public_board import latest_fresh_public_snapshot_date
    from backend.storage.pg_ddl import PUBLIC_BOARD_OWNER

    profile_id = "pytest_public_" + uuid4().hex[:10]
    tenant_id, owner_id = PUBLIC_BOARD_OWNER
    older, newer = date(2026, 1, 5), date(2026, 1, 6)
    service = StockSTStatusService(market)
    for trade_date in (older, newer):
        service.upsert_facts(
            [
                StockSTStatusFact(
                    code="600001.SH",
                    trade_date=trade_date,
                    status=PointInTimeSTStatus(
                        is_st=False,
                        source="test_fixture",
                        source_ref=trade_date.isoformat(),
                        quality=STStatusQuality.ACCURATE,
                    ),
                )
            ],
            change_reason="seed",
        )
    versions = {
        trade_date: service.input_version_for_date(trade_date)
        for trade_date in (older, newer)
    }
    ph = param_hash(build_params())
    try:
        for trade_date in (older, newer):
            pg.execute(
                "INSERT INTO score_snapshot_meta "
                "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,computed_at,"
                "stale,n_codes,param_hash,st_input_version) "
                "VALUES (%s,%s,1,%s,%s,%s,FALSE,0,%s,%s)",
                [
                    trade_date,
                    profile_id,
                    tenant_id,
                    owner_id,
                    datetime.now(UTC),
                    ph,
                    versions[trade_date],
                ],
            )
        service.upsert_facts(
            [
                StockSTStatusFact(
                    code="600001.SH",
                    trade_date=newer,
                    status=PointInTimeSTStatus(
                        is_st=True,
                        source="test_fixture",
                        source_ref="corrected",
                        quality=STStatusQuality.ACCURATE,
                    ),
                )
            ],
            change_reason="correction",
        )

        assert latest_fresh_public_snapshot_date(
            profile_id, 1, pg=pg, market=market
        ) == older
    finally:
        pg.execute(
            "DELETE FROM score_snapshot_meta WHERE tenant_id=%s AND owner_user_id=%s "
            "AND profile_id=%s",
            [tenant_id, owner_id, profile_id],
        )
