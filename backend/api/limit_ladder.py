"""Limit-up ladder snapshot, status, export and recompute API."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from backend.api.response import ApiResponse, err, ok
from backend.auth.context import get_current_context
from backend.auth.deps import require_perm, require_system_perm
from backend.services.limit_ladder_query import LimitLadderFilters, LimitLadderQueryService
from backend.services.limit_ladder_task_coordinator import LimitLadderTaskCoordinator

router = APIRouter(prefix="/api/limit-ladder", tags=["limit-ladder"])
_VIEW = [Depends(require_perm("limit-ladder:view"))]
BoardsQuery = Annotated[list[str] | None, Query()]
KeywordQuery = Annotated[str | None, Query(max_length=50)]
HotspotKeyQuery = Annotated[str | None, Query(max_length=100)]


def _trade_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="trade_date must use YYYY-MM-DD") from exc


def _filters(
    window: int,
    boards: list[str] | None,
    ignore_st: bool,
    one_word_only: bool,
    keyword: str | None,
    hotspot_type: str | None,
    hotspot_key: str | None,
) -> LimitLadderFilters:
    normalized = LimitLadderFilters(
        window=window,
        boards=tuple(dict.fromkeys(boards or ())),
        ignore_st=ignore_st,
        one_word_only=one_word_only,
        keyword=(keyword or "").strip() or None,
        hotspot_type=hotspot_type,  # type: ignore[arg-type]
        hotspot_key=(hotspot_key or "").strip() or None,
    )
    try:
        normalized.validate()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return normalized


@router.get("/trade-dates", response_model=ApiResponse, dependencies=_VIEW)
def trade_dates(limit: int = Query(250, ge=1, le=1000)) -> ApiResponse:
    return ok(LimitLadderQueryService().trade_dates(limit=limit))


@router.get("/{trade_date}/status", response_model=ApiResponse, dependencies=_VIEW)
def status(trade_date: str) -> ApiResponse:
    return ok(LimitLadderQueryService().status(_trade_date(trade_date)))


@router.get("/{trade_date}/export", dependencies=_VIEW)
def export(
    trade_date: str,
    window: int = 31,
    boards: BoardsQuery = None,
    ignore_st: bool = True,
    one_word_only: bool = False,
    keyword: KeywordQuery = None,
    hotspot_type: str | None = None,
    hotspot_key: HotspotKeyQuery = None,
) -> Response:
    parsed_date = _trade_date(trade_date)
    filters = _filters(window, boards, ignore_st, one_word_only, keyword, hotspot_type, hotspot_key)
    try:
        filename, content = LimitLadderQueryService().export_csv(parsed_date, filters)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/{trade_date}/recompute",
    response_model=ApiResponse,
    dependencies=[Depends(require_system_perm("limit-ladder:recompute"))],
)
def recompute(trade_date: str, request: Request) -> ApiResponse:
    parsed_date = _trade_date(trade_date)
    date_status = LimitLadderQueryService().status(parsed_date)
    if date_status["business_code"] == "NOT_TRADING_DAY":
        return err(4004, "所选日期不是交易日", date_status)
    result = LimitLadderTaskCoordinator().ensure_date_task(
        parsed_date,
        source="admin_recompute",
        auth_context=get_current_context(),
        request=request,
    )
    return ok(
        {
            "command_id": result.command_id,
            "task_id": result.task_id,
            "status": result.status,
            "reused": result.reused,
        }
    )


@router.get("/{trade_date}", response_model=ApiResponse, dependencies=_VIEW)
def query(
    trade_date: str,
    request: Request,
    window: int = 31,
    boards: BoardsQuery = None,
    ignore_st: bool = True,
    one_word_only: bool = False,
    keyword: KeywordQuery = None,
    hotspot_type: str | None = None,
    hotspot_key: HotspotKeyQuery = None,
) -> ApiResponse:
    parsed_date = _trade_date(trade_date)
    filters = _filters(window, boards, ignore_st, one_word_only, keyword, hotspot_type, hotspot_key)
    return ok(
        LimitLadderQueryService().query(
            parsed_date,
            filters,
            auth_context=get_current_context(),
            request=request,
        )
    )
