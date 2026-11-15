"""一键流程 + 定时任务调度测试。"""

from __future__ import annotations

import threading
import time
from datetime import date

import pandas as pd
import pytest

from backend.common.timeutil import shanghai_now_naive
from backend.scheduler.scheduler import (
    ScheduledJobService,
    compile_trigger,
    dispatch_due_events,
    enqueue_terminal_events,
    freq_text,
)
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


def test_scheduled_job_server_pagination_sort_and_options():
    """调度主表在存储层分页排序；依赖候选使用独立轻量查询。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        svc = ScheduledJobService(c)
        for name, freq_type, freq_config in (
            ("C周任务", "weekly", {"weekdays": [1, 3], "time": "09:00"}),
            ("B日任务乙", "daily", {"time": "15:00"}),
            ("D月任务", "monthly", {"day": 2, "time": "08:00"}),
            ("A日任务甲", "daily", {"time": "09:00"}),
            ("ECron任务", "cron", {"cron": "0 8 * * 1-5"}),
        ):
            svc.create(
                name=name, task_type="verify", params={}, freq_type=freq_type,
                freq_config=freq_config, trading_day_only=False, enabled=False,
            )

        first = svc.list_page(page=1, size=2, sort_by="name", sort_order="asc")
        second = svc.list_page(page=2, size=2, sort_by="name", sort_order="asc")
        assert first["total"] == 5 and first["page"] == 1 and first["size"] == 2
        assert [row["name"] for row in first["jobs"]] == ["A日任务甲", "B日任务乙"]
        assert [row["name"] for row in second["jobs"]] == ["C周任务", "D月任务"]

        by_frequency = svc.list_page(page=1, size=5, sort_by="freq", sort_order="asc")
        assert [row["name"] for row in by_frequency["jobs"]] == [
            "A日任务甲", "B日任务乙", "C周任务", "D月任务", "ECron任务",
        ]
        assert svc.list_options(query="日任务", limit=10) == [
            {"id": by_frequency["jobs"][0]["id"], "name": "A日任务甲", "enabled": False},
            {"id": by_frequency["jobs"][1]["id"], "name": "B日任务乙", "enabled": False},
        ]


def test_scheduled_dependency_validation_and_cycle_rejected():
    """兼容单上游入参，普通关系拒绝环路，引用中的上游不能删除。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        svc = ScheduledJobService(c)
        root = svc.create(
            name="增量更新", task_type="recompute", params={}, freq_type="daily",
            freq_config={"time": "16:00"}, trading_day_only=False, enabled=False)
        child = svc.create(
            name="更新后质检", task_type="checkup", params={}, freq_type=None, freq_config={},
            trigger_mode="dependency", dependency_job_id=root["id"],
            dependency_condition="completion",
            dependency_delay={"value": 1, "unit": "minute"},
            retry_config={"enabled": True, "condition": "failure",
                          "delay": {"value": 5, "unit": "minute"}, "max_retries": 3},
            trading_day_only=False, enabled=False)
        assert child["trigger_text"] == "增量更新·完成后，延迟1分钟"
        assert child["retry_config"]["max_retries"] == 3
        with pytest.raises(ValueError, match="循环依赖"):
            svc.update(
                root["id"], name=root["name"], task_type=root["task_type"], params={},
                freq_type=None, freq_config={}, trigger_mode="dependency",
                dependency_job_id=child["id"], dependency_condition="success",
                dependency_delay={"value": 0, "unit": "second"}, retry_config=None,
                trading_day_only=False, enabled=False)
        with pytest.raises(ValueError, match="仍被以下任务依赖"):
            svc.delete(root["id"])


