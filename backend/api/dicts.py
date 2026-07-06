"""数据字典 API（阶段五 T6）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.response import ApiResponse, ok
from backend.auth.deps import require_perm, require_system_perm
from backend.services.dict_service import DictService

router = APIRouter(prefix="/api/dict", tags=["dict"])


class DictTypeCreate(BaseModel):
    code: str
    name: str
    enabled: bool = True
    sort: int = 100
    remark: str | None = None


class DictTypeUpdate(BaseModel):
    code: str | None = None
    name: str
    enabled: bool = True
    sort: int = 100
    remark: str | None = None


class DictItemCreate(BaseModel):
    type_code: str
    code: str
    label: str
    enabled: bool = True
    sort: int = 100
    remark: str | None = None


class DictItemUpdate(BaseModel):
    type_code: str | None = None
    code: str | None = None
    label: str
    enabled: bool = True
    sort: int = 100
    remark: str | None = None


@router.get(
    "/types",
    response_model=ApiResponse,
    dependencies=[Depends(require_system_perm("dict:view"))],
)
def list_types(
    q: str | None = None,
    enabled: bool | None = None,
    page: int = 1,
    size: int = 50,
) -> ApiResponse:
    return ok(DictService().list_types(q=q, enabled=enabled, page=page, size=size))


@router.post(
    "/types",
    response_model=ApiResponse,
    dependencies=[Depends(require_system_perm("dict:type-manage"))],
)
def create_type(body: DictTypeCreate) -> ApiResponse:
    return ok(DictService().create_type(
        code=body.code,
        name=body.name,
        enabled=body.enabled,
        sort=body.sort,
        remark=body.remark,
    ), msg="已创建")


@router.put(
    "/types/{code}",
    response_model=ApiResponse,
    dependencies=[Depends(require_system_perm("dict:type-manage"))],
)
def update_type(code: str, body: DictTypeUpdate) -> ApiResponse:
    return ok(DictService().update_type(
        code,
        body_code=body.code,
        name=body.name,
        enabled=body.enabled,
        sort=body.sort,
        remark=body.remark,
    ), msg="已保存")


@router.delete(
    "/types/{code}",
    response_model=ApiResponse,
    dependencies=[Depends(require_system_perm("dict:type-manage"))],
)
def delete_type(code: str) -> ApiResponse:
    DictService().delete_type(code)
    return ok(msg="已删除")


@router.get(
    "/items",
    response_model=ApiResponse,
    dependencies=[Depends(require_system_perm("dict:view"))],
)
def list_items(
    type_code: str,
    q: str | None = None,
    enabled: bool | None = None,
    page: int = 1,
    size: int = 50,
    sort_by: str = "sort",
    sort_order: str = "asc",
) -> ApiResponse:
    return ok(DictService().list_items(
        type_code=type_code,
        q=q,
        enabled=enabled,
        page=page,
        size=size,
        sort_by=sort_by,
        sort_order=sort_order,
    ))


@router.get(
    "/items/public",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm("dict:read"))],
)
def public_items(type_code: str) -> ApiResponse:
    return ok(DictService().get_enabled_items(type_code))


@router.post(
    "/items",
    response_model=ApiResponse,
    dependencies=[Depends(require_system_perm("dict:item-manage"))],
)
def create_item(body: DictItemCreate) -> ApiResponse:
    return ok(DictService().create_item(
        type_code=body.type_code,
        code=body.code,
        label=body.label,
        enabled=body.enabled,
        sort=body.sort,
        remark=body.remark,
    ), msg="已创建")


@router.put(
    "/items/{type_code}/{code}",
    response_model=ApiResponse,
    dependencies=[Depends(require_system_perm("dict:item-manage"))],
)
def update_item(type_code: str, code: str, body: DictItemUpdate) -> ApiResponse:
    return ok(DictService().update_item(
        type_code,
        code,
        body_type_code=body.type_code,
        body_code=body.code,
        label=body.label,
        enabled=body.enabled,
        sort=body.sort,
        remark=body.remark,
    ), msg="已保存")


@router.delete(
    "/items/{type_code}/{code}",
    response_model=ApiResponse,
    dependencies=[Depends(require_system_perm("dict:item-manage"))],
)
def delete_item(type_code: str, code: str) -> ApiResponse:
    DictService().delete_item(type_code, code)
    return ok(msg="已删除")
