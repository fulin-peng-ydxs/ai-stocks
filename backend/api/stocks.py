"""个股 / 数据查询 API（SDD §12，T-M3-9）。"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
from fastapi import APIRouter, Query

from backend.api.response import ApiResponse, ok
from backend.groups.stock_group import StockGroupRepo
from backend.storage import get_client
from backend.storage.repository import MarketRepository

router = APIRouter(prefix="/api", tags=["stocks", "data"])


# 服务端排序白名单（防注入）：前端字段 → SQL 列；pct_chg 为查询内别名
_STOCK_SORT_COLS = {"pct_chg": "pct_chg", "name": "sb.name", "industry": "sb.industry", "code": "sb.code"}


@router.get("/stocks", response_model=ApiResponse)
def list_stocks(q: str | None = None, board: str | None = None,
                exclude_st: bool = False, trade_date: str | None = None,
                sort_by: str = "pct_chg", sort_order: str = "asc",
                page: int = 1, size: int = 50) -> ApiResponse:
    """个股列表（按交易日展示当日涨跌幅 + 板块/ST/退市筛选 + 服务端排序）。

    board: 主板/创业板/科创板 / 'ST'(只看 ST) / '退市'(只看退市)；除 '退市' 外均排除已退市。
    exclude_st=true 且非 ST 板块 → 过滤名称含 ST 的股票。
    trade_date 默认最新交易日，LEFT JOIN 当日行情算涨跌幅 pct_chg。
    sort_by ∈ {pct_chg,name,industry,code}，sort_order ∈ {asc,desc}；NULL（停牌）恒排末尾。
    """
    c = get_client()
    td = (date.fromisoformat(trade_date) if trade_date else pd.Timestamp(
        c.query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]).date())
    conds, params = ["1=1"], []
    if q:
        conds.append("(sb.code LIKE ? OR sb.name LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if board == "退市":
        conds.append("sb.delist_date IS NOT NULL")
    else:
        conds.append("sb.delist_date IS NULL")        # 其他板块一律排除退市
        if board == "ST":
            conds.append("sb.name LIKE '%ST%'")
        elif board:
            conds.append("sb.board = ?")
            params.append(board)
        if exclude_st and board != "ST":
            conds.append("sb.name NOT LIKE '%ST%'")
    where = " AND ".join(conds)
    total = int(c.query_df(f"SELECT count(*) AS n FROM stock_basic sb WHERE {where}", params).iloc[0]["n"])

    col = _STOCK_SORT_COLS.get(sort_by, "pct_chg")
    order = "DESC" if str(sort_order).lower() == "desc" else "ASC"
    order_clause = f"{col} {order} NULLS LAST, sb.code ASC"
    df = c.query_df(
        f"SELECT sb.code, sb.name, sb.board, sb.industry, sb.list_date, sb.delist_date, "
        f"       (sb.name LIKE '%ST%') AS is_st, "
        f"       CASE WHEN b.pre_close > 0 THEN (b.close / b.pre_close - 1) * 100 END AS pct_chg "
        f"FROM stock_basic sb "
        f"LEFT JOIN daily_bar b ON b.code = sb.code AND b.trade_date = ? "
        f"WHERE {where} ORDER BY {order_clause} LIMIT {int(size)} OFFSET {int((page-1)*size)}",
        [td, *params])
    rows = df.to_dict("records")
    groups_by_code = StockGroupRepo(c).groups_for_codes([r["code"] for r in rows])
    for r in rows:
        r["list_date"] = str(r["list_date"]) if r.get("list_date") is not None and not pd.isna(r["list_date"]) else None
        r["delist_date"] = str(r["delist_date"]) if r.get("delist_date") is not None and not pd.isna(r["delist_date"]) else None
        r["is_st"] = bool(r["is_st"])
        r["pct_chg"] = round(float(r["pct_chg"]), 2) if r.get("pct_chg") is not None and not pd.isna(r["pct_chg"]) else None
        r["groups"] = groups_by_code.get(r["code"], [])
    return ok({"total": total, "page": page, "size": size, "trade_date": str(td), "list": rows})


@router.get("/stocks/{code}/bars", response_model=ApiResponse)
def stock_bars(code: str, adjust: str = "qfq", lookback: int = 250,
               end: str | None = None) -> ApiResponse:
    c = get_client()
    end_date = date.fromisoformat(end) if end else pd.Timestamp(
        c.query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]).date()
    name_df = c.query_df("SELECT name FROM stock_basic WHERE code = ?", [code])
    name = str(name_df.iloc[0]["name"]) if not name_df.empty else None
    df = MarketRepository(c).get_bars(code, end_date, lookback=lookback, adjust=adjust)
    if df.empty:
        return ok({"code": code, "name": name, "adjust": adjust, "bars": []})

    def _f(v, n=3):  # 安全转 float（NaN→None）
        return round(float(v), n) if v is not None and not pd.isna(v) else None

    out = [{
        "date": str(pd.Timestamp(r["trade_date"]).date()),
        "open": _f(r["open"]), "high": _f(r["high"]),
        "low": _f(r["low"]), "close": _f(r["close"]),
        "pre_close": _f(r["pre_close"]),              # 用于算涨幅/振幅
        "volume": int(r["volume"]) if not pd.isna(r["volume"]) else 0,
        "amount": _f(r["amount"], 0),                 # 成交额（元，不复权）
        "turnover_rate": _f(r["turnover_rate"], 2),   # 换手率 %
    } for _, r in df.iterrows()]
    return ok({"code": code, "name": name, "adjust": adjust, "bars": out})


@router.get("/stocks/{code}/signal", response_model=ApiResponse)
def stock_signal(code: str, date_: str | None = Query(None, alias="date")) -> ApiResponse:
    """个股当日买点 + 技术风险标签（按需计算，T-M6-3）。"""
    from backend.services.screen_score import ScreenScoreService

    c = get_client()
    d = date.fromisoformat(date_) if date_ else pd.Timestamp(
        c.query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]).date()
    svc = ScreenScoreService(c)
    sig = svc.compute_signals(d, [code]).get(code, {})
    return ok({"code": code, "date": str(d),
               "buy_point": sig.get("buy_point"), "risk_flags": sig.get("risk_flags", []),
               "buypoint_markers": svc.buypoint_markers(code, d, lookback=250)})


_CMP_SYM = {">=": "≥", "<=": "≤", ">": ">", "<": "<", "==": "=", "!=": "≠", "between": "介于"}


def _describe_tree(tree: dict, snap: pd.DataFrame, name_map: dict) -> dict:
    """把买/卖条件树拍平为 {op, conds:[{label, met}]}，每个叶子带本股当日是否成立。"""
    from backend.signals.trade_profile import _eval_leaf

    op = tree.get("op", "AND") if tree else "AND"
    conds: list[dict] = []

    def walk(node: dict) -> None:
        if not node:
            return
        if "op" in node:
            for ch in node.get("children", []):
                walk(ch)
            return
        ind = node["indicator"]
        nm = name_map.get(ind, ind)
        ps = node.get("params") or {}
        pstr = ("(" + ",".join(f"{k}={v}" for k, v in ps.items()) + ")") if ps else ""
        val = node.get("value")
        if isinstance(val, bool):
            label = f"{nm}{pstr} {'成立' if val else '不成立'}"
        else:
            label = f"{nm}{pstr} {_CMP_SYM.get(node.get('cmp', '=='), node.get('cmp'))} {val}"
        try:
            met = bool(_eval_leaf(node, snap).iloc[0])
        except (ValueError, KeyError):
            met = False
        conds.append({"label": label, "met": met})

    walk(tree or {})
    return {"op": op, "conds": conds}


@router.get("/stocks/{code}/trade-eval", response_model=ApiResponse)
def stock_trade_eval(code: str, profile_id: str,
                     date_: str | None = Query(None, alias="date")) -> ApiResponse:
    """个股×买卖指标方案：当日买/卖条件是否触发 + 各条件成立明细（v2.0 替代固定买点引擎）。

    点时安全（仅用 ≤ 当日数据）。买卖方案所用指标均非横截面，单股快照求值即正确。
    """
    from backend.api.response import err
    from backend.indicators.definition import IndicatorDefRepo
    from backend.indicators.engine import IndicatorEngine
    from backend.signals.trade_profile import TradeProfileRepo, collect_indicators, eval_conditions

    c = get_client()
    prof = TradeProfileRepo(c).get(profile_id)
    if not prof:
        return err(404, "买卖方案不存在")
    d = date.fromisoformat(date_) if date_ else pd.Timestamp(
        c.query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]).date()
    eng = IndicatorEngine(c)
    snap = eng.wide_snapshot(d, d, codes=[code])
    if snap.empty:
        return ok({"code": code, "date": str(d), "profile_id": profile_id,
                   "name": prof["name"], "buy_signal": False, "sell_signal": False,
                   "buy": {"op": "AND", "conds": []}, "sell": {"op": "OR", "conds": []},
                   "backstop": prof.get("backstop") or {}})
    snap = snap.set_index("code")
    inds = collect_indicators(prof["buy_tree"]) + collect_indicators(prof.get("sell_tree") or {})
    try:
        eng.attach_columns(snap, inds, d)
        buy = bool(eval_conditions(prof["buy_tree"], snap).iloc[0]) if prof.get("buy_tree") else False
        sell_tree = prof.get("sell_tree") or {}
        sell = bool(eval_conditions(sell_tree, snap).iloc[0]) if sell_tree else False
    except (ValueError, KeyError) as e:
        return err(400, f"条件无法求值: {e}")
    name_map = {d2["key"]: d2["name_cn"] for d2 in IndicatorDefRepo(c).list()}
    return ok({
        "code": code, "date": str(d), "profile_id": profile_id, "name": prof["name"],
        "version": prof.get("version"),
        "buy_signal": buy, "sell_signal": sell,
        "buy": _describe_tree(prof["buy_tree"], snap, name_map),
        "sell": _describe_tree(prof.get("sell_tree") or {}, snap, name_map),
        "backstop": prof.get("backstop") or {},
    })


@router.get("/stocks/{code}/indicators", response_model=ApiResponse)
def stock_indicators(code: str, lookback: int = 60) -> ApiResponse:
    from backend.indicators.engine import IndicatorEngine
    c = get_client()
    # v2.0：指标动态实时计算（无 indicator 表）。多取窗口暖机后裁末段 lookback 行。
    # 注：rs_pct 为横截面量，单股序列不填（个股查询页该列为空，M2.4 适配）。
    df = IndicatorEngine(c).compute_series(code, lookback=int(lookback) + 520)
    if df.empty:
        return ok({"code": code, "indicators": []})
    df = df.sort_values("trade_date").tail(int(lookback))
    rows = df.to_dict("records")
    for r in rows:
        r["trade_date"] = str(pd.Timestamp(r["trade_date"]).date())
    return ok({"code": code, "indicators": rows})


@router.get("/data/status", response_model=ApiResponse)
def data_status() -> ApiResponse:
    c = get_client()
    span = c.query_df(
        "SELECT max(trade_date) AS latest, count(DISTINCT code) AS codes, count(*) AS rows FROM daily_bar").iloc[0]
    issues = int(c.query_df("SELECT count(*) AS n FROM data_quality_issue").iloc[0]["n"])
    last_updates = c.query_df(
        "SELECT table_name, source, status, row_count, date_start, date_end, detail, updated_at "
        "FROM data_update_log ORDER BY id DESC LIMIT 20").to_dict("records")
    for u in last_updates:
        u["updated_at"] = str(u["updated_at"])
        u["date_start"] = None if u["date_start"] is None else str(u["date_start"])
        u["date_end"] = None if u["date_end"] is None else str(u["date_end"])
    return ok({
        "latest_trade_date": str(span["latest"]),
        "distinct_codes": int(span["codes"]), "bar_rows": int(span["rows"]),
        "quality_issues": issues, "recent_updates": last_updates,
    })


@router.get("/data/update-logs", response_model=ApiResponse)
def update_logs(page: int = 1, size: int = 10, status: str | None = None,
                table_name: str | None = None, sort: str = "time", order: str = "desc") -> ApiResponse:
    """采集日志（M2.9.5 服务端分页/排序/筛选）。sort ∈ {time,table,status}，order ∈ {asc,desc}。"""
    c = get_client()
    conds, params = [], []
    if status:
        conds.append("status = ?"); params.append(status)
    if table_name:
        conds.append("table_name = ?"); params.append(table_name)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    col = {"time": "updated_at", "table": "table_name", "status": "status"}.get(sort, "updated_at")
    direction = "ASC" if str(order).lower() == "asc" else "DESC"
    total = int(c.query_df(f"SELECT count(*) AS n FROM data_update_log{where}", params).iloc[0]["n"])
    off = int((page - 1) * size)
    rows = c.query_df(
        f"SELECT table_name, source, status, row_count, date_start, date_end, detail, updated_at "
        f"FROM data_update_log{where} ORDER BY {col} {direction}, id DESC LIMIT ? OFFSET ?",
        [*params, int(size), off]).to_dict("records")
    for u in rows:
        u["updated_at"] = str(u["updated_at"])
        u["date_start"] = None if u["date_start"] is None else str(u["date_start"])
        u["date_end"] = None if u["date_end"] is None else str(u["date_end"])
    # 供前端筛选下拉：去重目标表
    tables = c.query_df("SELECT DISTINCT table_name FROM data_update_log ORDER BY table_name")["table_name"].tolist()
    return ok({"list": rows, "total": total, "page": page, "size": size, "tables": tables})


@router.get("/data/trade-dates", response_model=ApiResponse)
def trade_dates() -> ApiResponse:
    """已有行情的全部交易日（升序），供前端日历只允许选真实交易日。"""
    c = get_client()
    df = c.query_df("SELECT DISTINCT trade_date FROM daily_bar ORDER BY trade_date")
    dates = [str(pd.Timestamp(d).date()) for d in df["trade_date"]]
    return ok({
        "dates": dates,
        "min": dates[0] if dates else None,
        "max": dates[-1] if dates else None,
        "count": len(dates),
    })


# /data/quality 已迁移至 backend/api/data_admin.py（含 severity/status 分级与筛选，FR-DM-4）。
