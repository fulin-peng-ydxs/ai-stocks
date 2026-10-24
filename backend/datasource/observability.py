"""任务请求观测：线程安全聚合，仅在已有检查点中持久化，不逐 HTTP 写 PG。"""

from __future__ import annotations

import threading
import time
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

_SCOPE = ContextVar("collection_observation", default=None)


class RequestTracker:
    """当前状态互斥，累计网络与等待时长为线程耗时，阶段 ETA 用墙钟吞吐。"""

    def __init__(self):
        self.lock = threading.RLock()
        self.states = {}
        self.counts = Counter()
        self.started = time.monotonic()
        self.phase_started = self.started
        self.phase = object()  # 首次快照也建立基线，续跑历史完成量不计作本轮吞吐。
        self.phase_initial = 0
        self.phase_failures = 0
        self.meta = {}

    def add(self, **values):
        with self.lock:
            self.counts.update(values)

    def snapshot(self, checkpoint=None):
        checkpoint = checkpoint or {}
        now = time.monotonic()
        with self.lock:
            phase = checkpoint.get("phase")
            done = int(checkpoint.get("phase_done") or 0)
            total = int(checkpoint.get("phase_total") or 0)
            if phase != self.phase:
                self.phase, self.phase_started, self.phase_initial = phase, now, done
                self.phase_failures = self.counts["failures"]
            elapsed = now - self.phase_started
            rate = (done - self.phase_initial) / elapsed if elapsed > 0 else 0
            eta = (
                (total - done) / rate
                if rate > 0 and total > 0 and total >= done
                and done - self.phase_initial >= 20 else None
            )
            if self.counts["failures"] > self.phase_failures:
                eta = None
            return {
                **dict(self.counts),
                "requests": self.counts["requests"],
                "failures": self.counts["failures"],
                "network_seconds": round(self.counts["network_seconds"], 3),
                "wait_seconds": round(self.counts["wait_seconds"], 3),
                "states": dict(Counter(self.states.values())),
                "completed": done,
                "elapsed_seconds": round(now - self.started, 3),
                "eta_seconds": round(max(0, eta)) if eta is not None else None,
                **self.meta,
            }


def current_scope():
    return _SCOPE.get()


@contextmanager
def observe_work(tracker=None, *, state="processing"):
    if tracker is None:
        yield
        return
    key = uuid4().hex
    token = _SCOPE.set((tracker, key))
    with tracker.lock:
        tracker.states[key] = state
    try:
        yield
    finally:
        with tracker.lock:
            tracker.states.pop(key, None)
        _SCOPE.reset(token)


def set_work_state(state):
    scope = _SCOPE.get()
    if scope:
        tracker, key = scope
        with tracker.lock:
            tracker.states[key] = state


@contextmanager
def work_state(state):
    scope = _SCOPE.get()
    previous = None
    if scope:
        with scope[0].lock:
            previous = scope[0].states.get(scope[1], "processing")
        set_work_state(state)
    try:
        yield
    finally:
        if previous is not None:
            set_work_state(previous)


def record(**values):
    scope = _SCOPE.get()
    if scope:
        scope[0].add(**values)
