"""股票分组测试（个股查询·篮子，M2.4+）：CRUD + 成员增删 + 各股加入日涨幅 + 整组等权平均。"""

from __future__ import annotations

from datetime import date

import pandas as pd

from backend.groups.stock_group import StockGroupRepo
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


def _seed(c):
    """两只股，各 3 个交易日，前复权因子=1，便于核对涨幅。"""
    bars = pd.DataFrame([
        # A：100 → 110 → 120（自 01-02 起 +20%）
        ("A", date(2026, 1, 2), 100.0, 1.0),
        ("A", date(2026, 1, 5), 110.0, 1.0),
        ("A", date(2026, 1, 6), 120.0, 1.0),
        # B：50 → 40 → 45（自 01-05 起 +12.5%）
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


def test_group_crud_and_returns():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        _seed(c)
        repo = StockGroupRepo(c)
        default_gid = repo.default_group_id()
        default_group = repo.get(default_gid)
        assert default_group["name"] == "自选"
        assert default_group["color"] == "#f56c6c"
        assert default_group["is_default"] is True

        gid = repo.create("龙头组", date(2026, 1, 2), "测试", ["A"], color="#409eff")
        assert gid
        # 追加 B，加入日 01-05（各自基准）
        repo.add_members(gid, ["B"], add_date=date(2026, 1, 5))

        g = repo.get(gid)
        assert g["name"] == "龙头组" and g["count"] == 2
        assert g["color"] == "#409eff"
        assert g["members"]["total"] == 2
        m = {x["code"]: x for x in g["members"]["list"]}
        assert m["A"]["add_date"] == "2026-01-02" and abs(m["A"]["ret"] - 0.20) < 1e-9   # 100→120
        assert m["B"]["add_date"] == "2026-01-05" and abs(m["B"]["ret"] - (-0.10)) < 1e-9  # 50→45
        # 整组等权平均 = (0.20 + -0.10)/2 = 0.05
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
        try:
            repo.delete(default_gid)
            assert False, "默认自选分组不能删除"
        except ValueError:
            pass


def test_member_before_data_has_null_return():
    """加入日晚于该股最后数据 → 无法取基准价，涨幅置空，不计入整组平均。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        _seed(c)
        repo = StockGroupRepo(c)
        gid = repo.create("组", date(2026, 1, 2), "", ["A"])
        repo.add_members(gid, ["B"], add_date=date(2026, 6, 1))  # B 无 6 月数据
        g = repo.get(gid)
        m = {x["code"]: x for x in g["members"]["list"]}
        assert m["B"]["ret"] is None
        assert abs(g["avg_ret"] - 0.20) < 1e-9  # 仅 A 计入
