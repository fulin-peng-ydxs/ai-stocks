"""一键流程 + 定时任务调度测试。"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backend.scheduler.scheduler import ScheduledJobService, compile_trigger, freq_text
from backend.services.pipeline import DailyPipeline
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


def test_daily_pipeline_no_data_aborts_cleanly():
    """空库 + 跳过更新 → 定位不到交易日，干净中止（ok=False，留步骤痕迹）。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        res = DailyPipeline(c).run(skip_update=True)
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


def test_freq_compile_and_text():
    """频率编译器：预设三种 + cron 合法编译；人话描述正确；非法配置抛错。"""
    compile_trigger("daily", {"time": "15:30"})
    compile_trigger("weekly", {"weekdays": [1, 3, 5], "time": "16:00"})
    compile_trigger("monthly", {"day": 3, "time": "09:00"})
    compile_trigger("cron", {"cron": "30 15 * * 1-5"})
    assert "每天" in freq_text("daily", {"time": "15:30"})
    assert "周一" in freq_text("weekly", {"weekdays": [1], "time": "16:00"})
    with pytest.raises(ValueError):
        compile_trigger("weekly", {"weekdays": [], "time": "10:00"})   # 空星期
    with pytest.raises(ValueError):
        compile_trigger("monthly", {"day": 31, "time": "10:00"})        # 超 28
    with pytest.raises(ValueError):
        compile_trigger("daily", {"time": "25:00"})                     # 非法时分


def test_scheduled_job_crud():
    """定时任务 CRUD（enabled=False 不触碰调度器）：建/读/删 + 不可调度类型被拒。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        svc = ScheduledJobService(c)
        job = svc.create(name="盘后质检", task_type="verify", params={},
                         freq_type="daily", freq_config={"time": "16:05"},
                         trading_day_only=True, enabled=False)
        assert job["name"] == "盘后质检" and job["freq_text"] == "每天 16:05"
        assert job["enabled"] is False and len(svc.list()) == 1
        with pytest.raises(ValueError):   # fix 不在可调度类型内
            svc.create(name="x", task_type="fix", params={}, freq_type="daily",
                       freq_config={"time": "10:00"}, trading_day_only=False, enabled=False)
        svc.delete(job["id"])
        assert svc.list() == []
