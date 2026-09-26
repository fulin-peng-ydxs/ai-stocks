"""评分榜单 API（SDD §12，T-M3-8）：某日评分结果与分页查询。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from backend.api.response import ApiResponse, err, ok
from backend.auth.context import get_current_context
from backend.auth.deps import require_perm
from backend.services.public_board import get_public_board_profile, latest_market_date
from backend.services.stock_board_correlation import StockBoardCorrelationService
from backend.storage import get_client, get_pg_client
from backend.storage.pg_ddl import PUBLIC_BOARD_OWNER

router = APIRouter(prefix="/api", tags=["scores"])


def _current_user_stock_groups(c, pg, codes: list[str]) -> dict[str, list[dict]]:
    """批量读取当前请求归属者的股票分组；调用方负责先校验分组查看权限。"""
    from backend.groups.stock_group import StockGroupRepo

    return StockGroupRepo(pg=pg, market=c).groups_for_codes(codes)


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
    from backend.services.ranked_stock_result import ranked_rows

    return ok({
        "date": str(run_date),
        "top": top,
        "include_st": bool(prof.get("include_st", True)),
        "profile_version": int(prof.get("version") or 1),
        "list": ranked_rows(c, run_date, board),
    })


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
    from backend.services.ranked_stock_result import ranked_rows

    return ok({"date": date_, "top": top, "include_st": False,
               "list": ranked_rows(c, run_date, board)})


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

    body: {profile_ref | profile_id, run_date?, page?, page_size?, listed_boards?, keyword?,
           export_all?, force?}
    force 仅允许方案 owner（需 board:compute）或 system 管理员执行。
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
    try:
        page = max(1, int(body.get("page", 1)))
        page_size = max(10, min(int(body.get("page_size", 50)), 200))
    except (TypeError, ValueError):
        return err(400, "page 和 page_size 必须是整数")
    listed_boards = body.get("listed_boards") or []
    if not isinstance(listed_boards, list) or any(
        value not in ("main", "star", "gem") for value in listed_boards
    ):
        return err(400, "listed_boards 只支持 main、star、gem")
    keyword = str(body.get("keyword") or "").strip()[:50]
    export_all = bool(body.get("export_all"))
    if run_date is None:
        return ok({
            "run_date": "", "page": page, "page_size": page_size,
            "total": 0, "count": 0, "list": [],
        })
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
    if force and not (
        ctx
        and (
            ctx.is_system
            or (
                prof["tenant_id"] == ctx.tenant_id
                and prof["owner_user_id"] == ctx.user_id
            )
        )
    ):
        return err(403, "只能重算自己的评分方案榜单")
    from backend.services.stock_st_status import STStatusNotReadyError

    try:
        was_fresh = snapshot_repo.is_fresh(run_date, pid, version)
        if force:
            pg.execute(
                "UPDATE score_snapshot_meta SET stale=true WHERE trade_date=%s AND profile_id=%s "
                "AND profile_version=%s AND tenant_id=%s AND owner_user_id=%s",
                [run_date, pid, version, prof["tenant_id"], prof["owner_user_id"]],
            )
        board = snapshot_repo.get_board(run_date, pid, profile=prof)
    except STStatusNotReadyError as exc:
        return ok({
            "run_date": str(run_date),
            "page": page,
            "page_size": page_size,
            "total": 0,
            "count": 0,
            "business_code": "ST_STATUS_NOT_READY",
            "st_status_error": str(exc),
            "list": [],
        })
    if board.empty:
        return ok({
            "run_date": str(run_date),
            "page": page,
            "page_size": page_size,
            "total": 0,
            "count": 0,
            "business_code": "READY",
            "cache_status": "cached" if was_fresh and not force else "materialized",
            "include_st": bool(prof.get("include_st", True)),
            "profile_version": version,
            "list": [],
        })
    from backend.services.ranked_stock_result import ranked_page
    try:
        total, rows = ranked_page(
            c,
            run_date,
            board,
            page=1 if export_all else page,
            page_size=max(len(board), 1) if export_all else page_size,
            listed_boards=listed_boards,
            keyword=keyword,
        )
    except STStatusNotReadyError as exc:
        return ok({
            "run_date": str(run_date),
            "page": page,
            "page_size": page_size,
            "total": 0,
            "count": 0,
            "business_code": "ST_STATUS_NOT_READY",
            "st_status_error": str(exc),
            "list": [],
        })
    codes = [row["code"] for row in rows]
    # 自选分组属于当前请求用户的 PG 私有资产；仅在具备查看权限时按榜单代码批量读取，
    # 与公共评分快照在服务层内存合并，避免跨库 JOIN 和前端逐行查询。
    if not export_all and ctx and (ctx.is_system or "stock-group:view" in ctx.resources):
        groups_by_code = _current_user_stock_groups(c, pg, codes)
        for row in rows:
            row["groups"] = groups_by_code.get(row["code"], [])
    if not export_all:
        StockBoardCorrelationService(c).attach_related_boards(rows, run_date)
    return ok({
        "run_date": str(run_date),
        "page": 1 if export_all else page,
        "page_size": len(rows) if export_all else page_size,
        "total": total,
        "count": len(rows),
        "business_code": "READY",
        "profile_ref": prof.get("profile_ref") or repo.make_ref(prof["tenant_id"], prof["owner_user_id"], pid),
        "profile_version": version,
        "profile_name": prof.get("name"),
        "include_st": bool(prof.get("include_st", True)),
        "cache_status": "cached" if was_fresh and not force else "materialized",
        "list": rows,
    })
