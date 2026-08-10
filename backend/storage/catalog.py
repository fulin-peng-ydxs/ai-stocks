"""基础数据表元数据字典（数据概览·数据字典，FR-DM-1 / DM-D11）。

设计：表/字段的中文说明、作用、关联关系是**相对稳定的文档**，用代码内置字典维护，
不另建需手维护的字典表（DM-D11）。运行时由 build_catalog() 拼上每表行数、最新数据时间、
未解决质检数，供 GET /api/data/catalog 渲染。

新增基础数据维度（如股东数）时，在此登记一张表的字段说明即可被概览自动收录。
"""

from __future__ import annotations

import pandas as pd

from backend.storage.duckdb_client import DuckDBClient, get_client

# 时序数据表：其"最新数据时间"应跟上全局最新交易日，据此判鲜活（M2.9 DM-D15）。
# 非时序表（日历/日志/质检台账）鲜活度无意义，fresh=None。
_TIMESERIES_TABLES: frozenset[str] = frozenset(
    {"daily_bar", "daily_metrics", "index_bar", "board_bar", "board_fund_flow"})

_BOARD_ISSUES_BY_TABLE: dict[str, tuple[str, ...]] = {
    "board_dict": ("board_index_gap", "board_member_incomplete", "board_fund_unmatched", "board_fund_missing", "board_fund_stale"),
    "board_member": ("board_member_incomplete",),
    "board_bar": ("board_index_gap",),
    "board_fund_flow": ("board_fund_unmatched", "board_fund_missing", "board_fund_stale"),
}

