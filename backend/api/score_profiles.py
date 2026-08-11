"""评分规则方案 API（v2.0 §7）——CRUD + 版本 + 按方案试算榜单。"""

from __future__ import annotations

from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator

from backend.api.response import ApiResponse, err, ok
from backend.auth.context import get_current_context
from backend.auth.deps import require_perm, require_visibility_perm
from backend.scoring.score_profile import ScoreProfileRepo
from backend.services.asset_audit import record_asset_copy_audit, record_asset_visibility_audit
from backend.services.asset_visibility import normalize_visibility
from backend.storage import get_client

router = APIRouter(prefix="/api", tags=["score-profiles"])


class ScoreProfileBody(BaseModel):
    id: str | None = None
    name: str
    items: list[dict]
    grade_thresholds: dict | None = None


class ScoreProfileVisibilityBody(BaseModel):
    visibility: str

    @field_validator("visibility", mode="before")
    @classmethod
    def _normalize_visibility(cls, value):
        if value is None:
            raise ValueError("visibility 必须是 private、tenant 或 public")
        return normalize_visibility(str(value))


class ScoreProfileCopyBody(BaseModel):
    # C8：前端不再传 id，后端自动生成唯一 id + 名称「原名 副本」；name 可选（一般也不传）
    name: str | None = None
    version: int | None = None


def _has_perm(code: str) -> bool:
    ctx = get_current_context()
    if ctx is None:
        return False
    return ctx.is_system or code in ctx.resources


@router.get("/score-profiles", response_model=ApiResponse,
            dependencies=[Depends(require_perm("score-profile:view"))])
def list_score_profiles(
    source: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse:
    # source=mine：下拉只加载自己的资产（纯 owner，R3/C2）；
    # source=preset|tenant|public：搜索弹窗浏览（分页 + q，R5/R14）；
    # 不传维持 list_visible 兼容。复用 score-profile:view 守卫，不新增端点/资源码。
    if source is not None and source not in ("mine", "preset", "tenant", "public"):
        return err(400, "source 必须是 mine、preset、tenant 或 public")
    repo = ScoreProfileRepo()
    if source == "mine":
        return ok(repo.list_mine())
    if source in ("preset", "tenant", "public"):
        return ok(repo.browse(source, q=q, page=page, page_size=page_size))
    return ok(repo.list_visible())


@router.get("/score-profiles/{pid}", response_model=ApiResponse,
            dependencies=[Depends(require_perm("score-profile:view"))])
def get_score_profile(pid: str) -> ApiResponse:
    p = ScoreProfileRepo().get_visible(pid)
    return ok(p) if p else err(404, "方案不存在")


@router.get("/score-profiles/{pid}/versions", response_model=ApiResponse,
            dependencies=[Depends(require_perm("score-profile:view"))])
def score_profile_versions(pid: str) -> ApiResponse:
    data = ScoreProfileRepo().versions_visible(pid)
    return ok(data) if data else err(404, "方案不存在")


@router.post("/score-profiles", response_model=ApiResponse,
             dependencies=[Depends(require_perm("score-profile:save"))])
def save_score_profile(body: ScoreProfileBody) -> ApiResponse:
    try:
        pid, v = ScoreProfileRepo().save_with_id(body.id, body.name, body.items, body.grade_thresholds)
    except ValueError as e:
        return err(400, str(e))
    return ok({"id": pid, "version": v, "msg": "已保存"})


@router.delete("/score-profiles/{pid}", response_model=ApiResponse,
               dependencies=[Depends(require_perm("score-profile:delete"))])
def delete_score_profile(pid: str) -> ApiResponse:
    repo = ScoreProfileRepo()
    p = repo.get_visible(pid, include_owner=True)
    if not p:
        return err(404, "方案不存在")
    if p.get("readonly"):
        return err(403, "只能删除自己的评分方案")
    try:
        repo.delete(p["id"])
    except ValueError as e:
        return err(409, str(e))
    return ok({"msg": "已删除"})


@router.post("/score-profiles/{pid}/visibility", response_model=ApiResponse,
             dependencies=[Depends(require_visibility_perm(
                 "score-profile:view",
                 "score-profile:publish-tenant",
                 "score-profile:publish-public",
             ))])
def set_score_profile_visibility(pid: str, body: ScoreProfileVisibilityBody) -> ApiResponse:
    visibility = body.visibility
    if visibility == "tenant" and not _has_perm("score-profile:publish-tenant"):
        return err(403, "无权公开到租户")
    if visibility == "public" and not _has_perm("score-profile:publish-public"):
        return err(403, "无权公开到全体用户")
    repo = ScoreProfileRepo()
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
        action="score_profile_visibility",
        target_type="score_profile",
        ref_key="profile_ref",
        fallback_resource_prefix="score-profile",
        affected_count=int(p.get("affected_run_count") or 0),
    )
    return ok(p)


