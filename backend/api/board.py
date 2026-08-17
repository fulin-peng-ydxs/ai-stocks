"""评分榜单 API（SDD §12，T-M3-8）：某日评分结果 + Top N 榜单。"""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, Query

from backend.api.response import ApiResponse, err, ok
from backend.auth.context import get_current_context
from backend.auth.deps import require_perm
from backend.services.public_board import get_public_board_profile, latest_market_date
from backend.storage import get_client, get_pg_client
from backend.storage.pg_ddl import PUBLIC_BOARD_OWNER

router = APIRouter(prefix="/api", tags=["scores"])


def _board_by_profile(c, run_date: date, top: int, profile_ref_or_id: str) -> ApiResponse:
    """用评分方案对某日全市场打分排序（与回测 _decision_data 同口径）。

    走评分快照层（§10.1）：命中且未失效→用缓存；否则惰性重算落库。
    """
    from backend.scoring.score_profile import ScoreProfileRepo
    from backend.scoring.snapshot import ScoreSnapshotRepo

    prof = ScoreProfileRepo(c).get_visible(profile_ref_or_id, include_owner=True)
    if not prof:
        return ok({"date": str(run_date), "top": top, "list": []})
    board = ScoreSnapshotRepo(
        c,
        tenant_id=prof["tenant_id"],
        owner_user_id=prof["owner_user_id"],
    ).get_board(run_date, prof["id"], top=top, profile=prof)
    if board.empty:
        return ok({"date": str(run_date), "top": top, "list": []})
    codes = board["code"].tolist()
    names = c.query_df(
        f"SELECT code, name, board FROM stock_basic WHERE code IN ({','.join('?' * len(codes))})", codes)
    nm = dict(zip(names["code"], names["name"]))
    bd = dict(zip(names["code"], names["board"]))
    rows = [{
        "rank": int(r["rank"]), "code": r["code"], "name": nm.get(r["code"]),
        "board": bd.get(r["code"]),
        "total_score": round(float(r["total_score"]), 2), "grade": str(r["grade"]),
    } for _, r in board.iterrows()]
    return ok({"date": str(run_date), "top": top, "list": rows})


@router.get("/board/compute", response_model=ApiResponse,
            dependencies=[Depends(require_perm("board:compute"))])
def board_compute(date_: str = Query(..., alias="date"), top: int = 50,
                  score_profile_id: str | None = None) -> ApiResponse:
    """按需计算某交易日的每日榜单 Top N（不落库），供回测"查看买入当日榜单"。

    与回测引擎选股**同口径**：全市场、排除 ST、按综合分降序。
    - 传 score_profile_id：用该评分方案打分（= 回测 strategy 选 score_profile 时的口径）；
    - 不传：用旧固定 ScoreModel（= 回测未选评分方案、或独立每日榜单页的口径）。
    务必与本次回测所选方案一致，否则名次会与交易回放的 entry_rank 不符。
    """
    run_date = date.fromisoformat(date_)
    c = get_client()
    if score_profile_id:
        return _board_by_profile(c, run_date, top, score_profile_id)

    from backend.services.screen_score import ScreenScoreService
    board = ScreenScoreService(c).rank_board(run_date, top_n=top, persist=False)
    if board is None or board.empty:
        return ok({"date": date_, "top": top, "list": []})
    codes = board["code"].tolist()
    name_df = c.query_df(
        f"SELECT code, name, board FROM stock_basic WHERE code IN ({','.join('?' * len(codes))})", codes
    )
    name_map = dict(zip(name_df["code"], name_df["name"]))
    board_map = dict(zip(name_df["code"], name_df["board"]))
    rows = [{
        "rank": int(r["rank"]), "code": r["code"], "name": name_map.get(r["code"]),
        "board": board_map.get(r["code"]),
        "total_score": round(float(r["total_score"]), 2), "grade": str(r["grade"]),
    } for _, r in board.iterrows()]
    return ok({"date": date_, "top": top, "list": rows})


@router.get("/board/profiles", response_model=ApiResponse,
            dependencies=[Depends(require_perm("board:view"))])
