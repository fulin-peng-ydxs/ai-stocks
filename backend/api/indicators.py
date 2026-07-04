"""技术指标定义 API（M2.1b）——统一管理内置 + 自定义指标:目录 / 新建 / 启停 / 删除。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.response import ApiResponse, err, ok
from backend.auth.deps import require_perm, require_system
from backend.indicators.definition import IndicatorDefRepo

router = APIRouter(prefix="/api", tags=["indicators"])


class IndicatorDefBody(BaseModel):
    key: str
    name_cn: str
    dtype: str                       # bool | number
    expression: str                  # DSL 表达式模板，含 {param} 占位
    params: list[dict] | None = None
    category: str = "自定义"
    direction: str | None = None
    desc: str = ""
    categories: list[str] | None = None


class EnabledBody(BaseModel):
    enabled: bool


class CategoriesBody(BaseModel):
    categories: list[str]


@router.get("/indicators/registry", response_model=ApiResponse,
            dependencies=[Depends(require_perm("indicator:registry"))])
def indicators_registry(include_disabled: bool = True) -> ApiResponse:
    """技术指标目录（内置 + 自定义）。include_disabled=false 只返回启用项（供选择列表）。"""
    items = IndicatorDefRepo().list(include_disabled=include_disabled)
    return ok({"count": len(items), "items": items})


@router.post("/indicators/def", response_model=ApiResponse, dependencies=[Depends(require_system)])
def save_indicator_def(body: IndicatorDefBody) -> ApiResponse:
    try:
        IndicatorDefRepo().save_custom(
            body.key, body.name_cn, body.dtype, body.expression,
            params=body.params, category=body.category, direction=body.direction,
            desc=body.desc, categories=body.categories)
    except ValueError as e:
        return err(400, str(e))
    return ok({"key": body.key, "msg": "已保存"})


@router.patch("/indicators/def/{key}/enabled", response_model=ApiResponse,
              dependencies=[Depends(require_system)])
def set_indicator_enabled(key: str, body: EnabledBody) -> ApiResponse:
    IndicatorDefRepo().set_enabled(key, body.enabled)
    return ok({"key": key, "enabled": body.enabled})


@router.patch("/indicators/def/{key}/categories", response_model=ApiResponse,
              dependencies=[Depends(require_system)])
def set_indicator_categories(key: str, body: CategoriesBody) -> ApiResponse:
    """设置指标的分类标签（多分类,可自定义；内置指标也可改）。"""
    IndicatorDefRepo().set_categories(key, body.categories)
    return ok({"key": key, "categories": body.categories})


@router.delete("/indicators/def/{key}", response_model=ApiResponse, dependencies=[Depends(require_system)])
def delete_indicator_def(key: str) -> ApiResponse:
    try:
        IndicatorDefRepo().delete(key)
    except ValueError as e:
        return err(400, str(e))
    return ok({"msg": "已删除"})
