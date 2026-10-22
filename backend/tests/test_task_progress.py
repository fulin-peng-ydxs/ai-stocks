"""子任务进度必须保留父范围、真实计数和原上下文状态。"""

from types import SimpleNamespace

import pytest

from backend.services.async_task import TaskContext
from backend.services.task_progress import TaskProgressScope


def test_nested_progress_does_not_finish_parent_on_first_phase():
    events = []
    parent = SimpleNamespace(progress=lambda p, msg: events.append((p, msg)),
                             set_phase=lambda *args, **kwargs: None)
    outer = TaskProgressScope(parent, 0.2, 0.5)
    child = TaskProgressScope(outer, 0.08, 0.9,
                             phases=[("daily_bar", 3), ("price_factor", 1)])
    child.set_phase("daily_bar", phase_total=10, phase_done=10)
    assert events[-1][0] == pytest.approx(0.408)
    child.set_phase("price_factor", phase_total=10, phase_done=0)
    child.set_phase("price_factor", phase_total=10, phase_done=10)
    child.progress(1, "取数结束")
    assert events[-1][0] == pytest.approx(0.47)
    assert [p for p, _ in events] == sorted(p for p, _ in events)
    assert max(p for p, _ in events) < 0.5


def test_scope_delegates_repair_cache_and_checkpoints_to_original_context():
    parent = SimpleNamespace(checkpoint={})
    parent.set_checkpoint = lambda **data: parent.checkpoint.update(data)
    scope = TaskProgressScope(parent, 0.1, 0.2)
    scope._intraday_repair_cache = {"stock": "cached"}
    scope.related_stage_errors = {"stock": "source failed"}
    scope.set_checkpoint(issue_done_ids=[1])
    assert parent._intraday_repair_cache == {"stock": "cached"}
    assert parent.related_stage_errors == {"stock": "source failed"}
    assert parent.checkpoint == {"issue_done_ids": [1]}


def test_context_reserves_100_percent_for_terminal_write():
    updates = []
    svc = SimpleNamespace(_max_log_seq=lambda tid: 0,
                          _set=lambda tid, **fields: updates.append(fields))
    ctx = TaskContext(svc, "test")
    ctx.progress(1, "处理器取数结束")
    assert updates == [{"progress": 0.99, "message": "处理器取数结束"}]