def test_schedule_delay_and_retry_count_reject_decimals():
    """延迟和最大重试次数声明为整数，不得把 API 小数静默截断。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        svc = ScheduledJobService(c)
        root = svc.create(
            name="上游", task_type="recompute", params={}, freq_type="daily",
            freq_config={"time": "16:00"}, trading_day_only=False, enabled=False)
        with pytest.raises(ValueError, match="依赖延迟须为整数"):
            svc.create(
                name="小数延迟", task_type="checkup", params={}, freq_type=None, freq_config={},
                trigger_mode="dependency", dependency_job_id=root["id"],
                dependency_condition="success", dependency_delay={"value": 1.5, "unit": "minute"},
                trading_day_only=False, enabled=False)
        with pytest.raises(ValueError, match="最大重试次数须为整数"):
            svc.create(
                name="小数重试", task_type="checkup", params={}, freq_type="daily",
                freq_config={"time": "17:00"},
                retry_config={"enabled": True, "condition": "failure",
                              "delay": {"value": 1, "unit": "minute"}, "max_retries": 1.5},
                trading_day_only=False, enabled=False)


def _insert_terminal_task(c, *, tid: str, job_id: str, status: str,
                          retry_count: int = 0, attempt: int = 1):

    now = shanghai_now_naive()
    c.execute(
        "INSERT INTO async_task "
        "(id,task_type,params,status,progress,message,trigger_source,job_id,job_name,chain_id,"
        "retry_count,execution_attempt,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [tid, "recompute", "{}", status, 1.0, status, "manual", job_id, "上游", tid,
         retry_count, attempt, now, now])


def test_terminal_events_match_result_and_retry_limit():
    """完成不包含 interrupted；失败依赖与自身重试均幂等，达到上限留 exhausted 记录。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        svc = ScheduledJobService(c)
        root = svc.create(
            name="上游", task_type="recompute", params={}, freq_type="daily",
            freq_config={"time": "16:00"},
            retry_config={"enabled": True, "condition": "failure",
                          "delay": {"value": 0, "unit": "second"}, "max_retries": 1},
            trading_day_only=False, enabled=False)
        c.execute("UPDATE scheduled_job SET enabled=true WHERE id=?", [root["id"]])
        child = svc.create(
            name="失败处理", task_type="checkup", params={}, freq_type=None, freq_config={},
            trigger_mode="dependency", dependency_job_id=root["id"],
            dependency_condition="failure", dependency_delay={"value": 0, "unit": "second"},
            trading_day_only=False, enabled=True)
        _insert_terminal_task(c, tid="failed_1", job_id=root["id"], status="failed")
        with c.transaction():
            assert enqueue_terminal_events("failed_1", client=c) == 2
            enqueue_terminal_events("failed_1", client=c)  # 同一尝试重复收尾不得重复事件
        events = c.query_df(
            "SELECT trigger_kind,status,retry_count,target_job_id FROM scheduled_trigger_event "
            "ORDER BY trigger_kind")
        assert len(events) == 2
        assert set(events["trigger_kind"]) == {"dependency", "retry"}
        assert child["id"] in set(events["target_job_id"])

        _insert_terminal_task(
            c, tid="failed_retry", job_id=root["id"], status="failed", retry_count=1)
        with c.transaction():
            enqueue_terminal_events("failed_retry", client=c)
        exhausted = c.query_df(
            "SELECT status,message FROM scheduled_trigger_event "
            "WHERE source_task_id='failed_retry' AND trigger_kind='retry'").iloc[0]
        assert exhausted["status"] == "exhausted"
        assert "最大重试次数" in exhausted["message"]

        _insert_terminal_task(c, tid="stopped", job_id=root["id"], status="interrupted")
        with c.transaction():
            assert enqueue_terminal_events("stopped", client=c) == 0


