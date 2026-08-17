"""板块行情只读 API（板块概念需求 R7-R10/R13/R14，plan §6.8 T8）。

板块列表/详情/bars/members 与市场指数基准 bars，权限 `sectors:view`（业务授权码，T10a seed）。
参数白名单：未知参数 400；`sort_by` 稳定字段码；`trade_date` 截面语义；
空值「—」（前端）；404/400/403。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api.response import ApiResponse, ok
from backend.auth.deps import require_perm
from backend.services.board_query import MEMBER_SORT_FIELDS, SORT_FIELDS, BoardQueryService
from backend.services.board_watchlist import BoardWatchlistService
from backend.services.market_benchmark import MarketBenchmarkService

router = APIRouter(prefix="/api/sectors", tags=["sectors"])

_VIEW = [Depends(require_perm("sectors:view"))]
_WATCHLIST_VIEW = [Depends(require_perm("sector-watchlist:view"))]
_WATCHLIST_UPDATE = [Depends(require_perm("sector-watchlist:update"))]

class WatchlistBody(BaseModel):
    board_code: str = Field(min_length=1, max_length=32)


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
    size: int = Query(20, ge=1, le=200),
) -> ApiResponse:
    """板块列表（涨幅/最近快照返回数/净流入/累计成员领涨 + 分页排序）。"""
    if sort_by not in SORT_FIELDS:
        raise _bad_params(f"不支持的排序字段: {sort_by}（可选 {list(SORT_FIELDS)}）")
    data = BoardQueryService().list_sectors(
        trade_date=trade_date, board_type=board_type, sort_by=sort_by,
        order=order, keyword=keyword, page=page, size=size)
    return ok(data)


@router.get("/watchlist", response_model=ApiResponse, dependencies=_WATCHLIST_VIEW)
def list_watchlist() -> ApiResponse:
    """当前用户的板块自选代码与加入快照。"""
    return ok(BoardWatchlistService().list())


@router.get(
    "/watchlist/markets",
    response_model=ApiResponse,
    dependencies=[*_VIEW, *_WATCHLIST_VIEW],
)
def list_watchlist_markets(
    trade_date: date | None = Query(None),
    board_type: str | None = Query(None, pattern="^(concept|industry)$"),
    sort_by: str = Query("pct_today"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    keyword: str | None = Query(None, max_length=50),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> ApiResponse:
    """当前用户自选板块的行情截面，失效板块仍返回快照。"""
    if sort_by not in SORT_FIELDS:
        raise _bad_params(f"不支持的排序字段: {sort_by}（可选 {list(SORT_FIELDS)}）")
    return ok(BoardWatchlistService().list_markets(
        trade_date=trade_date,
        board_type=board_type,
        sort_by=sort_by,
        order=order,
        keyword=keyword,
        page=page,
        size=size,
    ))


@router.post("/watchlist", response_model=ApiResponse, dependencies=_WATCHLIST_UPDATE)
def add_watchlist(body: WatchlistBody) -> ApiResponse:
    """加入板块自选；重复加入保持幂等。"""
    try:
        return ok(BoardWatchlistService().add(body.board_code))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/watchlist/{board_code}",
    response_model=ApiResponse,
    dependencies=_WATCHLIST_UPDATE,
)
def remove_watchlist(board_code: str) -> ApiResponse:
    """移出板块自选；成员不存在时保持幂等。"""
    return ok(BoardWatchlistService().remove(board_code))


@router.get(
    "/benchmarks/{index_code}/bars",
    response_model=ApiResponse,
    dependencies=_VIEW,
)
def get_benchmark_bars(
    index_code: str,
    start: date = Query(..., description="区间起点"),
    end: date = Query(..., description="区间终点"),
) -> ApiResponse:
    """板块相对强弱使用的市场指数基准，只开放系统已配置的回测基准。"""
    if start > end:
        raise _bad_params("start 不能晚于 end")
    service = MarketBenchmarkService()
    try:
        bars = service.get_range(index_code, start, end)
    except ValueError as exc:
        raise _bad_params(str(exc)) from exc
    return ok({
        "index_code": index_code,
        "name": service.name(index_code),
        "start": str(start),
        "end": str(end),
        "list": bars,
    })


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
    include_indicators: bool = Query(False, description="是否返回板块指数 MACD"),
) -> ApiResponse:
    """板块指数区间序列（原值，周期由前端区间参数控制）。"""
    if start > end:
        raise _bad_params("start 不能晚于 end")
    service = BoardQueryService()
    data = service.get_bars(code, start, end)
    indicators = service.get_bar_indicators(code, start, end) if include_indicators else []
    return ok({
        "board_code": code,
        "start": str(start),
        "end": str(end),
        "list": data,
        "indicators": indicators,
    })


@router.get("/{code}/members", response_model=ApiResponse, dependencies=_VIEW)
def get_sector_members(
    code: str,
    trade_date: date | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    sort_by: str = Query("pct"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
) -> ApiResponse:
    """成分股统一分页（size 默认 20，页面可配 10/20/30/50）。"""
    if sort_by not in MEMBER_SORT_FIELDS:
        raise _bad_params(
            f"不支持的成分股排序字段: {sort_by}（可选 {list(MEMBER_SORT_FIELDS)}）"
        )
    data = BoardQueryService().get_members(code, trade_date, page, size, sort_by, order)
    return ok(data)
