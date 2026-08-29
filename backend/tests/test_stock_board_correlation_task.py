"""个股走势关联板块 T5：异步任务、互斥、取消、统计与动态调度。"""

from __future__ import annotations

import threading
import time
from datetime import date
from types import SimpleNamespace

import pytest

from backend.scheduler.scheduler import SCHEDULABLE_TASK_TYPES, ScheduledJobService
from backend.services import async_task as async_task_module
from backend.services.async_task import (
    _HANDLERS,
    TASK_CAPABILITIES,
    TASK_TYPES,
    WRITE_TASK_TYPES,
    AsyncTaskService,
    ConcurrentTaskError,
    _h_stock_board_correlation,
)
from backend.services.stock_board_correlation import (
    CorrelationRunResult,
    normalize_correlation_task_params,
)
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


@pytest.fixture
def market(tmp_path):
    with DuckDBClient(db_path=tmp_path / "task-market.duckdb") as client:
        init_db(client)
        client.execute(
            "INSERT INTO stock_basic (code,name,board,list_date) VALUES "
            "('600000.SH','甲','主板','2020-01-01'),"
            "('300001.SZ','乙','创业板','2020-01-01'),"
            "('830001.BJ','北交','北交所','2020-01-01')"
        )
        yield client


class _Ctx:
    def __init__(self):
        self.logs: list[tuple[str, str]] = []
        self.progresses: list[tuple[float, str]] = []
        self.cancel_checks = 0

    def log(self, message, level="info"):
        self.logs.append((message, level))

    def progress(self, value, message):
        self.progresses.append((value, message))

    def check_cancel(self):
        self.cancel_checks += 1


def _wait(svc: AsyncTaskService, task_id: str, timeout: float = 3.0) -> dict:
    started = time.time()
    while time.time() - started < timeout:
        task = svc.get(task_id)
        if task and task["status"] in ("done", "failed", "interrupted"):
            return task
        time.sleep(0.02)
    raise AssertionError("任务等待超时")


def test_task_type_capability_handler_mutex_and_schedule_registration(market):
    assert "stock_board_correlation" in TASK_TYPES
    assert "stock_board_correlation" in WRITE_TASK_TYPES
    assert "stock_board_correlation" in SCHEDULABLE_TASK_TYPES
    assert _HANDLERS["stock_board_correlation"] is _h_stock_board_correlation
    capability = TASK_CAPABILITIES["stock_board_correlation"]
    assert capability == {
        "can_cancel": True,
        "can_resume": False,
        "cancel_mode": "checkpoint",
        "resume_granularity": None,
        "cancel_message": "会在当前计算阶段或原子切换开始前停止；原子切换开始后不中断",
    }
    assert market.query_df(
        "SELECT count(*) AS n FROM scheduled_job "
        "WHERE task_type='stock_board_correlation'"
    ).iloc[0]["n"] == 0


def test_params_normalize_text_deduplicate_defaults_and_validate_scope(market):
    normalized = normalize_correlation_task_params(
        {"codes": " 600000.sh,300001.sz,600000.SH ", "force": True},
        client=market,
    )
    assert normalized == {
        "codes": ["600000.SH", "300001.SZ"],
        "force": True,
    }
    assert normalize_correlation_task_params({}) == {"codes": [], "force": False}
    assert normalize_correlation_task_params({"codes": " ,  "}) == {
        "codes": [],
        "force": False,
    }

    with pytest.raises(ValueError, match="force 必须是布尔值"):
        normalize_correlation_task_params({"force": 1})
    with pytest.raises(ValueError, match="不支持参数"):
        normalize_correlation_task_params({"window": 60})
    with pytest.raises(ValueError, match="codes 必须是数组或逗号分隔文本"):
        normalize_correlation_task_params({"codes": 600000})
    with pytest.raises(ValueError, match="未知股票"):
        normalize_correlation_task_params({"codes": ["600404.SH"]}, client=market)
    with pytest.raises(ValueError, match="格式非法"):
        normalize_correlation_task_params({"codes": ["830001.BJ"]}, client=market)


