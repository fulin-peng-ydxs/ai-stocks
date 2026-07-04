"""数据管理异步任务 API（SDD §10，M2.6 + M2.8-B）。

- POST /api/data/tasks            创建异步任务，立即返回 task_id（同类写任务并发 → 409）。
- GET  /api/data/tasks            近期任务列表（可按 status 过滤）。
- GET  /api/data/tasks/{id}       轮询单个任务进度/结果。
- GET  /api/data/tasks/{id}/logs  增量实时日志（after_seq）。
- POST /api/data/tasks/{id}/resume 续跑被中断的任务。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.response import ApiResponse, err, ok
from backend.auth.deps import require_system_perm
from backend.services.async_task import (
    TASK_TYPES,
    TASK_CAPABILITIES,
    AsyncTaskService,
    ConcurrentTaskError,
)

router = APIRouter(prefix="/api/data", tags=["data-tasks"])

# stage4·T5：整 router 在 main.py 挂 require_system 硬守卫（system-only 数据管理）；
# 此处每端点叠加精确码 data-task:manage 供路由扫描（T8）与审计识别，运行时仍由 system 兜底。
_TASK_GUARD = [Depends(require_system_perm("data-task:manage"))]


class TaskIn(BaseModel):
    task_type: str                 # update|backfill|ingest_date|ingest_codes|recompute|verify|checkup|fix
    params: dict | None = None


@router.post("/tasks", response_model=ApiResponse, dependencies=_TASK_GUARD)
def create_task(body: TaskIn) -> ApiResponse:
    if body.task_type not in TASK_TYPES:
        return err(400, f"未知任务类型: {body.task_type}（可选 {list(TASK_TYPES)}）")
    try:
        tid = AsyncTaskService().create(body.task_type, body.params or {})
    except ConcurrentTaskError as e:
        return err(409, f"已有同类任务在运行（{e.task_type}），请等待其完成或稍后再试",
                   {"running_id": e.running_id})
    except ValueError as e:
        return err(400, str(e))
    return ok({"task_id": tid})


@router.get("/tasks/{task_id}", response_model=ApiResponse, dependencies=_TASK_GUARD)
def get_task(task_id: str) -> ApiResponse:
    t = AsyncTaskService().get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    return ok(t)


@router.get("/tasks/{task_id}/logs", response_model=ApiResponse, dependencies=_TASK_GUARD)
def get_task_logs(task_id: str, after_seq: int = 0) -> ApiResponse:
    svc = AsyncTaskService()
    if not svc.get(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return ok({"logs": svc.get_logs(task_id, after_seq)})


@router.post("/tasks/{task_id}/resume", response_model=ApiResponse, dependencies=_TASK_GUARD)
def resume_task(task_id: str) -> ApiResponse:
    try:
        AsyncTaskService().resume(task_id)
    except ConcurrentTaskError as e:
        return err(409, f"已有同类任务在运行（{e.task_type}）", {"running_id": e.running_id})
    except ValueError as e:
        return err(400, str(e))
    return ok({"task_id": task_id})


@router.post("/tasks/{task_id}/cancel", response_model=ApiResponse, dependencies=_TASK_GUARD)
def cancel_task(task_id: str) -> ApiResponse:
    """请求终止运行中/排队中的任务（协作式：到下一个检查点停下，标记为可续跑）。"""
    svc = AsyncTaskService()
    task = svc.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not TASK_CAPABILITIES.get(task["task_type"], {}).get("can_cancel"):
        return err(400, f"该任务类型不支持终止: {task['task_type']}")
    if not svc.cancel(task_id):
        return err(400, "任务已结束，无法终止")
    return ok({"task_id": task_id, "cancelling": True})


@router.get("/tasks", response_model=ApiResponse, dependencies=_TASK_GUARD)
def list_tasks(limit: int = 20, status: str | None = None, task_type: str | None = None,
               page: int | None = None, size: int | None = None,
               sort: str = "time", order: str = "desc") -> ApiResponse:
    return ok(AsyncTaskService().list(limit, status, task_type, page, size, sort, order))
