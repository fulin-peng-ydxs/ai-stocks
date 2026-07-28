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


def test_macd_columns_score_without_special_resolver_branch():
    snap = pd.DataFrame({
        "macd_diff": [-1.0, 0.5, 1.0],
        "macd_dea": [-1.0, 0.25, 1.0],
        "macd_hist": [-1.0, 0.5, 1.0],
        "macd_golden_cross": [False, True, pd.NA],
        "macd_dead_cross": [True, False, pd.NA],
    }, index=["WEAK", "CROSS", "STRONG"])
    profile = {"items": [
        {"indicator": "macd_diff", "weight": 0.2,
         "scoring": {"type": "linear", "min": -1.0, "max": 1.0}},
        {"indicator": "macd_dea", "weight": 0.2,
         "scoring": {"type": "linear", "min": -1.0, "max": 1.0}},
        {"indicator": "macd_hist", "weight": 0.2,
         "scoring": {"type": "linear", "min": -1.0, "max": 1.0}},
        {"indicator": "macd_golden_cross", "weight": 0.2, "scoring": {"type": "bool"}},
        {"indicator": "macd_dead_cross", "weight": 0.2, "scoring": {"type": "bool"}},
    ]}
    out = ScoreProfileModel(profile).score(snap)
    assert out.loc["WEAK", "total_score"] == 20.0
    assert out.loc["CROSS", "total_score"] == 62.5
    assert out.loc["STRONG", "total_score"] == 60.0
    assert {item["indicator"] for item in profile["items"]} <= set(out.columns)


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


def test_repo_save_with_id_generates_from_name(market, pg):
    repo = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    items = [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}]
    pid, v1 = repo.save_with_id(None, "趋势评分", items)
    try:
        assert pid == "score_trend_score"
        assert v1 == 1
        assert repo.get(pid)["name"] == "趋势评分"
        pid2, _ = repo.save_with_id(None, "趋势评分", items)
        assert pid2 == "score_trend_score_2"
    finally:
        repo.delete(pid)
        repo.delete("score_trend_score_2")


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


def test_profile_ref_uses_common_codec_and_accepts_legacy_prefix(market, pg):
    """收敛后 profile_ref 走通用 avr_ 编码；部署过渡期旧 spr_ ref 仍能解析。"""
    import base64
    import json

    items = [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}]
    repo = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    try:
        repo.save("ref_codec_src", "编码收敛方案", items)
        row = next(r for r in repo.list_visible() if r["id"] == "ref_codec_src")
        # 新 ref 统一为通用前缀
        assert row["profile_ref"].startswith("avr_")
        assert repo.get_visible(row["profile_ref"])["name"] == "编码收敛方案"

        # 手工构造旧 spr_ 前缀 ref（3 元 payload，无 asset_type），应仍可解析
        payload = json.dumps([TEST_TENANT, TEST_OWNER, "ref_codec_src"], ensure_ascii=False, separators=(",", ":"))
        legacy_ref = "spr_" + base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
        assert repo.get_visible(legacy_ref)["name"] == "编码收敛方案"
    finally:
        pg.execute("DELETE FROM score_profile WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
                   ["ref_codec_src", TEST_TENANT, TEST_OWNER])
        pg.execute("DELETE FROM score_profile_version WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
                   ["ref_codec_src", TEST_TENANT, TEST_OWNER])


def test_own_preset_source_takes_priority_over_mine(market, pg):
    """系统内置方案即便位于当前 owner 归属下，也应优先标记为 preset 而非 mine。"""
    repo = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    items = [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}]
    try:
        repo.save("own_builtin_default", "默认趋势分", items, is_preset=True)
        row = next(r for r in repo.list_visible() if r["id"] == "own_builtin_default")
        assert row["is_preset"] is True
        assert row["source"] == "preset"
    finally:
        pg.execute("DELETE FROM score_profile WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
                   ["own_builtin_default", TEST_TENANT, TEST_OWNER])
        pg.execute("DELETE FROM score_profile_version WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
                   ["own_builtin_default", TEST_TENANT, TEST_OWNER])


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

        # C8：后端生成唯一 id，返回 id/profile_ref/name/version；复制体落 viewer 名下 private
        res = viewer.copy_visible(src["profile_ref"], "我的副本")
        assert res["version"] == 1 and res["name"] == "我的副本" and res["id"] and res["profile_ref"]
        copied = viewer.get(res["id"])
        assert copied["name"] == "我的副本"
        assert copied["visibility"] == "private"
        # 单击即复制、无需改名：再复制一次得到不同 id（后端自动去重）
        res2 = viewer.copy_visible(src["profile_ref"], "我的副本")
        assert res2["id"] != res["id"]
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


