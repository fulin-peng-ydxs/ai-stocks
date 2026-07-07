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
from backend.storage import get_client

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
    id: str
    name: str | None = None


def _has_perm(code: str) -> bool:
    ctx = get_current_context()
    if ctx is None:
        return False
    return ctx.is_system or code in ctx.resources


@router.get("/trade-profiles", response_model=ApiResponse,
            dependencies=[Depends(require_perm("trade-profile:view"))])
def list_trade_profiles() -> ApiResponse:
    return ok(TradeProfileRepo().list_visible())


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
    repo.delete(p["id"])
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
        version = repo.copy_visible(pid, body.id, body.name)
    except ValueError as e:
        msg = str(e)
        return err(409 if "已存在" in msg else 404, msg)
    copied = repo.get_visible(body.id, include_owner=True)
    record_asset_copy_audit(
        source,
        copied,
        action="trade_profile_copy",
        target_type="trade_profile",
        resource_code="trade-profile:save",
        ref_key="profile_ref",
    )
    return ok({"id": body.id, "version": version, "msg": "已复制"})


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
    st = set(c.query_df("SELECT code FROM stock_basic WHERE name LIKE '%ST%'")["code"])
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
