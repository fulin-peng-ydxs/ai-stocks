"""评分规则方案 API（v2.0 §7）——CRUD + 版本 + 按方案试算榜单。"""

from __future__ import annotations

from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.response import ApiResponse, err, ok
from backend.auth.deps import require_perm
from backend.scoring.score_profile import ScoreProfileRepo
from backend.storage import get_client

router = APIRouter(prefix="/api", tags=["score-profiles"])


class ScoreProfileBody(BaseModel):
    id: str
    name: str
    items: list[dict]
    grade_thresholds: dict | None = None


@router.get("/score-profiles", response_model=ApiResponse,
            dependencies=[Depends(require_perm("score-profile:view"))])
def list_score_profiles() -> ApiResponse:
    return ok(ScoreProfileRepo().list())


@router.get("/score-profiles/{pid}", response_model=ApiResponse,
            dependencies=[Depends(require_perm("score-profile:view"))])
def get_score_profile(pid: str) -> ApiResponse:
    p = ScoreProfileRepo().get(pid)
    return ok(p) if p else err(404, "方案不存在")


@router.get("/score-profiles/{pid}/versions", response_model=ApiResponse,
            dependencies=[Depends(require_perm("score-profile:view"))])
def score_profile_versions(pid: str) -> ApiResponse:
    return ok({"id": pid, "versions": ScoreProfileRepo().versions(pid)})


@router.post("/score-profiles", response_model=ApiResponse,
             dependencies=[Depends(require_perm("score-profile:save"))])
def save_score_profile(body: ScoreProfileBody) -> ApiResponse:
    try:
        v = ScoreProfileRepo().save(body.id, body.name, body.items, body.grade_thresholds)
    except ValueError as e:
        return err(400, str(e))
    return ok({"id": body.id, "version": v, "msg": "已保存"})


@router.delete("/score-profiles/{pid}", response_model=ApiResponse,
               dependencies=[Depends(require_perm("score-profile:delete"))])
def delete_score_profile(pid: str) -> ApiResponse:
    ScoreProfileRepo().delete(pid)
    return ok({"msg": "已删除"})


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
        prof = repo.get(body["profile_id"])
        if not prof:
            return err(404, "方案不存在")
        board = ScoreSnapshotRepo(c).get_board(run_date, body["profile_id"], top=top, profile=prof)
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
