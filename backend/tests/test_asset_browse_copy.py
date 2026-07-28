"""T2B：三类方案 browse（preset|tenant|public + q + 分页）+ 复制契约（C8）。

用 screen ProfileRepo（纯 PG）验证真实 SQL：
- preset 段严格 is_preset AND public AND 平台槽，private preset 零泄露（R14）；
- public 段强制补集排除平台槽公开预设（四来源互斥）、排除自己；
- q 关键字 + 分页；
- copy_visible 后端生成唯一 id、名称「原名 副本」、返回 id/profile_ref/name/version（C8）。
scoped_where 结构化互斥已由 test_stage6_asset_visibility 覆盖，此处是接口级落地验证。
"""

from __future__ import annotations

from backend.screening.presets import PRESET_PROFILES
from backend.screening.profile import ProfileRepo
from backend.services.asset_visibility import ASSET_SCREEN_PROFILE, make_asset_ref
from backend.tests.conftest import TEST_OWNER, TEST_TENANT

_EXPR = PRESET_PROFILES[0]["expression"]
_OTHER = "pytest_other_browse"
_SLOT_T, _SLOT_O = "default", "admin"


def _cleanup(pg, ids, owners=(TEST_OWNER, _OTHER)):
    for o in owners:
        pg.execute("DELETE FROM screen_profile WHERE owner_user_id=%s", [o])
        pg.execute("DELETE FROM screen_profile_version WHERE owner_user_id=%s", [o])
    for pid in ids:  # 平台槽临时预设按 id 精确清理，避免动到真实 admin 数据
        pg.execute("DELETE FROM screen_profile WHERE id=%s AND owner_user_id=%s", [pid, _SLOT_O])
        pg.execute("DELETE FROM screen_profile_version WHERE id=%s AND owner_user_id=%s", [pid, _SLOT_O])


def test_browse_preset_strict_public_no_private_leak(pg):
    slot = ProfileRepo(pg=pg, tenant_id=_SLOT_T, owner_user_id=_SLOT_O)
    viewer = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    slot_ids = ["t2b_pub_preset", "t2b_priv_preset"]
    try:
        slot.save("t2b_pub_preset", "内置公开X", _EXPR, is_preset=True)
        slot.set_visibility("t2b_pub_preset", "public")
        slot.save("t2b_priv_preset", "内置私有X", _EXPR, is_preset=True)  # 默认 private

        ids = {r["id"] for r in viewer.browse("preset", q="内置")["items"]}
        assert "t2b_pub_preset" in ids
        assert "t2b_priv_preset" not in ids  # R14 严格：private preset 零泄露
    finally:
        _cleanup(pg, slot_ids)


def test_browse_public_force_excludes_platform_slot_preset(pg):
    slot = ProfileRepo(pg=pg, tenant_id=_SLOT_T, owner_user_id=_SLOT_O)
    viewer = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    slot_ids = ["t2b_slot_pub"]
    try:
        slot.save("t2b_slot_pub", "平台槽公开预设", _EXPR, is_preset=True)
        slot.set_visibility("t2b_slot_pub", "public")

        preset_ids = {r["id"] for r in viewer.browse("preset", q="平台槽")["items"]}
        public_ids = {r["id"] for r in viewer.browse("public", q="平台槽")["items"]}
        assert "t2b_slot_pub" in preset_ids          # 只归系统内置段
        assert "t2b_slot_pub" not in public_ids       # 强制补集：public 段不重复出现
    finally:
        _cleanup(pg, slot_ids)


def test_browse_tenant_public_exclude_self_with_q_and_pagination(pg):
    A = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    B = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=_OTHER)
    try:
        for i in (1, 2, 3):
            B.save(f"t2bq_{i}", f"t2bq 他人公开 {i}", _EXPR)
            B.set_visibility(f"t2bq_{i}", "public")
        # A 自己的公开资产：public 段必须排除自己
        A.save("t2bq_self", "t2bq 我的公开", _EXPR)
        A.set_visibility("t2bq_self", "public")

        page1 = A.browse("public", q="t2bq", page=1, page_size=2)
        assert page1["total"] == 3            # 只数 B 的 3 条，排除自己
        assert len(page1["items"]) == 2       # 分页生效
        page2 = A.browse("public", q="t2bq", page=2, page_size=2)
        assert len(page2["items"]) == 1
        all_ids = {r["id"] for r in page1["items"]} | {r["id"] for r in page2["items"]}
        assert all_ids == {"t2bq_1", "t2bq_2", "t2bq_3"}
        assert "t2bq_self" not in all_ids
        # 提供者脱敏：不回显真实 owner
        assert all(r["owner_label"] in ("同租户用户", "其他租户用户") for r in page1["items"])
        assert all(_OTHER not in r.values() for r in page1["items"])
    finally:
        _cleanup(pg, [])


def test_copy_visible_backend_generates_id_and_returns_ref(pg):
    A = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    B = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=_OTHER)
    try:
        B.save("t2b_src", "源筛选", _EXPR)
        B.set_visibility("t2b_src", "public")
        src_ref = make_asset_ref(ASSET_SCREEN_PROFILE, TEST_TENANT, _OTHER, "t2b_src")

        res = A.copy_visible(src_ref)
        # C8：后端生成 id + 名称「原名 副本」，返回 id/profile_ref/name/version
        assert res["name"] == "源筛选 副本"
        assert res["id"] and res["profile_ref"] and res["version"] == 1
        # 落到 A 名下、private
        got = A.get(res["id"])
        assert got is not None and got["visibility"] == "private"
        # 再复制一次：id 不同（后端自动去重，单击即复制、无需改名）
        res2 = A.copy_visible(src_ref)
        assert res2["id"] != res["id"]
    finally:
        _cleanup(pg, [])
