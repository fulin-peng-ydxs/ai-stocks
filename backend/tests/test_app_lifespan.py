"""ASGI 生命周期回归：保持启动门禁、恢复顺序及退出清理，不触碰业务库。"""

import warnings

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def lifecycle_calls(monkeypatch):
    """只替换生命周期内的资源操作，保留真实应用工厂和 ASGI 生命周期装配。"""
    from backend import main

    calls = []
    for name in ("_check_storages", "_reconcile_tasks", "_start_scheduler", "_stop_scheduler"):
        monkeypatch.setattr(main, name, lambda name=name: calls.append(name))
    return main, calls


def test_app_lifespan_runs_startup_and_shutdown_once_in_order(lifecycle_calls):
    main, calls = lifecycle_calls
    # 工厂本身不连接存储或启动后台线程，也不再注册已弃用的事件接口。
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        app = main.create_app()
    assert calls == []
    with TestClient(app):
        assert calls == ["_check_storages", "_reconcile_tasks", "_start_scheduler"]
    assert calls == [
        "_check_storages", "_reconcile_tasks", "_start_scheduler", "_stop_scheduler",
    ]


def test_app_lifespan_cleans_up_after_serving_scope_failure(lifecycle_calls):
    main, calls = lifecycle_calls
    with pytest.raises(RuntimeError, match="请求期失败"), TestClient(main.create_app()):
        raise RuntimeError("请求期失败")
    assert calls == [
        "_check_storages", "_reconcile_tasks", "_start_scheduler", "_stop_scheduler",
    ]


@pytest.mark.parametrize("stage", ["_check_storages", "_start_scheduler"])
def test_app_lifespan_startup_failure_prevents_serving(lifecycle_calls, monkeypatch, stage):
    main, calls = lifecycle_calls

    def fail():
        calls.append(stage)
        raise RuntimeError("启动拒绝")

    monkeypatch.setattr(main, stage, fail)
    with pytest.raises(RuntimeError, match="启动拒绝"), TestClient(main.create_app()):
        pytest.fail("启动失败后不应进入服务阶段")
    assert calls == (["_check_storages"] if stage == "_check_storages" else [
        "_check_storages", "_reconcile_tasks", "_start_scheduler",
    ])


def test_reconcile_failure_remains_a_logged_startup_warning(monkeypatch, caplog):
    """任务恢复仍可告警降级；不能在迁移入口时误改成跳过恢复或阻断启动。"""
    from backend import main
    from backend.services.async_task import AsyncTaskService

    calls = []
    monkeypatch.setattr(main.log, "handlers", [*main.log.handlers, caplog.handler])
    monkeypatch.setattr(main, "_check_storages", lambda: calls.append("storage"))
    monkeypatch.setattr(main, "_start_scheduler", lambda: calls.append("scheduler"))
    monkeypatch.setattr(main, "_stop_scheduler", lambda: calls.append("shutdown"))

    def fail_init(self):
        calls.append("reconcile")
        raise RuntimeError("恢复失败测试")

    monkeypatch.setattr(AsyncTaskService, "__init__", fail_init)
    with TestClient(main.create_app()):
        assert calls == ["storage", "reconcile", "scheduler"]
    assert calls == ["storage", "reconcile", "scheduler", "shutdown"]
    assert "启动期任务 reconcile 异常" in caplog.text
    assert "恢复失败测试" in caplog.text


def test_shutdown_keeps_scheduler_before_storage_close_order(monkeypatch):
    """退出仍复用原资源关闭函数，先停调度再释放三类存储。"""
    from types import SimpleNamespace

    from backend import main, storage
    from backend.scheduler import scheduler

    calls = []
    monkeypatch.setattr(scheduler, "shutdown_scheduler", lambda: calls.append("scheduler"))
    monkeypatch.setattr(storage, "close_duckdb_clients", lambda: calls.append("duckdb"))
    monkeypatch.setattr(storage, "get_pg_client", lambda: SimpleNamespace(
        close=lambda: calls.append("postgres"),
    ))
    monkeypatch.setattr(storage, "get_redis_client", lambda: SimpleNamespace(
        close=lambda: calls.append("redis"),
    ))
    main._stop_scheduler()
    assert calls == ["scheduler", "duckdb", "postgres", "redis"]
