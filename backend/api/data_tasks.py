"""数据管理异步任务 API（SDD §10，M2.6 + M2.8-B）。

- POST /api/data/tasks            创建异步任务，立即返回 task_id（同类写任务并发 → 409）。
- GET  /api/data/tasks            近期任务列表（可按 status 过滤）。
- GET  /api/data/tasks/{id}       轮询单个任务进度/结果。
- GET  /api/data/tasks/{id}/logs  增量实时日志（after_seq）。
- POST /api/data/tasks/{id}/resume 续跑被中断的任务。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api.response import ApiResponse, err, ok
from backend.services.async_task import (
    TASK_TYPES,
    AsyncTaskService,
    ConcurrentTaskError,
)

router = APIRouter(prefix="/api/data", tags=["data-tasks"])


class TaskIn(BaseModel):
    task_type: str                 # update|backfill|ingest_date|ingest_codes|recompute|verify|fix
    params: dict | None = None


@router.post("/tasks", response_model=ApiResponse)
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


@router.get("/tasks/{task_id}", response_model=ApiResponse)
def get_task(task_id: str) -> ApiResponse:
    t = AsyncTaskService().get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    return ok(t)


@router.get("/tasks/{task_id}/logs", response_model=ApiResponse)
def get_task_logs(task_id: str, after_seq: int = 0) -> ApiResponse:
    svc = AsyncTaskService()
    if not svc.get(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return ok({"logs": svc.get_logs(task_id, after_seq)})


@router.post("/tasks/{task_id}/resume", response_model=ApiResponse)
def resume_task(task_id: str) -> ApiResponse:
    try:
        AsyncTaskService().resume(task_id)
    except ConcurrentTaskError as e:
        return err(409, f"已有同类任务在运行（{e.task_type}）", {"running_id": e.running_id})
    except ValueError as e:
        return err(400, str(e))
    return ok({"task_id": task_id})


@router.get("/tasks", response_model=ApiResponse)
def list_tasks(limit: int = 20, status: str | None = None) -> ApiResponse:
    return ok({"tasks": AsyncTaskService().list(limit, status)})