@router.post("/score-profiles/{pid}/copy", response_model=ApiResponse,
             dependencies=[Depends(require_perm("score-profile:save"))])
def copy_score_profile(pid: str, body: ScoreProfileCopyBody) -> ApiResponse:
    repo = ScoreProfileRepo()
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
        action="score_profile_copy",
        target_type="score_profile",
        resource_code="score-profile:save",
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


@router.post("/score-profiles/run", response_model=ApiResponse,
             dependencies=[Depends(require_perm("score:run"))])
def run_score_profile(body: dict) -> ApiResponse:
    """按评分方案对某交易日全市场（排除 ST）打分排序，返回 Top N。

    body: {profile_id | items+grade_thresholds, run_date?, top?}
    - 已保存方案(profile_id)：走**评分快照层**（§10.1，命中即用/失效重算），与各评分入口同一缓存口径。
    - 未保存方案(inline items)：无版本可缓存，当场实时算（配置页编辑试算）。
    """
    import json

    from backend.scoring.snapshot import ScoreSnapshotRepo, score_day

    c = get_client()
    repo = ScoreProfileRepo()
    run_date = (date.fromisoformat(body["run_date"]) if body.get("run_date")
                else pd.Timestamp(c.query_df("SELECT max(trade_date) d FROM daily_bar").iloc[0]["d"]).date())
    top = int(body.get("top", 50))

    if body.get("profile_id"):
        prof = repo.get_visible(body["profile_id"], include_owner=True)
        if not prof:
            return err(404, "方案不存在")
        board = ScoreSnapshotRepo(
            c,
            tenant_id=prof["tenant_id"],
            owner_user_id=prof["owner_user_id"],
        ).get_board(run_date, prof["id"], top=top, profile=prof)
    else:
        # 未保存方案：实时打分（不入快照，无版本键）
        prof = {"items": body.get("items", []), "grade_thresholds": body.get("grade_thresholds")}
        try:
            board = score_day(c, run_date, prof).head(top)
        except ValueError as e:
            return err(400, str(e))

    if board.empty:
        return ok({"run_date": str(run_date), "top": top, "count": 0, "list": []})
    codes = board["code"].tolist()
    names = c.query_df(
        f"SELECT code, name FROM stock_basic WHERE code IN ({','.join('?' * len(codes))})", codes)
    nm = dict(zip(names["code"], names["name"]))

    def _subs(v) -> dict:
        if isinstance(v, dict):
            return v
        try:
            return json.loads(v) if v else {}
        except (ValueError, TypeError):
            return {}

    rows = [{
        "rank": int(r["rank"]), "code": r["code"], "name": nm.get(r["code"]),
        "total_score": float(r["total_score"]), "grade": r["grade"],
        "sub_scores": _subs(r.get("sub_scores")),
    } for _, r in board.iterrows()]
    return ok({"run_date": str(run_date), "top": top, "count": len(rows), "list": rows})
