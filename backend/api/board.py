"""评分榜单 API（SDD §12，T-M3-8）：某日评分结果 + Top N 榜单。"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends, Query

from backend.api.response import ApiResponse, err, ok
from backend.auth.deps import require_perm
from backend.storage import get_client, get_pg_client
from backend.storage.pg_ddl import PUBLIC_BOARD_OWNER

router = APIRouter(prefix="/api", tags=["scores"])

# 每日榜单 score_result 的**公共读**：有意固定平台公共归属（PUBLIC_BOARD_OWNER=default/admin 平台槽），
# 全员登录用户看同一份、不按当前用户过滤（stage4·C1 平台公共榜单特例；铁律见 pg_ddl.PUBLIC_BOARD_OWNER
# 与 CLAUDE.md「资产归属与隔离」）。非 stage1 遗留默认，勿"纠正"为 get_current_owner()。
_OWN = list(PUBLIC_BOARD_OWNER)


def _resolve_date(d: str | None, c) -> date:
    if d:
        return date.fromisoformat(d)
    # 最新榜单日：score_result 在 PG；无则回落行情最新日（DuckDB）
    r = get_pg_client().query_df(
        "SELECT max(trade_date) AS d FROM score_result WHERE tenant_id=%s AND owner_user_id=%s",
        _OWN).iloc[0]["d"]
    if r is None or pd.isna(r):
        r = c.query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]
    return pd.Timestamp(r).date()


def _query_scores(trade_date: date, model_id: str, limit: int | None) -> list[dict]:
    # 跨库编排：评分结果取 PG（资产），股票名取 DuckDB（行情），内存按 code 合并（禁跨库 JOIN）
    sql = (
        "SELECT trade_date, code, total_score, rank, grade, sub_scores, buy_point, risk_flags "
        "FROM score_result WHERE trade_date=%s AND model_id=%s "
        "AND tenant_id=%s AND owner_user_id=%s ORDER BY rank"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    df = get_pg_client().query_df(sql, [trade_date, model_id, *_OWN])
    rows = df.to_dict("records")
    if rows:
        codes = [r["code"] for r in rows]
        ph = ",".join("?" * len(codes))
        names_df = get_client().query_df(
            f"SELECT code, name FROM stock_basic WHERE code IN ({ph})", codes)
        names = dict(zip(names_df["code"], names_df["name"]))
    else:
        names = {}
    for r in rows:
        r["name"] = names.get(r["code"])
        r["trade_date"] = str(r["trade_date"])
        if r.get("sub_scores"):
            r["sub_scores"] = json.loads(r["sub_scores"])
        if r.get("risk_flags"):
            try:
                r["risk_flags"] = json.loads(r["risk_flags"])
            except (TypeError, ValueError):
                pass
    return rows


@router.get("/scores/top", response_model=ApiResponse,
            dependencies=[Depends(require_perm("board:view"))])
def scores_top(
    date_: str | None = Query(None, alias="date"),
    model_id: str = "default",
    top: int = 20,
) -> ApiResponse:
    c = get_client()
    d = _resolve_date(date_, c)
    return ok({"trade_date": str(d), "top": top, "list": _query_scores(d, model_id, top)})


def _board_by_profile(c, run_date: date, top: int, profile_id: str) -> ApiResponse:
    """用评分方案对某日全市场打分排序（与回测 _decision_data 同口径）。

    走评分快照层（§10.1）：命中且未失效→用缓存；否则惰性重算落库。
    """
    from backend.scoring.score_profile import ScoreProfileRepo
    from backend.scoring.snapshot import ScoreSnapshotRepo

    prof = ScoreProfileRepo(c).get(profile_id)
    if not prof:
        return ok({"date": str(run_date), "top": top, "list": []})
    board = ScoreSnapshotRepo(c).get_board(run_date, profile_id, top=top, profile=prof)
    if board.empty:
        return ok({"date": str(run_date), "top": top, "list": []})
    codes = board["code"].tolist()
    names = c.query_df(
        f"SELECT code, name FROM stock_basic WHERE code IN ({','.join('?' * len(codes))})", codes)
    nm = dict(zip(names["code"], names["name"]))
    rows = [{
        "rank": int(r["rank"]), "code": r["code"], "name": nm.get(r["code"]),
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
        f"SELECT code, name FROM stock_basic WHERE code IN ({','.join('?' * len(codes))})", codes
    )
    name_map = dict(zip(name_df["code"], name_df["name"]))
    rows = [{
        "rank": int(r["rank"]), "code": r["code"], "name": name_map.get(r["code"]),
        "total_score": round(float(r["total_score"]), 2), "grade": str(r["grade"]),
    } for _, r in board.iterrows()]
    return ok({"date": date_, "top": top, "list": rows})


@router.get("/board/profiles", response_model=ApiResponse,
            dependencies=[Depends(require_perm("board:view"))])
def board_profiles() -> ApiResponse:
    """公共榜单可选的**预设评分方案**列表（C1 平台公共榜单特例）。

    有意读 PUBLIC_BOARD_OWNER（default/admin 平台槽）的**预设**方案（is_preset=true），全员登录用户看
    同一份、与当前用户归属无关——普通用户没有自建方案也能选公共预设看榜单（补齐 C1 公共榜单闭环：
    此前榜单页误用 /score-profiles（score-profile:view，system-only + 按调用者归属）导致普通用户空/403）。
    方案的增删改仍归 /system/config（score-profile:*，system-only），此处**只读、只暴露预设**。
    """
    from backend.scoring.score_profile import ScoreProfileRepo
    repo = ScoreProfileRepo(get_client(), get_pg_client(),
                            tenant_id=_OWN[0], owner_user_id=_OWN[1])
    return ok([p for p in repo.list() if p.get("is_preset")])


@router.post("/board/run", response_model=ApiResponse,
             dependencies=[Depends(require_perm("board:view"))])
def board_run(body: dict) -> ApiResponse:
    """按**公共预设方案**对某交易日全市场（排除 ST）打分排序，返回 Top N（含分项达标分）。

    C1 平台公共榜单特例：方案与评分快照均归 PUBLIC_BOARD_OWNER、全员共享一份（不按当前用户过滤，
    亦不写调用者个人快照）。只接受公共**预设**方案 id——个人自建方案的实时试算走 /score-profiles/run
    （score:run，写调用者个人归属），二者归属与快照缓存天然分开、互不污染。
    body: {profile_id, run_date?, top?}
    """
    import json

    from backend.scoring.score_profile import ScoreProfileRepo
    from backend.scoring.snapshot import ScoreSnapshotRepo

    c = get_client()
    pg = get_pg_client()
    pid = body.get("profile_id")
    prof = (ScoreProfileRepo(c, pg, tenant_id=_OWN[0], owner_user_id=_OWN[1]).get(pid)
            if pid else None)
    if not prof or not prof.get("is_preset"):
        return err(404, "方案不存在")
    run_date = (date.fromisoformat(body["run_date"]) if body.get("run_date")
                else pd.Timestamp(c.query_df("SELECT max(trade_date) d FROM daily_bar").iloc[0]["d"]).date())
    top = int(body.get("top", 50))
    board = ScoreSnapshotRepo(c, pg, tenant_id=_OWN[0], owner_user_id=_OWN[1]).get_board(
        run_date, pid, top=top, profile=prof)
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


@router.get("/scores", response_model=ApiResponse,
            dependencies=[Depends(require_perm("board:view"))])
def scores(
    date_: str | None = Query(None, alias="date"),
    model_id: str = "default",
    page: int = 1,
    size: int = 50,
) -> ApiResponse:
    c = get_client()
    d = _resolve_date(date_, c)
    all_rows = _query_scores(d, model_id, None)
    start = (page - 1) * size
    return ok({
        "trade_date": str(d), "total": len(all_rows),
        "page": page, "size": size, "list": all_rows[start:start + size],
    })
