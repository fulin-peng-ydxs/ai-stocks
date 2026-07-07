"""筛选方案 CRUD + 运行筛选 API（SDD §12，T-M3-8）。"""

from __future__ import annotations

from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.response import ApiResponse, err, ok
from backend.auth.context import get_current_context
from backend.auth.deps import require_perm, require_visibility_perm
from backend.common.exceptions import NotFoundError, ValidationError
from backend.screening.condition import ConditionError, validate_ast
from backend.screening.profile import ProfileRepo
from backend.services.asset_audit import record_asset_copy_audit, record_asset_visibility_audit
from backend.services.screen_score import ScreenScoreService
from backend.storage import get_client

router = APIRouter(prefix="/api", tags=["screening"])


class ProfileIn(BaseModel):
    id: str
    name: str
    expression: dict
    params: dict | None = None


class ProfileVisibilityBody(BaseModel):
    visibility: str


class ProfileCopyBody(BaseModel):
    id: str
    name: str | None = None


class ScreenRunIn(BaseModel):
    profile_id: str | None = None
    expression: dict | None = None  # 临时方案（不存库）直接跑
    run_date: str | None = None     # YYYY-MM-DD，默认最新交易日
    exclude_st: bool = True         # 默认排除 ST


def _latest_date() -> date:
    d = get_client().query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]
    return pd.Timestamp(d).date()


def _has_perm(code: str) -> bool:
    ctx = get_current_context()
    if ctx is None:
        return False
    return ctx.is_system or code in ctx.resources


@router.get("/profiles", response_model=ApiResponse,
            dependencies=[Depends(require_perm("screen-profile:view"))])
def list_profiles() -> ApiResponse:
    return ok(ProfileRepo().list_visible())


@router.get("/profiles/{pid}", response_model=ApiResponse,
            dependencies=[Depends(require_perm("screen-profile:view"))])
def get_profile(pid: str) -> ApiResponse:
    p = ProfileRepo().get_visible(pid)
    if not p:
        raise NotFoundError(f"方案不存在: {pid}")
    return ok(p)


@router.get("/profiles/{pid}/versions", response_model=ApiResponse,
            dependencies=[Depends(require_perm("screen-profile:view"))])
def profile_versions(pid: str) -> ApiResponse:
    """方案历史版本（T-M6-7，回看/恢复对比）。"""
    data = ProfileRepo().versions_visible(pid)
    if not data:
        raise NotFoundError(f"方案不存在: {pid}")
    return ok(data)


@router.post("/profiles", response_model=ApiResponse,
             dependencies=[Depends(require_perm("screen-profile:save"))])
def upsert_profile(body: ProfileIn) -> ApiResponse:
    try:
        validate_ast(body.expression)
    except ConditionError as e:
        raise ValidationError(f"条件非法: {e}") from e
    version = ProfileRepo().save(body.id, body.name, body.expression, body.params)
    return ok({"id": body.id, "version": version}, msg="已保存")


@router.delete("/profiles/{pid}", response_model=ApiResponse,
               dependencies=[Depends(require_perm("screen-profile:delete"))])
def delete_profile(pid: str) -> ApiResponse:
    repo = ProfileRepo()
    p = repo.get_visible(pid, include_owner=True)
    if not p:
        raise NotFoundError(f"方案不存在: {pid}")
    if p.get("readonly"):
        return err(403, "只能删除自己的筛选方案")
    repo.delete(p["id"])   # 走 PG 资产仓库（按归属删方案 + 版本历史）
    return ok(msg="已删除")


@router.post("/profiles/{pid}/visibility", response_model=ApiResponse,
             dependencies=[Depends(require_visibility_perm(
                 "screen-profile:view",
                 "screen-profile:publish-tenant",
                 "screen-profile:publish-public",
             ))])
def set_profile_visibility(pid: str, body: ProfileVisibilityBody) -> ApiResponse:
    visibility = body.visibility
    if visibility == "tenant" and not _has_perm("screen-profile:publish-tenant"):
        return err(403, "无权公开到租户")
    if visibility == "public" and not _has_perm("screen-profile:publish-public"):
        return err(403, "无权公开到全体用户")
    repo = ProfileRepo()
    before = repo.get_visible(pid, include_owner=True)
    if not before:
        raise NotFoundError(f"方案不存在: {pid}")
    try:
        p = repo.set_visibility(pid, visibility, published_by=get_current_context().user_id)  # type: ignore[union-attr]
    except ValueError as e:
        return err(400, str(e))
    except PermissionError as e:
        return err(403, str(e))
    if not p:
        raise NotFoundError(f"方案不存在: {pid}")
    record_asset_visibility_audit(
        before,
        p,
        action="screen_profile_visibility",
        target_type="screen_profile",
        ref_key="profile_ref",
        fallback_resource_prefix="screen-profile",
    )
    return ok(p)


@router.post("/profiles/{pid}/copy", response_model=ApiResponse,
             dependencies=[Depends(require_perm("screen-profile:save"))])
def copy_profile(pid: str, body: ProfileCopyBody) -> ApiResponse:
    repo = ProfileRepo()
    source = repo.get_visible(pid, include_owner=True)
    if not source:
        return err(404, "方案不存在")
    try:
        version = repo.copy_visible(pid, body.id, body.name)
    except ValueError as e:
        msg = str(e)
        return err(409 if "已存在" in msg else 404, msg)
    copied = repo.get_visible(body.id, include_owner=True)
    record_asset_copy_audit(
        source,
        copied,
        action="screen_profile_copy",
        target_type="screen_profile",
        resource_code="screen-profile:save",
        ref_key="profile_ref",
    )
    return ok({"id": body.id, "version": version, "msg": "已复制"})


@router.post("/screen/run", response_model=ApiResponse,
             dependencies=[Depends(require_perm("screen:run"))])
def run_screen(body: ScreenRunIn) -> ApiResponse:
    run_date = date.fromisoformat(body.run_date) if body.run_date else _latest_date()
    if not body.profile_id and not body.expression:
        raise ValidationError("需提供 profile_id 或 expression")
    if body.expression is not None:
        try:
            validate_ast(body.expression)
        except ConditionError as e:
            raise ValidationError(f"条件非法: {e}") from e
    # 命中 + 榜单同款评分 + ST 标记/排除 + 按综合分降序
    hits = ScreenScoreService().screen_scored(
        run_date, profile_id=body.profile_id, expression=body.expression,
        exclude_st=body.exclude_st,
    )
    return ok({
        "run_date": str(run_date),
        "count": len(hits),
        "exclude_st": body.exclude_st,
        "hits": hits,
    })