# 每张基础数据表的元信息。
# - date_col：用于取"最新数据时间"的列（None 表示该表无时间维度，取 NULL）。
# - relations：与其它表的关联关系（人类可读）。
TABLE_CATALOG: dict[str, dict] = {
    "stock_basic": {
        "name_cn": "股票基础信息",
        "purpose": "全市场股票主数据：代码/名称/交易所/板块/上市退市日/行业/涨跌幅限制，所有维度的关联主键来源。",
        "date_col": None,
        "relations": ["daily_bar/daily_metrics 经 code 关联", "stock_group_member 经 code 关联"],
        "fields": [
            {"name": "code", "type": "VARCHAR", "name_cn": "股票代码", "desc": "含交易所后缀，如 600000.SH（主键）"},
            {"name": "name", "type": "VARCHAR", "name_cn": "名称", "desc": "当前名称（含 ST 前缀）"},
            {"name": "exchange", "type": "VARCHAR", "name_cn": "交易所", "desc": "SH 上交所 / SZ 深交所"},
            {"name": "board", "type": "VARCHAR", "name_cn": "板块", "desc": "主板 / 创业板 / 科创板"},
            {"name": "list_date", "type": "DATE", "name_cn": "上市日", "desc": "用于次新过滤与缺口起点"},
            {"name": "delist_date", "type": "DATE", "name_cn": "退市日", "desc": "NULL 表示在市"},
            {"name": "total_share", "type": "BIGINT", "name_cn": "总股本", "desc": "最新值"},
            {"name": "float_share", "type": "BIGINT", "name_cn": "流通股本", "desc": "最新值"},
            {"name": "industry", "type": "VARCHAR", "name_cn": "行业", "desc": "所属行业（行业集中度约束用）"},
            {"name": "concept", "type": "VARCHAR", "name_cn": "概念", "desc": "概念标签（JSON）"},
            {"name": "price_limit_pct", "type": "DOUBLE", "name_cn": "涨跌幅限制", "desc": "板块涨跌幅限制：主板 0.10 / 创业板与科创板 0.20；ST 按交易日规则另算"},
        ],
    },
    "daily_bar": {
        "name_cn": "日线行情",
        "purpose": "核心大表：不复权 OHLC + 复权因子 + 成交量额/换手 + 涨跌停/停牌/一字板标记，选股与回测的行情基础。",
        "date_col": "trade_date",
        "relations": ["code → stock_basic", "trade_date → trade_calendar"],
        "fields": [
            {"name": "code", "type": "VARCHAR", "name_cn": "股票代码", "desc": "主键之一"},
            {"name": "trade_date", "type": "DATE", "name_cn": "交易日", "desc": "主键之一"},
            {"name": "open", "type": "DOUBLE", "name_cn": "开盘价", "desc": "不复权原始价"},
            {"name": "high", "type": "DOUBLE", "name_cn": "最高价", "desc": "不复权"},
            {"name": "low", "type": "DOUBLE", "name_cn": "最低价", "desc": "不复权"},
            {"name": "close", "type": "DOUBLE", "name_cn": "收盘价", "desc": "不复权"},
            {"name": "pre_close", "type": "DOUBLE", "name_cn": "前收盘", "desc": "算涨跌停/涨跌幅"},
            {"name": "volume", "type": "BIGINT", "name_cn": "成交量", "desc": "股"},
            {"name": "amount", "type": "DOUBLE", "name_cn": "成交额", "desc": "元"},
            {"name": "adj_factor", "type": "DOUBLE", "name_cn": "复权因子(源)", "desc": "源端反推，含舍入噪声，留作审计/后复权绝对价"},
            {"name": "adj_factor_clean", "type": "DOUBLE", "name_cn": "复权因子(去抖)", "desc": "去抖后分段恒定，前/后复权 K线价/涨跌幅实际用此列"},
            {"name": "turnover_rate", "type": "DOUBLE", "name_cn": "换手率", "desc": "%"},
            {"name": "is_st", "type": "BOOLEAN", "name_cn": "是否ST", "desc": "当日是否 ST（尽力而为）"},
            {"name": "is_suspended", "type": "BOOLEAN", "name_cn": "是否停牌", "desc": "历史遗留列(恒False)；停牌实际以「开市日无行情」推导，确认停牌记于 stock_suspension 表"},
            {"name": "limit_status", "type": "TINYINT", "name_cn": "涨跌停", "desc": "0 正常 / 1 涨停 / -1 跌停"},
            {"name": "is_one_word", "type": "BOOLEAN", "name_cn": "一字板", "desc": "是否一字涨跌停"},
        ],
    },
    "daily_metrics": {
        "name_cn": "每日市值指标",
        "purpose": "逐日衍生指标：流通市值 / 总市值，股票池规模过滤与分层。",
        "date_col": "trade_date",
        "relations": ["(code, trade_date) → daily_bar"],
        "fields": [
            {"name": "code", "type": "VARCHAR", "name_cn": "股票代码", "desc": "主键之一"},
            {"name": "trade_date", "type": "DATE", "name_cn": "交易日", "desc": "主键之一"},
            {"name": "float_mv", "type": "DOUBLE", "name_cn": "流通市值", "desc": "close × 流通股本（元）"},
            {"name": "total_mv", "type": "DOUBLE", "name_cn": "总市值", "desc": "元（逐股质量达标关键字段）"},
        ],
    },
    "index_bar": {
        "name_cn": "指数日线",
        "purpose": "基准指数行情（沪深300/中证500/中证全指），回测基准与相对强弱计算。",
        "date_col": "trade_date",
        "relations": ["trade_date → trade_calendar"],
        "fields": [
            {"name": "index_code", "type": "VARCHAR", "name_cn": "指数代码", "desc": "如 000300.SH（主键之一）"},
            {"name": "trade_date", "type": "DATE", "name_cn": "交易日", "desc": "主键之一"},
            {"name": "open", "type": "DOUBLE", "name_cn": "开盘", "desc": ""},
            {"name": "high", "type": "DOUBLE", "name_cn": "最高", "desc": ""},
            {"name": "low", "type": "DOUBLE", "name_cn": "最低", "desc": ""},
            {"name": "close", "type": "DOUBLE", "name_cn": "收盘", "desc": ""},
            {"name": "volume", "type": "BIGINT", "name_cn": "成交量", "desc": ""},
            {"name": "amount", "type": "DOUBLE", "name_cn": "成交额", "desc": ""},
        ],
    },
    "trade_calendar": {
        "name_cn": "交易日历",
        "purpose": "开市日判定，缺口检测与点时安全的基础。",
        "date_col": "trade_date",
        "relations": ["被 daily_bar/index_bar 引用"],
        "fields": [
            {"name": "trade_date", "type": "DATE", "name_cn": "日期", "desc": "主键"},
            {"name": "is_open", "type": "BOOLEAN", "name_cn": "是否开市", "desc": "true=交易日"},
        ],
    },
    "data_update_log": {
        "name_cn": "采集更新日志",
        "purpose": "每次采集留痕（表/源/区间/行数/状态），支持断点续跑与采集时间线展示。",
        "date_col": "updated_at",
        "relations": ["按 table_name 指向各数据表"],
        "fields": [
            {"name": "id", "type": "BIGINT", "name_cn": "序号", "desc": "自增"},
            {"name": "table_name", "type": "VARCHAR", "name_cn": "目标表", "desc": "采集写入的表"},
            {"name": "source", "type": "VARCHAR", "name_cn": "数据源", "desc": "akshare / baostock"},
            {"name": "date_start", "type": "DATE", "name_cn": "起始日", "desc": "本次采集区间起"},
            {"name": "date_end", "type": "DATE", "name_cn": "结束日", "desc": "本次采集区间止"},
            {"name": "row_count", "type": "BIGINT", "name_cn": "行数", "desc": "本次写入行数"},
            {"name": "status", "type": "VARCHAR", "name_cn": "状态", "desc": "success / failed / partial"},
            {"name": "detail", "type": "VARCHAR", "name_cn": "详情", "desc": "失败原因/摘要"},
            {"name": "updated_at", "type": "TIMESTAMP", "name_cn": "时间", "desc": "记录时间"},
        ],
    },
    "data_quality_issue": {
        "name_cn": "数据质量问题",
        "purpose": "质检发现的问题台账：类型/严重度/状态，支持单条重拉/重算修复闭环。",
        "date_col": "detected_at",
        "relations": ["code → stock_basic", "(code, trade_date) → daily_bar"],
        "fields": [
            {"name": "id", "type": "BIGINT", "name_cn": "序号", "desc": "自增"},
            {"name": "code", "type": "VARCHAR", "name_cn": "股票代码", "desc": "涉及股票"},
            {"name": "trade_date", "type": "DATE", "name_cn": "交易日", "desc": "涉及日期（可空）"},
            {"name": "issue_type", "type": "VARCHAR", "name_cn": "问题类型", "desc": "null_close/ohl_repaired(L1) / mv_missing(L2) / abnormal_change/adj_jump(L3) / data_gap/stale(L4)"},
            {"name": "severity", "type": "VARCHAR", "name_cn": "严重度", "desc": "high/mid/low"},
            {"name": "status", "type": "VARCHAR", "name_cn": "状态", "desc": "open/fixing/resolved/ignored"},
            {"name": "detail", "type": "VARCHAR", "name_cn": "详情", "desc": "问题描述"},
            {"name": "detected_at", "type": "TIMESTAMP", "name_cn": "检出时间", "desc": ""},
            {"name": "resolved_at", "type": "TIMESTAMP", "name_cn": "解决时间", "desc": "修复完成回写"},
        ],
    },
    "board_dict": {
        "name_cn": "板块字典",
        "purpose": "概念/行业板块主数据：路径 code（概念 30xxxx / 行业 88xxxx）+ App clid + 能力字段（has_members/has_bar/has_fund_flow），所有板块维度关联主键来源。",
        "date_col": "last_seen_at",
        "relations": ["board_member/board_bar/board_fund_flow 经 board_code 关联"],
        "fields": [
            {"name": "board_code", "type": "VARCHAR", "name_cn": "板块代码", "desc": "同花顺路径 code（主键）"},
            {"name": "app_code", "type": "VARCHAR", "name_cn": "App代码", "desc": "同花顺 App clid"},
            {"name": "name", "type": "VARCHAR", "name_cn": "板块名", "desc": ""},
            {"name": "board_type", "type": "VARCHAR", "name_cn": "板块类型", "desc": "concept / industry"},
            {"name": "member_count", "type": "BIGINT", "name_cn": "成分数", "desc": "最近已应用快照的冗余成分数"},
            {"name": "member_snapshot_at", "type": "TIMESTAMP", "name_cn": "最近完整成分快照", "desc": "最近一次完整快照成功落库时间"},
            {"name": "has_members", "type": "BOOLEAN", "name_cn": "有成分", "desc": ""},
            {"name": "has_bar", "type": "BOOLEAN", "name_cn": "有指数", "desc": ""},
            {"name": "has_fund_flow", "type": "BOOLEAN", "name_cn": "有资金流", "desc": ""},
        ],
    },
    "board_member": {
        "name_cn": "板块成分股",
        "purpose": "板块↔成分股多对多关系，只进不出累积（每行一只成分股，不删除）。",
        "date_col": None,
        "relations": ["board_code → board_dict", "code → stock_basic"],
        "fields": [
            {"name": "board_code", "type": "VARCHAR", "name_cn": "板块代码", "desc": ""},
            {"name": "code", "type": "VARCHAR", "name_cn": "成分股代码", "desc": "含交易所后缀"},
        ],
    },
    "board_bar": {
        "name_cn": "板块指数",
        "purpose": "板块指数日线（同花顺原始连续指数，存原值不套复权链）。",
        "date_col": "trade_date",
        "relations": ["board_code → board_dict"],
        "fields": [
            {"name": "board_code", "type": "VARCHAR", "name_cn": "板块代码", "desc": ""},
            {"name": "trade_date", "type": "DATE", "name_cn": "交易日", "desc": ""},
            {"name": "open", "type": "DOUBLE", "name_cn": "开盘", "desc": ""},
            {"name": "high", "type": "DOUBLE", "name_cn": "最高", "desc": ""},
            {"name": "low", "type": "DOUBLE", "name_cn": "最低", "desc": ""},
            {"name": "close", "type": "DOUBLE", "name_cn": "收盘", "desc": ""},
            {"name": "volume", "type": "DOUBLE", "name_cn": "成交量", "desc": ""},
            {"name": "amount", "type": "DOUBLE", "name_cn": "成交额", "desc": ""},
        ],
    },
    "board_fund_flow": {
        "name_cn": "板块资金流",
        "purpose": "板块资金流（概念/行业 × 即时/3日/5日/10日/20日周期），含领涨股。",
        "date_col": "snapshot_date",
        "relations": ["board_code → board_dict"],
        "fields": [
            {"name": "board_code", "type": "VARCHAR", "name_cn": "板块代码", "desc": ""},
            {"name": "snapshot_date", "type": "DATE", "name_cn": "快照日", "desc": ""},
            {"name": "period", "type": "VARCHAR", "name_cn": "周期", "desc": "即时/3日/5日/10日/20日"},
            {"name": "inflow", "type": "DOUBLE", "name_cn": "流入", "desc": ""},
            {"name": "outflow", "type": "DOUBLE", "name_cn": "流出", "desc": ""},
            {"name": "net_inflow", "type": "DOUBLE", "name_cn": "净流入", "desc": ""},
            {"name": "leader_stock", "type": "VARCHAR", "name_cn": "领涨股", "desc": ""},
            {"name": "leader_pct", "type": "DOUBLE", "name_cn": "领涨股涨幅", "desc": ""},
        ],
    },
}


