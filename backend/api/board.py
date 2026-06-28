"""评分榜单 API（SDD §12，T-M3-8）：某日评分结果 + Top N 榜单。"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
from fastapi import APIRouter, Query

from backend.api.response import ApiResponse, ok
from backend.storage import get_client, get_pg_client
from backend.storage.pg_ddl import DEFAULT_OWNER_USER_ID, DEFAULT_TENANT_ID

router = APIRouter(prefix="/api", tags=["scores"])

# 评分结果 score_result 属用户资产（→PG）；stage1 auth 未落地，按默认归属读取。
_OWN = [DEFAULT_TENANT_ID, DEFAULT_OWNER_USER_ID]


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


@router.get("/scores/top", response_model=ApiResponse)
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


@router.get("/board/compute", response_model=ApiResponse)
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


@router.get("/scores", response_model=ApiResponse)
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
