"""股票分组测试（个股查询·篮子，M2.4+）：CRUD + 成员增删 + 各股加入日涨幅 + 整组等权平均。

混合持久层（stage1·T2）：分组/成员在 PG（资产），行情在 DuckDB（只读）。
本测试用内存 DuckDB 喂行情、真实 PG 存资产（独立测试归属 + 用后清理）；PG 不可用则整体 skip。
同时覆盖跨库编排：成员从 PG 取、行情从 DuckDB 取、内存按 code 合并算涨幅。
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backend.common.exceptions import StorageError
from backend.groups.stock_group import StockGroupRepo
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.pg_client import PostgresClient
from backend.storage.pg_ddl import init_pg_db

# 测试专用归属，避免污染真实数据；setup/teardown 据此清理
_T_TENANT = "pytest"
_T_OWNER = "pytest_stock_group"


def _seed_market(c):
    """两只股，各 3 个交易日，前复权因子=1，便于核对涨幅。"""
    bars = pd.DataFrame([
        ("A", date(2026, 1, 2), 100.0, 1.0),
        ("A", date(2026, 1, 5), 110.0, 1.0),
        ("A", date(2026, 1, 6), 120.0, 1.0),
        ("B", date(2026, 1, 2), 60.0, 1.0),
        ("B", date(2026, 1, 5), 50.0, 1.0),
        ("B", date(2026, 1, 6), 45.0, 1.0),
    ], columns=["code", "trade_date", "close", "adj_factor"])
    c.register_df("_bars", bars)
    c.execute("INSERT INTO daily_bar (code, trade_date, close, adj_factor) SELECT code, trade_date, close, adj_factor FROM _bars")
    c.unregister("_bars")
    basic = pd.DataFrame([("A", "甲股"), ("B", "乙股")], columns=["code", "name"])
    c.register_df("_basic", basic)
    c.execute("INSERT INTO stock_basic (code, name) SELECT code, name FROM _basic")
    c.unregister("_basic")


@pytest.fixture()
def repo():
    """市场内存 DuckDB + 真实 PG（测试归属，用前用后清理）；PG 不可用则 skip。"""
    pg = PostgresClient()
    try:
        if not pg.ping():
            pytest.skip("PostgreSQL 未就绪")
    except StorageError:
        pytest.skip("PostgreSQL 未就绪")
    init_pg_db(pg)

    def _cleanup():
        for t in ("stock_group_member", "stock_group"):
            pg.execute(f"DELETE FROM {t} WHERE owner_user_id=%s", [_T_OWNER])

    _cleanup()
    mkt = DuckDBClient(db_path=":memory:")
    init_db(mkt)
    _seed_market(mkt)
    yield StockGroupRepo(pg=pg, market=mkt, tenant_id=_T_TENANT, owner_user_id=_T_OWNER)
    _cleanup()
    mkt.close()
    pg.close()


def test_group_crud_and_returns(repo):
    default_gid = repo.default_group_id()
    default_group = repo.get(default_gid)
    assert default_group["name"] == "自选"
    assert default_group["color"] == "#f56c6c"
    assert default_group["is_default"] is True

    gid = repo.create("龙头组", date(2026, 1, 2), "测试", ["A"], color="#409eff")
    assert gid
    repo.add_members(gid, ["B"], add_date=date(2026, 1, 5))

    g = repo.get(gid)
    assert g["name"] == "龙头组" and g["count"] == 2
    assert g["color"] == "#409eff"
    assert g["members"]["total"] == 2
    m = {x["code"]: x for x in g["members"]["list"]}
    assert m["A"]["add_date"] == "2026-01-02" and abs(m["A"]["ret"] - 0.20) < 1e-9
    assert m["B"]["add_date"] == "2026-01-05" and abs(m["B"]["ret"] - (-0.10)) < 1e-9
    assert abs(g["avg_ret"] - 0.05) < 1e-9

    # 已在组内不覆盖加入日期
    repo.add_members(gid, ["A"], add_date=date(2026, 1, 6))
    assert {x["code"]: x for x in repo.get(gid)["members"]["list"]}["A"]["add_date"] == "2026-01-02"

    # 改加入日期 → 涨幅基准变（A 自 01-05：110→120）
    repo.set_member_date(gid, "A", date(2026, 1, 5))
    assert abs({x["code"]: x for x in repo.get(gid)["members"]["list"]}["A"]["ret"] - round(120 / 110 - 1, 4)) < 1e-9

    # 元信息 + 列表
    repo.update_meta(gid, name="改名组")
    assert repo.get(gid)["name"] == "改名组"
    assert any(x["id"] == gid and x["member_count"] == 2 for x in repo.list())
    assert repo.groups_for_codes(["A"])["A"][0]["name"] == "改名组"
    page1 = repo.get(gid, page=1, size=1, sort_by="code", sort_order="asc")
    page2 = repo.get(gid, page=2, size=1, sort_by="code", sort_order="asc")
    assert page1["members"]["total"] == 2
    assert [x["code"] for x in page1["members"]["list"]] == ["A"]
    assert [x["code"] for x in page2["members"]["list"]] == ["B"]
    assert repo.get(gid, q="乙")["members"]["list"][0]["code"] == "B"

    # 默认自选可增删成员，但分组本身不可删除/改名/改色
    repo.add_members(default_gid, ["A"])
    assert repo.get(default_gid)["count"] == 1
    repo.remove_members(default_gid, ["A"])
    assert repo.get(default_gid)["count"] == 0
    repo.update_meta(default_gid, name="不能改", color="#409eff")
    assert repo.get(default_gid)["name"] == "自选"
    assert repo.get(default_gid)["color"] == "#f56c6c"

    # 移除 + 删除
    repo.remove_members(gid, ["B"])
    assert repo.get(gid)["count"] == 1
    repo.delete(gid)
    assert repo.get(gid) is None
    with pytest.raises(ValueError):
        repo.delete(default_gid)


def test_group_page_attaches_related_boards_by_each_members_last_date(repo):
    as_of = date(2026, 8, 28)
    repo.mkt.execute(
        "INSERT INTO stock_basic (code,name,board) VALUES ('600000.SH','浦发银行','主板')"
    )
    repo.mkt.execute(
        "INSERT INTO daily_bar (code,trade_date,close,pre_close,adj_factor) VALUES "
        "('600000.SH',?,10.5,10.0,1.0)",
        [as_of],
    )
    repo.mkt.execute(
        "INSERT INTO board_dict (board_code,name,board_type) VALUES ('881001','银行','industry')"
    )
    repo.mkt.execute(
        "INSERT INTO stock_board_correlation_state VALUES "
        "('600000.SH',?,TIMESTAMP '2026-08-29 10:00:00','stock-board-correlation-v2',"
        "'000001.SH',false,true,false)",
        [as_of],
    )
    repo.mkt.execute(
        "INSERT INTO stock_board_correlation VALUES "
        "('600000.SH','industry','881001',0.8,0.8,0.8,20,60,'high','000001.SH',false,?,"
        "TIMESTAMP '2026-08-29 10:00:00','stock-board-correlation-v2')",
        [as_of],
    )
    gid = repo.create("相关性组", as_of, codes=["600000.SH"])

    group = repo.get(gid)

    row = group["members"]["list"][0]
    assert row["last_date"] == "2026-08-28"
    assert row["related_boards"]["industry"]["name"] == "银行"


def test_member_before_data_has_null_return(repo):
    """加入日晚于该股最后数据 → 无法取基准价，涨幅置空，不计入整组平均。"""
    gid = repo.create("组", date(2026, 1, 2), "", ["A"])
    repo.add_members(gid, ["B"], add_date=date(2026, 6, 1))  # B 无 6 月数据
    g = repo.get(gid)
    m = {x["code"]: x for x in g["members"]["list"]}
    assert m["B"]["ret"] is None
    assert abs(g["avg_ret"] - 0.20) < 1e-9  # 仅 A 计入


def test_isolation_by_owner(repo):
    """不同归属者互不可见（多租户隔离 R9）。"""
    gid = repo.create("我的组", date(2026, 1, 2), "", ["A"])
    other = StockGroupRepo(pg=repo.pg, market=repo.mkt, tenant_id=_T_TENANT,
                           owner_user_id="pytest_other_owner")
    try:
        assert other.get(gid) is None                      # 看不到别人的组
        assert all(x["id"] != gid for x in other.list())   # 列表里也没有
    finally:
        for t in ("stock_group_member", "stock_group"):
            repo.pg.execute(f"DELETE FROM {t} WHERE owner_user_id=%s", ["pytest_other_owner"])


def test_same_group_id_different_owner_no_clobber(repo):
    """回归(P0)：两个 owner 用同一 group id 互不覆盖（复合主键 + ON CONFLICT 含归属）。"""
    other = StockGroupRepo(pg=repo.pg, market=repo.mkt, tenant_id=_T_TENANT,
                           owner_user_id="pytest_other_owner")
    try:
        # 直接以相同 id 写两行（绕过 _new_id，模拟 id 碰撞/预设场景）
        for r, owner, name in ((repo, _T_OWNER, "我的组"), (other, "pytest_other_owner", "他的组")):
            r.pg.execute(
                "INSERT INTO stock_group (id,tenant_id,owner_user_id,name,is_default) "
                "VALUES ('DUPG',%s,%s,%s,false) "
                "ON CONFLICT (tenant_id, owner_user_id, id) DO UPDATE SET name=EXCLUDED.name",
                [_T_TENANT, owner, name])
        assert repo.get("DUPG")["name"] == "我的组"
        assert other.get("DUPG")["name"] == "他的组"
        assert len(repo.pg.query_df("SELECT 1 FROM stock_group WHERE id='DUPG'")) == 2
    finally:
        repo.pg.execute("DELETE FROM stock_group WHERE id='DUPG'")
