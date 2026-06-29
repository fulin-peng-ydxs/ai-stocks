"""筛选方案仓库（screen_profile，PG）测试：save/get/list/delete + 归属隔离（混合持久层 stage1·T2/整改）。

重点回归 [P1]：删除接口必须删 PG（曾误删 DuckDB 致 PG 残留 live + 版本行）。
"""

from __future__ import annotations

from backend.screening.presets import PRESET_PROFILES
from backend.screening.profile import ProfileRepo
from backend.tests.conftest import TEST_OWNER, TEST_TENANT

_EXPR = PRESET_PROFILES[0]["expression"]   # 取一个合法预设表达式 AST


def test_screen_profile_crud_and_delete_in_pg(pg):
    repo = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    repo.save("sp_del", "待删方案", _EXPR)
    assert repo.get("sp_del") is not None
    assert any(v["version"] == 1 for v in repo.versions("sp_del"))
    repo.delete("sp_del")
    # 删后 PG 里方案与版本都不在
    assert repo.get("sp_del") is None
    assert pg.query_df(
        "SELECT 1 FROM screen_profile WHERE id='sp_del' AND owner_user_id=%s", [TEST_OWNER]).empty
    assert pg.query_df(
        "SELECT 1 FROM screen_profile_version WHERE id='sp_del' AND owner_user_id=%s", [TEST_OWNER]).empty


def test_screen_profile_isolation_and_same_id(pg):
    A = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    B = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id="pytest_other")
    try:
        A.save("DUP", "A筛选", _EXPR)
        B.save("DUP", "B筛选", _EXPR)
        assert A.get("DUP")["name"] == "A筛选"
        assert B.get("DUP")["name"] == "B筛选"
        assert A.delete("DUP") is None       # A 删自己的
        assert A.get("DUP") is None
        assert B.get("DUP")["name"] == "B筛选"  # 不影响 B
    finally:
        for o in (TEST_OWNER, "pytest_other"):
            pg.execute("DELETE FROM screen_profile WHERE id='DUP' AND owner_user_id=%s", [o])
            pg.execute("DELETE FROM screen_profile_version WHERE id='DUP' AND owner_user_id=%s", [o])
