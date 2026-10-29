"""BaoStock公共取源执行器：任务内复用独立会话，跨任务共用Redis网络额度。"""

from __future__ import annotations

import multiprocessing
import os
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, TimeoutError
from concurrent.futures.process import BrokenProcessPool
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import Lock

from backend.common.exceptions import DataSourceError, SourceRequestError
from backend.config.source_registry import BAOSTOCK_MAX_CONCURRENCY
from backend.datasource.base import check_thread_cancel, thread_cancel_scope
from backend.datasource.observability import (
    RequestTracker,
    observe_work,
    record,
    record_source,
    work_state,
)

# 仅传递公开只读取源操作；关联原始/复权请求作为一个完整操作在同一进程内完成。
OPERATIONS = frozenset({
    "get_st_status", "get_daily_bar", "get_basic_dates", "get_industry",
    "get_delisted_list", "get_stock_list", "get_stock_info", "get_index_bar",
    "get_trade_calendar",
})
_scope = ContextVar("baostock_execution_scope", default=None)
_cancel_event = None


def current_executor():
    return _scope.get()


@contextmanager
def bind_executor(executor):
    """仅传递BaoStock任务执行器，不传播其它来源的请求预算或缓存上下文。"""
    token = _scope.set(executor)
    try:
        yield executor
    finally:
        _scope.reset(token)


@contextmanager
def execution_scope(workers=None, *, tracker=None):
    """嵌套业务阶段共享一个执行器；进程只在首次真实取源时创建。"""
    existing = current_executor()
    if existing is not None:
        yield existing
        return
    from backend.config.request_snapshot import get_request_settings
    from backend.datasource.request_policy import request_policy

    requested = workers or get_request_settings().datasource.update_concurrency
    capacity = min(int(requested), request_policy("baostock").concurrency)
    with BaostockExecutor(capacity, tracker=tracker) as executor, bind_executor(executor):
        yield executor


def pooled_operation(method):
    """生产业务作用域统一分发；工作进程和单路模式复用原SDK方法及解析。"""
    if method.__name__ not in OPERATIONS:
        raise ValueError(f"未登记的BaoStock取源操作: {method.__name__}")

    @wraps(method)
    def call(source, *args, **kwargs):
        executor = current_executor()
        if executor is None or executor.workers == 1:
            return method(source, *args, **kwargs)
        return executor.call(method.__name__, *args, **kwargs)
    return call


def _check_cancel():
    if _cancel_event is not None and _cancel_event.is_set():
        from backend.services.async_task import TaskCancelled
        raise TaskCancelled()


def _initialize(cancel_event):
    """spawn不继承父进程socket，每个工作进程拥有独立SDK单例和取消检查器。"""
    global _cancel_event
    _cancel_event = cancel_event
    from multiprocessing.util import Finalize

    from backend.datasource.baostock_source import shared_baostock

    # 退出只关闭本进程socket，避免清理阶段的logout网络请求重新挂起。
    Finalize(None, shared_baostock()._invalidate_login, exitpriority=10)


def _execute_operation(operation, args, kwargs):
    if operation not in OPERATIONS:
        raise ValueError(f"未登记的BaoStock取源操作: {operation}")
    from backend.datasource.baostock_source import shared_baostock
    return getattr(shared_baostock(), operation)(*args, **kwargs)


def _query(operation, args, kwargs, queued_at=None):
    """只返回完整取源结果；保留预算耗尽语义及取消，子进程不读写DuckDB。"""
    from backend.services.async_task import TaskCancelled

    tracker = RequestTracker()
    tracker.meta["_baostock_worker_pid"] = os.getpid()
    value, error, cancelled = None, None, False
    with observe_work(tracker), thread_cancel_scope(_check_cancel), bind_executor(None):
        queued = max(0, time.monotonic() - queued_at) if queued_at is not None else 0
        record(session_wait_seconds=queued)
        record_source("baostock", session_wait_seconds=queued)
        try:
            _check_cancel()
            record(**{f"baostock_{operation}_operations": 1})
            value = _execute_operation(operation, args, kwargs)
        except TaskCancelled:
            cancelled = True
        except Exception as exc:  # noqa: BLE001 -- 单操作失败不得返回半截区间
            error = {"message": f"{type(exc).__name__}: {str(exc)[:1000]}",
                     "exhausted": bool(getattr(exc, "request_attempts_exhausted", False))}
    return value, error, cancelled, dict(tracker.counts), tracker.sources, tracker.meta


class BaostockExecutor:
    """任务级可复用执行器；各操作共用一个有界进程池，取消不影响其它任务。"""

    def __init__(self, workers: int, *, tracker=None):
        if (isinstance(workers, bool) or not isinstance(workers, int)
                or not 1 <= workers <= BAOSTOCK_MAX_CONCURRENCY):
            raise ValueError(f"BaoStock独立进程数须为1～{BAOSTOCK_MAX_CONCURRENCY}的整数")
        self.workers, self.tracker = workers, tracker
        self.context = multiprocessing.get_context("spawn")
        self.cancel_event = self.executor = None
        self.setup_lock = Lock()
        self.worker_pids = set()
        self.closed = False

    def _pool(self):
        with self.setup_lock:
            if self.closed:
                raise SourceRequestError("BaoStock任务执行器已关闭，未发送请求")
            if self.executor is None:
                self.cancel_event = self.context.Event()
                self.executor = ProcessPoolExecutor(
                    max_workers=self.workers, mp_context=self.context,
                    initializer=_initialize, initargs=(self.cancel_event,),
                )
                if self.tracker is not None:
                    with self.tracker.lock:
                        self.tracker.meta["baostock_pool_capacity"] = self.workers
            return self.executor

    def _merge_observation(self, future):
        if self.tracker is None or future.cancelled() or future.exception() is not None:
            return
        _, _, _, counts, sources, meta = future.result()
        with self.tracker.lock:
            meta = dict(meta)
            pid = meta.pop("_baostock_worker_pid", None)
            if pid is not None:
                self.worker_pids.add(pid)
                self.tracker.meta["baostock_processes"] = len(self.worker_pids)
            self.tracker.counts.update(counts)
            for group, values in sources.items():
                self.tracker.sources.setdefault(group, Counter()).update(values)
            self.tracker.meta.update(meta)

    def cancel(self):
        with self.setup_lock:
            if self.cancel_event is not None:
                self.cancel_event.set()

    def call(self, operation, *args, **kwargs):
        """按操作自身的Future匹配返回，保留SDK原有的完整解析及有限重试。"""
        from backend.services.async_task import TaskCancelled

        if operation not in OPERATIONS:
            raise ValueError(f"未登记的BaoStock取源操作: {operation}")
        check_thread_cancel()
        future = None
        try:
            future = self._pool().submit(_query, operation, args, kwargs, time.monotonic())
            future.add_done_callback(self._merge_observation)
            with work_state("source_wait"):
                while True:
                    check_thread_cancel()
                    try:
                        value, error, cancelled, *_ = future.result(timeout=0.1)
                        break
                    except TimeoutError:
                        continue
            check_thread_cancel()
            if cancelled:
                raise TaskCancelled()
            if error is not None:
                exception = SourceRequestError if error["exhausted"] else DataSourceError
                raise exception(f"BaoStock {operation}取源失败：{error['message']}")
            return value
        except TaskCancelled:
            self.cancel()
            if future is not None:
                future.cancel()
            raise
        except BrokenProcessPool as exc:
            raise SourceRequestError("BaoStock工作进程异常退出，本次操作失败，可重新执行任务") from exc

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is not None:
            self.cancel()
        with self.setup_lock:
            self.closed = True
            executor = self.executor
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
