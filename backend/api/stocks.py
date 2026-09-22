"""个股 / 数据查询 API（SDD §12，T-M3-9）。"""

from __future__ import annotations

import math
from datetime import date
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.response import ApiResponse, ok
from backend.auth.context import get_current_context
from backend.auth.deps import require_perm, require_system_perm
from backend.groups.stock_group import StockGroupRepo
from backend.indicators.engine import _IND_COLS
from backend.indicators.period import MACD_OUTPUT_COLUMNS, IndicatorPeriod, compute_period_macd
from backend.services.intraday_quotes import IntradayQuoteService, IntradayServiceUnavailable
from backend.services.market_benchmark import MarketBenchmarkService
from backend.services.stock_board_correlation import StockBoardCorrelationService
from backend.services.stock_quote_summary import StockQuoteSummaryService
from backend.storage import get_read_client as get_client
from backend.storage.repository import MarketRepository

router = APIRouter(prefix="/api", tags=["stocks", "data"])


# 服务端排序白名单（防注入）：前端字段 → SQL 列；pct_chg/close 为查询内别名
_STOCK_SORT_COLS = {"pct_chg": "pct_chg", "close": "b.close", "name": "sb.name",
                    "industry": "sb.industry", "code": "sb.code"}

# 个股序列只开放业务指标列：code 已在响应外层，trade_date 始终返回；
# param_hash 属内部缓存契约。
_INDICATOR_FIELD_ALLOWLIST = frozenset(_IND_COLS) - {"code", "trade_date", "param_hash"}


def _parse_indicator_fields(fields: str | None) -> list[str] | None:
    """解析逗号字段列表；空项/重复项归一化，未知字段在计算前拒绝。"""
    if fields is None:
        return None
    selected: list[str] = []
    invalid: list[str] = []
    for raw in fields.split(","):
        field = raw.strip()
        if not field:
            continue
        if field not in _INDICATOR_FIELD_ALLOWLIST:
            if field not in invalid:
                invalid.append(field)
            continue
        if field not in selected:
            selected.append(field)
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的指标字段: {', '.join(invalid)}",
        )
    return selected


def _indicator_json_scalar(value):
    """把 pandas/NumPy 标量规范成严格 JSON；缺失和非有限数统一为 null。"""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (bool, int, str)):
        return value
    return value


