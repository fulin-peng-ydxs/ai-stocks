"""股票分组 API（个股查询·篮子，M2.4+）——CRUD + 成员增删 + 整组涨幅统计。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.response import ApiResponse, err, ok
from backend.auth.deps import require_perm
from backend.groups.stock_group import StockGroupRepo
from backend.services.stock_board_filters import (
    STOCK_LISTED_BOARD_VALUES,
    STOCK_STATUS_VALUES,
    parse_stock_board_values,
    parse_stock_status_values,
)

router = APIRouter(prefix="/api", tags=["stock-groups"])


class GroupCreate(BaseModel):
    name: str
    group_date: str | None = None      # YYYY-MM-DD，默认最新交易日
    description: str = ""
    color: str | None = None
    codes: list[str] | None = None


class GroupMeta(BaseModel):
    name: str | None = None
    group_date: str | None = None
    description: str | None = None
    color: str | None = None


class MembersBody(BaseModel):
    codes: list[str]
    add_date: str | None = None        # 追加成员的加入日期，默认最新交易日


class MemberDate(BaseModel):
    add_date: str


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


@router.get("/stock-groups", response_model=ApiResponse,
            dependencies=[Depends(require_perm("stock-group:view"))])
def list_groups() -> ApiResponse:
    return ok(StockGroupRepo().list())


@router.get("/stock-groups/{gid}", response_model=ApiResponse,
            dependencies=[Depends(require_perm("stock-group:view"))])
def get_group(gid: str, page: int = 1, size: int = 50, q: str | None = None,
              boards: str | None = None, statuses: str | None = None,
              board: str | None = None,
              exclude_st: bool = False,
              membership_board_code: str | None = None,
              exclude_delisted: bool = False,
              trade_date: date | None = None,
              sort_by: str = "add_date", sort_order: str = "asc") -> ApiResponse:
    try:
        selected_boards = parse_stock_board_values(boards)
        selected_statuses = parse_stock_status_values(statuses)
        using_dimensions = boards is not None or statuses is not None
        if using_dimensions:
            selected_boards = selected_boards or list(STOCK_LISTED_BOARD_VALUES)
            selected_statuses = selected_statuses or list(STOCK_STATUS_VALUES)
        g = StockGroupRepo().get(
            gid,
            page=page,
            size=size,
            q=q,
            boards=selected_boards or None,
            statuses=selected_statuses or None,
            board=None if using_dimensions else board,
            membership_board_code=membership_board_code,
            exclude_st=exclude_st,
            exclude_delisted=exclude_delisted,
            trade_date=trade_date,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except ValueError as exc:
        return err(400, str(exc))
    return ok(g) if g else err(404, "分组不存在")


@router.post("/stock-groups", response_model=ApiResponse,
             dependencies=[Depends(require_perm("stock-group:create"))])
def create_group(body: GroupCreate) -> ApiResponse:
    try:
        gid = StockGroupRepo().create(body.name, _d(body.group_date), body.description, body.codes, body.color)
    except ValueError as e:
        return err(400, str(e))
    return ok({"id": gid, "msg": "已创建"})


@router.patch("/stock-groups/{gid}", response_model=ApiResponse,
              dependencies=[Depends(require_perm("stock-group:update"))])
def update_group(gid: str, body: GroupMeta) -> ApiResponse:
    StockGroupRepo().update_meta(gid, body.name, _d(body.group_date), body.description, body.color)
    return ok({"id": gid, "msg": "已更新"})


@router.delete("/stock-groups/{gid}", response_model=ApiResponse,
               dependencies=[Depends(require_perm("stock-group:delete"))])
def delete_group(gid: str) -> ApiResponse:
    try:
        StockGroupRepo().delete(gid)
    except ValueError as e:
        return err(400, str(e))
    return ok({"msg": "已删除"})


@router.post("/stock-groups/{gid}/members", response_model=ApiResponse,
             dependencies=[Depends(require_perm("stock-group:member-update"))])
def add_members(gid: str, body: MembersBody) -> ApiResponse:
    n = StockGroupRepo().add_members(gid, body.codes, _d(body.add_date))
    return ok({"id": gid, "added": n})


@router.delete("/stock-groups/{gid}/members", response_model=ApiResponse,
               dependencies=[Depends(require_perm("stock-group:member-update"))])
def remove_members(gid: str, body: MembersBody) -> ApiResponse:
    StockGroupRepo().remove_members(gid, body.codes)
    return ok({"id": gid, "msg": "已移除"})


@router.patch("/stock-groups/{gid}/members/{code}", response_model=ApiResponse,
              dependencies=[Depends(require_perm("stock-group:member-update"))])
def set_member_date(gid: str, code: str, body: MemberDate) -> ApiResponse:
    StockGroupRepo().set_member_date(gid, code, date.fromisoformat(body.add_date))
    return ok({"id": gid, "code": code, "add_date": body.add_date})