def test_one_upstream_fans_out_independent_events(monkeypatch):
    """同一上游命中多个下游时分别留事件、规则快照和实际分发时间。"""
    from backend.scheduler import scheduler as scheduler_module
    from backend.services.async_task import AsyncTaskService

    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        svc = ScheduledJobService(c)
        root = svc.create(
            name="上游", task_type="recompute", params={}, freq_type="daily",
            freq_config={"time": "16:00"}, trading_day_only=False, enabled=False)
        child_ids = []
        for name in ("下游一", "下游二"):
            child = svc.create(
                name=name, task_type="checkup", params={}, freq_type=None, freq_config={},
                trigger_mode="dependency", dependency_job_id=root["id"],
                dependency_condition="success", dependency_delay={"value": 0, "unit": "second"},
                trading_day_only=False, enabled=True)
            child_ids.append(child["id"])
        _insert_terminal_task(c, tid="done_fanout", job_id=root["id"], status="done")
        with c.transaction():
            assert enqueue_terminal_events("done_fanout", client=c) == 2
        monkeypatch.setattr(scheduler_module, "get_client", lambda: c)
        created = []
        monkeypatch.setattr(
            AsyncTaskService, "create",
            lambda self, *args, **kwargs: created.append(kwargs["job_id"]) or f"task_{len(created)}")
        assert dispatch_due_events() == 2
        events = c.query_df(
            "SELECT target_job_id,trigger_condition,status,dispatched_at "
            "FROM scheduled_trigger_event ORDER BY target_job_id")
        assert set(events["target_job_id"]) == set(child_ids)
        assert set(events["trigger_condition"]) == {"success"}
        assert set(events["status"]) == {"dispatched"}
        assert events["dispatched_at"].notna().all()
        assert set(created) == set(child_ids)
        c.execute(
            "UPDATE scheduled_trigger_event SET trigger_condition=NULL WHERE target_job_id=?",
            [child_ids[0]])
        historical = svc.list_events(child_ids[0])
        assert historical[0]["trigger_condition"] is None
        assert historical[0]["dispatched_at"] is not None


def test_write_task_creation_serializes_busy_check_and_insert(monkeypatch):
    """并发创建写任务时 busy 检查不得并行，最终只能落一条 pending。"""
    from backend.services.async_task import AsyncTaskService, ConcurrentTaskError

    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        services = [AsyncTaskService(c), AsyncTaskService(c)]
        original = AsyncTaskService._running_write
        active = 0
        max_active = 0
        active_lock = threading.Lock()

        def observed_running_write(self):
            nonlocal active, max_active
            with active_lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            try:
                return original(self)
            finally:
                with active_lock:
                    active -= 1

        monkeypatch.setattr(AsyncTaskService, "_running_write", observed_running_write)
        monkeypatch.setattr(AsyncTaskService, "_run", lambda *args, **kwargs: None)
        monkeypatch.setattr(AsyncTaskService, "_audit_task", staticmethod(lambda **kwargs: None))
        start = threading.Barrier(2)
        outcomes = []

        def create(service):
            start.wait(timeout=2)
            try:
                outcomes.append(service.create("update"))
            except ConcurrentTaskError:
                outcomes.append("busy")

        threads = [threading.Thread(target=create, args=(service,)) for service in services]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        assert all(not thread.is_alive() for thread in threads)
        assert max_active == 1
        assert outcomes.count("busy") == 1
        assert int(c.query_df(
            "SELECT count(*) AS n FROM async_task WHERE status='pending'").iloc[0]["n"]) == 1


def test_dependency_dispatch_waits_for_write_slot(monkeypatch):
    """依赖事件遇写任务互斥不跳过；下一轮资源可用后只创建一个下游任务。"""
    from backend.scheduler import scheduler as scheduler_module
    from backend.services.async_task import AsyncTaskService, ConcurrentTaskError

    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        svc = ScheduledJobService(c)
        root = svc.create(
            name="上游", task_type="recompute", params={}, freq_type="daily",
            freq_config={"time": "16:00"}, trading_day_only=False, enabled=False)
        child = svc.create(
            name="下游", task_type="checkup", params={}, freq_type=None, freq_config={},
            trigger_mode="dependency", dependency_job_id=root["id"],
            dependency_condition="success", dependency_delay={"value": 0, "unit": "second"},
            trading_day_only=False, enabled=True)
        _insert_terminal_task(c, tid="done_1", job_id=root["id"], status="done")
        with c.transaction():
            enqueue_terminal_events("done_1", client=c)
        monkeypatch.setattr(scheduler_module, "get_client", lambda: c)
        monkeypatch.setattr(
            AsyncTaskService, "create",
            lambda self, *args, **kwargs: (_ for _ in ()).throw(
                ConcurrentTaskError("update", "task_busy")))
        assert dispatch_due_events() == 0
        waiting = c.query_df("SELECT status FROM scheduled_trigger_event").iloc[0]["status"]
        assert waiting == "waiting"

        created = []
        monkeypatch.setattr(
            AsyncTaskService, "create",
            lambda self, *args, **kwargs: created.append(kwargs["trigger_event_id"]) or "task_child")
        assert dispatch_due_events() == 1
        event = c.query_df("SELECT status,task_id,target_job_id FROM scheduled_trigger_event").iloc[0]
        assert event["status"] == "dispatched" and event["task_id"] == "task_child"
        assert event["target_job_id"] == child["id"] and len(created) == 1


