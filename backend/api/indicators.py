"""技术指标定义 API（M2.1b）——统一管理内置 + 自定义指标:目录 / 新建 / 启停 / 删除。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.api.response import ApiResponse, err, ok
from backend.auth.deps import require_perm, require_system_perm
from backend.indicators.definition import IndicatorDefRepo
from backend.services.indicator_definition_service import (
    IndicatorDefinitionService,
    IndicatorReferenceError,
)

router = APIRouter(prefix="/api", tags=["indicators"])


class IndicatorParamBody(BaseModel):
    name: str
    label: str
    type: str
    default: float | int
    min: float | int | None = None
    max: float | int | None = None
    unit: str = ""
    description: str = ""


class IndicatorDefBody(BaseModel):
    key: str
    name_cn: str
    dtype: str                       # bool | number
    expression: str                  # DSL 表达式模板，含 {param} 占位
    params: list[IndicatorParamBody] | None = None
    category: str = "自定义"
    direction: str | None = None
    desc: str = ""
    categories: list[str] | None = None


class EnabledBody(BaseModel):
    enabled: bool


class CategoriesBody(BaseModel):
    categories: list[str]


class IndicatorPreviewBody(BaseModel):
    dtype: str
    expression: str
    params: list[IndicatorParamBody] | None = None
    values: dict[str, float | int] = Field(default_factory=dict)
    code: str
    trade_date: date | None = None


CUSTOM_INDICATOR_TEMPLATES = [
    {"key": "range_position", "name": "区间位置", "dtype": "number",
     "expression": "(C - LLV(L, {window})) / (HHV(H, {window}) - LLV(L, {window})) * 100",
     "params": [{"name": "window", "label": "统计周期", "type": "int", "default": 60,
                 "min": 2, "max": 1200, "unit": "交易日", "description": "价格区间的回看长度"}]},
    {"key": "distance_to_high", "name": "距N日高点", "dtype": "number",
     "expression": "(HHV(H, {window}) - C) / HHV(H, {window}) * 100",
     "params": [{"name": "window", "label": "统计周期", "type": "int", "default": 240,
                 "min": 2, "max": 1200, "unit": "交易日", "description": "高点的回看长度"}]},
    {"key": "ma_spread", "name": "快慢均线差", "dtype": "number",
     "expression": "(MA(C, {fast}) / MA(C, {slow}) - 1) * 100",
     "params": [
         {"name": "fast", "label": "快线周期", "type": "int", "default": 20,
          "min": 2, "max": 500, "unit": "交易日", "description": "较短均线周期"},
         {"name": "slow", "label": "慢线周期", "type": "int", "default": 60,
          "min": 3, "max": 1000, "unit": "交易日", "description": "较长均线周期"},
     ]},
]


@router.get("/indicators/registry", response_model=ApiResponse,
            dependencies=[Depends(require_perm("indicator:registry"))])
def indicators_registry(include_disabled: bool = True) -> ApiResponse:
    """技术指标目录（内置 + 自定义）。include_disabled=false 只返回启用项（供选择列表）。"""
    items = IndicatorDefRepo().list(include_disabled=include_disabled)
    return ok({"count": len(items), "items": items, "templates": CUSTOM_INDICATOR_TEMPLATES})


@router.post("/indicators/def", response_model=ApiResponse,
             dependencies=[Depends(require_system_perm("indicator:def-manage"))])
def save_indicator_def(body: IndicatorDefBody) -> ApiResponse:
    try:
        item = IndicatorDefinitionService().save(body.model_dump())
    except ValueError as e:
        return err(409 if "引用" in str(e) else 400, str(e))
    return ok({"key": body.key, "msg": "已保存", "item": item})


@router.patch("/indicators/def/{key}", response_model=ApiResponse,
              dependencies=[Depends(require_system_perm("indicator:def-manage"))])
def update_indicator_def(key: str, body: IndicatorDefBody) -> ApiResponse:
    if body.key != key:
        return err(400, "指标 key 不可修改；请另存为新指标")
    try:
        item = IndicatorDefinitionService().save(body.model_dump(), key=key)
    except LookupError as e:
        return err(404, str(e))
    except ValueError as e:
        return err(409 if "引用" in str(e) else 400, str(e))
    return ok({"key": key, "msg": "已保存", "item": item})


@router.post("/indicators/def/preview", response_model=ApiResponse,
             dependencies=[Depends(require_system_perm("indicator:def-manage"))])
def preview_indicator_def(body: IndicatorPreviewBody) -> ApiResponse:
    try:
        return ok(IndicatorDefinitionService().preview(body.model_dump()))
    except ValueError as e:
        return err(400, str(e))


@router.get("/indicators/def/{key}/references", response_model=ApiResponse,
            dependencies=[Depends(require_system_perm("indicator:def-manage"))])
def indicator_def_references(key: str) -> ApiResponse:
    if IndicatorDefRepo().get(key) is None:
        return err(404, "指标不存在")
    return ok(IndicatorDefinitionService().references(key))


@router.patch("/indicators/def/{key}/enabled", response_model=ApiResponse,
              dependencies=[Depends(require_system_perm("indicator:def-manage"))])
def set_indicator_enabled(key: str, body: EnabledBody) -> ApiResponse:
    IndicatorDefRepo().set_enabled(key, body.enabled)
    return ok({"key": key, "enabled": body.enabled})


@router.patch("/indicators/def/{key}/categories", response_model=ApiResponse,
              dependencies=[Depends(require_system_perm("indicator:def-manage"))])
def set_indicator_categories(key: str, body: CategoriesBody) -> ApiResponse:
    """设置指标的分类标签（多分类,可自定义；内置指标也可改）。"""
    IndicatorDefRepo().set_categories(key, body.categories)
    return ok({"key": key, "categories": body.categories})


@router.delete("/indicators/def/{key}", response_model=ApiResponse,
               dependencies=[Depends(require_system_perm("indicator:def-manage"))])
def delete_indicator_def(key: str) -> ApiResponse:
    try:
        IndicatorDefinitionService().delete(key)
    except LookupError as e:
        return err(404, str(e))
    except IndicatorReferenceError as e:
        return err(409, str(e), e.references)
    except ValueError as e:
        return err(400, str(e))
    return ok({"msg": "已删除"})