def _serialize_indicator_rows(df: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    for raw in df.to_dict("records"):
        row = {key: _indicator_json_scalar(value) for key, value in raw.items()}
        trade_date = row.get("trade_date")
        row["trade_date"] = (
            None if trade_date is None else str(pd.Timestamp(trade_date).date())
        )
        rows.append(row)
    return rows


@router.get("/stocks", response_model=ApiResponse,
            dependencies=[Depends(require_perm("stocks:view"))])
def list_stocks(q: str | None = None, board: str | None = None,
                membership_board_code: str | None = None,
                exclude_st: bool = False, trade_date: date | None = None,
                sort_by: str = "pct_chg", sort_order: str = "asc",
                page: int = 1, size: int = 50) -> ApiResponse:
    """个股列表（按交易日展示当日涨跌幅 + 上市板块/行业概念归属筛选 + 服务端排序）。

    board: 主板/创业板/科创板 / 'ST'(只看 ST) / '退市'(只看退市)；除 '退市' 外均排除已退市。
    exclude_st=true 且非 ST 板块 → 过滤该交易日的权威 ST 点时事实。
    trade_date 默认最新交易日，LEFT JOIN 当日行情算涨跌幅 pct_chg。
    sort_by ∈ {pct_chg,close,name,industry,code}，sort_order ∈ {asc,desc}；NULL（停牌）恒排末尾。
    """
    c = get_client()
    td = (trade_date if trade_date else pd.Timestamp(
        c.query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]).date())
    from backend.services.stock_st_status import StockSTStatusService

    if board == "退市":
        missing = c.query_df(
            "SELECT sb.code FROM stock_basic sb WHERE sb.delist_date IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM stock_st_status_daily st "
            "WHERE st.code=sb.code AND st.trade_date<=LEAST(sb.delist_date, ?) "
            "AND st.quality='accurate') LIMIT 5",
            [td],
        )["code"].astype(str).tolist()
        if missing:
            from backend.services.stock_st_status import STStatusNotReadyError

            raise STStatusNotReadyError(
                f"退市股票缺少退市前 ST 点时事实，示例 {','.join(missing)}；请先运行 ST状态刷新"
            )
        st_join = (
            "LEFT JOIN LATERAL (SELECT s.is_st FROM stock_st_status_daily s "
            "WHERE s.code=sb.code AND s.trade_date<=LEAST(sb.delist_date, ?) "
            "AND s.quality='accurate' ORDER BY s.trade_date DESC LIMIT 1) st ON TRUE "
        )
    else:
        listed_codes = c.query_df(
            "SELECT code FROM stock_basic WHERE (list_date IS NULL OR list_date<=?) "
            "AND delist_date IS NULL",
            [td],
        )["code"].astype(str).tolist()
        StockSTStatusService(c).status_map(td, listed_codes)
        st_join = "JOIN stock_st_status_daily st ON st.code=sb.code AND st.trade_date=? "
    conds, params = ["1=1"], []
    if q:
        conds.append("(sb.code LIKE ? OR sb.name LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if board == "退市":
        conds.append("sb.delist_date IS NOT NULL")
    else:
        conds.append("sb.delist_date IS NULL")        # 其他板块一律排除退市
        if board == "ST":
            conds.append("st.is_st IS TRUE")
        elif board:
            conds.append("sb.board = ?")
            params.append(board)
        if exclude_st and board != "ST":
            conds.append("st.is_st IS FALSE")
    if membership_board_code:
        conds.append(
            "EXISTS (SELECT 1 FROM board_member bm "
            "JOIN board_dict bd ON bd.board_code=bm.board_code "
            "WHERE bm.code=sb.code AND bd.board_code=? "
            "AND bd.board_type IN ('industry','concept') "
            "AND (bm.first_seen_date IS NULL OR bm.first_seen_date<=?))"
        )
        params.extend([membership_board_code, td])
    where = " AND ".join(conds)
    total = int(c.query_df(
        f"SELECT count(*) AS n FROM stock_basic sb "
        f"{st_join}"
        f"WHERE {where}",
        [td, *params],
    ).iloc[0]["n"])

    col = _STOCK_SORT_COLS.get(sort_by, "pct_chg")
    order = "DESC" if str(sort_order).lower() == "desc" else "ASC"
    order_clause = f"{col} {order} NULLS LAST, sb.code ASC"
    df = c.query_df(
        f"SELECT sb.code, sb.name, sb.board, sb.industry, sb.list_date, sb.delist_date, "
        f"       st.is_st AS is_st, b.close AS close, "
        f"       CASE WHEN b.pre_close > 0 THEN (b.close / b.pre_close - 1) * 100 END AS pct_chg "
        f"FROM stock_basic sb "
        f"{st_join}"
        f"LEFT JOIN daily_bar b ON b.code = sb.code AND b.trade_date = ? "
        f"WHERE {where} ORDER BY {order_clause} LIMIT {int(size)} OFFSET {int((page-1)*size)}",
        [td, td, *params])
    rows = df.to_dict("records")
    ctx = get_current_context()
    can_view_groups = bool(
        ctx and (ctx.is_system or "stock-group:view" in ctx.resources)
    )
    groups_by_code = (
        StockGroupRepo(market=c).groups_for_codes([r["code"] for r in rows])
        if can_view_groups
        else {}
    )
    StockBoardCorrelationService(c).attach_related_boards(rows, td)
    for r in rows:
        r["list_date"] = str(r["list_date"]) if r.get("list_date") is not None and not pd.isna(r["list_date"]) else None
        r["delist_date"] = str(r["delist_date"]) if r.get("delist_date") is not None and not pd.isna(r["delist_date"]) else None
        r["is_st"] = bool(r["is_st"])
        r["close"] = round(float(r["close"]), 2) if r.get("close") is not None and not pd.isna(r["close"]) else None
        r["pct_chg"] = round(float(r["pct_chg"]), 2) if r.get("pct_chg") is not None and not pd.isna(r["pct_chg"]) else None
        r["groups"] = groups_by_code.get(r["code"], [])
    return ok({"total": total, "page": page, "size": size, "trade_date": str(td), "list": rows})


@router.get(
    "/stocks/membership-options",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm("stocks:view"))],
)
def stock_membership_options() -> ApiResponse:
    """返回个股查询可用的同花顺行业与概念单选项。"""
    return ok({"list": StockBoardCorrelationService(get_client()).list_membership_options()})


