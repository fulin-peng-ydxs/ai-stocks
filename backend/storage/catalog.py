"""双库数据资产目录（数据概览，FR-DM-1 / DM-D11）。

DuckDB main 与 PostgreSQL public 的物理表和字段由系统目录自动发现；代码内只维护
稳定的业务注解、生命周期和事实源路由。未注解的物理表必须以 unregistered 暴露，
规划中且尚无物理表的维度继续由 data_dimension_registry 管理。
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import Any, Literal

import pandas as pd

from backend.storage.duckdb_client import DuckDBClient, get_client
from backend.storage.pg_client import PostgresClient, get_pg_client

# 时序数据表：其"最新数据时间"应跟上全局最新交易日，据此判鲜活（M2.9 DM-D15）。
# 非时序表（日历/日志/质检台账）鲜活度无意义，fresh=None。
_TIMESERIES_TABLES: frozenset[str] = frozenset(
    {
        "daily_bar",
        "daily_metrics",
        "index_bar",
        "board_bar",
        "board_fund_flow",
        "stock_board_correlation",
        "stock_board_correlation_state",
        "stock_st_status_date_revision",
    }
)

_BOARD_ISSUES_BY_TABLE: dict[str, tuple[str, ...]] = {
    "board_dict": ("board_index_gap", "board_index_invalid", "board_member_incomplete", "board_fund_unmatched"),
    "board_member": ("board_member_incomplete",),
    "board_bar": ("board_index_gap", "board_index_gap_daily", "board_index_invalid"),
    "board_fund_flow": ("board_fund_unmatched", "board_fund_missing", "board_fund_stale"),
}

_MARKET_INDEX_ISSUES: tuple[str, ...] = (
    "market_index_gap", "market_index_gap_daily", "market_index_invalid",
)

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
            {"name": "is_st", "type": "BOOLEAN", "name_cn": "是否ST", "desc": "过渡物化投影；唯一事实来自 stock_st_status_daily"},
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
        "purpose": (
            "六类市场指数行情（中证 500、沪深 300、上证指数、科创 50、深证成指、"
            "创业板指），用于回测基准与相对强弱计算；按配置指数分别检查"
            "鲜活度、近端缺口和行合法性。"
        ),
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
        "relations": [
            "个股 code → stock_basic",
            "市场指数 code → index_bar.index_code",
            "板块 code → board_dict.board_code",
        ],
        "fields": [
            {"name": "id", "type": "BIGINT", "name_cn": "序号", "desc": "自增"},
            {"name": "code", "type": "VARCHAR", "name_cn": "对象代码", "desc": "股票、市场指数或板块代码；源级问题可空"},
            {"name": "trade_date", "type": "DATE", "name_cn": "交易日", "desc": "涉及日期（可空）"},
            {"name": "issue_type", "type": "VARCHAR", "name_cn": "问题类型", "desc": "个股 L1-L4、市场指数或板块质量问题"},
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
            {"name": "member_count", "type": "BIGINT", "name_cn": "最近完整快照返回数", "desc": "最近一次完整成分快照返回的成员数量；行情统计另用 board_member 历史累计关系"},
            {"name": "member_snapshot_at", "type": "TIMESTAMP", "name_cn": "最近完整成分快照", "desc": "最近一次完整快照成功落库时间"},
            {"name": "has_members", "type": "BOOLEAN", "name_cn": "有成分", "desc": ""},
            {"name": "has_bar", "type": "BOOLEAN", "name_cn": "有指数", "desc": ""},
            {"name": "has_fund_flow", "type": "BOOLEAN", "name_cn": "有资金流", "desc": ""},
        ],
    },
    "board_member": {
        "name_cn": "板块成分股",
        "purpose": "板块↔成分股多对多关系，只进不出累积；首次观测日为空的存量关系兼容全部历史。",
        "date_col": "first_seen_date",
        "relations": ["board_code → board_dict", "code → stock_basic"],
        "fields": [
            {"name": "board_code", "type": "VARCHAR", "name_cn": "板块代码", "desc": ""},
            {"name": "code", "type": "VARCHAR", "name_cn": "成分股代码", "desc": "含交易所后缀"},
            {"name": "first_seen_date", "type": "DATE", "name_cn": "首次观测日", "desc": "首次完整采集到该关系的业务日；NULL 视为历史已存在"},
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
    "stock_board_correlation": {
        "name_cn": "个股走势关联板块冠军",
        "purpose": "每只股票当前行业/概念走势相关冠军及双窗口市场中性相关结果；仅保存当前态，不保存候选和历史快照。",
        "date_col": "as_of_date",
        "relations": [
            "code → stock_basic",
            "board_code → board_dict",
            "code → stock_board_correlation_state",
        ],
        "fields": [
            {"name": "code", "type": "VARCHAR", "name_cn": "股票代码", "desc": "主键之一"},
            {"name": "board_type", "type": "VARCHAR", "name_cn": "板块类型", "desc": "industry / concept，主键之一"},
            {"name": "board_code", "type": "VARCHAR", "name_cn": "冠军板块代码", "desc": "关联 board_dict"},
            {"name": "score", "type": "DOUBLE", "name_cn": "综合相关分", "desc": "0.6×corr_20 + 0.4×corr_60"},
            {"name": "corr_20", "type": "DOUBLE", "name_cn": "20日相关系数", "desc": "市场中性收益相关系数"},
            {"name": "corr_60", "type": "DOUBLE", "name_cn": "60日相关系数", "desc": "市场中性收益相关系数"},
            {"name": "sample_20", "type": "INTEGER", "name_cn": "20日样本数", "desc": "冠军至少 15 个有效样本"},
            {"name": "sample_60", "type": "INTEGER", "name_cn": "60日样本数", "desc": "冠军至少 40 个有效样本"},
            {"name": "confidence", "type": "VARCHAR", "name_cn": "可信度", "desc": "high / medium / low"},
            {"name": "benchmark_code", "type": "VARCHAR", "name_cn": "实际基准", "desc": "本股中性化实际使用的市场指数"},
            {"name": "benchmark_fallback", "type": "BOOLEAN", "name_cn": "是否回退基准", "desc": "板块基准不足时整股回退上证指数"},
            {"name": "as_of_date", "type": "DATE", "name_cn": "数据截止日", "desc": "本轮共同目标交易日"},
            {"name": "computed_at", "type": "TIMESTAMP", "name_cn": "计算时间", "desc": "本轮成功计算时间"},
            {"name": "algorithm_version", "type": "VARCHAR", "name_cn": "算法版本", "desc": "用于强制重算与一致性校验"},
        ],
    },
    "stock_board_correlation_state": {
        "name_cn": "个股走势关联板块状态",
        "purpose": "记录每只股票最近一次成功处理口径及行业/概念冠军是否存在，使两类合法为空时仍可与未计算区分。",
        "date_col": "as_of_date",
        "relations": ["code → stock_basic", "code → stock_board_correlation"],
        "fields": [
            {"name": "code", "type": "VARCHAR", "name_cn": "股票代码", "desc": "主键"},
            {"name": "as_of_date", "type": "DATE", "name_cn": "数据截止日", "desc": "本轮共同目标交易日"},
            {"name": "computed_at", "type": "TIMESTAMP", "name_cn": "计算时间", "desc": "本轮成功处理时间"},
            {"name": "algorithm_version", "type": "VARCHAR", "name_cn": "算法版本", "desc": "与冠军结果保持一致"},
            {"name": "benchmark_code", "type": "VARCHAR", "name_cn": "实际基准", "desc": "本股中性化实际使用的市场指数"},
            {"name": "benchmark_fallback", "type": "BOOLEAN", "name_cn": "是否回退基准", "desc": "是否整股回退上证指数"},
            {"name": "has_industry_champion", "type": "BOOLEAN", "name_cn": "有行业冠军", "desc": "FALSE 可表示合法空结果"},
            {"name": "has_concept_champion", "type": "BOOLEAN", "name_cn": "有概念冠军", "desc": "FALSE 可表示合法空结果"},
        ],
    },
}


def _table_exists(client: DuckDBClient, table: str) -> bool:
    df = client.query_df(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='main' AND table_name=?", [table])
    return not df.empty


def _build_legacy_duck_catalog(client: DuckDBClient | None = None) -> list[dict]:
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
        elif (table == "index_bar" or table in _BOARD_ISSUES_BY_TABLE) \
                and _table_exists(client, "data_quality_issue"):
            issue_types = _MARKET_INDEX_ISSUES if table == "index_bar" \
                else _BOARD_ISSUES_BY_TABLE[table]
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
            elif table == "index_bar":
                # 必须每个已配置市场指数都追平，不能被全表 max(date) 掩盖单指数停更。
                from backend.services.market_benchmark import configured_benchmark_codes

                codes = configured_benchmark_codes()
                ph = ",".join("?" * len(codes))
                latest_by_code = client.query_df(
                    f"SELECT index_code, max(trade_date) AS latest "
                    f"FROM index_bar WHERE index_code IN ({ph}) GROUP BY index_code",
                    codes,
                ) if codes else pd.DataFrame(columns=["index_code", "latest"])
                latest_map = {
                    str(r["index_code"]): str(pd.Timestamp(r["latest"]).date())
                    for _, r in latest_by_code.iterrows()
                    if r["latest"] is not None and not pd.isna(r["latest"])
                }
                fresh = bool(codes) and bool(global_latest) and all(
                    latest_map.get(code) is not None and latest_map[code] >= global_latest
                    for code in codes
                )
            else:
                latest_date = str(pd.Timestamp(latest_time).date())
                # 板块源（指数/资金流）采集节奏可能领先个股行情（如周末已采到下周一的板块数据），
                # 最新时间不早于全局最新交易日即算新鲜；个股时序表须严格等于最新交易日。
                fresh = (latest_date >= global_latest if table in ("board_fund_flow", "board_bar")
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


# ── 双库物理资产目录 ──────────────────────────────────────────────

DatabaseFilter = Literal["all", "duckdb", "postgres"]
CountMode = Literal["estimated", "exact"]


class CatalogExactCountError(RuntimeError):
    """单表精确统计失败；目录估算结果本身仍可继续使用。"""

_SAFE_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_DUCK_EXTRA_META: dict[str, dict[str, Any]] = {
    "data_dimension_registry": {
        "name_cn": "数据维度注册",
        "category": "数据治理",
        "purpose": "登记已采集、部分覆盖与规划中的数据维度，驱动数据概览展示。",
        "ownership_scope": "platform_global",
        "source": "系统登记",
    },
    "data_source_provenance": {
        "name_cn": "数据来源溯源",
        "category": "数据治理",
        "purpose": "记录非默认数据源的分段取数事实，用于来源审计与问题排查。",
        "ownership_scope": "market_global",
        "source": "采集任务",
    },
    "indicator_def": {
        "name_cn": "技术指标定义",
        "category": "指标配置",
        "purpose": "统一保存内置指标与表达式指标定义，供筛选、评分、买卖和回测消费。",
        "ownership_scope": "platform_global",
        "source": "系统内置/管理员配置",
    },
    "stock_suspension": {
        "name_cn": "股票停牌事实",
        "category": "行情参考",
        "purpose": "保存已确认的开市日停牌事实，避免用日线占位行破坏可交易语义。",
        "ownership_scope": "market_global",
        "source": "行情重采确认",
    },
    "stock_st_status_daily": {
        "name_cn": "每日点时 ST 状态",
        "category": "行情参考",
        "purpose": "保存每股每日权威 ST 点时事实、来源和质量，供全业务统一消费。",
        "ownership_scope": "market_global",
        "source": "行情/ST 状态维护",
    },
    "stock_st_status_history": {
        "name_cn": "ST 状态变更历史",
        "category": "行情参考",
        "purpose": "保存 ST 值、来源或质量变化的不可变历史。",
        "ownership_scope": "market_global",
        "source": "ST 状态维护",
    },
    "stock_st_status_refresh_state": {
        "name_cn": "ST 刷新发布状态",
        "category": "行情参考",
        "purpose": "标记 ST 批量刷新是否完成，防止业务读取刷新中的混合批次。",
        "ownership_scope": "market_global",
        "source": "ST 状态维护",
    },
    "stock_st_status_date_revision": {
        "name_cn": "ST 日期修订版本",
        "category": "行情参考",
        "purpose": "保存每个交易日 ST 事实的单调修订号，供榜单和天梯读取时低成本校验缓存。",
        "ownership_scope": "market_global",
        "source": "ST 状态维护",
    },
    "limit_ladder_snapshot_state": {
        "name_cn": "连板天梯日期状态",
        "category": "连板天梯",
        "purpose": "保存交易日快照状态、当前成功版本、任务与失败摘要。",
        "ownership_scope": "market_global",
        "source": "连板天梯任务",
    },
    "limit_ladder_snapshot": {
        "name_cn": "连板天梯快照",
        "category": "连板天梯",
        "purpose": "保存不可变天梯快照元数据、覆盖门禁和窗口元数据。",
        "ownership_scope": "market_global",
        "source": "连板天梯任务",
    },
    "limit_ladder_snapshot_stock": {
        "name_cn": "连板天梯个股明细",
        "category": "连板天梯",
        "purpose": "保存快照发布时的股票身份、板位、ST、一字板与行业事实。",
        "ownership_scope": "market_global",
        "source": "连板天梯任务",
    },
    "limit_ladder_snapshot_concept": {
        "name_cn": "连板天梯概念明细",
        "category": "连板天梯",
        "purpose": "保存快照发布时的完整概念归属集合。",
        "ownership_scope": "market_global",
        "source": "连板天梯任务",
    },
    "limit_ladder_snapshot_aggregate": {
        "name_cn": "连板天梯聚合",
        "category": "连板天梯",
        "purpose": "保存快照发布校验使用的行业与概念聚合。",
        "ownership_scope": "market_global",
        "source": "连板天梯任务",
    },
    "limit_ladder_snapshot_window_metric": {
        "name_cn": "连板天梯窗口指标",
        "category": "连板天梯",
        "purpose": "保存每股四档窗口涨停次数、累计涨幅与短历史字段。",
        "ownership_scope": "market_global",
        "source": "连板天梯任务",
    },
    "limit_ladder_invalidation_outbox": {
        "name_cn": "连板天梯失效事件",
        "category": "连板天梯",
        "purpose": "可靠保存显式结果维护产生的快照失效意图及补偿状态。",
        "ownership_scope": "runtime_global",
        "source": "结果维护任务",
    },
}

_DUCK_CATEGORY_OVERRIDES = {
    "stock_basic": "行情参考",
    "daily_bar": "行情参考",
    "daily_metrics": "行情参考",
    "index_bar": "行情参考",
    "trade_calendar": "行情参考",
    "data_update_log": "数据治理",
    "data_quality_issue": "数据治理",
    "board_dict": "板块数据",
    "board_member": "板块数据",
    "board_bar": "板块数据",
    "board_fund_flow": "板块数据",
    "stock_board_correlation": "走势关联",
    "stock_board_correlation_state": "走势关联",
}

_PG_META_GROUPS: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("身份与权限", "platform_global", {
        "sys_tenant": "租户",
        "sys_user": "用户",
        "sys_role": "角色",
        "sys_menu": "菜单",
        "sys_resource": "功能点",
        "sys_user_role": "用户角色关系",
        "sys_role_menu": "角色菜单关系",
        "sys_role_resource": "角色功能点关系",
    }),
    ("方案与分组资产", "tenant_user", {
        "screen_profile": "筛选方案",
        "screen_profile_version": "筛选方案版本",
        "score_profile": "评分方案",
        "score_profile_version": "评分方案版本",
        "trade_profile": "买卖方案",
        "trade_profile_version": "买卖方案版本",
        "screen_result": "筛选结果",
        "score_result": "评分结果",
        "stock_group": "股票分组",
        "stock_group_member": "股票分组成员",
        "board_watchlist": "板块自选",
    }),
    ("交易纪律", "tenant_user", {
        "trade_discipline_rule": "交易纪律规则",
        "trade_discipline_rule_name_claim": "交易纪律名称占用",
        "trade_discipline_rule_version": "交易纪律规则版本",
        "trade_discipline_stock_rule": "交易纪律个股规则",
        "trade_discipline_action_subtype": "交易动作子类型",
        "trade_discipline_action_rule": "交易动作规则",
        "trade_discipline_rule_draft": "交易纪律草稿",
        "trade_discipline_draft_stock_rule": "交易纪律个股草稿",
        "trade_discipline_draft_action_rule": "交易动作草稿",
        "trade_discipline_rule_activation": "交易纪律启用记录",
        "trade_discipline_checkin": "交易纪律打卡",
        "trade_discipline_checkin_revision": "交易纪律打卡修订",
        "trade_discipline_reason": "交易纪律原因",
        "trade_discipline_violation": "交易纪律违规",
        "trade_discipline_operation": "交易纪律操作",
    }),
    ("回测资产", "tenant_user", {
        "backtest_run": "回测运行",
        "backtest_trade": "回测成交",
        "backtest_equity": "回测权益曲线",
        "backtest_metrics": "回测指标",
    }),
    ("评分快照", "tenant_user", {
        "score_snapshot": "评分快照",
        "score_snapshot_meta": "评分快照元数据",
    }),
    ("盘感训练", "tenant_user", {
        "training_session": "盘感训练会话",
        "training_round": "盘感训练回合",
        "training_trade": "盘感训练成交",
    }),
    ("布局与配置", "platform_global", {
        "layout_preset": "布局预设",
        "layout_page_config": "页面布局配置",
        "layout_field_policy": "布局字段策略",
        "app_config": "平台运行配置",
        "dict_type": "数据字典类型",
        "dict_item": "数据字典项",
    }),
    ("布局与配置", "user", {
        "layout_user_config": "用户布局配置",
        "user_preference": "用户偏好",
    }),
    ("任务与调度", "runtime_global", {
        "storage_migration": "存储迁移状态",
        "async_task": "异步任务",
        "task_log": "任务日志",
        "scheduled_job": "定时任务",
        "scheduled_trigger_event": "调度触发事件",
    }),
    ("审计与协调", "platform_global", {
        "audit_log": "审计日志",
        "limit_ladder_task_ledger": "连板天梯任务账本",
        "limit_ladder_audit_outbox": "连板天梯审计事件",
    }),
)

_PG_TABLE_META: dict[str, dict[str, Any]] = {}
for _category, _scope, _names in _PG_META_GROUPS:
    for _table, _name_cn in _names.items():
        _PG_TABLE_META[_table] = {
            "name_cn": _name_cn,
            "category": _category,
            "ownership_scope": _scope,
            "purpose": f"{_name_cn}，属于{_category}领域的 PostgreSQL 当前事实表。",
            "source": "业务服务",
        }

_COMMON_FIELD_META: dict[str, tuple[str, str]] = {
    "tenant_id": ("租户 ID", "数据所属租户"),
    "owner_user_id": ("所有者用户 ID", "用户资产真实所有者"),
    "created_at": ("创建时间", "记录创建时间"),
    "updated_at": ("更新时间", "记录最近更新时间"),
    "fix_task_id": ("修复任务 ID", "进入修复中状态时绑定的异步任务"),
    "ignore_scope": ("忽略范围", "仅本次 occurrence / 整体 object"),
    "ignore_active": ("忽略是否生效", "当前忽略规则是否仍在生效"),
    "source": ("数据来源", "产生该记录的数据来源"),
    "member_history_start_date": ("成员历史起点", "板块成员历史可用起始日"),
    "last_seen_at": ("最近观测时间", "最近一次从数据源观测到该对象的时间"),
    "net_ratio": ("净流入占比", "净流入相对成交规模的比例"),
}

_DIRECT_LATEST_COLUMNS: dict[str, str] = {
    "daily_bar": "trade_date",
    "daily_metrics": "trade_date",
    "index_bar": "trade_date",
    "trade_calendar": "trade_date",
    "data_update_log": "updated_at",
    "data_quality_issue": "detected_at",
    "data_source_provenance": "fetched_at",
    "board_dict": "last_seen_at",
    "board_member": "first_seen_date",
    "board_bar": "trade_date",
    "board_fund_flow": "snapshot_date",
    "stock_board_correlation": "as_of_date",
    "stock_board_correlation_state": "as_of_date",
    "stock_st_status_daily": "trade_date",
    "stock_st_status_history": "changed_at",
    "stock_st_status_refresh_state": "updated_at",
    "stock_st_status_date_revision": "trade_date",
    "limit_ladder_snapshot_state": "trade_date",
    "limit_ladder_snapshot": "trade_date",
    "limit_ladder_invalidation_outbox": "updated_at",
}

_FRESH_TABLES = {
    "daily_bar", "daily_metrics", "index_bar", "board_bar", "board_fund_flow",
    "stock_board_correlation", "stock_board_correlation_state", "stock_st_status_daily",
    "stock_st_status_refresh_state",
    "stock_st_status_date_revision",
    "limit_ladder_snapshot_state", "limit_ladder_snapshot", "limit_ladder_snapshot_stock",
    "limit_ladder_snapshot_concept", "limit_ladder_snapshot_aggregate",
    "limit_ladder_snapshot_window_metric",
}

_LADDER_CHILD_TABLES = {
    "limit_ladder_snapshot_stock",
    "limit_ladder_snapshot_concept",
    "limit_ladder_snapshot_aggregate",
    "limit_ladder_snapshot_window_metric",
}

_RUNTIME_TABLES = {"async_task", "task_log", "scheduled_job", "scheduled_trigger_event"}
_LAYOUT_PLATFORM_TABLES = {
    "app_config",
    "layout_preset",
    "layout_page_config",
    "layout_field_policy",
}


def _duck_table_sets() -> tuple[set[str], set[str]]:
    from backend.storage import ddl, pg_ddl

    duck_groups = (
        ddl.M1_TABLES, ddl.M2_TABLES, ddl.M3_TABLES, ddl.M4_TABLES, ddl.M5_TABLES,
        ddl.M6_TABLES, ddl.M28_TABLES, ddl.M_TRAINING_TABLES, ddl.M_BOARD_TABLES,
        ddl.M_STOCK_BOARD_CORRELATION_TABLES, ddl.M_LIMIT_LADDER_TABLES,
    )
    pg_groups = (pg_ddl._ASSET_TABLES, pg_ddl._OTHER_TABLES, pg_ddl._RBAC_TABLES)
    duck = set().union(*(set(group) for group in duck_groups))
    pg = set().union(*(set(group) for group in pg_groups))
    return duck, pg


def _clean(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (datetime, pd.Timestamp)):
        return str(value)
    return value


def _field_annotations(table: str) -> dict[str, dict[str, str]]:
    meta = TABLE_CATALOG.get(table, {})
    annotations = {item["name"]: item for item in meta.get("fields", [])}
    return annotations


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if hasattr(value, "tolist"):
        result = value.tolist()
        return result if isinstance(result, list) else [result]
    return [value]


def _duck_schema(client: DuckDBClient) -> tuple[list[dict], dict[str, list[dict]], dict[str, int]]:
    tables = client.query_df(
        "SELECT table_name, estimated_size FROM duckdb_tables() "
        "WHERE schema_name='main' AND internal=false ORDER BY table_name"
    ).to_dict("records")
    columns = client.query_df(
        "SELECT table_name,column_name,column_index,data_type,is_nullable,column_default "
        "FROM duckdb_columns() WHERE schema_name='main' AND internal=false "
        "ORDER BY table_name,column_index"
    ).to_dict("records")
    constraints = client.query_df(
        "SELECT table_name,constraint_type,constraint_column_names,referenced_table,"
        "referenced_column_names FROM duckdb_constraints() WHERE schema_name='main'"
    ).to_dict("records")
    primary: dict[str, set[str]] = {}
    references: dict[tuple[str, str], str] = {}
    for item in constraints:
        names = _as_list(item.get("constraint_column_names"))
        if item.get("constraint_type") == "PRIMARY KEY":
            primary.setdefault(str(item["table_name"]), set()).update(map(str, names))
        if item.get("constraint_type") == "FOREIGN KEY" and item.get("referenced_table"):
            target_names = _as_list(item.get("referenced_column_names"))
            for index, name in enumerate(names):
                target = target_names[index] if index < len(target_names) else "?"
                references[(str(item["table_name"]), str(name))] = (
                    f"{item['referenced_table']}.{target}"
                )
    fields: dict[str, list[dict]] = {}
    for item in columns:
        table = str(item["table_name"])
        name = str(item["column_name"])
        annotation = _field_annotations(table).get(name, {})
        common_cn, common_desc = _COMMON_FIELD_META.get(name, (name, ""))
        fields.setdefault(table, []).append({
            "name": name,
            "name_cn": annotation.get("name_cn", common_cn),
            "type": str(item["data_type"]),
            "nullable": bool(item["is_nullable"]),
            "default": _clean(item.get("column_default")),
            "primary_key": name in primary.get(table, set()),
            "references": references.get((table, name)),
            "desc": annotation.get("desc", common_desc),
        })
    estimates = {
        str(item["table_name"]): int(item["estimated_size"] or 0) for item in tables
    }
    return tables, fields, estimates


def _pg_schema(client: PostgresClient) -> tuple[list[dict], dict[str, list[dict]], dict[str, int]]:
    tables = client.query_df(
        "SELECT c.relname AS table_name, greatest(c.reltuples,0)::bigint AS estimated_rows, "
        "pg_total_relation_size(c.oid)::bigint AS storage_bytes "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind='r' ORDER BY c.relname"
    ).to_dict("records")
    columns = client.query_df(
        "SELECT table_name,column_name,ordinal_position,data_type,is_nullable,column_default "
        "FROM information_schema.columns WHERE table_schema='public' "
        "ORDER BY table_name,ordinal_position"
    ).to_dict("records")
    constraints = client.query_df(
        "SELECT tc.table_name,tc.constraint_type,kcu.column_name,ccu.table_name AS foreign_table,"
        "ccu.column_name AS foreign_column FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu ON tc.constraint_name=kcu.constraint_name "
        "AND tc.table_schema=kcu.table_schema LEFT JOIN information_schema.constraint_column_usage ccu "
        "ON tc.constraint_name=ccu.constraint_name AND tc.table_schema=ccu.table_schema "
        "WHERE tc.table_schema='public' AND tc.constraint_type IN ('PRIMARY KEY','FOREIGN KEY')"
    ).to_dict("records")
    primary: dict[str, set[str]] = {}
    references: dict[tuple[str, str], str] = {}
    for item in constraints:
        table = str(item["table_name"])
        name = str(item["column_name"])
        if item["constraint_type"] == "PRIMARY KEY":
            primary.setdefault(table, set()).add(name)
        elif item.get("foreign_table"):
            references[(table, name)] = f"{item['foreign_table']}.{item['foreign_column']}"
    fields: dict[str, list[dict]] = {}
    for item in columns:
        table = str(item["table_name"])
        name = str(item["column_name"])
        common_cn, common_desc = _COMMON_FIELD_META.get(name, (name, ""))
        fields.setdefault(table, []).append({
            "name": name,
            "name_cn": common_cn,
            "type": str(item["data_type"]).upper(),
            "nullable": str(item["is_nullable"]).upper() == "YES",
            "default": _clean(item.get("column_default")),
            "primary_key": name in primary.get(table, set()),
            "references": references.get((table, name)),
            "desc": common_desc,
        })
    estimates = {
        str(item["table_name"]): int(item["estimated_rows"] or 0) for item in tables
    }
    return tables, fields, estimates


def _duck_runtime_metrics(
    client: DuckDBClient, tables: set[str]
) -> tuple[dict, dict, str | None, dict[str, bool]]:
    latest: dict[str, str | None] = {table: None for table in tables}
    global_latest: str | None = None
    if "daily_bar" in tables:
        value = client.query_df("SELECT max(trade_date) AS value FROM daily_bar").iloc[0]["value"]
        global_latest = None if _clean(value) is None else str(pd.Timestamp(value).date())
    selections = [
        f"(SELECT max({column}) FROM {table}) AS {table}"
        for table, column in _DIRECT_LATEST_COLUMNS.items() if table in tables
    ]
    if selections:
        row = client.query_df("SELECT " + ",".join(selections)).iloc[0]
        for table in row.index:
            latest[table] = None if _clean(row[table]) is None else str(row[table])
    ladder_tables = (
        {"limit_ladder_snapshot", "limit_ladder_snapshot_state"} | _LADDER_CHILD_TABLES
    ) & tables
    if ladder_tables:
        # 一次往返取得主表/状态和四张子表各自的最新有效业务日；空子表不得借用
        # 主表日期伪装为已产出数据。
        selections = [
            (
                "SELECT 'limit_ladder_snapshot' AS table_name,max(s.trade_date) AS value "
                "FROM limit_ladder_snapshot s JOIN limit_ladder_snapshot_state st "
                "ON st.current_snapshot_id=s.snapshot_id WHERE st.status='valid'"
            )
        ]
        for child in sorted(_LADDER_CHILD_TABLES & tables):
            selections.append(
                f"SELECT '{child}' AS table_name,max(s.trade_date) AS value FROM {child} c "
                "JOIN limit_ladder_snapshot s ON s.snapshot_id=c.snapshot_id "
                "JOIN limit_ladder_snapshot_state st ON st.current_snapshot_id=s.snapshot_id "
                "WHERE st.status='valid'"
            )
        ladder_rows = client.query_df(" UNION ALL ".join(selections)).to_dict("records")
        for item in ladder_rows:
            value = item.get("value")
            latest[str(item["table_name"])] = None if _clean(value) is None else str(value)
        latest["limit_ladder_snapshot_state"] = latest.get("limit_ladder_snapshot")
    issues: dict[str, int] = {table: 0 for table in tables}
    if "data_quality_issue" in tables:
        issue_rows = client.query_df(
            "SELECT issue_type,count(*) AS n FROM data_quality_issue "
            "WHERE status IN ('open','fixing') GROUP BY issue_type"
        ).to_dict("records")
        issue_counts = {str(item["issue_type"]): int(item["n"]) for item in issue_rows}
        issues["data_quality_issue"] = sum(issue_counts.values())
        issues["index_bar"] = sum(issue_counts.get(key, 0) for key in _MARKET_INDEX_ISSUES)
        for table, issue_types in _BOARD_ISSUES_BY_TABLE.items():
            issues[table] = sum(issue_counts.get(key, 0) for key in issue_types)
    if "limit_ladder_invalidation_outbox" in tables:
        issues["limit_ladder_invalidation_outbox"] = int(client.query_df(
            "SELECT count(*) AS n FROM limit_ladder_invalidation_outbox WHERE status='pending'"
        ).iloc[0]["n"])
    fresh_overrides: dict[str, bool] = {}
    if "index_bar" in tables:
        from backend.services.market_benchmark import configured_benchmark_codes

        codes = configured_benchmark_codes()
        if codes and global_latest:
            placeholders = ",".join("?" for _ in codes)
            rows = client.query_df(
                f"SELECT index_code,max(trade_date) AS latest FROM index_bar "
                f"WHERE index_code IN ({placeholders}) GROUP BY index_code",
                codes,
            ).to_dict("records")
            latest_by_code = {
                str(item["index_code"]): str(pd.Timestamp(item["latest"]).date())
                for item in rows if _clean(item.get("latest")) is not None
            }
            fresh_overrides["index_bar"] = all(
                latest_by_code.get(code) is not None and latest_by_code[code] >= global_latest
                for code in codes
            )
        else:
            fresh_overrides["index_bar"] = False
    return latest, issues, global_latest, fresh_overrides


def _freshness(table: str, latest_time: str | None, global_latest: str | None) -> bool | None:
    if table not in _FRESH_TABLES:
        return None
    if latest_time is None or global_latest is None:
        return False
    latest_date = str(pd.Timestamp(latest_time).date())
    if table in {"board_bar", "board_fund_flow"}:
        return latest_date >= global_latest
    return latest_date == global_latest


def _source_routing(pg: PostgresClient | None) -> tuple[str, str]:
    if pg is None:
        # 低层 DuckDB 单测/离线调用不探测外库；API 总是显式传入 PG 客户端。
        return "postgres", "postgres"
    from backend.services.migrate_config_storage import config_storage_backend
    from backend.storage.task_runtime import task_runtime_backend

    return (
        task_runtime_backend(refresh=True, pg_client=pg),
        config_storage_backend(pg),
    )


def _lifecycle(database: str, table: str, overlap: set[str], task_backend: str,
               layout_backend: str) -> tuple[str, str]:
    if table not in overlap:
        return "active", database
    truth = "postgres"
    if table in _RUNTIME_TABLES:
        truth = task_backend
    elif table in _LAYOUT_PLATFORM_TABLES:
        truth = layout_backend
    return ("active", truth) if database == truth else ("legacy_readonly", truth)


def _validate_options(database: str, count_mode: str, table: str | None) -> None:
    if database not in {"all", "duckdb", "postgres"}:
        raise ValueError("database 仅支持 all、duckdb、postgres")
    if count_mode not in {"estimated", "exact"}:
        raise ValueError("count_mode 仅支持 estimated、exact")
    if table is not None and not _SAFE_IDENTIFIER_RE.fullmatch(table):
        raise ValueError("table 格式非法")
    if count_mode == "exact" and (database == "all" or not table):
        raise ValueError("精确统计必须指定明确 database 和 table")


def build_catalog(
    client: DuckDBClient | None = None,
    *,
    pg_client: PostgresClient | None = None,
    database: DatabaseFilter = "duckdb",
    include_legacy: bool = False,
    table: str | None = None,
    count_mode: CountMode = "estimated",
) -> list[dict]:
    """构建双库物理表目录；两库分别查询后在内存合并，禁止跨库 JOIN。"""
    _validate_options(database, count_mode, table)
    duck = client or get_client()
    pg = pg_client or (get_pg_client() if database in {"all", "postgres"} else None)
    _, pg_ddl_tables = _duck_table_sets()
    duck_ddl_tables, _ = _duck_table_sets()
    overlap = duck_ddl_tables & pg_ddl_tables
    task_backend, layout_backend = _source_routing(pg)
    rows: list[dict] = []

    if database in {"all", "duckdb"}:
        duck_tables, duck_fields, estimates = _duck_schema(duck)
        names = {str(item["table_name"]) for item in duck_tables}
        latest, issues, global_latest, fresh_overrides = _duck_runtime_metrics(duck, names)
        exact_count = None
        if count_mode == "exact" and table:
            if table not in names:
                raise ValueError(f"DuckDB 表不存在: {table}")
            try:
                exact_count = int(
                    duck.query_df(f'SELECT count(*) AS n FROM "{table}"').iloc[0]["n"]
                )
            except Exception as exc:
                raise CatalogExactCountError(
                    f"DuckDB 表 {table} 精确统计失败"
                ) from exc
        for item in duck_tables:
            name = str(item["table_name"])
            if table and name != table:
                continue
            lifecycle, truth = _lifecycle("duckdb", name, overlap, task_backend, layout_backend)
            if lifecycle == "legacy_readonly" and not include_legacy:
                continue
            base = TABLE_CATALOG.get(name) or _DUCK_EXTRA_META.get(name)
            if base is None and name in overlap:
                pg_meta = _PG_TABLE_META.get(name, {})
                base = {
                    **pg_meta,
                    "purpose": (
                        f"{pg_meta.get('name_cn', name)}的 DuckDB 迁移旧表；"
                        f"当前事实源为 {truth}，仅供受控回滚或历史核验。"
                    ),
                    "source": "历史迁移存量",
                }
            metadata_complete = base is not None
            meta = base or {}
            row_count = exact_count if count_mode == "exact" else estimates.get(name)
            rows.append({
                "key": f"duckdb:main:{name}",
                "database": "duckdb",
                "schema": "main",
                "table": name,
                "name_cn": meta.get("name_cn", name),
                "category": meta.get("category", _DUCK_CATEGORY_OVERRIDES.get(name, "未登记")),
                "purpose": meta.get("purpose", "物理表已发现，业务元数据待补充。"),
                "lifecycle": lifecycle if metadata_complete else "unregistered",
                "source_of_truth": truth,
                "metadata_complete": metadata_complete,
                "ownership_scope": meta.get("ownership_scope", "market_global"),
                "data_source": meta.get("source", "—"),
                "row_count": row_count,
                "row_count_mode": count_mode if row_count is not None else "unavailable",
                "rows": row_count,
                "storage_bytes": None,
                "latest_time": latest.get(name),
                "fresh": fresh_overrides.get(
                    name, _freshness(name, latest.get(name), global_latest)
                ),
                "open_issues": issues.get(name, 0),
                "fields": duck_fields.get(name, []),
                "relations": meta.get("relations", []),
                "measured_at": (
                    datetime.now(UTC).isoformat() if count_mode == "exact" else None
                ),
            })

    if database in {"all", "postgres"}:
        assert pg is not None
        pg_tables, pg_fields, estimates = _pg_schema(pg)
        names = {str(item["table_name"]) for item in pg_tables}
        exact_count = None
        if count_mode == "exact" and table:
            if table not in names:
                raise ValueError(f"PostgreSQL 表不存在: {table}")
            try:
                exact_count = int(
                    pg.query_df(f'SELECT count(*) AS n FROM "{table}"').iloc[0]["n"]
                )
            except Exception as exc:
                raise CatalogExactCountError(
                    f"PostgreSQL 表 {table} 精确统计失败"
                ) from exc
        sizes = {str(item["table_name"]): int(item["storage_bytes"] or 0) for item in pg_tables}
        for item in pg_tables:
            name = str(item["table_name"])
            if table and name != table:
                continue
            lifecycle, truth = _lifecycle("postgres", name, overlap, task_backend, layout_backend)
            if lifecycle == "legacy_readonly" and not include_legacy:
                continue
            meta = _PG_TABLE_META.get(name)
            metadata_complete = meta is not None
            meta = meta or {}
            row_count = exact_count if count_mode == "exact" else estimates.get(name)
            rows.append({
                "key": f"postgres:public:{name}",
                "database": "postgres",
                "schema": "public",
                "table": name,
                "name_cn": meta.get("name_cn", name),
                "category": meta.get("category", "未登记"),
                "purpose": meta.get("purpose", "物理表已发现，业务元数据待补充。"),
                "lifecycle": lifecycle if metadata_complete else "unregistered",
                "source_of_truth": truth,
                "metadata_complete": metadata_complete,
                "ownership_scope": meta.get("ownership_scope", "platform_global"),
                "data_source": meta.get("source", "业务服务"),
                "row_count": row_count,
                "row_count_mode": count_mode if row_count is not None else "unavailable",
                "rows": row_count,
                "storage_bytes": sizes.get(name),
                "latest_time": None,
                "fresh": None,
                "open_issues": 0,
                "fields": pg_fields.get(name, []),
                "relations": [],
                "measured_at": (
                    datetime.now(UTC).isoformat() if count_mode == "exact" else None
                ),
            })
    return sorted(rows, key=lambda item: (item["database"], item["category"], item["table"]))


def build_catalog_payload(
    *,
    database: DatabaseFilter = "all",
    include_legacy: bool = False,
    table: str | None = None,
    count_mode: CountMode = "estimated",
    client: DuckDBClient | None = None,
    pg_client: PostgresClient | None = None,
) -> dict:
    """返回 API 使用的目录和双库摘要；任一目标库失败时整体失败。"""
    duck = client or get_client()
    pg = pg_client or get_pg_client()
    all_tables = build_catalog(
        duck,
        pg_client=pg,
        database=database,
        include_legacy=True,
        count_mode="estimated",
    )
    if table and not any(item["table"] == table for item in all_tables):
        raise ValueError(f"{database} 表不存在: {table}")
    if count_mode == "exact":
        tables = build_catalog(
            duck,
            pg_client=pg,
            database=database,
            include_legacy=include_legacy,
            table=table,
            count_mode="exact",
        )
    else:
        tables = [
            item for item in all_tables
            if (not table or item["table"] == table)
            and (include_legacy or item["lifecycle"] != "legacy_readonly")
        ]
    summary: dict[str, Any] = {}
    for db in ("duckdb", "postgres"):
        selected = [item for item in all_tables if item["database"] == db]
        if not selected and database != "all" and database != db:
            continue
        summary[db] = {
            "connected": True,
            "schema": "main" if db == "duckdb" else "public",
            "database_name": None,
            "active_tables": sum(item["lifecycle"] == "active" for item in selected),
            "legacy_tables": sum(item["lifecycle"] == "legacy_readonly" for item in selected),
            "unregistered_tables": sum(item["lifecycle"] == "unregistered" for item in selected),
            "database_size_bytes": None,
        }
    if "duckdb" in summary:
        summary["duckdb"]["database_name"] = duck.db_path.name
        try:
            summary["duckdb"]["database_size_bytes"] = os.path.getsize(duck.db_path)
        except OSError:
            pass
    if "postgres" in summary and pg is not None:
        database = pg.query_df(
            "SELECT current_database() AS name,"
            "pg_database_size(current_database())::bigint AS size"
        ).iloc[0]
        summary["postgres"]["database_name"] = str(database["name"])
        summary["postgres"]["database_size_bytes"] = int(database["size"])
    return {"summary": summary, "tables": tables}