def _table_exists(client: DuckDBClient, table: str) -> bool:
    df = client.query_df(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='main' AND table_name=?", [table])
    return not df.empty


def build_catalog(client: DuckDBClient | None = None) -> list[dict]:
    """拼装数据字典：每表元信息 + 运行时行数 / 最新数据时间 / 未解决质检数。

    返回 [{table, name_cn, purpose, rows, latest_time, fields, relations, open_issues}]。
    """
    client = client or get_client()
    # 全局最新交易日：时序表鲜活度的基准（最新时间为空或滞后 → 不算正常，DM-D15）。
    global_latest = None
    if _table_exists(client, "daily_bar"):
        gt = client.query_df("SELECT max(trade_date) AS t FROM daily_bar").iloc[0]["t"]
        global_latest = None if gt is None or str(gt) == "NaT" else str(pd.Timestamp(gt).date())
    # 一次性取各表的未解决质检数（按 issue 涉及表归类有难度，这里给全局 open 数附在相关表）
    out: list[dict] = []
    for table, meta in TABLE_CATALOG.items():
        rows = 0
        latest_time = None
        if _table_exists(client, table):
            rows = int(client.query_df(f"SELECT count(*) AS n FROM {table}").iloc[0]["n"])
            date_col = meta.get("date_col")
            if date_col:
                df = client.query_df(f"SELECT max({date_col}) AS t FROM {table}")
                t = df.iloc[0]["t"]
                latest_time = None if t is None or str(t) == "NaT" else str(t)
        open_issues = 0
        if table == "data_quality_issue" and _table_exists(client, table):
            open_issues = int(client.query_df(
                "SELECT count(*) AS n FROM data_quality_issue WHERE status='open'"
            ).iloc[0]["n"])
        elif table in _BOARD_ISSUES_BY_TABLE and _table_exists(client, "data_quality_issue"):
            issue_types = _BOARD_ISSUES_BY_TABLE[table]
            ph = ",".join("?" * len(issue_types))
            open_issues = int(client.query_df(
                f"SELECT count(*) AS n FROM data_quality_issue "
                f"WHERE status IN ('open','fixing') AND issue_type IN ({ph})",
                list(issue_types)).iloc[0]["n"])
        # 鲜活度：仅时序数据表参与判定；最新时间为空 → False（不再误判"正常"）。
        fresh = None
        if table in _TIMESERIES_TABLES:
            if latest_time is None or global_latest is None:
                fresh = False
            else:
                latest_date = str(pd.Timestamp(latest_time).date())
                fresh = (latest_date >= global_latest if table == "board_fund_flow"
                         else latest_date == global_latest)
        out.append({
            "table": table,
            "name_cn": meta["name_cn"],
            "purpose": meta["purpose"],
            "rows": rows,
            "latest_time": latest_time,
            "fresh": fresh,
            "fields": meta["fields"],
            "relations": meta["relations"],
            "open_issues": open_issues,
        })
    return out
