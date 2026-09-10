"""买卖指标方案 API（v2.0 §6，M2.3）——CRUD + 版本 + 条件试算预览。"""

from __future__ import annotations

from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator

from backend.api.response import ApiResponse, err, ok
from backend.auth.context import get_current_context
from backend.auth.deps import require_perm, require_visibility_perm
from backend.services.asset_audit import record_asset_copy_audit, record_asset_visibility_audit
from backend.services.asset_visibility import normalize_visibility
from backend.signals.trade_profile import (
    TradeProfileRepo,
    collect_indicators,
    eval_conditions,
)
from backend.storage import get_read_client as get_client

router = APIRouter(prefix="/api", tags=["trade-profiles"])


class TradeProfileBody(BaseModel):
    id: str | None = None
    name: str
    buy_tree: dict
    sell_tree: dict | None = None
    backstop: dict | None = None


class TradeProfileVisibilityBody(BaseModel):
    visibility: str

    @field_validator("visibility", mode="before")
    @classmethod
    def _normalize_visibility(cls, value):
        if value is None:
            raise ValueError("visibility 必须是 private、tenant 或 public")
        return normalize_visibility(str(value))


class TradeProfileCopyBody(BaseModel):
    # C8：前端不再传 id，后端自动生成唯一 id + 名称「原名 副本」；name 可选
    name: str | None = None
    version: int | None = None


def _has_perm(code: str) -> bool:
    ctx = get_current_context()
    if ctx is None:
        return False
    return ctx.is_system or code in ctx.resources


@router.get("/trade-profiles", response_model=ApiResponse,
            dependencies=[Depends(require_perm("trade-profile:view"))])
def list_trade_profiles(
    source: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse:
    # source=mine：下拉只加载自己的资产（纯 owner，R3/C2）；
    # source=preset|tenant|public：搜索弹窗浏览（分页 + q，R5/R14）；不传维持 list_visible 兼容
    repo = TradeProfileRepo()
    if source is not None and source not in ("mine", "preset", "tenant", "public"):
        return err(400, "source 必须是 mine、preset、tenant 或 public")
    if source == "mine":
        return ok(repo.list_mine())
    if source in ("preset", "tenant", "public"):
        return ok(repo.browse(source, q=q, page=page, page_size=page_size))
    return ok(repo.list_visible())


@router.get("/trade-profiles/{pid}", response_model=ApiResponse,
            dependencies=[Depends(require_perm("trade-profile:view"))])
def get_trade_profile(pid: str) -> ApiResponse:
    p = TradeProfileRepo().get_visible(pid)
    return ok(p) if p else err(404, "方案不存在")


@router.get("/trade-profiles/{pid}/versions", response_model=ApiResponse,
            dependencies=[Depends(require_perm("trade-profile:view"))])
def trade_profile_versions(pid: str) -> ApiResponse:
    data = TradeProfileRepo().versions_visible(pid)
    return ok(data) if data else err(404, "方案不存在")


@router.post("/trade-profiles", response_model=ApiResponse,
             dependencies=[Depends(require_perm("trade-profile:save"))])
def save_trade_profile(body: TradeProfileBody) -> ApiResponse:
    try:
        pid, v = TradeProfileRepo().save_with_id(
            body.id, body.name, body.buy_tree, body.sell_tree, body.backstop)
    except ValueError as e:
        return err(400, str(e))
    return ok({"id": pid, "version": v, "msg": "已保存"})


@router.delete("/trade-profiles/{pid}", response_model=ApiResponse,
               dependencies=[Depends(require_perm("trade-profile:delete"))])
def delete_trade_profile(pid: str) -> ApiResponse:
    repo = TradeProfileRepo()
    p = repo.get_visible(pid, include_owner=True)
    if not p:
        return err(404, "方案不存在")
    if p.get("readonly"):
        return err(403, "只能删除自己的买卖方案")
    try:
        repo.delete(p["id"])
    except ValueError as e:
        return err(409, str(e))
    return ok({"msg": "已删除"})


@router.post("/trade-profiles/{pid}/visibility", response_model=ApiResponse,
             dependencies=[Depends(require_visibility_perm(
                 "trade-profile:view",
                 "trade-profile:publish-tenant",
                 "trade-profile:publish-public",
             ))])
def set_trade_profile_visibility(pid: str, body: TradeProfileVisibilityBody) -> ApiResponse:
    visibility = body.visibility
    if visibility == "tenant" and not _has_perm("trade-profile:publish-tenant"):
        return err(403, "无权公开到租户")
    if visibility == "public" and not _has_perm("trade-profile:publish-public"):
        return err(403, "无权公开到全体用户")
    repo = TradeProfileRepo()
    before = repo.get_visible(pid, include_owner=True)
    if not before:
        return err(404, "方案不存在")
    try:
        p = repo.set_visibility(pid, visibility, published_by=get_current_context().user_id)  # type: ignore[union-attr]
    except ValueError as e:
        return err(400, str(e))
    except PermissionError as e:
        return err(403, str(e))
    if not p:
        return err(404, "方案不存在")
    record_asset_visibility_audit(
        before,
        p,
        action="trade_profile_visibility",
        target_type="trade_profile",
        ref_key="profile_ref",
        fallback_resource_prefix="trade-profile",
        affected_count=int(p.get("affected_run_count") or 0),
    )
    return ok(p)


@router.post("/trade-profiles/{pid}/copy", response_model=ApiResponse,
             dependencies=[Depends(require_perm("trade-profile:save"))])
def copy_trade_profile(pid: str, body: TradeProfileCopyBody) -> ApiResponse:
    repo = TradeProfileRepo()
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
        action="trade_profile_copy",
        target_type="trade_profile",
        resource_code="trade-profile:save",
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


@router.post("/trade-profiles/preview", response_model=ApiResponse,
             dependencies=[Depends(require_perm("trade-profile:preview"))])
def preview_conditions(body: dict) -> ApiResponse:
    """对某交易日全市场(排除 ST)试算一棵条件树的命中 → 命中数 + 样例。

    body: {tree, run_date?, top?}
    """
    from backend.indicators.engine import IndicatorEngine

    tree = body.get("tree")
    if not tree:
        return ok({"hit": 0, "list": []})
    c = get_client()
    run_date = (date.fromisoformat(body["run_date"]) if body.get("run_date")
                else pd.Timestamp(c.query_df("SELECT max(trade_date) d FROM daily_bar").iloc[0]["d"]).date())
    top = int(body.get("top", 30))

    eng = IndicatorEngine(c)
    snap = eng.wide_snapshot(run_date, run_date)
    if snap.empty:
        return ok({"run_date": str(run_date), "hit": 0, "list": []})
    snap = snap.set_index("code")
    from backend.services.stock_st_status import StockSTStatusService

    statuses = StockSTStatusService(c).status_map(run_date, snap.index.astype(str).tolist())
    st = {code for code, is_st in statuses.items() if is_st}
    snap = snap[~snap.index.isin(st)]
    try:
        eng.attach_columns(snap, collect_indicators(tree), run_date)
        hit = eval_conditions(tree, snap)
    except (ValueError, KeyError) as e:
        return err(400, f"条件无法求值: {e}")
    codes = list(snap.index[hit.values])
    sample = codes[:top]
    names = (c.query_df(
        f"SELECT code, name FROM stock_basic WHERE code IN ({','.join('?' * len(sample))})", sample)
        if sample else pd.DataFrame(columns=["code", "name"]))
    nm = dict(zip(names["code"], names["name"]))
    return ok({"run_date": str(run_date), "hit": len(codes),
               "list": [{"code": x, "name": nm.get(x)} for x in sample]})
