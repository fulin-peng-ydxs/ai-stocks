"""盘感训练 API（agent-works/market-sense-training/）。

盲测 + 逐日揭示 + T+1 真实撮合的手动交易训练。端点见各路由。
防作弊：running 态返回的视图均经服务层脱敏（无未来 K 线、无真实 code/name/日期）。
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from backend.api.response import ApiResponse, err, ok
from backend.services.training_service import TrainingService

router = APIRouter(prefix="/api/training", tags=["training"])


class StartBody(BaseModel):
    mode: str = "single"                  # single | multi
    range_start: str | None = None        # YYYY-MM-DD
    range_end: str | None = None
    n_rounds: int = 5                     # multi 模式回合数
    window_days: int = 20                 # 每回合连续交易日
    initial_capital: float = 100_000
    fee_enabled: bool = True
    filters: dict | None = None           # 随机范围过滤（boards/exclude_st 等）


class TradeBody(BaseModel):
    side: str                             # buy | sell
    hands: int
    reason: str = ""


class RevealBody(BaseModel):
    cursor_idx: int | None = None         # 前端已知进度（乐观锁）


class ReviewBody(BaseModel):
    note: str = ""


@router.post("/sessions", response_model=ApiResponse)
def start_session(body: StartBody) -> ApiResponse:
    try:
        view = TrainingService().create_session(body.model_dump())
    except ValueError as e:
        return err(400, str(e))
    return ok(view)


@router.get("/sessions", response_model=ApiResponse)
def list_sessions(page: int = 1, size: int = 20, status: str | None = None,
                  sort_by: str = "created_at", sort_order: str = "desc") -> ApiResponse:
    return ok(TrainingService().list_sessions(page, size, status, sort_by, sort_order))


@router.get("/growth", response_model=ApiResponse)
def growth() -> ApiResponse:
    return ok(TrainingService().growth())


@router.get("/sessions/{sid}", response_model=ApiResponse)
def get_session(sid: str) -> ApiResponse:
    try:
        return ok(TrainingService().get_view(sid))
    except ValueError as e:
        return err(404, str(e))


@router.delete("/sessions/{sid}", response_model=ApiResponse)
def delete_session(sid: str) -> ApiResponse:
    TrainingService().delete(sid)
    return ok({"msg": "已删除"})


@router.post("/sessions/{sid}/reveal", response_model=ApiResponse)
def reveal(sid: str, body: RevealBody) -> ApiResponse:
    try:
        return ok(TrainingService().reveal(sid, body.cursor_idx))
    except ValueError as e:
        return err(400, str(e))


@router.post("/sessions/{sid}/trade", response_model=ApiResponse)
def trade(sid: str, body: TradeBody) -> ApiResponse:
    try:
        return ok(TrainingService().place_intent(sid, body.side, body.hands, body.reason))
    except ValueError as e:
        return err(400, str(e))


@router.post("/sessions/{sid}/cancel", response_model=ApiResponse)
def cancel(sid: str) -> ApiResponse:
    try:
        return ok(TrainingService().cancel_intent(sid))
    except ValueError as e:
        return err(400, str(e))


@router.post("/sessions/{sid}/settle-round", response_model=ApiResponse)
def settle_round(sid: str) -> ApiResponse:
    try:
        return ok(TrainingService().settle_round(sid))
    except ValueError as e:
        return err(400, str(e))


@router.patch("/sessions/{sid}/review", response_model=ApiResponse)
def review(sid: str, body: ReviewBody) -> ApiResponse:
    try:
        TrainingService().update_review(sid, body.note)
    except ValueError as e:
        return err(404, str(e))
    return ok({"msg": "已保存"})