def test_dispatch_and_disable_cannot_overwrite_each_other(monkeypatch):
    """分发先认领时停用须等待；完成后不得把 dispatched 事件改为 cancelled。"""
    from backend.scheduler import scheduler as scheduler_module
    from backend.services.async_task import AsyncTaskService

    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        svc = ScheduledJobService(c)
        root = svc.create(
            name="上游", task_type="recompute", params={}, freq_type="daily",
            freq_config={"time": "16:00"}, trading_day_only=False, enabled=False)
        child = svc.create(
            name="下游", task_type="checkup", params={}, freq_type=None, freq_config={},
            trigger_mode="dependency", dependency_job_id=root["id"],
            dependency_condition="success", dependency_delay={"value": 0, "unit": "second"},
            trading_day_only=False, enabled=True)
        _insert_terminal_task(c, tid="done_disable_race", job_id=root["id"], status="done")
        with c.transaction():
            enqueue_terminal_events("done_disable_race", client=c)
        monkeypatch.setattr(scheduler_module, "get_client", lambda: c)
        creating = threading.Event()
        release = threading.Event()

        def slow_create(self, *args, **kwargs):
            creating.set()
            assert release.wait(timeout=2)
            return "task_claimed"

        monkeypatch.setattr(AsyncTaskService, "create", slow_create)
        dispatch_thread = threading.Thread(target=dispatch_due_events)
        dispatch_thread.start()
        assert creating.wait(timeout=2)
        disable_thread = threading.Thread(target=svc.set_enabled, args=(child["id"], False))
        disable_thread.start()
        time.sleep(0.05)
        assert disable_thread.is_alive()  # 分发持有事件锁，停用不能插入 claim 与落库之间。
        release.set()
        dispatch_thread.join(timeout=3)
        disable_thread.join(timeout=3)
        assert not dispatch_thread.is_alive() and not disable_thread.is_alive()
        event = c.query_df(
            "SELECT status,task_id,dispatched_at FROM scheduled_trigger_event").iloc[0]
        assert event["status"] == "dispatched"
        assert event["task_id"] == "task_claimed"
        assert pd.notna(event["dispatched_at"])
        assert svc.get(child["id"])["enabled"] is False


