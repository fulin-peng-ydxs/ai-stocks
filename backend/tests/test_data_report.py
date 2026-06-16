"""数据完整性体检报告测试（在内存库构造，验证覆盖率/空值/指数统计逻辑）。"""

from __future__ import annotations

from datetime import date

import pandas as pd

from backend.services.data_report import DataIntegrityReport
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


def _seed(c):
    init_db(c)
    # 日历：1/2~1/5 + 1/8 共 5 个开市日；1/6,1/7 周末非开市
    cal = pd.DataFrame(
        [{"trade_date": date(2024, 1, d), "is_open": d not in (6, 7)} for d in range(2, 9)]
    )
    c.register_df("cal", cal)
    c.execute("INSERT INTO trade_calendar SELECT * FROM cal")
    c.unregister("cal")

    # 股票 AAA：5 个开市日全有（覆盖 100%）
    # 股票 BBB：缺 1/4（覆盖 4/5=80%）
    opens = [date(2024, 1, d) for d in (2, 3, 4, 5, 8)]
    rows = []
    for code, miss in [("AAA.SH", None), ("BBB.SH", date(2024, 1, 4))]:
        for d in opens:
            if d == miss:
                continue
            rows.append({"code": code, "trade_date": d, "open": 10, "high": 10, "low": 10,
                         "close": 10, "pre_close": 10, "volume": 100, "amount": 1000.0,
                         "adj_factor": 1.0, "turnover_rate": 1.0, "is_st": False,
                         "is_suspended": False, "limit_status": 0, "is_one_word": False})
    df = pd.DataFrame(rows)
    c.register_df("b", df)
    c.execute("INSERT INTO daily_bar BY NAME SELECT * FROM b")
    c.unregister("b")
    c.execute("INSERT INTO stock_basic (code,name,board) VALUES ('AAA.SH','甲','主板'),('BBB.SH','乙','主板')")


def test_overview_counts():
    with DuckDBClient(db_path=":memory:") as c:
        _seed(c)
        ov = DataIntegrityReport(c).overview()
        assert ov["distinct_codes_with_bars"] == 2
        assert ov["row_counts"]["daily_bar"] == 9  # 5 + 4


def test_coverage_finds_gap():
    with DuckDBClient(db_path=":memory:") as c:
        _seed(c)
        cov = DataIntegrityReport(c).coverage(min_coverage=0.999)
        assert cov["stocks_total"] == 2
        # BBB 覆盖 80% < 阈值
        assert cov["stocks_below_threshold"] == 1
        worst = cov["worst_samples"][0]
        assert worst["code"] == "BBB.SH"
        assert abs(worst["coverage"] - 0.8) < 1e-6


def test_calendar_open_days():
    with DuckDBClient(db_path=":memory:") as c:
        _seed(c)
        rep = DataIntegrityReport(c)
        assert rep.calendar_open_days(date(2024, 1, 1), date(2024, 1, 31)) == 5