@router.get(
    "/stocks/{code}/related-boards",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm("stocks:view"))],
)
def stock_related_boards(code: str, business_date: date | None = None) -> ApiResponse:
    """返回股票累计归属及当前冠军摘要；未传业务日期时按"默认最新交易日"启用历史保护。

    与列表页口径一致：业务日期 = daily_bar 最新交易日；当冠军 as_of_date 与之不一致时返回
    as_of_mismatch（冠军为空），禁止用最新结果装饰历史行。无最新交易日（空表）时不保护，
    退化为直接返回最近结果。
    """
    try:
        client = get_client()
        requested_business_date = business_date is not None
        if business_date is None:
            latest = client.query_df(
                "SELECT max(trade_date) AS d FROM daily_bar"
            ).iloc[0]["d"]
            if latest is not None and not pd.isna(latest):
                business_date = pd.Timestamp(latest).date()
        service = StockBoardCorrelationService(client)
        membership = service.get_membership_with_market(code, business_date)
        membership["related_boards"] = service.get_related_boards(
            [code], business_date, schedule_missing=requested_business_date
        )[membership["code"]]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(membership)


@router.get(
    "/stocks/{code}/quote-summary",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm("stocks:view"))],
)
def stock_quote_summary(code: str) -> ApiResponse:
    """返回个股详情头部所需的最新收盘行情、市值与股本。"""
    try:
        return ok(StockQuoteSummaryService(get_client()).get(code))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/stocks/{code}/bars", response_model=ApiResponse,
            dependencies=[Depends(require_perm("stocks:view"))])
def stock_bars(code: str, adjust: str = "qfq", lookback: int = 250,
               end: date | None = None) -> ApiResponse:
    c = get_client()
    end_date = end if end else pd.Timestamp(
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


@router.get(
    "/stocks/{code}/intraday",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm("stocks:view"))],
)
def stock_intraday(code: str, trade_date: date) -> ApiResponse:
    """按需返回近期交易日的 1 分钟不复权分时；只读本地门禁，源数据仅缓存 Redis。"""
    try:
        return ok(IntradayQuoteService().get(code, trade_date))
    except IntradayServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get(
    "/stocks/benchmarks/{index_code}/bars",
    response_model=ApiResponse,
    dependencies=[Depends(require_perm("stocks:view"))],
)
def stock_benchmark_bars(
    index_code: str,
    lookback: Annotated[int, Query(ge=2, le=6000)] = 61,
    end: date | None = None,
) -> ApiResponse:
    """个股相对强弱使用的市场交易日基准；与板块入口共享查询但保持 stocks 权限。"""
    c = get_client()
    end_date = end if end else pd.Timestamp(
        c.query_df("SELECT max(trade_date) AS d FROM index_bar").iloc[0]["d"]
    ).date()
    service = MarketBenchmarkService(c)
    try:
        rows = service.get_lookback(index_code, end_date, int(lookback))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    bars = [
        {
            "date": row["trade_date"],
            **{key: value for key, value in row.items() if key != "trade_date"},
            "pre_close": None,
            "turnover_rate": None,
        }
        for row in rows
    ]
    return ok({
        "index_code": index_code,
        "name": service.name(index_code),
        "end": str(end_date),
        "bars": bars,
    })


@router.get("/stocks/{code}/signal", response_model=ApiResponse,
            dependencies=[Depends(require_perm("stocks:view"))])
