"""评分规则方案测试（v2.0 M2.2）：阈值打分 bool/band/linear + 动态权重 + 仓库 CRUD/版本。"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.scoring.score_profile import (
    ScoreProfileModel,
    ScoreProfileRepo,
    resolve_indicator,
    score_one,
)
from backend.storage.pg_ddl import PUBLIC_BOARD_OWNER
from backend.tests.conftest import TEST_OWNER, TEST_TENANT


def _snap():
    return pd.DataFrame({
        "is_bull_arrange": [True, False, True],
        "is_vol_breakout": [True, False, False],
        "is_turnover_healthy": [True, True, False],
        "dist_to_high_2y": [0.0, 0.25, 0.5],   # 越小越接近新高
        "rs_pct": [100.0, 50.0, 0.0],
        "float_mv": [1e9, 5e9, 1e10],
    }, index=["A", "B", "C"])


def test_score_one_bool():
    s = score_one(pd.Series([True, False, None]).astype("boolean"), {"type": "bool"})
    assert list(s) == [100.0, 0.0, 0.0]


def test_score_one_linear_increasing_and_decreasing():
    v = pd.Series([0.0, 50.0, 100.0])
    inc = score_one(v, {"type": "linear", "min": 0.0, "max": 100.0})
    assert list(inc) == [0.0, 50.0, 100.0]
    # 越小越高：min=0.5→0, max=0.0→100
    d = pd.Series([0.0, 0.25, 0.5])
    dec = score_one(d, {"type": "linear", "min": 0.5, "max": 0.0})
    assert list(dec) == [100.0, 50.0, 0.0]


def test_score_one_band():
    v = pd.Series([95, 85, 70, 30])
    bands = [[90, 101, 100], [80, 90, 75], [60, 80, 50], [0, 60, 0]]
    s = score_one(v, {"type": "band", "bands": bands})
    assert list(s) == [100.0, 75.0, 50.0, 0.0]


def test_profile_model_weighted_total_and_grade():
    snap = _snap()
    profile = {
        "grade_thresholds": {"watch": 80, "leader": 90, "core": 95},
        "items": [
            {"indicator": "rs_pct", "weight": 0.5, "scoring": {"type": "linear", "min": 0.0, "max": 100.0}},
            {"indicator": "is_bull_arrange", "weight": 0.5, "scoring": {"type": "bool"}},
        ],
    }
    out = ScoreProfileModel(profile).score(snap)
    # A: rs100*0.5 + bull100*0.5 = 100；B: 50*0.5+0 =25；C: 0+100*0.5=50
    assert out.loc["A", "total_score"] == 100.0
    assert out.loc["B", "total_score"] == 25.0
    assert out.loc["C", "total_score"] == 50.0
    assert out.loc["A", "grade"] == "主升浪核心"
    assert out.loc["A", "rs_pct"] == 100.0  # 分项达标分可解释


def test_profile_model_weight_auto_normalize():
    """权重和≠1 时按和归一（前端通常已归一，后端兜底）。"""
    snap = _snap()
    profile = {"items": [
        {"indicator": "is_bull_arrange", "weight": 2.0, "scoring": {"type": "bool"}},
        {"indicator": "is_vol_breakout", "weight": 2.0, "scoring": {"type": "bool"}},
    ]}
    out = ScoreProfileModel(profile).score(snap)
    # A 两项都满足 → 100；权重和=4 自动归一
    assert out.loc["A", "total_score"] == 100.0
    # C: bull满足(100)*2 + vol否(0) → 200/4 = 50
    assert out.loc["C", "total_score"] == 50.0


def test_resolver_dynamic_param_and_errors():
    snap = pd.DataFrame({"ma20": [1.0], "hhv480": [2.0], "rs_pct": [50.0]})
    assert resolve_indicator("ma", {"period": 20}, snap).iloc[0] == 1.0
    assert resolve_indicator("hhv", {"window": 480}, snap).iloc[0] == 2.0
    with pytest.raises(ValueError):
        resolve_indicator("ma", {"period": 7}, snap)       # 非内置周期
    with pytest.raises(ValueError):
        resolve_indicator("不存在指标", {}, snap)


def test_repo_save_get_version_delete(market, pg):
    repo = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    items = [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}]
    v1 = repo.save("p1", "方案一", items)
    assert v1 == 1
    # 内容不变 → 版本不增
    assert repo.save("p1", "方案一", items) == 1
    # 实质变更 → +1
    items2 = items + [{"indicator": "is_bull_arrange", "weight": 0.5, "scoring": {"type": "bool"}}]
    assert repo.save("p1", "方案一", items2) == 2
    got = repo.get("p1")
    assert got["version"] == 2 and len(got["items"]) == 2
    assert len(repo.versions("p1")) == 2
    repo.delete("p1")
    assert repo.get("p1") is None


def test_repo_validate_rejects_bad_profile(market, pg):
    repo = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    with pytest.raises(ValueError):
        repo.save("bad", "空", [])                                  # 无指标项
    with pytest.raises(ValueError):
        repo.save("bad", "零权重", [{"indicator": "rs_pct", "weight": 0,
                                   "scoring": {"type": "bool"}}])


def test_repo_isolation_by_owner(market, pg):
    """不同归属者互不可见（多租户隔离 R9）。"""
    items = [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}]
    mine = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    mine.save("p_iso", "我的", items)
    other = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id="pytest_other")
    try:
        assert other.get("p_iso") is None
        assert all(x["id"] != "p_iso" for x in other.list())
    finally:
        pg.execute("DELETE FROM score_profile WHERE owner_user_id=%s", ["pytest_other"])
        pg.execute("DELETE FROM score_profile_version WHERE owner_user_id=%s", ["pytest_other"])


def test_same_id_different_owner_no_clobber(market, pg):
    """回归(P0)：两个 owner 用同一 id 互不覆盖、各读各的（复合主键隔离）。"""
    items = [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}]
    A = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    B = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id="pytest_other")
    try:
        A.save("DUP", "A的方案", items)
        B.save("DUP", "B的方案", items)          # 同 id 不同 owner
        assert A.get("DUP")["name"] == "A的方案"  # A 未被 B 覆盖
        assert B.get("DUP")["name"] == "B的方案"  # B 读到自己的
        rows = pg.query_df("SELECT owner_user_id FROM score_profile WHERE id='DUP'")
        assert len(rows) == 2                     # 两行并存，非一行被覆盖
    finally:
        for o in (TEST_OWNER, "pytest_other"):
            pg.execute("DELETE FROM score_profile WHERE id='DUP' AND owner_user_id=%s", [o])
            pg.execute("DELETE FROM score_profile_version WHERE id='DUP' AND owner_user_id=%s", [o])


def test_visible_profiles_include_public_and_tenant_scoped(market, pg):
    """R28：可见列表=自己的 + 全体公开 + 同租户公开；他人私有和异租户租户公开不可见。"""
    items = [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}]
    mine = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    same = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id="pytest_same")
    other_tenant = ScoreProfileRepo(market=market, pg=pg, tenant_id="pytest_other_tenant", owner_user_id="pytest_cross")
    try:
        mine.save("mine_vis", "我的方案", items)
        same.save("same_private", "同租户私有", items)
        same.save("same_tenant", "同租户公开", items)
        same.set_visibility("same_tenant", "tenant", published_by="pytest_same")
        other_tenant.save("cross_tenant", "异租户内公开", items)
        other_tenant.set_visibility("cross_tenant", "tenant", published_by="pytest_cross")
        other_tenant.save("global_public", "全体公开", items)
        other_tenant.set_visibility("global_public", "public", published_by="pytest_cross")

        rows = mine.list_visible()
        ids = {r["id"] for r in rows}
        assert {"mine_vis", "same_tenant", "global_public"} <= ids
        assert "same_private" not in ids
        assert "cross_tenant" not in ids

        pub = next(r for r in rows if r["id"] == "global_public")
        assert pub["readonly"] is True and pub["source"] == "public"
        assert mine.get_visible(pub["profile_ref"])["name"] == "全体公开"
    finally:
        for owner in (TEST_OWNER, "pytest_same", "pytest_cross"):
            pg.execute("DELETE FROM score_profile WHERE owner_user_id=%s", [owner])
            pg.execute("DELETE FROM score_profile_version WHERE owner_user_id=%s", [owner])


def test_visibility_owner_only_and_copy_visible(market, pg):
    """公开方案只能 owner 调整；非 owner 可只读引用并复制成自己的私有方案。"""
    items = [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}]
    owner = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id="pytest_pub_owner")
    viewer = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    try:
        owner.save("pub_copy_src", "可复制公开方案", items)
        src = owner.set_visibility("pub_copy_src", "tenant", published_by="pytest_pub_owner")
        assert src and src["visibility"] == "tenant"

        with pytest.raises(PermissionError):
            viewer.set_visibility(src["profile_ref"], "private", published_by=TEST_OWNER)

        assert viewer.copy_visible(src["profile_ref"], "copied_profile", "我的副本") == 1
        copied = viewer.get("copied_profile")
        assert copied["name"] == "我的副本"
        assert copied["visibility"] == "private"
    finally:
        for owner_id in ("pytest_pub_owner", TEST_OWNER):
            pg.execute("DELETE FROM score_profile WHERE owner_user_id=%s", [owner_id])
            pg.execute("DELETE FROM score_profile_version WHERE owner_user_id=%s", [owner_id])


def test_public_board_owner_preset_is_visible_as_readonly_preset(market, pg):
    """平台 PUBLIC_BOARD_OWNER 预设初始化为 public，普通 owner 通过 visible list 只读引用。"""
    items = [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}]
    ptid, pown = PUBLIC_BOARD_OWNER
    preset_repo = ScoreProfileRepo(market=market, pg=pg, tenant_id=ptid, owner_user_id=pown)
    viewer = ScoreProfileRepo(market=market, pg=pg, tenant_id="pytest_view_tenant", owner_user_id="pytest_viewer")
    try:
        preset_repo.save("pytest_public_preset", "平台公开预设", items, is_preset=True)
        rows = viewer.list_visible()
        preset = next(r for r in rows if r["id"] == "pytest_public_preset")
        assert preset["visibility"] == "public"
        assert preset["source"] == "preset"
        assert preset["readonly"] is True
    finally:
        pg.execute("DELETE FROM score_profile WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
                   [ptid, pown, "pytest_public_preset"])
        pg.execute("DELETE FROM score_profile_version WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
                   [ptid, pown, "pytest_public_preset"])