def test_delete_blocked_for_public_or_referenced_profile(market, pg):
    """P1:公开态方案或被回测引用的方案不可直接删除,防悬空引用;清理后可删。"""
    from datetime import date, datetime

    items = [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}]
    repo = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    try:
        # 公开态不可删
        repo.save("del_pub", "待删公开", items)
        repo.set_visibility("del_pub", "tenant", published_by=TEST_OWNER)
        with pytest.raises(ValueError, match="收回为私有"):
            repo.delete("del_pub")
        repo.set_visibility("del_pub", "private")

        # 被回测引用(opaque ref 形态)不可删
        repo.save("del_ref", "被引用", items)
        ref = ScoreProfileRepo.make_ref(TEST_TENANT, TEST_OWNER, "del_ref")
        pg.execute(
            "INSERT INTO backtest_run (id,tenant_id,owner_user_id,kind,score_profile_id,"
            "date_start,date_end,params,status,created_at,finished_at) "
            "VALUES ('bt_del_ref',%s,%s,'strategy',%s,%s,%s,'{}','done',%s,%s)",
            [TEST_TENANT, TEST_OWNER, ref, date(2024, 1, 1), date(2024, 1, 31),
             datetime(2024, 2, 1), datetime(2024, 2, 1)],
        )
        with pytest.raises(ValueError, match="被回测记录引用"):
            repo.delete("del_ref")

        # 解除引用后可删;无引用私有方案可删
        pg.execute("DELETE FROM backtest_run WHERE id='bt_del_ref'")
        repo.delete("del_ref")
        assert repo.get("del_ref") is None
        repo.delete("del_pub")
        assert repo.get("del_pub") is None
    finally:
        pg.execute("DELETE FROM backtest_run WHERE id='bt_del_ref'")
        pg.execute("DELETE FROM score_profile WHERE owner_user_id=%s AND id IN ('del_pub','del_ref')", [TEST_OWNER])
        pg.execute("DELETE FROM score_profile_version WHERE owner_user_id=%s AND id IN ('del_pub','del_ref')", [TEST_OWNER])


def test_delete_not_blocked_by_other_owner_same_id_run(market, pg):
    """P1 收口:引用检查按归属过滤,他人同名裸 id 的回测不应误挡本人删除自己的私有方案。"""
    from datetime import date, datetime

    items = [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}]
    mine = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    same_id = "shared_del_id"
    try:
        mine.save(same_id, "我的私有", items)  # 私有,无本人回测引用
        # 另一 owner 有一条回测引用同名裸 id
        pg.execute(
            "INSERT INTO backtest_run (id,tenant_id,owner_user_id,kind,score_profile_id,"
            "date_start,date_end,params,status,created_at,finished_at) "
            "VALUES ('bt_other_owner',%s,'pytest_other','strategy',%s,%s,%s,'{}','done',%s,%s)",
            [TEST_TENANT, same_id, date(2024, 1, 1), date(2024, 1, 31),
             datetime(2024, 2, 1), datetime(2024, 2, 1)],
        )
        mine.delete(same_id)  # 不应被他人回测误挡
        assert mine.get(same_id) is None
    finally:
        pg.execute("DELETE FROM backtest_run WHERE id='bt_other_owner'")
        pg.execute("DELETE FROM score_profile WHERE owner_user_id=%s AND id=%s", [TEST_OWNER, same_id])
        pg.execute("DELETE FROM score_profile_version WHERE owner_user_id=%s AND id=%s", [TEST_OWNER, same_id])


def test_copy_visible_backend_generates_id_and_default_name(market, pg):
    """C8：score.copy_visible 后端生成唯一 id；不传 name 默认「原名 副本」，与 screen/trade 口径一致。"""
    items = [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}]
    repo = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    try:
        repo.save("copy_src_empty", "源方案", items)
        res = repo.copy_visible("copy_src_empty")  # 不传 name
        assert res["name"] == "源方案 副本"
        assert res["id"] and res["id"] != "copy_src_empty" and res["version"] == 1
        assert repo.get(res["id"])["visibility"] == "private"
    finally:
        pg.execute("DELETE FROM score_profile WHERE owner_user_id=%s", [TEST_OWNER])
        pg.execute("DELETE FROM score_profile_version WHERE owner_user_id=%s AND id='copy_src_empty'", [TEST_OWNER])


def test_downgrade_owner_assets_to_private(market, pg):
    """P3:停用联动核心——批量把 owner 名下非私有资产降级 private 并清发布字段。"""
    from backend.services.asset_visibility import downgrade_owner_assets_to_private

    items = [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}]
    repo = ScoreProfileRepo(market=market, pg=pg, tenant_id=TEST_TENANT, owner_user_id="pytest_dg")
    try:
        repo.save("dg_pub", "公开方案", items)
        repo.set_visibility("dg_pub", "public", published_by="pytest_dg")
        assert repo.get_visible("dg_pub")["visibility"] == "public"
        with pg.transaction() as conn:
            downgrade_owner_assets_to_private(conn, tenant_id=TEST_TENANT, owner_user_id="pytest_dg")
        row = repo.get("dg_pub")
        assert row["visibility"] == "private"
        assert row["published_at"] is None and row.get("published_by") is None
    finally:
        pg.execute("DELETE FROM score_profile WHERE owner_user_id='pytest_dg'")
        pg.execute("DELETE FROM score_profile_version WHERE owner_user_id='pytest_dg'")
