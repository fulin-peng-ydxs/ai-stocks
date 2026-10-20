"""显式规模门禁：以合成源窗口经过真实服务、清洗和 DuckDB 落表，不写开发数据。"""

from __future__ import annotations

import json
import os
import resource
import sys
import time
from datetime import date, datetime

import pandas as pd
import pytest

from backend.services import eod_dates
from backend.services.intraday_archive import IntradayArchiveService
from backend.services.intraday_source import IntradaySourceService
from backend.tests.test_intraday_archive import Windows
from backend.tests.test_intraday_quotes import _frame


@pytest.mark.skipif(not os.getenv("INTRADAY_SCALE_STOCKS"), reason="仅显式执行代表性规模门禁")
def test_real_ingestion_scale(market, monkeypatch):
    count = int(os.environ["INTRADAY_SCALE_STOCKS"])
    monkeypatch.setattr(
        eod_dates, "shanghai_now", lambda: datetime(2026, 9, 10, 16, tzinfo=eod_dates.SHANGHAI)
    )
    days = pd.bdate_range("2026-09-01", "2026-09-10")
    market.execute(
        "INSERT INTO stock_basic(code,name,list_date) "
        "SELECT CAST(600000+i AS VARCHAR)||'.SH','规模样本','2026-09-01' FROM range(?) t(i)",
        [count],
    )
    with market.temp_view(pd.DataFrame({"trade_date": days.date, "is_open": True})) as view:
        market.execute(f"INSERT INTO trade_calendar SELECT * FROM {view}")
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,close) "
        "SELECT s.code,t.trade_date,3.6 FROM stock_basic s CROSS JOIN trade_calendar t"
    )
    frame = pd.concat([_frame(date.fromisoformat(str(d.date()))) for d in days], ignore_index=True)
    frame = frame[~frame.timestamp.dt.strftime("%H:%M").isin(["14:58", "14:59"])]
    payload = IntradaySourceService._frame_to_window(frame, "sina")
    payload["fetched_at"] = "2026-09-10T08:00:00+00:00"
    source = Windows([payload])
    service = IntradayArchiveService(market, quotes=source)
    start = time.monotonic()
    result = service.collect()
    assert result["ok"] and result["inserted"] == count * 8
    assert service.summary()["complete_days"] == count * 8
    rows = market.query_df("SELECT count(*) n FROM stock_intraday_bar").iloc[0].n
    assert rows == count * 8 * 238
    assert service.issues() == []
    # 再次真实入口执行只能跳过，不能二次请求源或增加分钟行。
    second = service.collect()
    assert second["skipped"] == count * 8 and len(source.calls) == count
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (
        1024**2 if sys.platform == "darwin" else 1024
    )
    print(
        json.dumps(
            {
                "stocks": count,
                "days": 8,
                "rows": int(rows),
                "elapsed_sec": round(time.monotonic() - start, 2),
                "peak_process_mb": round(peak, 1),
            }
        ),
        flush=True,
    )


@pytest.mark.skipif(not os.getenv("INTRADAY_SCALE_STOCKS"), reason="仅显式执行代表性规模门禁")
def test_quality_scan_scale_with_every_day_incomplete(market, monkeypatch):
    """同等规模的分钟事实经过正式扫描入口；每个股票日均缺一分钟，验证分批诊断。"""
    from backend.services.intraday_contract import REQUIRED_TIMES

    count = int(os.environ["INTRADAY_SCALE_STOCKS"])
    monkeypatch.setattr(
        eod_dates, "shanghai_now", lambda: datetime(2026, 9, 10, 16, tzinfo=eod_dates.SHANGHAI)
    )
    days = pd.bdate_range("2026-09-01", "2026-09-10")
    market.execute(
        "INSERT INTO stock_basic(code,name,list_date) "
        "SELECT CAST(600000+i AS VARCHAR)||'.SH','质量规模样本','2026-09-01' FROM range(?) t(i)",
        [count],
    )
    with market.temp_view(pd.DataFrame({"trade_date": days.date, "is_open": True})) as view:
        market.execute(f"INSERT INTO trade_calendar SELECT * FROM {view}")
    market.execute("INSERT INTO stock_intraday_monitor(code,monitoring_start) SELECT code,'2026-09-01' FROM stock_basic")
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,close) SELECT s.code,t.trade_date,3.6 "
        "FROM stock_basic s CROSS JOIN trade_calendar t"
    )
    with market.temp_view(pd.DataFrame({"clock": sorted(REQUIRED_TIMES - {'11:07'})})) as view:
        market.execute(
            "INSERT INTO stock_intraday_bar SELECT s.code,t.trade_date,"
            "CAST(CAST(t.trade_date AS VARCHAR)||' '||m.clock||':00' AS TIMESTAMP),"
            "3.6,3.6,3.6,3.6,10,3600,'sina',TIMESTAMP '2026-09-10 08:00:00' "
            f"FROM stock_basic s CROSS JOIN trade_calendar t CROSS JOIN {view} m "
            "ORDER BY s.code,t.trade_date,m.clock"
        )
    market.execute(
        "INSERT INTO stock_intraday_coverage(code,trade_date,point_count,status,source,fetched_at) "
        "SELECT code,trade_date,237,'partial','sina',TIMESTAMP '2026-09-10 08:00:00' FROM daily_bar"
    )
    start = time.monotonic()
    result = IntradayArchiveService(market).sync()
    assert result == {'intraday_gap': 0, 'intraday_partial': count * 8, 'intraday_invalid': 0}
    sample = json.loads(market.query_df("SELECT detail FROM data_quality_issue LIMIT 1").iloc[0, 0])
    assert sample['coverage']['missing_times'] == ['11:07']
    assert sample['availability']['status'] == 'needs_verification'
    assert market.query_df("SELECT count(*) FROM stock_intraday_source_state").iloc[0, 0] == 0
    print(json.dumps({
        'quality_stocks': count, 'quality_days': 8, 'quality_rows': count * 8 * 237,
        'issues': count * 8, 'scan_elapsed_sec': round(time.monotonic() - start, 2),
        'peak_process_mb': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (
            1024**2 if sys.platform == 'darwin' else 1024), 1),
    }), flush=True)