def test_dependency_create_and_upstream_delete_share_relationship_lock(monkeypatch):
    """新建下游与删除上游不能穿过引用检查，最终不得留下悬空依赖。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        svc = ScheduledJobService(c)
        root = svc.create(
            name="上游", task_type="recompute", params={}, freq_type="daily",
            freq_config={"time": "16:00"}, trading_day_only=False, enabled=False)
        original_validate = svc._validate
        validating = threading.Event()
        release = threading.Event()

        def slow_validate(*args, **kwargs):
            validating.set()
            assert release.wait(timeout=2)
            return original_validate(*args, **kwargs)

        monkeypatch.setattr(svc, "_validate", slow_validate)
        created = []
        delete_errors = []

        def create_child():
            created.append(svc.create(
                name="下游", task_type="checkup", params={}, freq_type=None, freq_config={},
                trigger_mode="dependency", dependency_job_id=root["id"],
                dependency_condition="success", dependency_delay={"value": 0, "unit": "second"},
                trading_day_only=False, enabled=False))

        def delete_root():
            try:
                svc.delete(root["id"])
            except ValueError as exc:
                delete_errors.append(str(exc))

        create_thread = threading.Thread(target=create_child)
        create_thread.start()
        assert validating.wait(timeout=2)
        delete_thread = threading.Thread(target=delete_root)
        delete_thread.start()
        time.sleep(0.05)
        assert delete_thread.is_alive()
        release.set()
        create_thread.join(timeout=3)
        delete_thread.join(timeout=3)
        assert len(created) == 1
        assert delete_errors and "仍被以下任务依赖" in delete_errors[0]
        assert svc.get(root["id"]) is not None
        assert created[0]["dependency_job_id"] == root["id"]


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

    def fake_ingest_board(self, ctx=None, board_type=None, board_codes=None, mode="update", target_end=None):
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

    def fake_ingest_board(self, ctx=None, board_type=None, board_codes=None, mode="update", target_end=None):
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

    def boom_board(self, ctx=None, board_type=None, board_codes=None, mode="update", target_end=None):
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


def test_pipeline_board_partial_result_continues_quality(tmp_path, monkeypatch):
    """板块服务未抛异常但返回 failed 列表时，流水线仍必须标失败并继续质检。"""
    from backend.services import ingest as ingest_mod
    from backend.services.data_report import DataIntegrityReport

    monkeypatch.setattr(
        ingest_mod.IngestionService, "ingest_board",
        lambda self, ctx=None, board_type=None, board_codes=None, mode="update": {
            "ok": False, "failed": ["bar:309121: timeout"],
        }, raising=True)
    monkeypatch.setattr(ingest_mod.IngestionService, "__init__",
                        lambda self, source=None: None, raising=True)
    monkeypatch.setattr(DataIntegrityReport, "scan_quality_issues",
                        lambda self: {"abnormal_change_rows": 0}, raising=True)
    monkeypatch.setattr(DataIntegrityReport, "scan_board_quality",
                        lambda self: {"index_gap": 0}, raising=True)
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        _seed_market_with_latest(c)
        res = DailyPipeline(c).run(skip_update=True)
    steps = {s["step"]: s["status"] for s in res["steps"]}
    assert steps == {"板块采集": "failed", "数据质检": "ok"}
    assert res["ok"] is False


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


def test_pipeline_quality_includes_market_index_and_board_scans(tmp_path, monkeypatch):
    """daily 质检步骤同时跑市场指数与板块扫描，避免出现孤立质检能力。"""
    from backend.services import ingest as ingest_mod
    from backend.services.data_report import DataIntegrityReport
    from backend.services.pipeline import DailyPipeline

    called = {"market_index": 0, "board": 0, "base": 0}

    def fake_scan_market_index(self):
        called["market_index"] += 1
        return {"index_gap": 1}

    def fake_scan_board(self):
        called["board"] += 1
        return {"index_gap": 2}

    monkeypatch.setattr(DataIntegrityReport, "scan_board_quality", fake_scan_board, raising=True)
    monkeypatch.setattr(
        DataIntegrityReport, "scan_market_index_quality", fake_scan_market_index, raising=True,
    )
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
        assert called["market_index"] == 1  # 配置市场指数扫描已接线
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
        assert job["params"] == {"mode": "update"}
        scoped = svc.create(
            name="概念指数资金流", task_type="board",
            params={"mode": "update", "board_type": "concept", "only": ["bar", "fund"],
                    "force_members": False},
            freq_type="daily", freq_config={"time": "16:00"},
            trading_day_only=True, enabled=False)
        assert scoped["params"] == {
            "mode": "update", "board_type": "concept", "only": ["bar", "fund"],
            "force_members": False,
        }
        forced = svc.create(
            name="强制板块当日", task_type="board",
            params={"mode": "update", "only": ["bar"], "force_current_day": True},
            freq_type="daily", freq_config={"time": "16:10"},
            trading_day_only=False, enabled=False)
        assert forced["params"]["force_current_day"] is True
        with pytest.raises(ValueError, match="update/backfill"):
            svc.create(name="非法板块模式", task_type="board", params={"mode": "daily"},
                       freq_type="daily", freq_config={"time": "15:30"},
                       trading_day_only=True, enabled=False)
        with pytest.raises(ValueError, match="至少选择一项"):
            svc.create(name="空板块阶段", task_type="board", params={"only": []},
                       freq_type="daily", freq_config={"time": "15:30"},
                       trading_day_only=True, enabled=False)
        with pytest.raises(ValueError, match="未知板块采集步骤"):
            svc.create(name="非法板块阶段", task_type="board", params={"only": ["price"]},
                       freq_type="daily", freq_config={"time": "15:30"},
                       trading_day_only=True, enabled=False)
        with pytest.raises(ValueError, match="只有板块增量采集"):
            svc.create(
                name="非法强制回填", task_type="board",
                params={"mode": "backfill", "force_current_day": True},
                freq_type="daily", freq_config={"time": "15:30"},
                trading_day_only=False, enabled=False)
        # 2. catalog 含板块表（审计问题4）
        cat = build_catalog(c)
        tables = {x["table"] for x in cat}
        assert {"board_dict", "board_member", "board_bar", "board_fund_flow"} <= tables
        bd = next(x for x in cat if x["table"] == "board_dict")
        assert bd["name_cn"] == "板块字典"


def test_source_status_includes_board_source(monkeypatch):
    """数据源健康列表把同花顺标为独立板块源，不混入行情主备源。"""
    from backend.config.settings import Settings
    from backend.services import data_sources, ths_cookie_status

    class _Repo:
        def list(self, sources):
            return {}

    monkeypatch.setattr(
        data_sources, "get_effective_settings",
        lambda: Settings(datasource={"socket_timeout_sec": 3}),
    )
    monkeypatch.setattr(ths_cookie_status, "ths_cookie_status", lambda **_kwargs: {})
    result = data_sources.source_status(do_ping=False, repo=_Repo())
    assert all(item["timeout_sec"] == 3 for item in result["sources"])
    roles = {item["source"]: item["role"] for item in result["sources"]}
    assert roles == {"akshare": "primary", "baostock": "fallback", "ths_board": "board",
                     "intraday_sina": "intraday",
                     "intraday_ths": "intraday", "eastmoney_capital": "reference", "sse_capital": "reference"}


def test_source_status_persists_latest_probe_and_keeps_last_success(monkeypatch):
    """失败测试更新最近状态和原因，但保留此前成功时间。"""
    from backend.config.settings import Settings
    from backend.services import data_sources, ths_cookie_status

    class _Repo:
        def __init__(self):
            self.records = {
                "akshare": {
                    "up": True,
                    "last_test_at": "2026-09-19T18:00:00+08:00",
                    "last_success_at": "2026-09-19T18:00:00+08:00",
                    "failure_reason": None,
                }
            }

        def list(self, sources):
            return {name: self.records[name] for name in sources if name in self.records}

        def record(self, source, *, up, tested_at, failure_reason):
            previous = self.records.get(source, {})
            self.records[source] = {
                "up": up,
                "last_test_at": tested_at.isoformat(timespec="seconds"),
                "last_success_at": (
                    tested_at.isoformat(timespec="seconds")
                    if up else previous.get("last_success_at")
                ),
                "failure_reason": failure_reason,
            }

    repo = _Repo()
    monkeypatch.setattr(
        data_sources,
        "get_effective_settings",
        lambda: Settings(datasource={"socket_timeout_sec": 3}),
    )
    monkeypatch.setattr(ths_cookie_status, "ths_cookie_status", lambda **_kwargs: {})
    results = iter([(False, "连接超时"), (True, None), (True, None), (True, None), (False, "分钟源连接失败"), (True, None), (True, None), (True, None)])
    monkeypatch.setattr(data_sources, "_ping", lambda *_args: next(results))

    tested = data_sources.source_status(do_ping=True, repo=repo)
    akshare = next(item for item in tested["sources"] if item["source"] == "akshare")
    assert akshare["up"] is False
    assert akshare["failure_reason"] == "连接超时"
    assert akshare["last_success_at"] == "2026-09-19T18:00:00+08:00"

    loaded = data_sources.source_status(do_ping=False, repo=repo)
    persisted = next(item for item in loaded["sources"] if item["source"] == "akshare")
    assert persisted["up"] is False
    assert persisted["last_test_at"] == akshare["last_test_at"]
    assert persisted["last_success_at"] == "2026-09-19T18:00:00+08:00"


def test_partial_daily_update_still_runs_quality_and_reports_failure(monkeypatch):
    from types import SimpleNamespace

    from backend.services import data_report
    seen = []
    monkeypatch.setattr('backend.services.IngestionService', lambda: SimpleNamespace(
        update=lambda **kw: {'ok':10,'fail':0,'stage_failures':{'valuation':'timeout'}}))
    monkeypatch.setattr(data_report, 'DataIntegrityReport', lambda c: SimpleNamespace(
        scan_quality_issues=lambda: seen.append('quality') or {},
        scan_market_index_quality=dict, scan_board_quality=dict))
    with DuckDBClient(':memory:') as c:
        init_db(c)
        c.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES ('A.SH','2026-01-05',10)")
        result = DailyPipeline(c).run(board=False)
        assert result['ok'] is False and seen == ['quality']
        assert [s['status'] for s in result['steps']] == ['failed','ok']


def test_known_unavailable_repair_stops_self_retry_but_keeps_failure_dependents():
    """来源不可覆盖不是技术故障；正常失败依赖仍触发，避免改变普通依赖语义。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        svc = ScheduledJobService(c)
        job = svc.create(
            name="分时恢复", task_type="fix", params={"issue_type": "intraday_partial"},
            freq_type="daily", freq_config={"time": "16:00"}, trading_day_only=False,
            retry_config={"enabled": True, "condition": "failure", "max_retries": 2,
                          "delay": {"value": 1, "unit": "second"}}, enabled=False,
        )
        c.execute("UPDATE scheduled_job SET enabled=true WHERE id=?", [job["id"]])
        svc.create(
            name="失败复检", task_type="checkup", params={}, freq_type=None, freq_config={},
            trigger_mode="dependency", dependency_job_id=job["id"],
            dependency_condition="failure", dependency_delay={"value": 0, "unit": "second"},
            trading_day_only=False, enabled=True,
        )
        _insert_terminal_task(c, tid="unavailable_intraday", job_id=job["id"], status="failed")
        c.execute("UPDATE async_task SET result=? WHERE id='unavailable_intraday'",
                  ['{"retryable":false,"unavailable":1,"technical_failure":0}'])
        assert enqueue_terminal_events("unavailable_intraday", client=c) == 1
        assert c.query_df("SELECT trigger_kind FROM scheduled_trigger_event").trigger_kind.tolist() == ["dependency"]


