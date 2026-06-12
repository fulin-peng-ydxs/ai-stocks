"""股票分组 API（个股查询·篮子，M2.4+）——CRUD + 成员增删 + 整组涨幅统计。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from backend.api.response import ApiResponse, err, ok
from backend.groups.stock_group import StockGroupRepo

router = APIRouter(prefix="/api", tags=["stock-groups"])


class GroupCreate(BaseModel):
    name: str
    group_date: str | None = None      # YYYY-MM-DD，默认最新交易日
    description: str = ""
    codes: list[str] | None = None


class GroupMeta(BaseModel):
    name: str | None = None
    group_date: str | None = None
    description: str | None = None


class MembersBody(BaseModel):
    codes: list[str]
    add_date: str | None = None        # 追加成员的加入日期，默认最新交易日


class MemberDate(BaseModel):
    add_date: str


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


@router.get("/stock-groups", response_model=ApiResponse)
def list_groups() -> ApiResponse:
    return ok(StockGroupRepo().list())


@router.get("/stock-groups/{gid}", response_model=ApiResponse)
def get_group(gid: str) -> ApiResponse:
    g = StockGroupRepo().get(gid)
    return ok(g) if g else err(404, "分组不存在")


@router.post("/stock-groups", response_model=ApiResponse)
def create_group(body: GroupCreate) -> ApiResponse:
    try:
        gid = StockGroupRepo().create(body.name, _d(body.group_date), body.description, body.codes)
    except ValueError as e:
        return err(400, str(e))
    return ok({"id": gid, "msg": "已创建"})


@router.patch("/stock-groups/{gid}", response_model=ApiResponse)
def update_group(gid: str, body: GroupMeta) -> ApiResponse:
    StockGroupRepo().update_meta(gid, body.name, _d(body.group_date), body.description)
    return ok({"id": gid, "msg": "已更新"})


@router.delete("/stock-groups/{gid}", response_model=ApiResponse)
def delete_group(gid: str) -> ApiResponse:
    StockGroupRepo().delete(gid)
    return ok({"msg": "已删除"})


@router.post("/stock-groups/{gid}/members", response_model=ApiResponse)
def add_members(gid: str, body: MembersBody) -> ApiResponse:
    n = StockGroupRepo().add_members(gid, body.codes, _d(body.add_date))
    return ok({"id": gid, "added": n})


@router.delete("/stock-groups/{gid}/members", response_model=ApiResponse)
def remove_members(gid: str, body: MembersBody) -> ApiResponse:
    StockGroupRepo().remove_members(gid, body.codes)
    return ok({"id": gid, "msg": "已移除"})


@router.patch("/stock-groups/{gid}/members/{code}", response_model=ApiResponse)
def set_member_date(gid: str, code: str, body: MemberDate) -> ApiResponse:
    StockGroupRepo().set_member_date(gid, code, date.fromisoformat(body.add_date))
    return ok({"id": gid, "code": code, "add_date": body.add_date})
