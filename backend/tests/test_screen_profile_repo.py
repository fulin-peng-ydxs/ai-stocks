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


def test_screen_profile_save_with_id_auto_generates(pg):
    """新建时 id 为空生成 UUID（与评分/买卖一致）；显式传旧 id 仍兼容。"""
    repo = ProfileRepo(pg=pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER)
    pid, v = repo.save_with_id(None, "自动生成方案", _EXPR)
    assert len(pid) == 32 and all(ch in "0123456789abcdef" for ch in pid) and v == 1
    got = repo.get(pid)
    assert got is not None and got["name"] == "自动生成方案"
    # 名称不参与内部身份，同名方案仍获得不同 UUID。
    pid2, v2 = repo.save_with_id(None, "自动生成方案", _EXPR)
    assert len(pid2) == 32 and pid2 != pid and v2 == 1
    # 明确传 id 仍走原语义
    assert repo.save_with_id("fixed_id", "固定标识", _EXPR)[0] == "fixed_id"
    try:
        pg.execute("DELETE FROM screen_profile_version WHERE id=%s AND owner_user_id=%s", [pid, TEST_OWNER])
        pg.execute("DELETE FROM screen_profile WHERE id=%s AND owner_user_id=%s", [pid, TEST_OWNER])
        pg.execute("DELETE FROM screen_profile_version WHERE id=%s AND owner_user_id=%s", [pid2, TEST_OWNER])
        pg.execute("DELETE FROM screen_profile WHERE id=%s AND owner_user_id=%s", [pid2, TEST_OWNER])
        pg.execute("DELETE FROM screen_profile WHERE id='fixed_id' AND owner_user_id=%s", [TEST_OWNER])
    except Exception:
        pass
