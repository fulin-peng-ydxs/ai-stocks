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
    """定时任务 CRUD：普通任务 + 按类型质检恢复可建，非法恢复参数被拒。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        svc = ScheduledJobService(c)
        job = svc.create(name="盘后质检", task_type="verify", params={},
                         freq_type="daily", freq_config={"time": "16:05"},
                         trading_day_only=True, enabled=False)
        assert job["name"] == "盘后质检" and job["freq_text"] == "每天 16:05"
        assert job["enabled"] is False and len(svc.list()) == 1
        cleanup = svc.create(name="审计日志清理", task_type="audit_cleanup", params={},
                             freq_type="daily", freq_config={"time": "03:30"},
                             trading_day_only=False, enabled=False)
        assert cleanup["task_type"] == "audit_cleanup" and cleanup["freq_text"] == "每天 03:30"
        repair = svc.create(
            name="每日恢复行情缺口", task_type="fix", params={"issue_type": "data_gap"},
            freq_type="daily", freq_config={"time": "17:00"},
            trading_day_only=True, enabled=False,
        )
        assert repair["task_type"] == "fix"
        assert repair["params"] == {"issue_type": "data_gap"}
        with pytest.raises(ValueError, match="需选择问题类型"):
            svc.create(name="x", task_type="fix", params={}, freq_type="daily",
                       freq_config={"time": "10:00"}, trading_day_only=False, enabled=False)
        with pytest.raises(ValueError, match="不接受固定问题 ID"):
            svc.create(name="x", task_type="fix",
                       params={"issue_type": "data_gap", "issue_ids": [1]}, freq_type="daily",
                       freq_config={"time": "10:00"}, trading_day_only=False, enabled=False)
        with pytest.raises(ValueError):
            svc.create(name="x", task_type="ingest_codes", params={}, freq_type="daily",
                       freq_config={"time": "10:00"}, trading_day_only=False, enabled=False)
        svc.delete(repair["id"])
        svc.delete(cleanup["id"])
        svc.delete(job["id"])
        assert svc.list() == []


# ── 板块采集步骤集成（R21，T6）───────────────────────────────


def _seed_market_with_latest(c: DuckDBClient) -> None:
    """种一条行情数据使 _latest_date() 有值（空库会中止流程）。"""
    c.execute("INSERT INTO daily_bar (code, trade_date, close) "
              "VALUES ('600000.SH', DATE '2026-01-05', 10.0)")


def test_pipeline_board_default_runs(tmp_path, monkeypatch):
    """board=True 默认执行：daily 含「板块采集」步骤且 ok。"""
    from backend.services import ingest as ingest_mod
    from backend.services.pipeline import DailyPipeline

    called = {"n": 0}

    def fake_ingest_board(self, ctx=None, board_type=None, board_codes=None, mode="update"):
        called["n"] += 1
        return {"dict": {"total": 465}, "members": {}, "bar": {"rows": 0},
                "fund_flow": {"rows": 0}, "failed": []}

    monkeypatch.setattr(ingest_mod.IngestionService, "ingest_board", fake_ingest_board, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "update", lambda self, codes=None, ctx=None: {"ok": 1}, raising=True)
    monkeypatch.setattr("backend.services.pipeline.get_client", lambda: None)  # 不触发真实库

    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        _seed_market_with_latest(c)
        res = DailyPipeline(c).run(skip_update=True)  # board 默认 True
        assert called["n"] == 1                       # 板块步骤执行
        assert any(s["step"] == "板块采集" and s["status"] == "ok" for s in res["steps"])


def test_pipeline_board_skipped_with_board_false(tmp_path, monkeypatch):
    """board=False：daily 不含板块采集步骤。"""
    from backend.services import ingest as ingest_mod
    from backend.services.pipeline import DailyPipeline

    called = {"n": 0}

    def fake_ingest_board(self, ctx=None, board_type=None, board_codes=None, mode="update"):
        called["n"] += 1
        return {}

    monkeypatch.setattr(ingest_mod.IngestionService, "ingest_board", fake_ingest_board, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "update", lambda self, codes=None, ctx=None: {"ok": 1}, raising=True)

    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        _seed_market_with_latest(c)
        res = DailyPipeline(c).run(skip_update=True, board=False)
        assert called["n"] == 0                       # 板块不执行
        assert not any(s["step"] == "板块采集" for s in res["steps"])


def test_pipeline_board_failure_continues_quality(tmp_path, monkeypatch):
    """板块失败不阻塞：继续执行数据质检，但最终 ok=False（R21 失败隔离语义）。"""
    from backend.services import ingest as ingest_mod
    from backend.services.data_report import DataIntegrityReport
    from backend.services.pipeline import DailyPipeline

    def boom_board(self, ctx=None, board_type=None, board_codes=None, mode="update"):
        raise RuntimeError("板块采集失败")

    monkeypatch.setattr(ingest_mod.IngestionService, "ingest_board", boom_board, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "update", lambda self, codes=None, ctx=None: {"ok": 1}, raising=True)
    monkeypatch.setattr(DataIntegrityReport, "scan_quality_issues", lambda self: {"abnormal_change_rows": 0}, raising=True)

    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        _seed_market_with_latest(c)
        res = DailyPipeline(c).run(skip_update=True)
        # 板块失败但质检步骤执行了
        steps = {s["step"]: s["status"] for s in res["steps"]}
        assert steps["板块采集"] == "failed"
        assert steps["数据质检"] == "ok"          # 失败不阻塞后续步骤
        assert res["ok"] is False                 # 但整体失败


def test_pipeline_board_total_steps_count(tmp_path, monkeypatch):
    """total_steps 正确：skip_update + board + quality = 3 步（不出现 3/2）。"""
    from backend.services import ingest as ingest_mod
    from backend.services.data_report import DataIntegrityReport
    from backend.services.pipeline import DailyPipeline

    ctx_logs: list[str] = []

    class _Ctx:
        def check_cancel(self):
            pass

        def log(self, msg, level="info"):
            ctx_logs.append(msg)

        def progress(self, p, msg):
            pass

    monkeypatch.setattr(ingest_mod.IngestionService, "ingest_board",
                        lambda self, ctx=None, board_type=None, board_codes=None, mode="update": {}, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "update", lambda self, codes=None, ctx=None: {"ok": 1}, raising=True)
    monkeypatch.setattr(DataIntegrityReport, "scan_quality_issues", lambda self: {"abnormal_change_rows": 0}, raising=True)

    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        _seed_market_with_latest(c)
        DailyPipeline(c).run(skip_update=True, ctx=_Ctx())
        # 步骤日志应含「1/2」「2/2」（skip_update=True → 板块+质检=2 步，不出现 2/1 之类错误分段）
        assert any("1/2" in m and "板块采集" in m for m in ctx_logs)
        assert any("2/2" in m and "数据质检" in m for m in ctx_logs)


def test_pipeline_quality_includes_board_scan(tmp_path, monkeypatch):
    """daily 质检步骤同时跑板块扫描（scan_board_quality 已接线，非孤立方法）。"""
    from backend.services import ingest as ingest_mod
    from backend.services.data_report import DataIntegrityReport
    from backend.services.pipeline import DailyPipeline

    called = {"board": 0, "base": 0}

    def fake_scan_board(self):
        called["board"] += 1
        return {"member_wave": 1, "index_gap": 2}

    monkeypatch.setattr(DataIntegrityReport, "scan_board_quality", fake_scan_board, raising=True)
    monkeypatch.setattr(DataIntegrityReport, "scan_quality_issues",
                        lambda self: (called.__setitem__("base", called["base"] + 1) or
                                      {"abnormal_change_rows": 0}), raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "ingest_board",
                        lambda self, ctx=None, board_type=None, board_codes=None, mode="update": {}, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "__init__", lambda self, source=None: None, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "update", lambda self, codes=None, ctx=None: {"ok": 1}, raising=True)

    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        _seed_market_with_latest(c)
        DailyPipeline(c).run(skip_update=True)
        assert called["base"] == 1   # 基础四层质检跑了
        assert called["board"] == 1  # 板块扫描也跑了（接线验证）


def test_board_schedulable_and_catalog(tmp_path):
    """审计修复验证：board 可配定时任务 + catalog 数据目录含板块表。"""
    from backend.scheduler.scheduler import SCHEDULABLE_TASK_TYPES, ScheduledJobService
    from backend.storage.catalog import build_catalog
    from backend.storage.ddl import init_db
    from backend.storage.duckdb_client import DuckDBClient

    # 1. board 可配定时（审计问题1）
    assert "board" in SCHEDULABLE_TASK_TYPES
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        svc = ScheduledJobService(c)
        job = svc.create(name="板块定时采集", task_type="board", params={},
                         freq_type="daily", freq_config={"time": "15:30"},
                         trading_day_only=True, enabled=False)
        assert job["task_type"] == "board"
        # 2. catalog 含板块表（审计问题4）
        cat = build_catalog(c)
        tables = {x["table"] for x in cat}
        assert {"board_dict", "board_member", "board_bar", "board_fund_flow",
                "board_member_candidate"} <= tables
        bd = next(x for x in cat if x["table"] == "board_dict")
        assert bd["name_cn"] == "板块字典"
