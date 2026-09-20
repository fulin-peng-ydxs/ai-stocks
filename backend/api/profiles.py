"""筛选方案 CRUD + 运行筛选 API（SDD §12，T-M3-8）。"""

from __future__ import annotations

from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator

from backend.api.response import ApiResponse, err, ok
from backend.auth.context import get_current_context
from backend.auth.deps import require_perm, require_visibility_perm
from backend.common.exceptions import NotFoundError, ValidationError
from backend.screening.condition import ConditionError, validate_ast
from backend.screening.profile import ProfileRepo
from backend.services.asset_audit import record_asset_copy_audit, record_asset_visibility_audit
from backend.services.asset_visibility import normalize_visibility
from backend.services.screen_score import ScreenScoreService
from backend.storage import get_pg_client
from backend.storage import get_read_client as get_client

router = APIRouter(prefix="/api", tags=["screening"])


class ProfileIn(BaseModel):
    id: str | None = None
    name: str
    expression: dict
    params: dict | None = None


class ProfileVisibilityBody(BaseModel):
    visibility: str

    @field_validator("visibility", mode="before")
    @classmethod
    def _normalize_visibility(cls, value):
        if value is None:
            raise ValueError("visibility 必须是 private、tenant 或 public")
        return normalize_visibility(str(value))


class ProfileCopyBody(BaseModel):
    # C8：前端不再传 id，后端自动生成唯一 id + 名称「原名 副本」；name 可选
    name: str | None = None
    version: int | None = None


class ScreenRunIn(BaseModel):
    profile_id: str | None = None
    expression: dict | None = None  # 临时方案（不存库）直接跑
    run_date: str | None = None     # YYYY-MM-DD，默认最新交易日
    exclude_st: bool = True         # 默认排除 ST
    score_profile_id: str | None = None


class ScreenRankIn(BaseModel):
    run_date: str
    score_profile_id: str | None = None
    codes: list[str]
    exclude_st: bool = False


def _latest_date() -> date:
    d = get_client().query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]
    return pd.Timestamp(d).date()


def _has_perm(code: str) -> bool:
    ctx = get_current_context()
    if ctx is None:
        return False
    return ctx.is_system or code in ctx.resources


def _attach_current_user_groups(rows: list[dict]) -> None:
    """按当前请求归属批量附加自选分组；无查看权限时保持统一空数组。"""
    if not rows or not _has_perm("stock-group:view"):
        return
    from backend.groups.stock_group import StockGroupRepo

    market = get_client()
    groups_by_code = StockGroupRepo(pg=get_pg_client(), market=market).groups_for_codes(
        [str(row["code"]) for row in rows]
    )
    for row in rows:
        row["groups"] = groups_by_code.get(str(row["code"]), [])


@router.get("/profiles", response_model=ApiResponse,
            dependencies=[Depends(require_perm("screen-profile:view"))])
def list_profiles(
    source: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse:
    # source=mine：下拉只加载自己的资产（纯 owner，R3/C2）；
    # source=preset|tenant|public：搜索弹窗浏览（分页 + q，R5/R14）；不传维持 list_visible 兼容
    repo = ProfileRepo()
    if source is not None and source not in ("mine", "preset", "tenant", "public"):
        return err(400, "source 必须是 mine、preset、tenant 或 public")
    if source == "mine":
        return ok(repo.list_mine())
    if source in ("preset", "tenant", "public"):
        return ok(repo.browse(source, q=q, page=page, page_size=page_size))
    return ok(repo.list_visible())


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
    try:
        pid, version = ProfileRepo().save_with_id(body.id, body.name, body.expression, body.params)
    except ValueError as e:
        return err(400, str(e))
    return ok({"id": pid, "version": version}, msg="已保存")


@router.delete("/profiles/{pid}", response_model=ApiResponse,
               dependencies=[Depends(require_perm("screen-profile:delete"))])
def delete_profile(pid: str) -> ApiResponse:
    repo = ProfileRepo()
    p = repo.get_visible(pid, include_owner=True)
    if not p:
        raise NotFoundError(f"方案不存在: {pid}")
    if p.get("readonly"):
        return err(403, "只能删除自己的筛选方案")
    try:
        repo.delete(p["id"])   # 走 PG 资产仓库（按归属删方案 + 版本历史）
    except ValueError as e:
        return err(409, str(e))
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
        affected_count=int(p.get("affected_run_count") or 0),
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
        result = repo.copy_visible(pid, body.name, body.version)
    except ValueError as e:
        msg = str(e)
        return err(409 if ("已存在" in msg or "冲突" in msg) else 404, msg)
    copied = repo.get_visible(result["profile_ref"], include_owner=True)
    record_asset_copy_audit(
        source,
        copied,
        action="screen_profile_copy",
        target_type="screen_profile",
        resource_code="screen-profile:save",
        ref_key="profile_ref",
        source_version=body.version,
    )
    return ok({
        "id": result["id"],
        "profile_ref": result["profile_ref"],
        "name": result["name"],
        "version": result["version"],
        "source_version": result.get("source_version"),
        "msg": "已复制",
    })


@router.post("/screen/run", response_model=ApiResponse,
             dependencies=[
                 Depends(require_perm("screen:run")),
                 Depends(require_perm("score-profile:view")),
             ])
def run_screen(body: ScreenRunIn) -> ApiResponse:
    run_date = date.fromisoformat(body.run_date) if body.run_date else _latest_date()
    if not body.profile_id and not body.expression:
        raise ValidationError("需提供 profile_id 或 expression")
    if not (body.score_profile_id or "").strip():
        raise ValidationError("请选择评分方案")
    if body.expression is not None:
        try:
            validate_ast(body.expression)
        except ConditionError as e:
            raise ValidationError(f"条件非法: {e}") from e
    # 命中 + 榜单同款评分 + ST 标记/排除 + 按综合分降序
    try:
        result = ScreenScoreService().screen_scored(
            run_date, profile_id=body.profile_id, expression=body.expression,
            score_profile_id=body.score_profile_id,
            exclude_st=body.exclude_st,
        )
    except ValueError as exc:
        if "不存在或不可见" in str(exc):
            return err(404, str(exc))
        raise ValidationError(str(exc)) from exc
    _attach_current_user_groups(result["hits"])
    return ok({**result, "count": len(result["hits"])})


@router.post("/screen/rank", response_model=ApiResponse,
             dependencies=[
                 Depends(require_perm("screen:run")),
                 Depends(require_perm("score-profile:view")),
             ])
def rank_screen_candidates(body: ScreenRankIn) -> ApiResponse:
    """按新评分方案重排当前页面候选集合，不重新执行筛选条件。"""
    if not (body.score_profile_id or "").strip():
        raise ValidationError("请选择评分方案")
    try:
        run_date = date.fromisoformat(body.run_date)
    except ValueError as exc:
        raise ValidationError("run_date 必须是 YYYY-MM-DD") from exc
    try:
        result = ScreenScoreService().rank_codes(
            run_date,
            score_profile_id=body.score_profile_id,
            codes=body.codes,
            exclude_st=body.exclude_st,
        )
    except ValueError as exc:
        if "不存在或不可见" in str(exc):
            return err(404, str(exc))
        raise ValidationError(str(exc)) from exc
    _attach_current_user_groups(result["hits"])
    return ok({**result, "count": len(result["hits"])})
