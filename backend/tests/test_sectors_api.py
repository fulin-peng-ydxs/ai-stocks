"""板块行情只读 API 与查询服务测试（板块概念 T8，plan §6.8）。

mock DuckDB 文件库 + seed 板块数据，验证：列表/详情/bars/members 四接口口径、
涨幅从 board_bar 计算（非资金流周期表）、涨跌家数口径、分页排序、空值、404/400。
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.services.board_query import BoardQueryService
from backend.services.market_benchmark import MarketBenchmarkService
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
    # 资金流：08-07 与行情截面同日；08-09 用于验证页面不误取全表最新快照。
    c.execute("INSERT INTO board_fund_flow (board_code, snapshot_date, period, net_inflow, "
              "leader_stock, leader_pct) VALUES "
              "('309121', DATE '2026-08-07', '即时', 45.6, '胜宏科技', 8.5), "
              "('309121', DATE '2026-08-09', '即时', 99.9, '未使用的新快照', 9.9)")
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
    assert r["fund_flow_date"] == "2026-08-07"
    rows = {x["board_code"]: x for x in r["list"]}
    ai = rows["309121"]
    # 今日涨幅：最近收盘 115 vs 前收 108 → 6.48%
    assert ai["pct_today"] == pytest.approx(6.48, abs=0.01)
    # 5 日涨幅：历史不足（只有 5 天，需 6 个点）→ None
    assert ai["pct_5d"] is None
    # 净流入取资金流即时行；领涨按行情日历史累计成员计算，不采用源端资金流领涨字段。
    assert ai["net_inflow"] == pytest.approx(45.6)
    assert ai["leader_stock"] == "平安银行"
    assert ai["leader_pct"] == pytest.approx(5.26, abs=0.01)
    # 涨跌家数：000001 涨、000002 平 → up=1 down=0
    assert ai["up_count"] == 1
    assert ai["down_count"] == 0
    # 成分数
    assert ai["member_count"] == 2
    # 半导体：仅一天指数 → 涨幅 None（历史不足）
    bd = rows["881121"]
    assert bd["pct_today"] is None
    assert bd["net_inflow"] is None  # 无资金流


def test_list_sectors_pct_today_none_when_board_missing_selected_date(c):
    """所选日期的板块指数和资金流都严格按同日匹配，不回退。"""
    svc = _svc(c)
    r = svc.list_sectors(trade_date=date(2026, 8, 8))
    assert r["trade_date"] == "2026-08-08"
    rows = {x["board_code"]: x for x in r["list"]}
    # AI PC 最近指数数据在 08-07，08-08 无数据 → 今日涨跌幅 None，但行仍保留
    assert rows["309121"]["pct_today"] is None
    assert rows["309121"]["net_inflow"] is None
    assert r["fund_flow_date"] is None
    # 有当日数据的交易日仍正常计算（08-06：108 vs 08-05 的 110）
    r_ok = svc.list_sectors(trade_date=date(2026, 8, 6))
    ai = {x["board_code"]: x for x in r_ok["list"]}["309121"]
    assert ai["pct_today"] == pytest.approx(-1.82, abs=0.01)
    assert ai["net_inflow"] is None
    assert r_ok["fund_flow_date"] is None


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


def test_list_sectors_multi_period_inflow(c):
    """列表返回各周期净流入字段（即时/3日/5日/10日/20日），并按 5 日净流入排序。"""
    # 为 AI PC 补齐行情截面日的多周期资金流
    for period, net in (("3日", 12.3), ("5日", -5.6), ("10日", 30.0), ("20日", -2.1)):
        c.execute(
            "INSERT INTO board_fund_flow (board_code, snapshot_date, period, net_inflow) "
            "VALUES ('309121', DATE '2026-08-07', ?, ?)", [period, net])
    svc = _svc(c)
    r = svc.list_sectors()
    ai = {x["board_code"]: x for x in r["list"]}["309121"]
    # 各周期净流入字段映射正确
    assert ai["net_inflow"] == pytest.approx(45.6)
    assert ai["net_inflow_3d"] == pytest.approx(12.3)
    assert ai["net_inflow_5d"] == pytest.approx(-5.6)
    assert ai["net_inflow_10d"] == pytest.approx(30.0)
    assert ai["net_inflow_20d"] == pytest.approx(-2.1)
    # 无资金流的板块各周期字段均为 None
    bd = {x["board_code"]: x for x in r["list"]}["881121"]
    assert bd["net_inflow_5d"] is None
    assert bd["net_inflow_20d"] is None
    # 按 5 日净流入排序：AI PC(-5.6) 有值、半导体(None→-inf)，desc 时 AI PC 在前、半导体垫底
    r_desc = svc.list_sectors(sort_by="net_inflow_5d", order="desc")
    assert r_desc["list"][0]["board_code"] == "309121"
    assert r_desc["list"][-1]["board_code"] == "881121"
    r_asc = svc.list_sectors(sort_by="net_inflow_5d", order="asc")
    assert r_asc["list"][0]["board_code"] == "881121"
    assert r_asc["list"][-1]["board_code"] == "309121"


def test_get_sector_detail_multi_period_inflow(c):
    """详情同样返回各周期净流入字段。"""
    for period, net in (("3日", 12.3), ("5日", -5.6)):
        c.execute(
            "INSERT INTO board_fund_flow (board_code, snapshot_date, period, net_inflow) "
            "VALUES ('309121', DATE '2026-08-07', ?, ?)", [period, net])
    d = _svc(c).get_sector("309121")
    assert d["net_inflow"] == pytest.approx(45.6)
    assert d["net_inflow_3d"] == pytest.approx(12.3)
    assert d["net_inflow_5d"] == pytest.approx(-5.6)
    assert d["net_inflow_10d"] is None


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


def test_get_sector_detail_fund_flow_strictly_matches_trade_date(c):
    """详情指定日期无资金流时返回空，不使用其他日期快照。"""
    d = _svc(c).get_sector("309121", date(2026, 8, 6))
    assert d is not None
    assert d["trade_date"] == "2026-08-06"
    assert d["fund_flow_date"] is None
    assert d["net_inflow"] is None


def test_detail_and_subset_queries_push_board_codes_into_fact_sql(c, monkeypatch):
    """详情与少量自选不能先聚合全市场再过滤，三张事实表都必须带板块谓词。"""
    queries: list[tuple[str, list]] = []
    original = c.query_df

    def traced(sql, params=None):
        queries.append((" ".join(str(sql).split()), list(params or [])))
        return original(sql, params)

    monkeypatch.setattr(c, "query_df", traced)
    svc = _svc(c)

    assert svc.get_sector("309121") is not None
    fact_queries = [item for item in queries if any(
        table in item[0] for table in ("FROM board_bar", "FROM board_fund_flow", "FROM board_member")
    ) and not item[0].startswith("SELECT max(")]
    assert len(fact_queries) == 3
    assert all("board_code IN (?)" in sql for sql, _ in fact_queries)
    assert all("309121" in params for _, params in fact_queries)

    queries.clear()
    subset = svc.list_sectors(board_codes={"309121"}, size=10)
    assert [row["board_code"] for row in subset["list"]] == ["309121"]
    scoped_queries = [item for item in queries if any(
        table in item[0]
        for table in ("FROM board_dict", "FROM board_bar", "FROM board_fund_flow", "FROM board_member")
    ) and not item[0].startswith("SELECT max(")]
    assert len(scoped_queries) == 4
    assert all("board_code IN (?)" in sql for sql, _ in scoped_queries)


def test_cumulative_member_market_is_distinct_from_latest_snapshot_count(c):
    """行情统计消费历史累计关系；最近完整快照返回数保持独立口径。"""
    c.execute("INSERT INTO board_member (board_code, code) VALUES ('309121', '000003.SZ')")
    c.execute("INSERT INTO stock_basic (code, name) VALUES ('000003.SZ', '累计成员')")
    c.execute(
        "INSERT INTO daily_bar (code, trade_date, close, pre_close, amount) "
        "VALUES ('000003.SZ', DATE '2026-08-07', 12, 10, 1000000)"
    )
    svc = _svc(c)

    rows = {x["board_code"]: x for x in svc.list_sectors()["list"]}
    assert rows["309121"]["member_count"] == 2
    assert rows["309121"]["up_count"] == 2
    assert rows["309121"]["leader_stock"] == "累计成员"
    detail = svc.get_sector("309121")
    assert detail["member_count"] == 2
    assert detail["up_count"] == 2
    assert detail["leader_stock"] == "累计成员"
    assert svc.get_members("309121")["total"] == 3


def test_get_sector_not_found(c):
    """不存在板块 → None。"""
    assert _svc(c).get_sector("999999") is None


# ── bars ──────────────────────────────────────────────────


def test_get_bars_range(c):
    """指数区间序列首根使用区间外上一交易点收盘作为前收。"""
    svc = _svc(c)
    bars = svc.get_bars("309121", date(2026, 8, 4), date(2026, 8, 7))
    assert len(bars) == 4
    assert bars[0]["trade_date"] == "2026-08-04"
    assert bars[0]["close"] == pytest.approx(105.0)
    assert bars[0]["pre_close"] == pytest.approx(100.0)
    assert bars[1]["pre_close"] == pytest.approx(105.0)
    assert bars[-1]["close"] == pytest.approx(115.0)

    earliest = svc.get_bars("309121", date(2026, 8, 3), date(2026, 8, 3))
    assert earliest[0]["pre_close"] is None


def test_get_bar_indicators_reuses_macd_definition_and_keeps_nullable_warmup(c):
    """板块 MACD 与统一指标定义同口径，历史不足时保持可空而不是伪造零值。"""
    indicators = _svc(c).get_bar_indicators(
        "309121", date(2026, 8, 4), date(2026, 8, 7),
    )
    assert [row["trade_date"] for row in indicators] == [
        "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07",
    ]
    assert all(row["macd_diff"] is None for row in indicators)
    assert all(row["macd_golden_cross"] is None for row in indicators)

    weekly = _svc(c).get_bar_indicators(
        "309121", date(2026, 8, 3), date(2026, 8, 7), "week",
    )
    assert [row["trade_date"] for row in weekly] == ["2026-08-07"]
    assert weekly[0]["macd_hist"] is None


def test_get_benchmark_bars_range(c):
    """市场指数基准与板块走势使用同一日期和 OHLC 字段契约。"""
    bars = MarketBenchmarkService(c).get_range(
        "000905.SH", date(2026, 8, 5), date(2026, 8, 7),
    )
    assert [row["trade_date"] for row in bars] == ["2026-08-05", "2026-08-06", "2026-08-07"]
    assert bars[-1]["close"] == pytest.approx(6120.0)


@pytest.mark.parametrize(
    ("code", "name"),
    [
        ("000905.SH", "中证 500"),
        ("000300.SH", "沪深 300"),
        ("000001.SH", "上证指数"),
        ("000688.SH", "科创 50"),
        ("399001.SZ", "深证成指"),
        ("399006.SZ", "创业板指"),
    ],
)
def test_market_benchmark_registry_exposes_all_configured_indices(code, name):
    """所有采集指数均进入共享查询白名单并返回稳定名称。"""
    MarketBenchmarkService.validate_code(code)
    assert MarketBenchmarkService.name(code) == name


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
    """成分股分页排序由服务端完成，pct/price/code 均保持稳定次序。"""
    svc = _svc(c)
    pct_rows = svc.get_members("309121", sort_by="pct", order="desc")["list"]
    assert pct_rows[0]["pct_chg"] >= pct_rows[1]["pct_chg"]

    code_rows = svc.get_members("309121", sort_by="code", order="desc")["list"]
    assert [row["code"] for row in code_rows] == sorted(
        [row["code"] for row in code_rows], reverse=True
    )

    price_rows = svc.get_members("309121", sort_by="price", order="asc")["list"]
    assert [row["close"] for row in price_rows] == [8.0, 10.0]


@pytest.mark.parametrize(
    ("keyword", "expected_code"),
    [("000001", "000001.SZ"), ("万科", "000002.SZ")],
)
def test_get_members_filters_by_code_or_name(c, keyword, expected_code):
    """代码或名称关键字在服务端过滤，并同步返回过滤后的总数。"""
    result = _svc(c).get_members("309121", keyword=keyword)

    assert result["total"] == 1
    assert [row["code"] for row in result["list"]] == [expected_code]


def test_get_members_treats_like_wildcards_as_literals(c):
    """搜索内容中的 SQL LIKE 通配符按普通字符处理。"""
    assert _svc(c).get_members("309121", keyword="%_")["total"] == 0


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
    ai = next(x for x in r["list"] if x["board_code"] == "309121")
    # 今日涨幅 = 指数涨跌（6.48%），资金流即时净流入独立
    assert ai["pct_today"] == pytest.approx(6.48, abs=0.01)
    assert ai["net_inflow"] == pytest.approx(45.6)


def test_leader_uses_selected_trade_date_and_stable_tiebreak(c):
    """领涨股随行情截面变化；同涨幅按成交额降序、代码升序稳定决胜。"""
    c.execute(
        "INSERT INTO daily_bar (code, trade_date, close, pre_close, amount) "
        "VALUES ('000001.SZ', DATE '2026-08-06', 10, 9, 100), "
        "('000002.SZ', DATE '2026-08-06', 20, 18, 200)"
    )
    historical = _svc(c).get_sector("309121", date(2026, 8, 6))
    assert historical["leader_stock"] == "万科A"
    assert historical["leader_pct"] == pytest.approx(11.11, abs=0.01)

    c.execute(
        "UPDATE daily_bar SET close=10, pre_close=9.5, amount=300 "
        "WHERE code='000002.SZ' AND trade_date=DATE '2026-08-07'"
    )
    latest = _svc(c).get_sector("309121", date(2026, 8, 7))
    assert latest["leader_stock"] == "万科A"
    assert latest["leader_pct"] == pytest.approx(5.26, abs=0.01)


def test_leader_excludes_suspended_or_invalid_quotes(c):
    """停牌、缺收盘或无有效前收的成分股不参与领涨排名。"""
    c.execute(
        "UPDATE daily_bar SET close=20, pre_close=10, is_suspended=true "
        "WHERE code='000002.SZ' AND trade_date=DATE '2026-08-07'"
    )
    latest = _svc(c).get_sector("309121", date(2026, 8, 7))
    assert latest["leader_stock"] == "平安银行"
