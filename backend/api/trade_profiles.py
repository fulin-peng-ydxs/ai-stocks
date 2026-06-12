"""买卖指标方案 API（v2.0 §6，M2.3）——CRUD + 版本 + 条件试算预览。"""

from __future__ import annotations

from datetime import date

import pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel

from backend.api.response import ApiResponse, err, ok
from backend.signals.trade_profile import (
    TradeProfileRepo,
    collect_indicators,
    eval_conditions,
)
from backend.storage import get_client

router = APIRouter(prefix="/api", tags=["trade-profiles"])


class TradeProfileBody(BaseModel):
    id: str
    name: str
    buy_tree: dict
    sell_tree: dict | None = None
    backstop: dict | None = None


@router.get("/trade-profiles", response_model=ApiResponse)
def list_trade_profiles() -> ApiResponse:
    return ok(TradeProfileRepo().list())


@router.get("/trade-profiles/{pid}", response_model=ApiResponse)
def get_trade_profile(pid: str) -> ApiResponse:
    p = TradeProfileRepo().get(pid)
    return ok(p) if p else err(404, "方案不存在")


@router.get("/trade-profiles/{pid}/versions", response_model=ApiResponse)
def trade_profile_versions(pid: str) -> ApiResponse:
    return ok({"id": pid, "versions": TradeProfileRepo().versions(pid)})


@router.post("/trade-profiles", response_model=ApiResponse)
def save_trade_profile(body: TradeProfileBody) -> ApiResponse:
    try:
        v = TradeProfileRepo().save(body.id, body.name, body.buy_tree, body.sell_tree, body.backstop)
    except ValueError as e:
        return err(400, str(e))
    return ok({"id": body.id, "version": v, "msg": "已保存"})


@router.delete("/trade-profiles/{pid}", response_model=ApiResponse)
def delete_trade_profile(pid: str) -> ApiResponse:
    TradeProfileRepo().delete(pid)
    return ok({"msg": "已删除"})


@router.post("/trade-profiles/preview", response_model=ApiResponse)
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