def board_profiles(
    source: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse:
    """榜单可选评分方案列表。

    source=mine：下拉只加载自己的评分方案（纯 owner，R3/C2）；
    source=preset|tenant|public：搜索弹窗浏览（分页 + q，R5/R14）；
    不传维持 list_visible 兼容（自己 + 租户公开 + 全体公开 + 系统内置混合）。
    """
    from backend.scoring.score_profile import ScoreProfileRepo

    if source is not None and source not in ("mine", "preset", "tenant", "public"):
        return err(400, "source 必须是 mine、preset、tenant 或 public")
    repo = ScoreProfileRepo(get_client(), get_pg_client())
    if source == "mine":
        return ok(repo.list_mine())
    if source in ("preset", "tenant", "public"):
        return ok(repo.browse(source, q=q, page=page, page_size=page_size))
    return ok(repo.list_visible())


@router.post("/board/run", response_model=ApiResponse,
             dependencies=[Depends(require_perm("board:view"))])
def board_run(body: dict) -> ApiResponse:
    """按可见评分方案读取榜单；快照缺失或 stale 时物化到方案 owner 的共享缓存槽。

    body: {profile_ref | profile_id, run_date?, top?, force?}
    """
    from backend.scoring.score_profile import ScoreProfileRepo
    from backend.scoring.snapshot import ScoreSnapshotRepo

    c = get_client()
    pg = get_pg_client()
    repo = ScoreProfileRepo(c, pg)
    ref_or_id = body.get("profile_ref") or body.get("profile_id")
    prof = repo.get_visible(ref_or_id, include_owner=True) if ref_or_id else None
    # 兼容旧前端：只传 profile_id 时仍可命中平台系统内置方案。
    if not prof and body.get("profile_id"):
        preset = get_public_board_profile(body.get("profile_id"), c, pg)
        if preset:
            prof = {
                **preset,
                "tenant_id": PUBLIC_BOARD_OWNER[0],
                "owner_user_id": PUBLIC_BOARD_OWNER[1],
            }
    if not prof:
        return err(404, "方案不存在")
    run_date = date.fromisoformat(body["run_date"]) if body.get("run_date") else latest_market_date(c)
    top = int(body.get("top", 50))
    if run_date is None:
        return ok({"run_date": "", "top": top, "count": 0, "list": []})
    pid = prof["id"]
    version = int(prof.get("version") or 1)
    snapshot_repo = ScoreSnapshotRepo(
        c,
        pg,
        tenant_id=prof["tenant_id"],
        owner_user_id=prof["owner_user_id"],
    )
    force = bool(body.get("force"))
    ctx = get_current_context()
    if force and not (ctx and (ctx.is_system or "board:compute" in ctx.resources)):
        return err(403, "强制刷新需要 board:compute 权限")
    from backend.scoring.snapshot import _current_param_hash
    was_fresh = snapshot_repo._fresh(run_date, pid, version, _current_param_hash())  # noqa: SLF001
    if force:
        pg.execute(
            "UPDATE score_snapshot_meta SET stale=true WHERE trade_date=%s AND profile_id=%s "
            "AND profile_version=%s AND tenant_id=%s AND owner_user_id=%s",
            [run_date, pid, version, prof["tenant_id"], prof["owner_user_id"]],
        )
    board = snapshot_repo.get_board(run_date, pid, top=top, profile=prof)
    if board.empty:
        return ok({
            "run_date": str(run_date),
            "top": top,
            "count": 0,
            "cache_status": "cached" if was_fresh and not force else "materialized",
            "list": [],
        })
    codes = board["code"].tolist()
    names = c.query_df(
        f"SELECT code, name, board FROM stock_basic WHERE code IN ({','.join('?' * len(codes))})", codes)
    nm = dict(zip(names["code"], names["name"]))
    bd = dict(zip(names["code"], names["board"]))

    def _subs(v) -> dict:
        if isinstance(v, dict):
            return v
        try:
            return json.loads(v) if v else {}
        except (ValueError, TypeError):
            return {}

    rows = [{
        "rank": int(r["rank"]), "code": r["code"], "name": nm.get(r["code"]),
        "board": bd.get(r["code"]),
        "total_score": float(r["total_score"]), "grade": r["grade"],
        "sub_scores": _subs(r.get("sub_scores")),
    } for _, r in board.iterrows()]
    return ok({
        "run_date": str(run_date),
        "top": top,
        "count": len(rows),
        "profile_ref": prof.get("profile_ref") or repo.make_ref(prof["tenant_id"], prof["owner_user_id"], pid),
        "profile_version": version,
        "cache_status": "cached" if was_fresh and not force else "materialized",
        "list": rows,
    })
