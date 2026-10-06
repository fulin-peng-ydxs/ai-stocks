"""双库数据资产目录（数据概览，FR-DM-1 / DM-D11）。

DuckDB main 与 PostgreSQL public 的物理表和字段由系统目录自动发现；代码内只维护
稳定的业务注解、生命周期和事实源路由。未注解的物理表必须以 unregistered 暴露，
规划中且尚无物理表的维度继续由 data_dimension_registry 管理。
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Literal

import pandas as pd

from backend.storage.catalog_metadata import (
    FRESHNESS_NOT_APPLICABLE,
    QUALITY_NOT_APPLICABLE,
    FreshnessPolicy,
    QualityPolicy,
    TableAssetMeta,
    resolve_field_metadata,
)
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
    "stock_special_trading_day": {
        "name_cn": "特殊交易日事实",
        "category": "行情参考",
        "purpose": "保存公告确认的退市整理首日无涨跌幅限制事实；事件非每日连续，无鲜活度和质检问题统计，导入执行强校验。",
        "ownership_scope": "market_global",
        "source": "官方公告人工核验/异步维护",
        "relations": [
            "code → stock_basic",
            "trade_date → trade_calendar",
            "task_id → PostgreSQL async_task（服务层关联）"
        ],
        "fields": [
            {
                "name": "code",
                "name_cn": "股票代码",
                "desc": "与 stock_basic.code 关联",
                "type": "VARCHAR"
            },
            {
                "name": "trade_date",
                "name_cn": "生效交易日",
                "desc": "仅按本日匹配，不向前后日期传播",
                "type": "DATE"
            },
            {
                "name": "event_type",
                "name_cn": "特殊交易类型",
                "desc": "delisting_first_day 表示退市整理期首日不设涨跌幅限制",
                "type": "VARCHAR"
            },
            {
                "name": "announcement_date",
                "name_cn": "公告日期",
                "desc": "公告公开日期，不得晚于生效交易日",
                "type": "DATE"
            },
            {
                "name": "source_ref",
                "name_cn": "公告链接",
                "desc": "经人工核验的交易所或巨潮资讯原始公告 HTTPS 链接",
                "type": "VARCHAR"
            },
            {
                "name": "note",
                "name_cn": "核验说明",
                "desc": "公告编号、核验结论或撤销原因",
                "type": "VARCHAR"
            },
            {
                "name": "active",
                "name_cn": "是否生效",
                "desc": "撤销时置 false，保留来源",
                "type": "BOOLEAN"
            },
            {
                "name": "task_id",
                "name_cn": "维护任务",
                "desc": "服务层关联 PostgreSQL async_task",
                "type": "VARCHAR"
            },
            {
                "name": "updated_at",
                "name_cn": "更新时间",
                "desc": "事实最近修改时间",
                "type": "TIMESTAMP"
            }
        ],
        "date_col": None
    },
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
            {"name": "app_code", "type": "VARCHAR", "name_cn": "应用代码", "desc": "同花顺应用侧 clid"},
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
            {"name": "industry_empty_reason", "type": "VARCHAR", "name_cn": "行业空结果原因", "desc": "无行业冠军时的结构化原因码；历史未重算数据可为空"},
            {"name": "industry_max_sample_20", "type": "INTEGER", "name_cn": "行业20日最高样本", "desc": "行业候选在20日窗口内共同有效样本数的最高值"},
            {"name": "industry_max_sample_60", "type": "INTEGER", "name_cn": "行业60日最高样本", "desc": "行业候选在60日窗口内共同有效样本数的最高值"},
            {"name": "concept_empty_reason", "type": "VARCHAR", "name_cn": "概念空结果原因", "desc": "无概念冠军时的结构化原因码；历史未重算数据可为空"},
            {"name": "concept_max_sample_20", "type": "INTEGER", "name_cn": "概念20日最高样本", "desc": "概念候选在20日窗口内共同有效样本数的最高值"},
            {"name": "concept_max_sample_60", "type": "INTEGER", "name_cn": "概念60日最高样本", "desc": "概念候选在60日窗口内共同有效样本数的最高值"},
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

_DUCK_CORE_SOURCES = {
    "stock_basic": "AKShare / baostock",
    "daily_bar": "AKShare / baostock",
    "daily_metrics": "日线行情与股本衍生",
    "index_bar": "AKShare",
    "trade_calendar": "AKShare",
    "data_update_log": "数据采集任务",
    "data_quality_issue": "数据质检任务",
    "board_dict": "同花顺公开接口",
    "board_member": "同花顺公开接口",
    "board_bar": "同花顺公开接口",
    "board_fund_flow": "同花顺公开接口",
    "stock_board_correlation": "个股走势关联计算",
    "stock_board_correlation_state": "个股走势关联计算",
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
        "layout_preset": "视觉预设",
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
        "data_source_health": "数据源健康状态",
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

_PG_TABLE_PURPOSES: dict[str, str] = {
    "sys_tenant": "保存租户主体、状态和基础配置，是租户隔离的根实体。",
    "sys_user": "保存登录用户、所属租户、账号状态与权限版本。",
    "sys_role": "定义平台级角色、租户下放策略，并聚合菜单和功能点授权。",
    "sys_menu": "保存运行时菜单树、路由、可见性和排序配置。",
    "sys_resource": "登记受控 API 与按钮功能点，是权限校验的资源事实源。",
    "sys_user_role": "维护用户与角色的多对多授权关系。",
    "sys_role_menu": "维护角色可见菜单关系。",
    "sys_role_resource": "维护角色与功能点的授权关系。",
    "screen_profile": "保存筛选方案当前身份、可见范围和版本指针。",
    "screen_profile_version": "保存筛选方案不可变版本及筛选规则快照。",
    "score_profile": "保存评分方案当前身份、可见范围和版本指针。",
    "score_profile_version": "保存评分方案不可变版本及评分配置快照。",
    "trade_profile": "保存买卖方案当前身份、可见范围和版本指针。",
    "trade_profile_version": "保存买卖方案不可变版本及买卖规则快照。",
    "screen_result": "保存指定筛选方案与交易日产生的逐股筛选结果。",
    "score_result": "保存指定评分方案与交易日产生的逐股评分结果。",
    "stock_group": "保存用户股票分组及其可见范围。",
    "stock_group_member": "保存股票分组与股票代码的成员关系。",
    "board_watchlist": "保存用户关注的板块列表和排序。",
    "trade_discipline_rule": "保存交易纪律规则主体、发布状态和当前版本指针。",
    "trade_discipline_rule_name_claim": "占用交易纪律规则名称，避免并发创建重名规则。",
    "trade_discipline_rule_version": "保存交易纪律规则的不可变发布版本。",
    "trade_discipline_stock_rule": "保存规则版本中针对个股的约束。",
    "trade_discipline_action_subtype": "定义交易动作子类型及展示属性。",
    "trade_discipline_action_rule": "保存规则版本允许或限制的交易动作。",
    "trade_discipline_rule_draft": "保存尚未发布的交易纪律规则草稿。",
    "trade_discipline_draft_stock_rule": "保存草稿中的个股约束。",
    "trade_discipline_draft_action_rule": "保存草稿中的交易动作约束。",
    "trade_discipline_rule_activation": "记录规则启用、停用和生效日期历史。",
    "trade_discipline_checkin": "保存用户每日交易纪律打卡主体。",
    "trade_discipline_checkin_revision": "保存打卡内容的不可变修订记录。",
    "trade_discipline_reason": "保存用户维护的交易原因字典。",
    "trade_discipline_violation": "保存打卡中识别出的纪律违规明细。",
    "trade_discipline_operation": "记录交易纪律业务操作和状态变化。",
    "backtest_run": "保存回测任务参数、状态、归属和复用来源。",
    "backtest_trade": "保存回测运行产生的逐笔模拟成交。",
    "backtest_equity": "保存回测运行的逐日权益曲线。",
    "backtest_metrics": "保存回测运行汇总收益与风险指标。",
    "score_snapshot": "保存榜单读取使用的逐股评分结果快照。",
    "score_snapshot_meta": "保存评分快照版本、生成状态和失效信息。",
    "training_session": "保存盘感训练会话的规则、范围和汇总状态。",
    "training_round": "保存训练会话中的逐回合决策与结果。",
    "training_trade": "保存训练回合内的模拟交易记录。",
    "layout_preset": "保存平台视觉预设及版本化配置。",
    "layout_page_config": "保存页面级布局和组件配置。",
    "layout_field_policy": "定义组件配置字段允许写入的配置层级。",
    "app_config": "保存平台级运行配置及迁移标记。",
    "data_source_health": "保存各外部数据源最近一次联通测试状态、时间、失败原因和最近成功时间。",
    "dict_type": "定义平台数据字典类型。",
    "dict_item": "保存数据字典类型下的可维护选项。",
    "layout_user_config": "保存用户在单页面上的个性化布局覆盖。",
    "user_preference": "保存跨页面共享的用户偏好。",
    "storage_migration": "记录存储迁移 marker、状态和执行摘要。",
    "async_task": "保存异步任务状态、进度、检查点和取消请求。",
    "task_log": "保存异步任务的结构化运行日志。",
    "scheduled_job": "保存定时任务定义、频率和启停状态。",
    "scheduled_trigger_event": "记录调度触发、派发和执行关联。",
    "audit_log": "保存平台权限和关键业务操作审计记录。",
    "limit_ladder_task_ledger": "协调连板天梯任务的幂等执行、重试和终态。",
    "limit_ladder_audit_outbox": "可靠投递连板天梯状态变化的审计事件。",
}

_PG_TABLE_META: dict[str, dict[str, Any]] = {}
for _category, _scope, _names in _PG_META_GROUPS:
    for _table, _name_cn in _names.items():
        _PG_TABLE_META[_table] = {
            "name_cn": _name_cn,
            "category": _category,
            "ownership_scope": _scope,
            "purpose": _PG_TABLE_PURPOSES.get(_table, ""),
            "source": "业务服务",
        }

_COMMON_FIELD_META: dict[str, tuple[str, str]] = {
    "tenant_id": ("租户标识", "数据所属租户"),
    "owner_user_id": ("所有者用户标识", "用户资产真实所有者"),
    "created_at": ("创建时间", "记录创建时间"),
    "updated_at": ("更新时间", "记录最近更新时间"),
    "tenant_assignable": ("允许租户分配", "平台是否允许租户管理员为本租户用户分配该角色"),
    "fix_task_id": ("修复任务标识", "进入修复中状态时绑定的异步任务"),
    "ignore_scope": ("忽略范围", "仅本次 occurrence / 整体 object"),
    "ignore_active": ("忽略是否生效", "当前忽略规则是否仍在生效"),
    "source": ("数据来源", "产生该记录的数据来源"),
    "is_up": ("是否连通", "最近一次联通测试是否成功"),
    "last_test_at": ("最近测试时间", "最近一次执行联通测试的时间"),
    "last_success_at": ("最近成功时间", "最近一次联通测试成功的时间"),
    "failure_reason": ("失败原因", "最近一次联通测试失败时的错误摘要"),
    "member_history_start_date": ("成员历史起点", "板块成员历史可用起始日"),
    "last_seen_at": ("最近观测时间", "最近一次从数据源观测到该对象的时间"),
    "net_ratio": ("净流入占比", "净流入相对成交规模的比例"),
    "layer": ("业务层级", "对象所属的受控业务或配置层级"),
    "parent_key": ("父指标标识", "参数预设所属的通用指标标识"),
    "preset_params": ("预设参数", "参数预设绑定的固定参数 JSON"),
    "include_st": ("ST 参与评分", "评分方案是否将目标交易日的 ST 股票纳入评分与全市场排名"),
}

_DUCK_FRESHNESS_POLICIES: dict[str, FreshnessPolicy] = {
    "stock_special_trading_day": FRESHNESS_NOT_APPLICABLE,
    "stock_basic": FRESHNESS_NOT_APPLICABLE,
    "daily_bar": FreshnessPolicy("direct", "trade_date", "latest_trade_date", "equal"),
    "daily_metrics": FreshnessPolicy("direct", "trade_date", "latest_trade_date", "equal"),
    "index_bar": FreshnessPolicy("direct", "trade_date", "latest_trade_date", "equal"),
    "trade_calendar": FreshnessPolicy("not_applicable", "trade_date"),
    "data_update_log": FreshnessPolicy("not_applicable", "updated_at"),
    "data_quality_issue": FreshnessPolicy("not_applicable", "detected_at"),
    "board_dict": FreshnessPolicy("not_applicable", "last_seen_at"),
    "board_member": FreshnessPolicy("not_applicable", "first_seen_date"),
    "board_bar": FreshnessPolicy("direct", "trade_date", "latest_trade_date", "not_before"),
    "board_fund_flow": FreshnessPolicy(
        "direct", "snapshot_date", "latest_trade_date", "not_before"
    ),
    "stock_board_correlation": FreshnessPolicy(
        "direct", "as_of_date", "latest_trade_date", "equal"
    ),
    "stock_board_correlation_state": FreshnessPolicy(
        "direct", "as_of_date", "latest_trade_date", "equal"
    ),
    "data_dimension_registry": FRESHNESS_NOT_APPLICABLE,
    "data_source_provenance": FreshnessPolicy("not_applicable", "fetched_at"),
    "indicator_def": FRESHNESS_NOT_APPLICABLE,
    "stock_suspension": FreshnessPolicy("not_applicable", "confirmed_at"),
    "stock_st_status_daily": FreshnessPolicy(
        "direct", "trade_date", "latest_trade_date", "equal"
    ),
    "stock_st_status_history": FreshnessPolicy("not_applicable", "changed_at"),
    "stock_st_status_refresh_state": FreshnessPolicy("not_applicable", "updated_at"),
    "stock_st_status_date_revision": FreshnessPolicy(
        "direct", "trade_date", "latest_trade_date", "equal"
    ),
    "limit_ladder_snapshot_state": FreshnessPolicy(
        "snapshot", "trade_date", "latest_trade_date", "equal"
    ),
    "limit_ladder_snapshot": FreshnessPolicy(
        "snapshot", "trade_date", "latest_trade_date", "equal"
    ),
    "limit_ladder_snapshot_stock": FreshnessPolicy(
        "snapshot_child", baseline="latest_trade_date", comparison="equal"
    ),
    "limit_ladder_snapshot_concept": FreshnessPolicy(
        "snapshot_child", baseline="latest_trade_date", comparison="equal"
    ),
    "limit_ladder_snapshot_aggregate": FreshnessPolicy(
        "snapshot_child", baseline="latest_trade_date", comparison="equal"
    ),
    "limit_ladder_snapshot_window_metric": FreshnessPolicy(
        "snapshot_child", baseline="latest_trade_date", comparison="equal"
    ),
    "limit_ladder_invalidation_outbox": FreshnessPolicy("not_applicable", "updated_at"),
}

_DUCK_QUALITY_POLICIES: dict[str, QualityPolicy] = {
    "stock_special_trading_day": QUALITY_NOT_APPLICABLE,
    "stock_basic": QUALITY_NOT_APPLICABLE,
    "daily_bar": QualityPolicy("issue_types", (
        "null_close", "ohl_repaired", "abnormal_change", "price_volume_mismatch",
        "adj_jump", "data_gap", "stale",
    )),
    "daily_metrics": QualityPolicy("issue_types", ("mv_missing", "mv_gap", "mv_invalid")),
    "index_bar": QualityPolicy("issue_types", _MARKET_INDEX_ISSUES),
    "trade_calendar": QUALITY_NOT_APPLICABLE,
    "data_update_log": QUALITY_NOT_APPLICABLE,
    "data_quality_issue": QualityPolicy("all_issues"),
    "board_dict": QualityPolicy("issue_types", _BOARD_ISSUES_BY_TABLE["board_dict"]),
    "board_member": QualityPolicy("issue_types", _BOARD_ISSUES_BY_TABLE["board_member"]),
    "board_bar": QualityPolicy("issue_types", _BOARD_ISSUES_BY_TABLE["board_bar"]),
    "board_fund_flow": QualityPolicy("issue_types", _BOARD_ISSUES_BY_TABLE["board_fund_flow"]),
    "stock_board_correlation": QUALITY_NOT_APPLICABLE,
    "stock_board_correlation_state": QUALITY_NOT_APPLICABLE,
    "data_dimension_registry": QUALITY_NOT_APPLICABLE,
    "data_source_provenance": QUALITY_NOT_APPLICABLE,
    "indicator_def": QUALITY_NOT_APPLICABLE,
    "stock_suspension": QUALITY_NOT_APPLICABLE,
    "stock_st_status_daily": QualityPolicy(
        "issue_types",
        ("st_status_missing", "st_status_approximate", "st_status_mismatch"),
    ),
    "stock_st_status_history": QUALITY_NOT_APPLICABLE,
    "stock_st_status_refresh_state": QUALITY_NOT_APPLICABLE,
    "stock_st_status_date_revision": QUALITY_NOT_APPLICABLE,
    "limit_ladder_snapshot_state": QUALITY_NOT_APPLICABLE,
    "limit_ladder_snapshot": QUALITY_NOT_APPLICABLE,
    "limit_ladder_snapshot_stock": QUALITY_NOT_APPLICABLE,
    "limit_ladder_snapshot_concept": QUALITY_NOT_APPLICABLE,
    "limit_ladder_snapshot_aggregate": QUALITY_NOT_APPLICABLE,
    "limit_ladder_snapshot_window_metric": QUALITY_NOT_APPLICABLE,
    "limit_ladder_invalidation_outbox": QualityPolicy(
        "pending_outbox", status_column="status", pending_value="pending"
    ),
}

_LADDER_CHILD_TABLES = {
    "limit_ladder_snapshot_stock",
    "limit_ladder_snapshot_concept",
    "limit_ladder_snapshot_aggregate",
    "limit_ladder_snapshot_window_metric",
}

_DUCK_PLATFORM_TABLES = {"data_update_log", "data_quality_issue"}


def _table_name_cn(database: str, table: str) -> str:
    if database == "postgres":
        return str(_PG_TABLE_META.get(table, {}).get("name_cn", table))
    raw = (
        TABLE_CATALOG.get(table)
        or _DUCK_EXTRA_META.get(table)
        or _PG_TABLE_META.get(table)
        or {}
    )
    return str(raw.get("name_cn", table))


def _table_asset_meta(
    database: Literal["duckdb", "postgres"],
    table: str,
    *,
    legacy_truth: str | None = None,
) -> tuple[TableAssetMeta | None, list[str]]:
    """构造表级强类型元数据，并返回缺失契约项。"""
    issues: list[str] = []
    if database == "postgres":
        raw = _PG_TABLE_META.get(table)
        freshness = FRESHNESS_NOT_APPLICABLE
        quality = QUALITY_NOT_APPLICABLE
    else:
        raw = TABLE_CATALOG.get(table) or _DUCK_EXTRA_META.get(table)
        freshness = _DUCK_FRESHNESS_POLICIES.get(table)
        quality = _DUCK_QUALITY_POLICIES.get(table)
        if raw is None and legacy_truth:
            pg_meta = _PG_TABLE_META.get(table)
            if pg_meta:
                raw = {
                    **pg_meta,
                    "purpose": (
                        f"{pg_meta['name_cn']}的 DuckDB 迁移旧表；当前事实源为 "
                        f"{legacy_truth}，仅供受控回滚或历史核验。"
                    ),
                    "source": "历史迁移存量",
                }
                freshness = FRESHNESS_NOT_APPLICABLE
                quality = QUALITY_NOT_APPLICABLE
    if raw is None:
        return None, ["缺少表级业务元数据"]
    if freshness is None:
        issues.append("未声明鲜活度策略")
    if quality is None:
        issues.append("未声明质量策略")
    required = {
        "name_cn": raw.get("name_cn"),
        "category": raw.get("category") or _DUCK_CATEGORY_OVERRIDES.get(table),
        "purpose": raw.get("purpose"),
        "ownership_scope": raw.get("ownership_scope") or (
            "platform_global" if table in _DUCK_PLATFORM_TABLES else "market_global"
        ),
        "data_source": raw.get("source") or _DUCK_CORE_SOURCES.get(table),
    }
    for key, value in required.items():
        if not isinstance(value, str) or not value.strip():
            issues.append(f"缺少 {key}")
    if issues:
        return None, issues
    assert freshness is not None and quality is not None
    return TableAssetMeta(
        database=database,
        table=table,
        name_cn=str(required["name_cn"]),
        category=str(required["category"]),
        purpose=str(required["purpose"]),
        ownership_scope=str(required["ownership_scope"]),
        data_source=str(required["data_source"]),
        relations=tuple(str(item) for item in raw.get("relations", [])),
        freshness=freshness,
        quality=quality,
    ), []

_RUNTIME_TABLES = {
    "data_source_health", "async_task", "task_log", "scheduled_job", "scheduled_trigger_event",
}
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
        "SELECT table_name,column_name,column_index,data_type,is_nullable,column_default,comment "
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
        common_cn, common_desc = _COMMON_FIELD_META.get(name, (None, None))
        reference = references.get((table, name))
        resolved = resolve_field_metadata(
            name=name,
            table_name_cn=_table_name_cn("duckdb", table),
            explicit_name=annotation.get("name_cn"),
            explicit_desc=annotation.get("desc"),
            database_comment=_clean(item.get("comment")),
            primary_key=name in primary.get(table, set()),
            reference=reference,
            glossary_name=common_cn,
            glossary_desc=common_desc,
        )
        fields.setdefault(table, []).append({
            "name": name,
            "type": str(item["data_type"]),
            "nullable": bool(item["is_nullable"]),
            "default": _clean(item.get("column_default")),
            "primary_key": name in primary.get(table, set()),
            "references": reference,
            **resolved,
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
        "SELECT cols.table_name,cols.column_name,cols.ordinal_position,cols.data_type,"
        "cols.is_nullable,cols.column_default,descr.description AS column_comment "
        "FROM information_schema.columns cols "
        "JOIN pg_namespace ns ON ns.nspname=cols.table_schema "
        "JOIN pg_class rel ON rel.relnamespace=ns.oid AND rel.relname=cols.table_name "
        "LEFT JOIN pg_description descr ON descr.objoid=rel.oid "
        "AND descr.objsubid=cols.ordinal_position "
        "WHERE cols.table_schema='public' ORDER BY cols.table_name,cols.ordinal_position"
    ).to_dict("records")
    constraints = client.query_df(
        "SELECT rel.relname AS table_name,con.contype,attr.attname AS column_name,"
        "foreign_rel.relname AS foreign_table,foreign_attr.attname AS foreign_column "
        "FROM pg_constraint con JOIN pg_class rel ON rel.oid=con.conrelid "
        "JOIN pg_namespace ns ON ns.oid=rel.relnamespace "
        "JOIN LATERAL unnest(con.conkey) WITH ORDINALITY local_key(attnum,ord) ON true "
        "JOIN pg_attribute attr ON attr.attrelid=rel.oid AND attr.attnum=local_key.attnum "
        "LEFT JOIN pg_class foreign_rel ON foreign_rel.oid=con.confrelid "
        "LEFT JOIN LATERAL unnest(con.confkey) WITH ORDINALITY foreign_key(attnum,ord) "
        "ON foreign_key.ord=local_key.ord "
        "LEFT JOIN pg_attribute foreign_attr ON foreign_attr.attrelid=foreign_rel.oid "
        "AND foreign_attr.attnum=foreign_key.attnum "
        "WHERE ns.nspname='public' AND con.contype IN ('p','f')"
    ).to_dict("records")
    primary: dict[str, set[str]] = {}
    references: dict[tuple[str, str], str] = {}
    for item in constraints:
        table = str(item["table_name"])
        name = str(item["column_name"])
        if item["contype"] == "p":
            primary.setdefault(table, set()).add(name)
        elif item.get("foreign_table"):
            references[(table, name)] = f"{item['foreign_table']}.{item['foreign_column']}"
    fields: dict[str, list[dict]] = {}
    for item in columns:
        table = str(item["table_name"])
        name = str(item["column_name"])
        common_cn, common_desc = _COMMON_FIELD_META.get(name, (None, None))
        reference = references.get((table, name))
        resolved = resolve_field_metadata(
            name=name,
            table_name_cn=_table_name_cn("postgres", table),
            explicit_name=None,
            explicit_desc=None,
            database_comment=_clean(item.get("column_comment")),
            primary_key=name in primary.get(table, set()),
            reference=reference,
            glossary_name=common_cn,
            glossary_desc=common_desc,
        )
        fields.setdefault(table, []).append({
            "name": name,
            "type": str(item["data_type"]).upper(),
            "nullable": str(item["is_nullable"]).upper() == "YES",
            "default": _clean(item.get("column_default")),
            "primary_key": name in primary.get(table, set()),
            "references": reference,
            **resolved,
        })
    estimates = {
        str(item["table_name"]): int(item["estimated_rows"] or 0) for item in tables
    }
    return tables, fields, estimates


def _duck_runtime_metrics(
    client: DuckDBClient, tables: set[str]
) -> tuple[dict, dict[str, int | None], str | None, dict[str, bool]]:
    latest: dict[str, str | None] = {table: None for table in tables}
    global_latest: str | None = None
    if "daily_bar" in tables:
        value = client.query_df("SELECT max(trade_date) AS value FROM daily_bar").iloc[0]["value"]
        global_latest = None if _clean(value) is None else str(pd.Timestamp(value).date())
    selections = [
        f'(SELECT max("{policy.column}") FROM "{table}") AS "{table}"'
        for table, policy in _DUCK_FRESHNESS_POLICIES.items()
        if table in tables and policy.column
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
    issues: dict[str, int | None] = {table: None for table in tables}
    if "data_quality_issue" in tables:
        issue_rows = client.query_df(
            "SELECT issue_type,count(*) AS n FROM data_quality_issue "
            "WHERE status IN ('open','fixing') GROUP BY issue_type"
        ).to_dict("records")
        issue_counts = {str(item["issue_type"]): int(item["n"]) for item in issue_rows}
        for table, policy in _DUCK_QUALITY_POLICIES.items():
            if table not in tables:
                continue
            if policy.mode == "all_issues":
                issues[table] = sum(issue_counts.values())
            elif policy.mode == "issue_types":
                issues[table] = sum(issue_counts.get(key, 0) for key in policy.issue_types)
    for table, policy in _DUCK_QUALITY_POLICIES.items():
        if table not in tables or policy.mode != "pending_outbox":
            continue
        assert policy.status_column and policy.pending_value
        issues[table] = int(client.query_df(
            f'SELECT coalesce(sum(CASE WHEN "{policy.status_column}"=? '
            f'THEN 1 ELSE 0 END),0) AS n FROM "{table}"',
            [policy.pending_value],
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
    policy = _DUCK_FRESHNESS_POLICIES.get(table)
    if policy is None or policy.mode == "not_applicable":
        return None
    if latest_time is None or global_latest is None:
        return False
    latest_date = str(pd.Timestamp(latest_time).date())
    if policy.comparison == "not_before":
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


def _relations(meta: TableAssetMeta | None, fields: list[dict]) -> list[str]:
    result = list(meta.relations if meta else ())
    result.extend(
        f"{field['name']} → {field['references']}"
        for field in fields
        if field.get("references")
    )
    return list(dict.fromkeys(result))


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
            meta, metadata_issues = _table_asset_meta(
                "duckdb",
                name,
                legacy_truth=truth if name in overlap else None,
            )
            fields = duck_fields.get(name, [])
            incomplete_fields = [
                field["name"] for field in fields if not field.get("metadata_complete")
            ]
            if incomplete_fields:
                metadata_issues.append(
                    f"字段元数据待补充: {', '.join(incomplete_fields)}"
                )
            metadata_complete = meta is not None and not metadata_issues
            row_count = exact_count if count_mode == "exact" else estimates.get(name)
            rows.append({
                "key": f"duckdb:main:{name}",
                "database": "duckdb",
                "schema": "main",
                "table": name,
                "name_cn": meta.name_cn if meta else name,
                "category": meta.category if meta else "未登记",
                "purpose": meta.purpose if meta else "物理表已发现，业务元数据待补充。",
                "lifecycle": lifecycle if meta is not None else "unregistered",
                "source_of_truth": truth,
                "metadata_complete": metadata_complete,
                "metadata_issues": metadata_issues,
                "ownership_scope": meta.ownership_scope if meta else "market_global",
                "data_source": meta.data_source if meta else "—",
                "freshness_policy": asdict(meta.freshness) if meta else None,
                "quality_policy": asdict(meta.quality) if meta else None,
                "row_count": row_count,
                "row_count_mode": count_mode if row_count is not None else "unavailable",
                "rows": row_count,
                "storage_bytes": None,
                "latest_time": latest.get(name),
                "fresh": fresh_overrides.get(
                    name, _freshness(name, latest.get(name), global_latest)
                ),
                "open_issues": issues.get(name),
                "fields": fields,
                "relations": _relations(meta, fields),
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
            meta, metadata_issues = _table_asset_meta("postgres", name)
            fields = pg_fields.get(name, [])
            incomplete_fields = [
                field["name"] for field in fields if not field.get("metadata_complete")
            ]
            if incomplete_fields:
                metadata_issues.append(
                    f"字段元数据待补充: {', '.join(incomplete_fields)}"
                )
            metadata_complete = meta is not None and not metadata_issues
            row_count = exact_count if count_mode == "exact" else estimates.get(name)
            rows.append({
                "key": f"postgres:public:{name}",
                "database": "postgres",
                "schema": "public",
                "table": name,
                "name_cn": meta.name_cn if meta else name,
                "category": meta.category if meta else "未登记",
                "purpose": meta.purpose if meta else "物理表已发现，业务元数据待补充。",
                "lifecycle": lifecycle if meta is not None else "unregistered",
                "source_of_truth": truth,
                "metadata_complete": metadata_complete,
                "metadata_issues": metadata_issues,
                "ownership_scope": meta.ownership_scope if meta else "platform_global",
                "data_source": meta.data_source if meta else "业务服务",
                "freshness_policy": asdict(meta.freshness) if meta else None,
                "quality_policy": asdict(meta.quality) if meta else None,
                "row_count": row_count,
                "row_count_mode": count_mode if row_count is not None else "unavailable",
                "rows": row_count,
                "storage_bytes": sizes.get(name),
                "latest_time": None,
                "fresh": None,
                "open_issues": None,
                "fields": fields,
                "relations": _relations(meta, fields),
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


def catalog_contract_report(tables: list[dict]) -> dict[str, Any]:
    """校验全量目录与 DDL、表级策略及字段说明契约。"""
    violations: list[str] = []
    keys = [str(item["key"]) for item in tables]
    if len(keys) != len(set(keys)):
        violations.append("发现重复的 database:schema:table 目录键")

    expected_duck, expected_pg = _duck_table_sets()
    discovered = {
        "duckdb": {str(item["table"]) for item in tables if item["database"] == "duckdb"},
        "postgres": {
            str(item["table"]) for item in tables if item["database"] == "postgres"
        },
    }
    for database, expected in (("duckdb", expected_duck), ("postgres", expected_pg)):
        missing = sorted(expected - discovered[database])
        extra = sorted(discovered[database] - expected)
        if missing:
            violations.append(f"{database} DDL 表未被物理发现: {', '.join(missing)}")
        if extra:
            violations.append(f"{database} 存在未纳入 DDL 的物理表: {', '.join(extra)}")

    field_total = 0
    field_complete = 0
    for item in tables:
        identity = f"{item['database']}.{item['schema']}.{item['table']}"
        field_names = {str(field["name"]) for field in item.get("fields", [])}
        if not item.get("metadata_complete"):
            detail = "；".join(item.get("metadata_issues") or ["原因未登记"])
            violations.append(f"{identity} 业务元数据不完整: {detail}")
        freshness = item.get("freshness_policy")
        if freshness is None:
            violations.append(f"{identity} 未显式声明鲜活度策略")
        else:
            if freshness.get("column") and freshness["column"] not in field_names:
                violations.append(
                    f"{identity} 鲜活度字段不存在: {freshness['column']}"
                )
            if freshness.get("mode") in {"direct", "snapshot", "snapshot_child"} and (
                not freshness.get("baseline") or not freshness.get("comparison")
            ):
                violations.append(f"{identity} 鲜活度比较基准未完整声明")
            if freshness.get("mode") in {"direct", "snapshot"} and not freshness.get("column"):
                violations.append(f"{identity} 鲜活度业务时间字段未声明")
        quality = item.get("quality_policy")
        if quality is None:
            violations.append(f"{identity} 未显式声明质量策略")
        elif quality.get("mode") == "issue_types" and not quality.get("issue_types"):
            violations.append(f"{identity} 质量问题类型集合为空")
        elif quality.get("mode") == "pending_outbox":
            status_column = quality.get("status_column")
            if not status_column or status_column not in field_names or not quality.get("pending_value"):
                violations.append(f"{identity} outbox 待处理统计字段未完整声明")
        for field in item.get("fields", []):
            field_total += 1
            if field.get("metadata_complete"):
                field_complete += 1
            else:
                violations.append(f"{identity}.{field['name']} 缺少中文名或说明")
    return {
        "ok": not violations,
        "violations": violations,
        "table_count": len(tables),
        "field_count": field_total,
        "field_metadata_complete": field_complete,
    }