@pytest.mark.parametrize("source_timezone", ["UTC", "America/New_York", "Asia/Shanghai", None])
def test_deferred_intraday_retry_respects_source_recheck_time(monkeypatch, source_timezone):
    """用户已启用的自身重试不能在来源复查时间前空跑，不影响普通失败依赖。"""
    import json
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from backend.scheduler import scheduler

    # 业务时点固定为北京时间；不随执行测试的主机时区改变预期。
    now = datetime(2026, 11, 16, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    monkeypatch.setattr(scheduler, "shanghai_now_naive", lambda: now)
    expected = now + timedelta(minutes=15)
    due = expected if source_timezone is None else expected.replace(
        tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(ZoneInfo(source_timezone))

    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        svc = ScheduledJobService(c)
        job = svc.create(
            name="分时等待来源", task_type="fix", params={"issue_type": "intraday_partial"},
            freq_type="daily", freq_config={"time": "16:00"}, trading_day_only=False,
            retry_config={"enabled": True, "condition": "failure", "max_retries": 2,
                          "delay": {"value": 1, "unit": "second"}}, enabled=False,
        )
        c.execute("UPDATE scheduled_job SET enabled=true WHERE id=?", [job["id"]])
        _insert_terminal_task(c, tid="deferred_intraday", job_id=job["id"], status="failed")
        c.execute("UPDATE async_task SET result=? WHERE id='deferred_intraday'",
                  [json.dumps({"retryable": True, "next_retry_at": due.isoformat()})])
        assert enqueue_terminal_events("deferred_intraday", client=c) == 1
        event = c.query_df("SELECT due_at FROM scheduled_trigger_event").iloc[0, 0]
        assert pd.Timestamp(event) == pd.Timestamp(expected)
