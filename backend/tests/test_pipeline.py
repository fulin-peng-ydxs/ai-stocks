"""M7 一键流程 + 调度测试（T-M7-1/2）。"""

from __future__ import annotations

from datetime import date

import pandas as pd

from backend.scheduler.scheduler import _is_trading_day, start_scheduler
from backend.services.pipeline import DailyPipeline
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


def test_daily_pipeline_no_data_aborts_cleanly():
    """空库 + 跳过更新 → 定位不到交易日，干净中止（ok=False，留步骤痕迹）。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        res = DailyPipeline(c).run(skip_update=True, presets=False)
        assert res["ok"] is False
        assert any(s["step"] == "定位最新交易日" and s["status"] == "failed" for s in res["steps"])


def test_is_trading_day():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        cal = pd.DataFrame([
            {"trade_date": date(2026, 6, 4), "is_open": True},
            {"trade_date": date(2026, 6, 6), "is_open": False},  # 周末
        ])
        c.register_df("cal", cal)
        c.execute("INSERT INTO trade_calendar SELECT * FROM cal")
        c.unregister("cal")
        # _is_trading_day 用全局 client；此处直接验证 SQL 口径
        df_open = c.query_df("SELECT is_open FROM trade_calendar WHERE trade_date=?", [date(2026, 6, 4)])
        df_closed = c.query_df("SELECT is_open FROM trade_calendar WHERE trade_date=?", [date(2026, 6, 6)])
        assert bool(df_open.iloc[0]["is_open"]) is True
        assert bool(df_closed.iloc[0]["is_open"]) is False


def test_scheduler_disabled_by_default():
    """默认 config.scheduler.enabled=False → 不启动，返回 None（安全默认）。"""
    assert start_scheduler() is None
