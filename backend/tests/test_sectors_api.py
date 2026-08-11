"""板块行情只读 API 与查询服务测试（板块概念 T8，plan §6.8）。

mock DuckDB 文件库 + seed 板块数据，验证：列表/详情/bars/members 四接口口径、
涨幅从 board_bar 计算（非资金流周期表）、涨跌家数口径、分页排序、空值、404/400。
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.services.board_query import BoardQueryService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


@pytest.fixture()
def c(tmp_path):
    c = DuckDBClient(db_path=str(tmp_path / "t.duckdb"))
    init_db(c)
    _seed(c)
    yield c
    c.close()


def _seed(c):
    """板块字典 + 指数 + 资金流 + 成分 + 个股行情。"""
    # 板块字典：AI PC（concept）+ 半导体（industry），AI PC 有成分/指数/资金流
    c.execute("INSERT INTO board_dict (board_code, app_code, name, board_type, "
              "has_members, has_bar, has_fund_flow, member_count) "
              "VALUES ('309121','886071','AI PC','concept',TRUE,TRUE,TRUE,2)")
    c.execute("INSERT INTO board_dict (board_code, name, board_type, has_members, has_bar) "
              "VALUES ('881121','半导体','industry',TRUE,TRUE)")
    # 指数（AI PC：连续 5 天，供 5 日涨幅算不出但今日可算；半导体同样）
    _seed_bar(c, "309121", ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"],
              [100.0, 105.0, 110.0, 108.0, 115.0])
    _seed_bar(c, "881121", ["2026-08-07"], [200.0])  # 仅一天：历史不足「—」
    for d, cl in zip(["2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"],
                     [6000.0, 6060.0, 6030.0, 6120.0]):
        c.execute("INSERT INTO index_bar (index_code, trade_date, close) "
                  "VALUES ('000905.SH', CAST(? AS DATE), ?)", [d, cl])
    # 资金流（AI PC 即时）
    c.execute("INSERT INTO board_fund_flow (board_code, snapshot_date, period, net_inflow, "
              "leader_stock, leader_pct) VALUES ('309121', DATE '2026-08-09', '即时', 45.6, '胜宏科技', 8.5)")
    # 成分（AI PC 2 只，半导体 0）
    for code in ("000001.SZ", "000002.SZ"):
        c.execute("INSERT INTO board_member (board_code, code) VALUES ('309121', ?)", [code])
    # 个股行情（AI PC 成分 08-07）
    for code, close, pre in (("000001.SZ", 10.0, 9.5), ("000002.SZ", 8.0, 8.0)):
        c.execute("INSERT INTO daily_bar (code, trade_date, close, pre_close) "
                  "VALUES (?, DATE '2026-08-07', ?, ?)", [code, close, pre])
    c.execute("INSERT INTO daily_bar (code, trade_date, close) VALUES ('600000.SH', DATE '2026-08-07', 10.0)")
    # stock_basic（成分名称）
    for code, name in (("000001.SZ", "平安银行"), ("000002.SZ", "万科A")):
        c.execute("INSERT INTO stock_basic (code, name) VALUES (?, ?)", [code, name])


def _seed_bar(c, board_code, dates, closes):
    for d, cl in zip(dates, closes):
        c.execute("INSERT INTO board_bar (board_code, trade_date, close) "
                  "VALUES (?, CAST(? AS DATE), ?)", [board_code, d, cl])


def _svc(c):
    return BoardQueryService(client=c)


# ── 列表 ──────────────────────────────────────────────────


def test_list_sectors_basic(c):
    """列表：只展示 has_members 或 has_bar 的板块，涨幅/净流入/领涨/涨跌家数口径正确。"""
    svc = _svc(c)
    r = svc.list_sectors()
    assert r["total"] == 2
    assert r["trade_date"] == "2026-08-07"
    assert r["fund_flow_date"] == "2026-08-09"
    rows = {x["board_code"]: x for x in r["list"]}
    ai = rows["309121"]
    # 今日涨幅：最近收盘 115 vs 前收 108 → 6.48%
    assert ai["pct_today"] == pytest.approx(6.48, abs=0.01)
    # 5 日涨幅：历史不足（只有 5 天，需 6 个点）→ None
    assert ai["pct_5d"] is None
    # 净流入 + 领涨（资金流即时行）
    assert ai["net_inflow"] == pytest.approx(45.6)
    assert ai["leader_stock"] == "胜宏科技"
    # 涨跌家数：000001 涨、000002 平 → up=1 down=0
    assert ai["up_count"] == 1
    assert ai["down_count"] == 0
    # 成分数
    assert ai["member_count"] == 2
    # 半导体：仅一天指数 → 涨幅 None（历史不足）
    bd = rows["881121"]
    assert bd["pct_today"] is None
    assert bd["net_inflow"] is None  # 无资金流


def test_list_sectors_filter_sort_paginate(c):
    """过滤（类型/关键词）+ 排序 + 分页。"""
    svc = _svc(c)
    r = svc.list_sectors(board_type="concept")
    assert r["total"] == 1 and r["list"][0]["board_code"] == "309121"
    r = svc.list_sectors(keyword="半导体")
    assert r["total"] == 1 and r["list"][0]["board_code"] == "881121"
    # 按净流入排序 desc
    r = svc.list_sectors(sort_by="net_inflow", order="desc")
    assert r["list"][0]["board_code"] == "309121"
    # 分页 size=1
    r = svc.list_sectors(size=1, page=2)
    assert r["total"] == 2 and len(r["list"]) == 1


# ── 详情 ──────────────────────────────────────────────────


def test_get_sector_detail(c):
    """详情：摘要 + 能力字段 + 涨幅/涨跌家数。"""
    svc = _svc(c)
    d = svc.get_sector("309121")
    assert d is not None
    assert d["name"] == "AI PC"
    assert d["board_type"] == "concept"
    assert d["member_count"] == 2
    assert d["pct_today"] == pytest.approx(6.48, abs=0.01)
    assert d["net_inflow"] == pytest.approx(45.6)
    assert d["up_count"] == 1 and d["down_count"] == 0
    assert d["has_members"] and d["has_bar"] and d["has_fund_flow"]


def test_member_count_is_latest_snapshot_not_cumulative_relation_count(c):
    """摘要成分数取最近完整源快照；成员分页 total 才是累计关系数。"""
    c.execute("INSERT INTO board_member (board_code, code) VALUES ('309121', '000003.SZ')")
    c.execute("INSERT INTO stock_basic (code, name) VALUES ('000003.SZ', '历史成分')")
    svc = _svc(c)

    rows = {x["board_code"]: x for x in svc.list_sectors()["list"]}
    assert rows["309121"]["member_count"] == 2
    assert svc.get_sector("309121")["member_count"] == 2
    assert svc.get_members("309121")["total"] == 3


def test_get_sector_not_found(c):
    """不存在板块 → None。"""
    assert _svc(c).get_sector("999999") is None


# ── bars ──────────────────────────────────────────────────


def test_get_bars_range(c):
    """指数区间序列（原值）。"""
    svc = _svc(c)
    bars = svc.get_bars("309121", date(2026, 8, 4), date(2026, 8, 7))
    assert len(bars) == 4
    assert bars[0]["trade_date"] == "2026-08-04"
    assert bars[0]["close"] == pytest.approx(105.0)
    assert bars[-1]["close"] == pytest.approx(115.0)


def test_get_benchmark_bars_range(c):
    """市场指数基准与板块走势使用同一日期和 OHLC 字段契约。"""
    bars = _svc(c).get_benchmark_bars(
        "000905.SH", date(2026, 8, 5), date(2026, 8, 7),
    )
    assert [row["trade_date"] for row in bars] == ["2026-08-05", "2026-08-06", "2026-08-07"]
    assert bars[-1]["close"] == pytest.approx(6120.0)


# ── members ───────────────────────────────────────────────


def test_get_members_paginated(c):
    """成分股分页 + 现价/涨跌幅/换手 + 名称。"""
    svc = _svc(c)
    m = svc.get_members("309121", size=1, page=1)
    assert m["total"] == 2
    assert len(m["list"]) == 1
    row = m["list"][0]
    assert row["name"] in ("平安银行", "万科A")
    assert row["close"] is not None
    assert row["pct_chg"] is not None
    m2 = svc.get_members("309121", size=1, page=2)
    assert len(m2["list"]) == 1
    assert m2["list"][0]["code"] != m["list"][0]["code"]


def test_get_members_supports_server_sort(c):
    """成分股分页排序由服务端完成，pct/code 均保持稳定次序。"""
    svc = _svc(c)
    pct_rows = svc.get_members("309121", sort_by="pct", order="desc")["list"]
    assert pct_rows[0]["pct_chg"] >= pct_rows[1]["pct_chg"]

    code_rows = svc.get_members("309121", sort_by="code", order="desc")["list"]
    assert [row["code"] for row in code_rows] == sorted(
        [row["code"] for row in code_rows], reverse=True
    )


def test_get_members_empty_board(c):
    """无成分板块 → 空列表 total=0。"""
    m = _svc(c).get_members("881121")
    assert m["total"] == 0 and m["list"] == []


# ── 口径：涨幅不读资金流周期表 ────────────────────────────


def test_pct_not_from_fund_flow_period(c):
    """涨幅从 board_bar 计算，资金流周期表仅提供净流入/领涨股（双口径边界）。"""
    svc = _svc(c)
    # 资金流只有即时行（无 5日 周期 net_ratio）——若涨幅误读资金流周期表会崩/错
    r = svc.list_sectors()
    ai = [x for x in r["list"] if x["board_code"] == "309121"][0]
    # 今日涨幅 = 指数涨跌（6.48%），资金流即时净流入独立
    assert ai["pct_today"] == pytest.approx(6.48, abs=0.01)
    assert ai["net_inflow"] == pytest.approx(45.6)