def test_manual_create_normalizes_params_and_shares_write_slot(market, monkeypatch):
    monkeypatch.setattr(AsyncTaskService, "_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AsyncTaskService, "_audit_task", staticmethod(lambda **kwargs: None))
    service = AsyncTaskService(market)

    task_id = service.create(
        "stock_board_correlation",
        {"codes": "600000.sh,600000.SH", "force": False},
    )
    task = service.get(task_id)
    assert task["params"] == {"codes": ["600000.SH"], "force": False}
    with pytest.raises(ConcurrentTaskError):
        service.create("board", {})


def test_handler_emits_fixed_phases_and_complete_result(monkeypatch):
    ctx = _Ctx()
    fake_client = SimpleNamespace()
    monkeypatch.setattr(async_task_module, "get_client", lambda: fake_client)

    from backend.services import stock_board_correlation as service_module

    monkeypatch.setattr(service_module, "get_client", lambda: fake_client)
    monkeypatch.setattr(
        service_module.StockBoardCorrelationService,
        "resolve_target_date",
        lambda self: date(2026, 8, 29),
    )
    monkeypatch.setattr(
        service_module.StockBoardCorrelationService,
        "resolve_target_codes",
        lambda self, target_date, codes: (["600000.SH", "000001.SZ"], True),
    )

    def fake_compute(self, codes, **kwargs):
        for phase in (
            "read_candidates",
            "load_prices",
            "calculate",
            "validate",
            "switch",
        ):
            kwargs["phase_callback"](phase)
            kwargs["cancel_check"]()
        return CorrelationRunResult(
            target_date=date(2026, 8, 29),
            target_count=2,
            candidate_count=5,
            industry_champion_count=2,
            concept_champion_count=1,
            empty_result_count=0,
            skipped_count=0,
            benchmark_counts={"000001.SH": 1, "399001.SZ": 1},
            fallback_count=1,
            calculation_seconds=0.1234567,
            write_seconds=0.0123456,
            switched=True,
        )

    monkeypatch.setattr(
        service_module.StockBoardCorrelationService, "compute_and_replace", fake_compute
    )
    result = _h_stock_board_correlation({"force": True}, ctx)

    assert [message for message, _ in ctx.logs] == [
        "阶段 1/5：读取候选",
        "阶段 2/5：加载行情",
        "阶段 3/5：批量计算",
        "阶段 4/5：结果校验",
        "阶段 5/5：原子切换",
    ]
    assert ctx.cancel_checks == 6
    assert result == {
        "ok": True,
        "message": "个股走势关联板块计算完成：2 只",
        "target_date": "2026-08-29",
        "target_stock_count": 2,
        "candidate_relation_count": 5,
        "industry_champion_count": 2,
        "concept_champion_count": 1,
        "empty_result_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "benchmark_counts": {"000001.SH": 1, "399001.SZ": 1},
        "fallback_count": 1,
        "calculation_seconds": 0.123457,
        "write_seconds": 0.012346,
        "switched": True,
    }


def test_expected_integrity_failure_returns_diagnostic_result(monkeypatch):
    ctx = _Ctx()
    fake_client = SimpleNamespace()
    monkeypatch.setattr(async_task_module, "get_client", lambda: fake_client)
    from backend.services import stock_board_correlation as service_module

    monkeypatch.setattr(service_module, "get_client", lambda: fake_client)
    monkeypatch.setattr(
        service_module.StockBoardCorrelationService,
        "resolve_target_date",
        lambda self: date(2026, 8, 29),
    )
    monkeypatch.setattr(
        service_module.StockBoardCorrelationService,
        "resolve_target_codes",
        lambda self, target_date, codes: (["600000.SH", "000001.SZ"], True),
    )

    def fail_compute(self, *args, **kwargs):
        raise service_module.CorrelationInputError("上证指数样本不足")

    monkeypatch.setattr(
        service_module.StockBoardCorrelationService, "compute_and_replace", fail_compute
    )
    result = _h_stock_board_correlation({}, ctx)

    assert result["ok"] is False
    assert result["message"] == "上证指数样本不足"
    assert result["target_date"] == "2026-08-29"
    assert result["target_stock_count"] == 2
    assert result["failed_count"] == 1
    assert result["switched"] is False
    assert ctx.logs[-1] == ("完整性校验失败：上证指数样本不足", "error")


def test_cancelled_task_is_not_marked_resumable(market, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def cancellable_handler(params, ctx):
        started.set()
        assert release.wait(timeout=2)
        ctx.check_cancel()
        raise AssertionError("取消检查应当抛出")

    monkeypatch.setitem(_HANDLERS, "stock_board_correlation", cancellable_handler)
    monkeypatch.setattr(AsyncTaskService, "_audit_task", staticmethod(lambda **kwargs: None))
    service = AsyncTaskService(market)
    task_id = service.create("stock_board_correlation", {})
    assert started.wait(timeout=2)
    assert service.cancel(task_id) is True
    release.set()

    task = _wait(service, task_id)
    assert task["status"] == "interrupted"
    assert task["message"] == "已终止（不支持续跑，重新执行将完整计算）"
    with pytest.raises(ValueError, match="不支持继续或重试"):
        service.resume(task_id)


def test_restart_reconcile_uses_capability_aware_message(market):
    market.execute(
        "INSERT INTO async_task "
        "(id,task_type,params,status,progress,message,created_at,updated_at) VALUES "
        "('task_corr_restart','stock_board_correlation','{}','running',0.5,'运行中',now(),now()),"
        "('task_update_restart','update','{}','running',0.5,'运行中',now(),now())"
    )

    result = AsyncTaskService(market).reconcile()

    assert result["interrupted"] == 2
    messages = market.query_df(
        "SELECT id,message FROM async_task ORDER BY id"
    ).set_index("id")["message"].to_dict()
    assert messages == {
        "task_corr_restart": "服务重启中断，不支持续跑，请重新执行",
        "task_update_restart": "服务重启中断，可续跑",
    }


def test_schedule_crud_normalizes_params_and_run_now_preserves_source(market, monkeypatch):
    service = ScheduledJobService(market)
    job = service.create(
        name="走势板块定时计算",
        task_type="stock_board_correlation",
        params={"codes": "600000.sh", "force": True},
        freq_type="daily",
        freq_config={"time": "16:30"},
        trading_day_only=True,
        enabled=False,
        retry_config={
            "enabled": True,
            "condition": "failure",
            "delay": {"value": 5, "unit": "minute"},
            "max_retries": 2,
        },
    )
    assert job["params"] == {"codes": ["600000.SH"], "force": True}
    assert job["retry_config"]["max_retries"] == 2

    updated = service.update(
        job["id"],
        name=job["name"],
        task_type=job["task_type"],
        params={"codes": [], "force": False},
        freq_type="weekly",
        freq_config={"weekdays": [1, 3, 5], "time": "16:30"},
        trading_day_only=True,
        enabled=False,
    )
    assert updated["params"] == {"codes": [], "force": False}

    captured = {}

    def fake_create(self, task_type, params, **kwargs):
        captured.update({"task_type": task_type, "params": params, **kwargs})
        return "task_corr_now"

    monkeypatch.setattr(AsyncTaskService, "create", fake_create)
    assert service.run_now(job["id"]) == "task_corr_now"
    assert captured == {
        "task_type": "stock_board_correlation",
        "params": {"codes": [], "force": False},
        "trigger_source": "manual",
        "job_id": job["id"],
        "job_name": job["name"],
    }

    service.delete(job["id"])
    assert service.get(job["id"]) is None
