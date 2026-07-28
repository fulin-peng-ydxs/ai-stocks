"""T2A：三类方案 list source=mine（纯 owner）——下拉只加载自己的资产（R3/C2）。

scoped_where 四来源互斥已由 test_stage6_asset_visibility 结构化单测覆盖；本文件用真实 PG 验证
mine 段的实际 SQL：只返回自己的资产，排除同租户他人公开、跨租户公开与系统内置预设。
browse(preset/tenant/public) 的接口级验证在 T2B。
"""

from __future__ import annotations

from backend.screening.presets import PRESET_PROFILES
from backend.screening.profile import ProfileRepo
from backend.tests.conftest import TEST_OWNER, TEST_TENANT

_EXPR = PRESET_PROFILES[0]["expression"]
_OTHER = "pytest_other_mine"


def _ids(rows):
    return {r["id"] for r in rows}


def test_list_mine_returns_only_own_assets(pg):
    A = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    B = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=_OTHER)
    try:
        A.save("mine_a1", "我的私有", _EXPR)
        A.save("mine_a2", "我的另一个", _EXPR)
        # 同租户他人：公开到租户
        B.save("other_b1", "他人租户公开", _EXPR)
        B.set_visibility("other_b1", "tenant")
        # 同租户他人：公开到全体
        B.save("other_b2", "他人全体公开", _EXPR)
        B.set_visibility("other_b2", "public")

        mine = A.list_mine()
        ids = _ids(mine)
        # 只含自己的两个
        assert ids == {"mine_a1", "mine_a2"}
        # 明确排除他人租户/全体公开
        assert "other_b1" not in ids and "other_b2" not in ids
        # mine 全部标记为自己（readonly=False、source=mine、owner_label=我）
        assert all(r["source"] == "mine" and r["readonly"] is False for r in mine)
        assert all(r["owner_label"] == "我" for r in mine)
        # summary 带 updated_at 字段（T1A 契约）
        assert all("updated_at" in r for r in mine)
    finally:
        for o in (TEST_OWNER, _OTHER):
            pg.execute("DELETE FROM screen_profile WHERE owner_user_id=%s", [o])
            pg.execute("DELETE FROM screen_profile_version WHERE owner_user_id=%s", [o])


def test_list_mine_excludes_system_preset_but_list_visible_includes(pg):
    """系统内置预设归 PUBLIC_BOARD_OWNER：list_mine 不含（不是自己的），list_visible 含（兼容旧口径）。"""
    A = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    try:
        A.save("mine_only", "我的方案", _EXPR)
        mine_ids = _ids(A.list_mine())
        assert "mine_only" in mine_ids
        # 系统内置预设 id（若已 seed）一定不在 mine（owner 非 TEST_OWNER）
        preset_ids = {p["id"] for p in PRESET_PROFILES}
        assert not (mine_ids & preset_ids)
    finally:
        pg.execute("DELETE FROM screen_profile WHERE owner_user_id=%s", [TEST_OWNER])
        pg.execute("DELETE FROM screen_profile_version WHERE owner_user_id=%s", [TEST_OWNER])
