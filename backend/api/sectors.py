"""板块行情只读 API（板块概念需求 R7-R10/R13/R14，plan §6.8 T8）。

4 个只读接口（列表/详情/bars/members），权限 `sectors:view`（业务授权码，T10a seed）。
参数白名单：未知参数 400；`sort_by` 稳定字段码；`trade_date` 截面语义；
空值「—」（前端）；404/400/403。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.response import ApiResponse, ok
from backend.auth.deps import require_perm
from backend.services.board_query import BoardQueryService, SORT_FIELDS

router = APIRouter(prefix="/api/sectors", tags=["sectors"])

_VIEW = [Depends(require_perm("sectors:view"))]


def _bad_params(msg: str) -> HTTPException:
    return HTTPException(status_code=400, detail=msg)


@router.get("", response_model=ApiResponse, dependencies=_VIEW)
def list_sectors(
    trade_date: date | None = Query(None, description="指定交易日（缺省=最新）"),
    board_type: str | None = Query(None, pattern="^(concept|industry)$"),
    sort_by: str = Query("pct_today"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    keyword: str | None = Query(None, max_length=50),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> ApiResponse:
    """板块列表（涨幅/成分数/净流入/领涨股 + 分页排序）。"""
    if sort_by not in SORT_FIELDS:
        raise _bad_params(f"不支持的排序字段: {sort_by}（可选 {list(SORT_FIELDS)}）")
    data = BoardQueryService().list_sectors(
        trade_date=trade_date, board_type=board_type, sort_by=sort_by,
        order=order, keyword=keyword, page=page, size=size)
    return ok(data)


@router.get("/{code}", response_model=ApiResponse, dependencies=_VIEW)
def get_sector(code: str, trade_date: date | None = Query(None)) -> ApiResponse:
    """板块详情摘要（含能力字段 + 指定交易日截面）。"""
    data = BoardQueryService().get_sector(code, trade_date)
    if data is None:
        raise HTTPException(status_code=404, detail=f"板块不存在或数据未采集: {code}")
    return ok(data)


@router.get("/{code}/bars", response_model=ApiResponse, dependencies=_VIEW)
def get_sector_bars(
    code: str,
    start: date = Query(..., description="区间起点"),
    end: date = Query(..., description="区间终点"),
) -> ApiResponse:
    """板块指数区间序列（原值，周期由前端区间参数控制）。"""
    if start > end:
        raise _bad_params("start 不能晚于 end")
    data = BoardQueryService().get_bars(code, start, end)
    return ok({"board_code": code, "start": str(start), "end": str(end), "list": data})


@router.get("/{code}/members", response_model=ApiResponse, dependencies=_VIEW)
def get_sector_members(
    code: str,
    trade_date: date | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> ApiResponse:
    """成分股统一分页（size 默认 20，页面可配 10/20/30/50）。"""
    data = BoardQueryService().get_members(code, trade_date, page, size)
    return ok(data)