def stock_signal(
    code: str,
    date_: Annotated[date | None, Query(alias="date")] = None,
) -> ApiResponse:
    """个股当日买点 + 技术风险标签（按需计算，T-M6-3）。"""
    from backend.services.screen_score import ScreenScoreService

    c = get_client()
    d = date_ if date_ else pd.Timestamp(
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


@router.get("/stocks/{code}/trade-eval", response_model=ApiResponse,
            dependencies=[Depends(require_perm("stocks:trade-eval"))])
def stock_trade_eval(
    code: str,
    profile_id: str,
    date_: Annotated[date | None, Query(alias="date")] = None,
) -> ApiResponse:
    """个股×买卖指标方案：当日买/卖条件是否触发 + 各条件成立明细（v2.0 替代固定买点引擎）。

    点时安全（仅用 ≤ 当日数据）。买卖方案所用指标均非横截面，单股快照求值即正确。
    """
    from backend.api.response import err
    from backend.indicators.definition import IndicatorDefRepo
    from backend.indicators.engine import IndicatorEngine
    from backend.signals.trade_profile import TradeProfileRepo, collect_indicators, eval_conditions

    c = get_client()
    # profile_id 对外兼容旧字段名，但值允许为 opaque profile_ref；裸 id 只能解析到当前 owner。
    # 可见性统一交给资产仓库，避免 public/tenant 方案在列表可见、到评估接口却再次 owner-only。
    prof = TradeProfileRepo(c).get_visible(profile_id)
    if not prof:
        return err(404, "买卖方案不存在")
    d = date_ if date_ else pd.Timestamp(
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


@router.get("/stocks/{code}/indicators", response_model=ApiResponse,
            dependencies=[Depends(require_perm("stocks:view"))])
def stock_indicators(
    code: str,
    lookback: Annotated[int, Query(ge=1, le=6000)] = 60,
    fields: str | None = None,
    end: date | None = None,
    period: IndicatorPeriod = "day",
) -> ApiResponse:
    from backend.indicators.engine import IndicatorEngine

    selected = _parse_indicator_fields(fields)
    c = get_client()
    if period != "day":
        unsupported = [field for field in selected or [] if field not in MACD_OUTPUT_COLUMNS]
        if unsupported:
            raise HTTPException(
                status_code=400,
                detail=f"{period} 周期暂不支持的指标字段: {', '.join(unsupported)}",
            )
        end_date = end
        if end_date is None:
            latest = c.query_df(
                "SELECT max(trade_date) AS d FROM daily_bar WHERE code = ?", [code]
            ).iloc[0]["d"]
            if latest is None or pd.isna(latest):
                return ok({
                    "code": code, "period": period, "adjust": "qfq", "indicators": [],
                })
            end_date = pd.Timestamp(latest).date()
        # 单股全历史仅为数千行；先完整暖机再裁输出，避免周/月切换改变尾段结果。
        daily = MarketRepository(c).get_bars(code, end_date, lookback=None, adjust="qfq")
        df = compute_period_macd(daily, period).tail(int(lookback))
        columns = list(selected) if selected is not None else list(MACD_OUTPUT_COLUMNS)
        df = df.reindex(columns=["trade_date", *columns])
        return ok({
            "code": code,
            "period": period,
            "adjust": "qfq",
            "indicators": _serialize_indicator_rows(df),
        })

    # v2.0：指标动态实时计算（无 indicator 表）。多取窗口暖机后裁末段 lookback 行。
    # 注：rs_pct 为横截面量，单股序列不填（个股查询页该列为空，M2.4 适配）。
    df = IndicatorEngine(c).compute_series(
        code,
        end_date=end,
        lookback=int(lookback) + 520,
    )
    if df.empty:
        return ok({
            "code": code, "period": period, "adjust": "qfq", "indicators": [],
        })
    df = df.sort_values("trade_date").tail(int(lookback))
    if selected is not None:
        df = df.reindex(columns=["trade_date", *selected])
    return ok({
        "code": code,
        "period": period,
        "adjust": "qfq",
        "indicators": _serialize_indicator_rows(df),
    })


# 数据管理页专属读接口：仅平台系统管理员可见（需求 §7 数据管理菜单 system-only；R8 守卫）。
# 注：/data/trade-dates 是全站日期选择器共享读，普通用户页面依赖，**不在此守卫内**。
@router.get("/data/status", response_model=ApiResponse,
            dependencies=[Depends(require_system_perm("data-status:view"))])
def data_status() -> ApiResponse:
    c = get_client()
    span = c.query_df(
        "SELECT max(trade_date) AS latest, count(DISTINCT code) AS codes, count(*) AS rows FROM daily_bar").iloc[0]
    issues = int(c.query_df(
        "SELECT count(*) AS n FROM data_quality_issue WHERE status IN ('open', 'fixing')").iloc[0]["n"])
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


@router.get("/data/update-logs", response_model=ApiResponse,
            dependencies=[Depends(require_system_perm("data-status:view"))])
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


@router.get("/data/trade-dates", response_model=ApiResponse,
            dependencies=[Depends(require_perm("trade-calendar:view"))])
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
