"""DuckDB 建表 DDL（SDD §4 数据库设计）。

约定：
- 日期统一 DATE；金额单位元；价格存**不复权**原值 + adj_factor，复权价在指标层按需算。
- 所有写入幂等：表带 PRIMARY KEY，写入用 INSERT ... ON CONFLICT DO UPDATE。
- M1 仅建数据底座相关表；指标/方案/结果/回测表在 M2/M3/M5 各自里程碑追加。

入口：init_db(client) 幂等创建全部 M1 表。
"""

from __future__ import annotations

import pandas as pd

from backend.common.exceptions import StorageError
from backend.common.logging import get_logger
from backend.storage.duckdb_client import DuckDBClient, get_client

log = get_logger("storage.ddl")


# ── 基础数据表（SDD §4.1）──────────────────────────────────────

# 股票基础信息：ST/股本时变，此处存最新值；时变 ST/股本见 daily_bar/daily_metrics
DDL_STOCK_BASIC = """
CREATE TABLE IF NOT EXISTS stock_basic (
    code            VARCHAR PRIMARY KEY,   -- 含交易所后缀，如 600000.SH
    name            VARCHAR,               -- 当前名称
    exchange        VARCHAR,               -- SH/SZ
    board           VARCHAR,               -- 主板/创业板/科创板
    list_date       DATE,                  -- 上市日
    delist_date     DATE,                  -- 退市日（NULL=在市）
    total_share     BIGINT,                -- 最新总股本
    float_share     BIGINT,                -- 最新流通股本
    industry        VARCHAR,               -- 所属行业
    concept         VARCHAR,               -- 概念标签（JSON 字符串，可多值）
    price_limit_pct DOUBLE                 -- 涨跌幅限制 0.10/0.20
);
"""

# 日线行情（核心大表）：存不复权原值 + 复权因子
DDL_DAILY_BAR = """
CREATE TABLE IF NOT EXISTS daily_bar (
    code          VARCHAR,
    trade_date    DATE,
    open          DOUBLE,        -- 不复权原始价
    high          DOUBLE,
    low           DOUBLE,
    close         DOUBLE,
    pre_close     DOUBLE,        -- 前收盘（算涨跌停用）
    volume        BIGINT,        -- 成交量（股）
    amount        DOUBLE,        -- 成交额（元）
    adj_factor    DOUBLE,        -- 复权因子（源端反推：后复权收盘÷不复权收盘，含舍入噪声，留作审计/后复权）
    adj_factor_clean DOUBLE,     -- 去抖后干净因子（分段恒定，K线前复权/后复权用此列；为空回落 adj_factor）
    turnover_rate DOUBLE,        -- 换手率(%)
    is_st         BOOLEAN,       -- 当日是否 ST（尽力而为）
    is_suspended  BOOLEAN,       -- 当日是否停牌
    limit_status  TINYINT,       -- 0 正常 / 1 涨停 / -1 跌停
    is_one_word   BOOLEAN,       -- 是否一字板
    PRIMARY KEY (code, trade_date)
);
"""

# 每日衍生指标
DDL_DAILY_METRICS = """
CREATE TABLE IF NOT EXISTS daily_metrics (
    code       VARCHAR,
    trade_date DATE,
    float_mv   DOUBLE,    -- 流通市值 = close × float_share（自算）
    total_mv   DOUBLE,    -- 总市值
    PRIMARY KEY (code, trade_date)
);
"""

# 指数日线
DDL_INDEX_BAR = """
CREATE TABLE IF NOT EXISTS index_bar (
    index_code VARCHAR,   -- 000300/000905/000985 …
    trade_date DATE,
    open       DOUBLE,
    high       DOUBLE,
    low        DOUBLE,
    close      DOUBLE,
    volume     BIGINT,
    amount     DOUBLE,
    PRIMARY KEY (index_code, trade_date)
);
"""

# 交易日历
DDL_TRADE_CALENDAR = """
CREATE TABLE IF NOT EXISTS trade_calendar (
    trade_date DATE PRIMARY KEY,
    is_open    BOOLEAN          -- 是否交易日
);
"""

# ── 运维表（SDD §4.6）──────────────────────────────────────────

# 数据更新日志（每次采集留痕，支持断点续跑）
DDL_DATA_UPDATE_LOG = """
CREATE TABLE IF NOT EXISTS data_update_log (
    id          BIGINT,
    table_name  VARCHAR,
    source      VARCHAR,        -- akshare/baostock
    date_start  DATE,
    date_end    DATE,
    row_count   BIGINT,
    status      VARCHAR,        -- success/failed/partial
    detail      VARCHAR,
    updated_at  TIMESTAMP
);
"""

# 数据质量问题（M2.8 起含 severity/status/resolved_at，支持修复闭环 FR-DM-4）
# M2.9.2 起四层问题类型（DM-D20）：
#   L1 null_close/ohl_repaired（入库时记）· L2 mv_missing · L3 abnormal_change/adj_jump
#   · L4 data_gap（疑似漏采，trade_date 存区间起，detail 含[lo,hi]）/ stale（鲜活滞后）
DDL_DATA_QUALITY_ISSUE = """
CREATE TABLE IF NOT EXISTS data_quality_issue (
    id          BIGINT,
    code        VARCHAR,
    trade_date  DATE,
    issue_type  VARCHAR,        -- null_close/ohl_repaired/mv_missing/abnormal_change/adj_jump/data_gap/stale
    severity    VARCHAR,        -- high/mid/low（DM-D10）
    status      VARCHAR,        -- open/fixing/resolved/ignored（默认 open）
    detail      VARCHAR,
    detected_at TIMESTAMP,
    resolved_at TIMESTAMP,       -- 修复完成回写
    fix_task_id VARCHAR,         -- 进入 fixing 时绑定的异步任务 id；任务失败/中断/重启可据此复位
    ignore_scope VARCHAR,        -- occurrence=仅本次 / object=同对象同类型整体
    ignore_active BOOLEAN        -- 忽略规则是否仍生效；本次问题消失或人工恢复后为 false
);
"""

# 确认停牌日（M2.9.2 DM-D19）：经"反向确定"重采后源端确实无数据的开市日 = 真停牌。
# 缺口判定减去本表实现收敛（停牌一旦确认就不再当缺口反复上报）。
# 注意：停牌日 daily_bar 无行，故单独建表记忆，**绝不往 daily_bar 插占位行**（业务靠"有行=可交易"）。
DDL_STOCK_SUSPENSION = """
CREATE TABLE IF NOT EXISTS stock_suspension (
    code        VARCHAR,
    trade_date  DATE,
    confirmed_at TIMESTAMP
);
"""

# ── 指标定义表（M2.1b）──────────────────────────────────
# v2.0 决策 D1：删除 indicator 预计算值表，指标全部动态实时计算。
# 但保留一张**定义**表（非值表）：统一管理内置与自定义指标的"定义"（名称/类型/表达式/参数/启停），
# 供 配置管理「技术指标」页 与 评分/筛选/买卖 引用。内置 kind=builtin（映射到动态计算列）；
# 自定义 kind=expr（保存一段带 {参数} 占位的 DSL 表达式，用时渲染参数后逐股点时求值）。
DDL_INDICATOR_DEF = """
CREATE TABLE IF NOT EXISTS indicator_def (
    key         VARCHAR PRIMARY KEY,
    name_cn     VARCHAR,
    category    VARCHAR,
    dtype       VARCHAR,         -- bool | number
    direction   VARCHAR,         -- higher_better | lower_better | NULL
    kind        VARCHAR,         -- builtin | expr
    expression  VARCHAR,         -- 表达式模板（kind=expr），含 {param} 占位
    params      VARCHAR,         -- 参数 schema（JSON）
    categories  VARCHAR,         -- 多分类标签（JSON 数组，可自定义）
    enabled     BOOLEAN,
    is_builtin  BOOLEAN,         -- 内置（不可删，仅可启停）
    descr       VARCHAR,
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP
);
"""

# 自增序列（DuckDB 无 AUTO_INCREMENT，用 SEQUENCE）
DDL_SEQUENCES = [
    "CREATE SEQUENCE IF NOT EXISTS seq_update_log START 1;",
    "CREATE SEQUENCE IF NOT EXISTS seq_quality_issue START 1;",
    "CREATE SEQUENCE IF NOT EXISTS seq_task_log START 1;",
]

# M1 全部 DDL（顺序无依赖）
M1_TABLES: dict[str, str] = {
    "stock_basic": DDL_STOCK_BASIC,
    "daily_bar": DDL_DAILY_BAR,
    "daily_metrics": DDL_DAILY_METRICS,
    "index_bar": DDL_INDEX_BAR,
    "trade_calendar": DDL_TRADE_CALENDAR,
    "data_update_log": DDL_DATA_UPDATE_LOG,
    "data_quality_issue": DDL_DATA_QUALITY_ISSUE,
    "stock_suspension": DDL_STOCK_SUSPENSION,
}

# M2 指标表：v2.0 删除 indicator 值表（动态计算）；保留 indicator_def 指标定义表
M2_TABLES: dict[str, str] = {
    "indicator_def": DDL_INDICATOR_DEF,
}

# ── 筛选 / 评分 / 结果表（M3，SDD §4.3/4.4）──────────────────────
# JSON 字段统一以 VARCHAR 存 JSON 字符串（Python json.dumps/loads），不依赖 DuckDB JSON 扩展。

DDL_SCREEN_PROFILE = """
CREATE TABLE IF NOT EXISTS screen_profile (
    id          VARCHAR PRIMARY KEY,
    name        VARCHAR,            -- 如"趋势龙头"
    version     INTEGER,            -- 版本号（改方案 +1）
    expression  VARCHAR,            -- 条件 AST（JSON 字符串，含 col/expr 叶子）
    params      VARCHAR,            -- 参数覆盖（JSON）
    is_preset   BOOLEAN,            -- 是否系统内置
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP
);
"""

# 评分规则方案（v2.0 §7）：技术指标 + 权重(总和100%) + 每指标阈值打分方式(bool/band/linear)。
# 取代 v1.0 固定 6 维 score_model。
DDL_SCORE_PROFILE = """
CREATE TABLE IF NOT EXISTS score_profile (
    id               VARCHAR PRIMARY KEY,
    name             VARCHAR,
    version          INTEGER,
    items            VARCHAR,       -- [{indicator,params,weight,scoring}]（JSON）
    grade_thresholds VARCHAR,       -- 分档阈值 {watch,leader,core}（JSON）
    is_preset        BOOLEAN,
    created_at       TIMESTAMP,
    updated_at       TIMESTAMP
);
"""

DDL_SCORE_PROFILE_VERSION = """
CREATE TABLE IF NOT EXISTS score_profile_version (
    id               VARCHAR,
    version          INTEGER,
    name             VARCHAR,
    items            VARCHAR,
    grade_thresholds VARCHAR,
    saved_at         TIMESTAMP,
    PRIMARY KEY (id, version)
);
"""

DDL_SCREEN_RESULT = """
CREATE TABLE IF NOT EXISTS screen_result (
    run_date    DATE,              -- 筛选所用交易日
    profile_id  VARCHAR,
    code        VARCHAR,
    hit         BOOLEAN,
    matched     VARCHAR,           -- 命中的条件明细（JSON）
    snapshot    VARCHAR,           -- 当时各指标取值（JSON，可解释）
    PRIMARY KEY (run_date, profile_id, code)
);
"""

DDL_SCORE_RESULT = """
CREATE TABLE IF NOT EXISTS score_result (
    trade_date  DATE,
    model_id    VARCHAR,
    code        VARCHAR,
    total_score DOUBLE,            -- 0~100
    sub_scores  VARCHAR,           -- 分项分（JSON）
    rank        INTEGER,           -- 当日排名
    grade       VARCHAR,           -- 观察/龙头候选/主升浪核心
    buy_point   VARCHAR,           -- 第一/二/三买点/无（M6 填）
    risk_flags  VARCHAR,           -- 风险标签（JSON，M6 填）
    PRIMARY KEY (trade_date, model_id, code)
);
"""

# 买卖指标方案（v2.0 §6，M2.3）：买入条件 + 卖出条件（指标组合）+ 可选兜底，买卖成对存一条。
DDL_TRADE_PROFILE = """
CREATE TABLE IF NOT EXISTS trade_profile (
    id          VARCHAR PRIMARY KEY,
    name        VARCHAR,
    version     INTEGER,
    buy_tree    VARCHAR,           -- 买入条件树（JSON）
    sell_tree   VARCHAR,           -- 卖出条件树（JSON）
    backstop    VARCHAR,           -- 兜底 {take_profit,stop_loss,max_hold_days}（JSON，可空）
    is_preset   BOOLEAN,
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP
);
"""

DDL_TRADE_PROFILE_VERSION = """
CREATE TABLE IF NOT EXISTS trade_profile_version (
    id          VARCHAR,
    version     INTEGER,
    name        VARCHAR,
    buy_tree    VARCHAR,
    sell_tree   VARCHAR,
    backstop    VARCHAR,
    saved_at    TIMESTAMP,
    PRIMARY KEY (id, version)
);
"""

# 方案版本历史（T-M6-7）：每次方案实质变更归档一版，供回看/恢复对比
DDL_SCREEN_PROFILE_VERSION = """
CREATE TABLE IF NOT EXISTS screen_profile_version (
    id          VARCHAR,
    version     INTEGER,
    name        VARCHAR,
    expression  VARCHAR,            -- 该版本条件 AST（JSON 字符串）
    saved_at    TIMESTAMP,
    PRIMARY KEY (id, version)
);
"""

# 股票分组（个股查询·篮子，M2.4+）：用户手动圈定的一批股票 + 各股加入日期（=涨幅基准）
DDL_STOCK_GROUP = """
CREATE TABLE IF NOT EXISTS stock_group (
    id          VARCHAR PRIMARY KEY,
    name        VARCHAR,
    group_date  DATE,              -- 建组日期（默认今天，可改）
    description VARCHAR,
    color       VARCHAR,
    is_default  BOOLEAN,
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP
);
"""

DDL_STOCK_GROUP_MEMBER = """
CREATE TABLE IF NOT EXISTS stock_group_member (
    group_id    VARCHAR,
    code        VARCHAR,
    add_date    DATE,              -- 该股加入日期（=最近涨幅基准；建组时默认=建组日期）
    note        VARCHAR,
    PRIMARY KEY (group_id, code)
);
"""

M3_TABLES: dict[str, str] = {
    "screen_profile": DDL_SCREEN_PROFILE,
    "score_profile": DDL_SCORE_PROFILE,
    "score_profile_version": DDL_SCORE_PROFILE_VERSION,
    "screen_result": DDL_SCREEN_RESULT,
    "score_result": DDL_SCORE_RESULT,
    "screen_profile_version": DDL_SCREEN_PROFILE_VERSION,
    "trade_profile": DDL_TRADE_PROFILE,
    "trade_profile_version": DDL_TRADE_PROFILE_VERSION,
    "stock_group": DDL_STOCK_GROUP,
    "stock_group_member": DDL_STOCK_GROUP_MEMBER,
}

# ── 可配置布局系统（agent-works/configurable-layout-system M4）──────────────
# 布局配置独立于 app_config：预设、页面层、用户层分表存储，config 为 JSON 字符串。
DDL_LAYOUT_PRESET = """
CREATE TABLE IF NOT EXISTS layout_preset (
    key            VARCHAR PRIMARY KEY,
    name           VARCHAR,
    description    VARCHAR,
    config         VARCHAR,
    enabled        BOOLEAN,
    is_builtin     BOOLEAN,
    schema_version INTEGER,
    created_at     TIMESTAMP,
    updated_at     TIMESTAMP
);
"""

DDL_LAYOUT_PAGE_CONFIG = """
CREATE TABLE IF NOT EXISTS layout_page_config (
    page_key       VARCHAR PRIMARY KEY,
    preset_key     VARCHAR,
    config         VARCHAR,
    schema_version INTEGER,
    updated_at     TIMESTAMP
);
"""

DDL_LAYOUT_USER_CONFIG = """
CREATE TABLE IF NOT EXISTS layout_user_config (
    user_id        VARCHAR,
    page_key       VARCHAR,
    config         VARCHAR,
    schema_version INTEGER,
    updated_at     TIMESTAMP,
    PRIMARY KEY (user_id, page_key)
);
"""

# 字段开放策略（layout-config-productization P10）：管理员收紧/放开"某组件某字段可在哪几层覆盖"。
# 是元配置（policy），不参与运行时值合并、不构成第五层优先级；缺行回落代码声明的最大开放集。
# allowed_layers 存 JSON 数组（preset/page/user 的子集），且必须 ⊆ 代码最大集。
DDL_LAYOUT_FIELD_POLICY = """
CREATE TABLE IF NOT EXISTS layout_field_policy (
    component_kind    VARCHAR,
    field             VARCHAR,
    allowed_layers    VARCHAR,
    updated_at        TIMESTAMP,
    PRIMARY KEY (component_kind, field)
);
"""

M4_TABLES: dict[str, str] = {
    "layout_preset": DDL_LAYOUT_PRESET,
    "layout_page_config": DDL_LAYOUT_PAGE_CONFIG,
    "layout_user_config": DDL_LAYOUT_USER_CONFIG,
    "layout_field_policy": DDL_LAYOUT_FIELD_POLICY,
}

# ── 回测结果表（M5，SDD §4.5）──────────────────────────────────
# JSON 字段统一以 VARCHAR 存 JSON 字符串。

# 回测任务：一次 run = 一个方案/模型在一段区间的回测
DDL_BACKTEST_RUN = """
CREATE TABLE IF NOT EXISTS backtest_run (
    id          VARCHAR PRIMARY KEY,
    kind        VARCHAR,            -- strategy(完整策略) / score_check(评分验证)；旧值 signal 兼容
    profile_id  VARCHAR,            -- 选股=筛选方案（strategy）
    model_id    VARCHAR,            -- 旧评分模型名（默认 default，保留兼容）
    score_profile_id VARCHAR,       -- 评分规则方案（strategy 排序 / score_check 验证）
    trade_profile_id VARCHAR,       -- 买卖指标方案（strategy 的买/卖/兜底）
    score_profile_version INTEGER,  -- 运行时各方案版本（命名展示 + 去重签名用）
    profile_version       INTEGER,
    trade_profile_version INTEGER,
    signature   VARCHAR,            -- 全条件指纹（日期+三方案及版本+所有数值参数）；同签名记录唯一
    date_start  DATE,
    date_end    DATE,
    params      VARCHAR,            -- 区间/持有期/卖出规则/成本/TopN/基准/信号口径（JSON）
    status      VARCHAR,            -- running/done/failed
    detail      VARCHAR,            -- 失败原因 / 摘要
    created_at  TIMESTAMP,
    finished_at TIMESTAMP
);
"""

# 逐笔交易（策略回测产出；signal 模式可不写）
DDL_BACKTEST_TRADE = """
CREATE TABLE IF NOT EXISTS backtest_trade (
    run_id        VARCHAR,
    seq           INTEGER,          -- 同 run 内自增序（同股可多次买卖）
    code          VARCHAR,
    entry_date    DATE,
    entry_price   DOUBLE,           -- 买入价（前复权，含滑点）
    exit_date     DATE,
    exit_price    DOUBLE,           -- 卖出价（前复权，含滑点）
    exit_reason   VARCHAR,          -- 卖出信号/止盈/止损/到期/停牌/退市/区间末强平/跌破MAxx
    exit_detail   VARCHAR,          -- 卖树部分命中时的命中指标标签（JSON 列表）；全命中或非卖树为空
    shares        BIGINT,           -- 持股数（整手）
    return_pct    DOUBLE,           -- 含成本净收益率
    pnl           DOUBLE,           -- 含成本净盈亏（元）
    hold_days     INTEGER,          -- 持有交易日数
    grade         VARCHAR,          -- 买入时评分分档（分层分析用）
    entry_score   DOUBLE,           -- 买入当日综合分（解释"无评级"：分未达观察阈值仍因排名买入）
    entry_rank    INTEGER,          -- 买入当日全市场评分榜名次
    entry_pick_rank INTEGER,        -- 方案内排名（命中票按分排序优先级）
    entry_pool    INTEGER,          -- 当日候选池大小（方案命中数/全市场评分数）
    PRIMARY KEY (run_id, seq)
);
"""

# 资金曲线（逐日组合净值 + 回撤 + 基准）
DDL_BACKTEST_EQUITY = """
CREATE TABLE IF NOT EXISTS backtest_equity (
    run_id           VARCHAR,
    trade_date       DATE,
    equity           DOUBLE,        -- 组合总权益（现金+持仓市值）
    cash             DOUBLE,        -- 现金
    position_value   DOUBLE,        -- 持仓市值
    n_positions      INTEGER,       -- 持仓只数
    drawdown         DOUBLE,        -- 相对历史峰值回撤（≤0）
    benchmark_equity DOUBLE,        -- 基准归一净值（初始=初始资金）
    PRIMARY KEY (run_id, trade_date)
);
"""

# 绩效指标（一行一 run）+ 分档命中率 JSON
DDL_BACKTEST_METRICS = """
CREATE TABLE IF NOT EXISTS backtest_metrics (
    run_id          VARCHAR PRIMARY KEY,
    total_return    DOUBLE,         -- 累计收益率
    annual_return   DOUBLE,         -- 年化收益率
    max_drawdown    DOUBLE,         -- 最大回撤（≤0）
    max_dd_days     INTEGER,        -- 最大回撤持续交易日
    annual_vol      DOUBLE,         -- 年化波动
    sharpe          DOUBLE,
    calmar          DOUBLE,
    sortino         DOUBLE,
    win_rate        DOUBLE,         -- 胜率
    profit_factor   DOUBLE,         -- 盈亏比（总盈/总亏）
    avg_hold_days   DOUBLE,         -- 平均持有交易日
    n_trades        INTEGER,
    benchmark_return DOUBLE,        -- 同期基准累计收益
    excess_return   DOUBLE,         -- 相对基准超额（累计）
    hit_rate_by_grade VARCHAR,      -- 各分档 N日涨幅≥X% 命中率 + base rate + 超额（JSON，核心概率口径）
    extra           VARCHAR         -- 其他（JSON，便于扩展不改表）
);
"""

M5_TABLES: dict[str, str] = {
    "backtest_run": DDL_BACKTEST_RUN,
    "backtest_trade": DDL_BACKTEST_TRADE,
    "backtest_equity": DDL_BACKTEST_EQUITY,
    "backtest_metrics": DDL_BACKTEST_METRICS,
}

# ── M2.6 数据管理闭环 + 评分快照（SDD §10/§10.1）────────────────
# 异步任务：更新/补数/重算/体检，后台线程执行，前端轮询进度
DDL_ASYNC_TASK = """
CREATE TABLE IF NOT EXISTS async_task (
    id          VARCHAR PRIMARY KEY,
    task_type   VARCHAR,            -- update | backfill | recompute | verify
    params      VARCHAR,            -- 入参（JSON）
    status      VARCHAR,            -- pending | running | done | failed | interrupted
    progress    DOUBLE,             -- 0~1
    message     VARCHAR,            -- 当前进度文案 / 结果摘要 / 失败原因
    result      VARCHAR,            -- 结果（JSON，可空）
    trigger_source VARCHAR,         -- manual | scheduled | dependency | retry
    job_id      VARCHAR,            -- 对应 scheduled_job（独立手工任务为空）
    job_name    VARCHAR,
    chain_id    VARCHAR,            -- 本次调度运行链根任务 id
    parent_task_id VARCHAR,          -- 依赖/重试来源任务 id
    trigger_event_id VARCHAR,       -- 产生本任务的持久化触发事件
    retry_count INTEGER,            -- 自身重试序号，首次执行为 0
    execution_attempt INTEGER,      -- 同一任务续跑时递增，终态事件据此幂等
    cancel_requested_at TIMESTAMP,  -- 人工终止请求时间；不再依赖 message 文案推断取消态
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP
);
"""

# 评分快照明细：按 日期+方案+版本+code 物化（惰性，§10.1）
DDL_SCORE_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS score_snapshot (
    trade_date      DATE,
    profile_id      VARCHAR,
    profile_version INTEGER,
    code            VARCHAR,
    total_score     DOUBLE,
    grade           VARCHAR,
    rank            INTEGER,        -- 当日该方案全市场(排除ST)降序名次
    sub_scores      VARCHAR,        -- 分项达标分 {指标key: 分}（JSON），供榜单分项徽章
    PRIMARY KEY (trade_date, profile_id, profile_version, code)
);
"""

# 评分快照元数据：失效只动这张小表（每天每方案一行），不碰百万行明细
DDL_SCORE_SNAPSHOT_META = """
CREATE TABLE IF NOT EXISTS score_snapshot_meta (
    trade_date      DATE,
    profile_id      VARCHAR,
    profile_version INTEGER,
    computed_at     TIMESTAMP,
    stale           BOOLEAN,        -- true=已标记失效，下次读取时重算
    n_codes         INTEGER,
    PRIMARY KEY (trade_date, profile_id, profile_version)
);
"""

M6_TABLES: dict[str, str] = {
    "async_task": DDL_ASYNC_TASK,
    "score_snapshot": DDL_SCORE_SNAPSHOT,
    "score_snapshot_meta": DDL_SCORE_SNAPSHOT_META,
}

# ── M2.8 数据管理收口（见 docs/v2.0数据管理模块完善-…）────────────────
# 配置覆盖层（DM-D3）：Web 改的参数落此，settings.yaml 仅兜底；读取覆盖层优先。
DDL_APP_CONFIG = """
CREATE TABLE IF NOT EXISTS app_config (
    key         VARCHAR PRIMARY KEY,   -- 点分路径，如 datasource.update_concurrency
    value       VARCHAR,               -- JSON 标量/对象（保留类型）
    updated_at  TIMESTAMP
);
"""

# 任务实时日志（FR-DM-9）：逐条记录在拉哪只股/哪天、阶段、i/N。保留策略见 DM-D8。
DDL_TASK_LOG = """
CREATE TABLE IF NOT EXISTS task_log (
    id          BIGINT,
    task_id     VARCHAR,
    seq         INTEGER,               -- 同任务内自增（增量按 after_seq 拉取）
    ts          TIMESTAMP,
    level       VARCHAR,               -- info | warn | error
    message     VARCHAR
);
"""

# 数据来源标记/溯源（数据源兜底审计）：默认主源(akshare)不记录；只在用了非默认源(如 baostock 兜底)
# 时按 (code, 表, 区间, 来源) 追加一条，供后续排查/审计"这段数据从哪来、两源是否有差异"。
# 只追加不更新（保留每次取数事件），查某股某段来源：有记录=该源，无记录=默认主源。
DDL_DATA_SOURCE_PROVENANCE = """
CREATE TABLE IF NOT EXISTS data_source_provenance (
    code        VARCHAR,
    table_name  VARCHAR,               -- 'daily_bar' 等
    date_start  DATE,
    date_end    DATE,
    source      VARCHAR,               -- 非默认源名（如 baostock）
    rows        INTEGER,               -- 该次写入行数
    fetched_at  TIMESTAMP
);
"""

# 数据维度注册表（FR-DM-1 / DM-D4/D5）：已采集 + 规划中（股东数/筹码峰占位）。
DDL_DATA_DIMENSION_REGISTRY = """
CREATE TABLE IF NOT EXISTS data_dimension_registry (
    dimension   VARCHAR PRIMARY KEY,   -- 维度标识，如 quote/valuation/shareholders
    name_cn     VARCHAR,
    status      VARCHAR,               -- collected | planned | partial
    source      VARCHAR,               -- 数据源/获取方式
    tables      VARCHAR,               -- 关联表（JSON 数组）
    descr       VARCHAR
);
"""

# 定时任务定义（调度系统重构）：用户自定义的多条定时任务，每条 = 一个任务类型 + 频率 + 参数。
# 调度器启动/运行时据此注册 APScheduler job；触发即创建一条 async_task（带来源标记）。
DDL_SCHEDULED_JOB = """
CREATE TABLE IF NOT EXISTS scheduled_job (
    id               VARCHAR PRIMARY KEY,   -- job_xxx
    name             VARCHAR,               -- 用户起的任务名（任务中心展示「定时·{name}」）
    task_type        VARCHAR,               -- update | backfill | ingest_date | recompute | verify
    params           VARCHAR,               -- 入参（JSON，按任务类型）
    freq_type        VARCHAR,               -- daily | weekly | monthly | cron
    freq_config      VARCHAR,               -- 频率配置（JSON）：{time} / {weekdays,time} / {day,time} / {cron}
    trigger_mode     VARCHAR,               -- time | dependency
    dependency_job_id VARCHAR,              -- 依赖的上游 scheduled_job id
    dependency_condition VARCHAR,           -- success | failure | completion
    dependency_delay VARCHAR,               -- {value,unit}，unit=second|minute|hour
    retry_config     VARCHAR,                -- {enabled,condition,delay,max_retries}
    trading_day_only BOOLEAN,               -- 仅交易日执行（非交易日跳过）
    enabled          BOOLEAN,               -- 启停
    last_run_at      TIMESTAMP,             -- 最近一次触发时间（可空）
    last_task_id     VARCHAR,               -- 最近一次触发产生的 async_task id（可空）
    created_at       TIMESTAMP,
    updated_at       TIMESTAMP
);
"""

# 依赖/重试触发事件：先持久化再延迟分发，服务重启或 DuckDB 写槽位繁忙时不丢链路。
DDL_SCHEDULED_TRIGGER_EVENT = """
CREATE TABLE IF NOT EXISTS scheduled_trigger_event (
    id               VARCHAR PRIMARY KEY,
    chain_id         VARCHAR,
    source_task_id   VARCHAR,
    source_attempt   INTEGER,
    source_status    VARCHAR,
    target_job_id    VARCHAR,
    trigger_kind     VARCHAR,               -- dependency | retry
    trigger_condition VARCHAR,              -- success | failure | completion（生成时规则快照）
    retry_count      INTEGER,
    due_at           TIMESTAMP,
    dispatched_at    TIMESTAMP,             -- 实际创建下游 async_task 的时间
    status           VARCHAR,               -- waiting | dispatching | dispatched | cancelled | exhausted | failed
    task_id          VARCHAR,
    job_snapshot     VARCHAR,
    message          VARCHAR,
    created_at       TIMESTAMP,
    updated_at       TIMESTAMP
);
"""

M28_TABLES: dict[str, str] = {
    "app_config": DDL_APP_CONFIG,
    "task_log": DDL_TASK_LOG,
    "data_dimension_registry": DDL_DATA_DIMENSION_REGISTRY,
    "data_source_provenance": DDL_DATA_SOURCE_PROVENANCE,
    "scheduled_job": DDL_SCHEDULED_JOB,
    "scheduled_trigger_event": DDL_SCHEDULED_TRIGGER_EVENT,
}

# ── 盘感训练（agent-works/market-sense-training/）────────────────
# 手动交易训练：盲测 + 逐日揭示 + T+1 真实撮合。一局 = N 回合，每回合 = 一只随机股
# + 区间内随机起点 + 连续 window_days 个交易日窗口。回合内独立资金账户。
# 价格口径（防失真）：回合内统一以 start_date 的 adj_factor_clean 为基准（base_factor）做前复权，
# 整段窗口固定基准 → 显示与记账价位一致、且只用 <= start_date 的因子（不引未来）。
# 涨跌停判定用**原始价**（pre_close/open 按 half-up 到分），与 broker.can_buy/sell_at_open 口径一致。
DDL_TRAINING_SESSION = """
CREATE TABLE IF NOT EXISTS training_session (
    id              VARCHAR PRIMARY KEY,   -- train_YYYYMMDDHHMMSSffffff
    user_id         VARCHAR,               -- 预留多用户，本期空
    mode            VARCHAR,               -- single | multi
    range_start     DATE,                  -- 随机起点范围
    range_end       DATE,
    n_rounds        INTEGER,               -- 回合数
    window_days     INTEGER,               -- 每回合连续交易日 K
    initial_capital DOUBLE,                -- 每回合初始资金
    filters         VARCHAR,               -- 随机范围过滤快照（JSON）
    fee_enabled     BOOLEAN,               -- 是否计入佣金/印花/过户/滑点
    status          VARCHAR,               -- running | completed | aborted
    cur_round       INTEGER,               -- 当前活跃回合序号（0-based）
    total_return    DOUBLE,                -- 结算汇总：各回合收益率等权均值
    score           DOUBLE,                -- 综合评分 0~100
    grade           VARCHAR,               -- 评级 S/A/B/C/D
    win_rate        DOUBLE,                -- 整局胜率（按卖出笔）
    max_drawdown    DOUBLE,                -- 各回合最大回撤的最差值
    n_trades        INTEGER,               -- 总成交笔数
    review_note     VARCHAR,               -- 整局复盘笔记
    created_at      TIMESTAMP,
    completed_at    TIMESTAMP
);
"""

# 回合：账户状态随训练实时更新，结算后落收益/基准
DDL_TRAINING_ROUND = """
CREATE TABLE IF NOT EXISTS training_round (
    session_id      VARCHAR,
    seq             INTEGER,               -- 回合序号（0-based）
    code            VARCHAR,               -- 真实个股（running 态前端不返回）
    start_date      DATE,                  -- 真实起点（窗口第 0 天）
    end_date        DATE,                  -- 窗口末交易日（预计算）
    window_days     INTEGER,
    base_factor     DOUBLE,                -- start_date 的 adj_factor_clean（回合内固定复权基准）
    price_limit_pct DOUBLE,                -- 板块涨跌幅限制（0.10/0.20；ST 按交易日规则另算）
    cursor_date     DATE,                  -- 当前已揭示到的真实交易日
    cursor_idx      INTEGER,               -- 当前相对第几天（0-based）
    status          VARCHAR,               -- pending | running | done
    cash            DOUBLE,                -- 当前现金
    pos_shares      BIGINT,                -- 当前持仓股数
    pos_cost        DOUBLE,                -- 当前持仓成本基（元，含费）
    pos_avg_price   DOUBLE,                -- 持仓均价（复权显示价）
    pending         VARCHAR,               -- 待成交意图（JSON {side,hands,reason} 或空）
    realized_pnl    DOUBLE,                -- 已实现盈亏累计
    round_return    DOUBLE,                -- 回合收益率（结算后）
    benchmark_return DOUBLE,               -- 首日满仓持有基准收益率
    final_equity    DOUBLE,                -- 回合结束总权益
    PRIMARY KEY (session_id, seq)
);
"""

# 逐笔成交（T+1 开盘成交后落库）
DDL_TRAINING_TRADE = """
CREATE TABLE IF NOT EXISTS training_trade (
    session_id      VARCHAR,
    round_seq       INTEGER,
    seq             INTEGER,               -- 回合内笔序（0-based）
    side            VARCHAR,               -- buy | sell
    decide_date     DATE,                  -- 决策日（看到的最后一根 K）
    fill_date       DATE,                  -- T+1 成交日
    rel_day         INTEGER,               -- 成交相对第几天（盲测展示）
    price           DOUBLE,                -- 复权成交价（含滑点）
    hands           INTEGER,               -- 手数
    shares          BIGINT,
    amount          DOUBLE,                -- 成交额（price×shares）
    fee             DOUBLE,                -- 费用合计
    pnl             DOUBLE,                -- 卖出/清算已实现盈亏（元）
    return_pct      DOUBLE,                -- 该笔卖出收益率（相对本次卖出对应成本）
    reason          VARCHAR,               -- 每笔操作理由（选填）
    auto_close      BOOLEAN,               -- 是否到期强制清算
    PRIMARY KEY (session_id, round_seq, seq)
);
"""

M_TRAINING_TABLES: dict[str, str] = {
    "training_session": DDL_TRAINING_SESSION,
    "training_round": DDL_TRAINING_ROUND,
    "training_trade": DDL_TRAINING_TRADE,
}

# ── 板块概念数据（agent-works/concept-industry-board/，R1-R6）──────────────
# 同花顺板块四块数据（字典/成分/指数/资金流），字段契约按需求 §6.1。
DDL_BOARD_DICT = """
CREATE TABLE IF NOT EXISTS board_dict (
    board_code VARCHAR PRIMARY KEY,        -- 同花顺路径 code（概念 30xxxx / 行业 88xxxx），取数/跳转统一用它
    app_code   VARCHAR,                    -- 同花顺 App 内部代码（概念 clid 88xxxx；行业 clid=路径 code）
    name       VARCHAR NOT NULL,
    board_type VARCHAR NOT NULL,           -- concept | industry
    source     VARCHAR NOT NULL DEFAULT 'ths',  -- 来源系统（非能力标记）
    has_members  BOOLEAN DEFAULT FALSE,    -- 是否有成分股数据
    has_bar      BOOLEAN DEFAULT FALSE,    -- 是否有板块指数
    has_fund_flow BOOLEAN DEFAULT FALSE,   -- 是否有资金流
    member_count  BIGINT,                  -- 最近一次完整快照返回数；行情统计另用 board_member 历史累计关系
    member_history_start_date DATE,        -- 成分快照首次完整采集日（板块级）
    member_snapshot_at TIMESTAMP,          -- 最近一次完整成分快照成功落库时间（修复复检与概览口径）
    last_seen_at  DATE,                    -- 最近一次在任意源出现
    updated_at    TIMESTAMP
);
"""

# 成分股多对多（只进不出：每行一只成分股累积，不删除、不做 diff）
DDL_BOARD_MEMBER = """
CREATE TABLE IF NOT EXISTS board_member (
    board_code VARCHAR,
    code       VARCHAR,                    -- 6 位代码补交易所后缀对齐 stock_basic.code（如 600000.SH）
    first_seen_date DATE,                  -- 首次完整采集到该关系的业务日；NULL=兼容存量，视为历史已存在
    PRIMARY KEY (board_code, code)
);
"""

# 板块指数日线（原始连续指数，原值不套个股复权链）
DDL_BOARD_BAR = """
CREATE TABLE IF NOT EXISTS board_bar (
    board_code VARCHAR,
    trade_date DATE,
    open  DOUBLE,
    high  DOUBLE,
    low   DOUBLE,
    close DOUBLE,
    volume DOUBLE,
    amount DOUBLE,
    PRIMARY KEY (board_code, trade_date)
);
"""

# 板块资金流（概念+行业，多周期）
DDL_BOARD_FUND_FLOW = """
CREATE TABLE IF NOT EXISTS board_fund_flow (
    board_code    VARCHAR,
    snapshot_date DATE,
    period        VARCHAR,                 -- 即时 | 3日 | 5日 | 10日 | 20日
    inflow    DOUBLE,
    outflow   DOUBLE,
    net_inflow DOUBLE,
    net_ratio DOUBLE,                      -- 涨跌幅/阶段涨跌幅（%）
    leader_stock VARCHAR,                  -- 领涨股（资金流源自带）
    leader_pct   DOUBLE,                   -- 领涨股涨幅（%）
    PRIMARY KEY (board_code, snapshot_date, period)
);
"""

# 个股走势关联板块冠军每日快照：每只股票每类型每交易日一行，保留各交易日结果；不保存候选明细。
DDL_STOCK_BOARD_CORRELATION = """
CREATE TABLE IF NOT EXISTS stock_board_correlation (
    code               VARCHAR NOT NULL,
    board_type         VARCHAR NOT NULL CHECK (board_type IN ('industry', 'concept')),
    board_code         VARCHAR NOT NULL,
    score              DOUBLE NOT NULL CHECK (isfinite(score) AND score BETWEEN -1 AND 1),
    corr_20            DOUBLE NOT NULL CHECK (isfinite(corr_20) AND corr_20 BETWEEN -1 AND 1),
    corr_60            DOUBLE NOT NULL CHECK (isfinite(corr_60) AND corr_60 BETWEEN -1 AND 1),
    sample_20          INTEGER NOT NULL CHECK (sample_20 >= 15),
    sample_60          INTEGER NOT NULL CHECK (sample_60 >= 40),
    confidence         VARCHAR NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
    benchmark_code     VARCHAR NOT NULL,
    benchmark_fallback BOOLEAN NOT NULL DEFAULT FALSE,
    as_of_date         DATE NOT NULL,
    computed_at        TIMESTAMP NOT NULL,
    algorithm_version  VARCHAR NOT NULL,
    PRIMARY KEY (code, board_type, as_of_date)
);
"""

# 每股每交易日计算状态快照：即使行业和概念都无合法冠军，也能表达该日已成功处理及实际数据口径。
DDL_STOCK_BOARD_CORRELATION_STATE = """
CREATE TABLE IF NOT EXISTS stock_board_correlation_state (
    code                    VARCHAR NOT NULL,
    as_of_date              DATE NOT NULL,
    computed_at             TIMESTAMP NOT NULL,
    algorithm_version       VARCHAR NOT NULL,
    benchmark_code          VARCHAR NOT NULL,
    benchmark_fallback      BOOLEAN NOT NULL DEFAULT FALSE,
    has_industry_champion   BOOLEAN NOT NULL DEFAULT FALSE,
    has_concept_champion    BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (code, as_of_date)
);
"""

M_BOARD_TABLES: dict[str, str] = {
    "board_dict": DDL_BOARD_DICT,
    "board_member": DDL_BOARD_MEMBER,
    "board_bar": DDL_BOARD_BAR,
    "board_fund_flow": DDL_BOARD_FUND_FLOW,
}

M_STOCK_BOARD_CORRELATION_TABLES: dict[str, str] = {
    "stock_board_correlation": DDL_STOCK_BOARD_CORRELATION,
    "stock_board_correlation_state": DDL_STOCK_BOARD_CORRELATION_STATE,
}

# ── 连板天梯领域事实（agent-works/limit-up-ladder/，T2）──────────────

DDL_STOCK_ST_STATUS_DAILY = """
CREATE TABLE IF NOT EXISTS stock_st_status_daily (
    code        VARCHAR NOT NULL,
    trade_date  DATE NOT NULL,
    is_st       BOOLEAN NOT NULL,
    source      VARCHAR NOT NULL,
    source_ref  VARCHAR,
    quality     VARCHAR NOT NULL CHECK (quality IN ('accurate', 'approximate')),
    captured_at TIMESTAMP NOT NULL,
    updated_at  TIMESTAMP NOT NULL,
    PRIMARY KEY (code, trade_date)
);
"""

DDL_STOCK_ST_STATUS_HISTORY = """
CREATE TABLE IF NOT EXISTS stock_st_status_history (
    version_id     VARCHAR PRIMARY KEY,
    code           VARCHAR NOT NULL,
    trade_date     DATE NOT NULL,
    old_is_st      BOOLEAN,
    new_is_st      BOOLEAN NOT NULL,
    old_source     VARCHAR,
    new_source     VARCHAR NOT NULL,
    old_source_ref VARCHAR,
    new_source_ref VARCHAR,
    old_quality    VARCHAR CHECK (old_quality IS NULL OR old_quality IN ('accurate', 'approximate')),
    new_quality    VARCHAR NOT NULL CHECK (new_quality IN ('accurate', 'approximate')),
    change_reason  VARCHAR NOT NULL,
    changed_at     TIMESTAMP NOT NULL,
    task_id        VARCHAR
);
"""

DDL_LIMIT_LADDER_SNAPSHOT_STATE = """
CREATE TABLE IF NOT EXISTS limit_ladder_snapshot_state (
    trade_date           DATE PRIMARY KEY,
    status               VARCHAR NOT NULL CHECK (
        status IN ('calculating', 'valid', 'invalid', 'recalculating', 'failed')
    ),
    current_snapshot_id  VARCHAR,
    last_success_at      TIMESTAMP,
    task_id              VARCHAR,
    rule_version         VARCHAR NOT NULL,
    upstream_fingerprint VARCHAR,
    failure_summary      VARCHAR,
    invalid_reason       VARCHAR,
    updated_at           TIMESTAMP NOT NULL
);
"""

DDL_LIMIT_LADDER_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS limit_ladder_snapshot (
    snapshot_id   VARCHAR PRIMARY KEY,
    trade_date    DATE NOT NULL,
    rule_version  VARCHAR NOT NULL,
    computed_at   TIMESTAMP NOT NULL,
    stock_count   INTEGER NOT NULL CHECK (stock_count >= 0),
    has_approx_st BOOLEAN NOT NULL,
    coverage_json VARCHAR NOT NULL,
    window_metadata_json VARCHAR NOT NULL DEFAULT '{}',
    source_version VARCHAR NOT NULL
);
"""

DDL_LIMIT_LADDER_SNAPSHOT_STOCK = """
CREATE TABLE IF NOT EXISTS limit_ladder_snapshot_stock (
    snapshot_id      VARCHAR NOT NULL,
    code             VARCHAR NOT NULL,
    name             VARCHAR NOT NULL,
    board            VARCHAR NOT NULL,
    price_limit_pct  DOUBLE NOT NULL CHECK (price_limit_pct > 0),
    is_st            BOOLEAN NOT NULL,
    st_quality       VARCHAR NOT NULL CHECK (st_quality IN ('accurate', 'approximate')),
    st_source        VARCHAR NOT NULL,
    is_one_word      BOOLEAN NOT NULL,
    consecutive_days INTEGER NOT NULL CHECK (consecutive_days >= 1),
    amount           DOUBLE NOT NULL CHECK (isfinite(amount) AND amount >= 0),
    industry_name    VARCHAR NOT NULL,
    industry_board_code VARCHAR,
    source_version   VARCHAR NOT NULL,
    PRIMARY KEY (snapshot_id, code)
);
"""

DDL_LIMIT_LADDER_SNAPSHOT_CONCEPT = """
CREATE TABLE IF NOT EXISTS limit_ladder_snapshot_concept (
    snapshot_id   VARCHAR NOT NULL,
    code          VARCHAR NOT NULL,
    board_code    VARCHAR NOT NULL,
    board_name    VARCHAR NOT NULL,
    source_version VARCHAR NOT NULL,
    PRIMARY KEY (snapshot_id, code, board_code)
);
"""

DDL_LIMIT_LADDER_SNAPSHOT_AGGREGATE = """
CREATE TABLE IF NOT EXISTS limit_ladder_snapshot_aggregate (
    snapshot_id VARCHAR NOT NULL,
    group_type  VARCHAR NOT NULL CHECK (group_type IN ('industry', 'concept')),
    group_key   VARCHAR NOT NULL,
    group_name  VARCHAR NOT NULL,
    stock_count INTEGER NOT NULL CHECK (stock_count >= 0),
    PRIMARY KEY (snapshot_id, group_type, group_key)
);
"""

DDL_LIMIT_LADDER_SNAPSHOT_WINDOW_METRIC = """
CREATE TABLE IF NOT EXISTS limit_ladder_snapshot_window_metric (
    snapshot_id          VARCHAR NOT NULL,
    code                 VARCHAR NOT NULL,
    window_days          INTEGER NOT NULL CHECK (window_days IN (10,20,31,60)),
    window_limit_up_days INTEGER NOT NULL CHECK (window_limit_up_days >= 0),
    window_return_pct    DOUBLE,
    window_start_date    DATE NOT NULL,
    actual_trade_days    INTEGER NOT NULL CHECK (actual_trade_days > 0),
    source_version       VARCHAR NOT NULL,
    PRIMARY KEY (snapshot_id, code, window_days)
);
"""

DDL_LIMIT_LADDER_INVALIDATION_OUTBOX = """
CREATE TABLE IF NOT EXISTS limit_ladder_invalidation_outbox (
    event_id       VARCHAR PRIMARY KEY,
    affected_from  DATE,
    reason         VARCHAR NOT NULL,
    status         VARCHAR NOT NULL CHECK (status IN ('pending','completed')),
    attempt_count  INTEGER NOT NULL CHECK (attempt_count >= 0),
    last_error     VARCHAR,
    created_at     TIMESTAMP NOT NULL,
    updated_at     TIMESTAMP NOT NULL,
    completed_at   TIMESTAMP
);
"""

M_LIMIT_LADDER_TABLES: dict[str, str] = {
    "stock_st_status_daily": DDL_STOCK_ST_STATUS_DAILY,
    "stock_st_status_history": DDL_STOCK_ST_STATUS_HISTORY,
    "limit_ladder_snapshot_state": DDL_LIMIT_LADDER_SNAPSHOT_STATE,
    "limit_ladder_snapshot": DDL_LIMIT_LADDER_SNAPSHOT,
    "limit_ladder_snapshot_stock": DDL_LIMIT_LADDER_SNAPSHOT_STOCK,
    "limit_ladder_snapshot_concept": DDL_LIMIT_LADDER_SNAPSHOT_CONCEPT,
    "limit_ladder_snapshot_aggregate": DDL_LIMIT_LADDER_SNAPSHOT_AGGREGATE,
    "limit_ladder_snapshot_window_metric": DDL_LIMIT_LADDER_SNAPSHOT_WINDOW_METRIC,
    "limit_ladder_invalidation_outbox": DDL_LIMIT_LADDER_INVALIDATION_OUTBOX,
}

_LIMIT_LADDER_INDEXES: tuple[str, ...] = (
    (
        "CREATE INDEX IF NOT EXISTS idx_st_status_history_code_date "
        "ON stock_st_status_history (code, trade_date, changed_at)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_limit_ladder_snapshot_date "
        "ON limit_ladder_snapshot (trade_date, computed_at)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_limit_ladder_stock_snapshot "
        "ON limit_ladder_snapshot_stock (snapshot_id, consecutive_days)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_limit_ladder_invalidation_pending "
        "ON limit_ladder_invalidation_outbox (status, created_at)"
    ),
)

# 数据维度注册表 seed（DM-D4/D5）：已采集维度 + 规划中占位（股东数/筹码峰）。
# 幂等 ON CONFLICT DO NOTHING：已存在则保留（允许后续人工调整 status）。
_DIMENSION_SEED: list[tuple] = [
    ("quote",        "日线行情",   "collected", "akshare(主)/baostock(备)", '["daily_bar"]',
     "OHLC/成交量额/换手/复权因子/涨跌停标记，选股回测核心"),
    ("valuation",    "估值市值",   "collected", "akshare(东财)",            '["daily_metrics"]',
     "流通市值/总市值，股票池过滤与规模分层"),
    ("basic",        "股票基础",   "collected", "akshare/baostock",         '["stock_basic"]',
     "代码/名称/交易所/板块/上市退市日/行业/涨跌幅限制"),
    ("index",        "指数行情",   "collected", "akshare",                  '["index_bar"]',
     (
         "六类市场指数日线（中证 500/沪深 300/上证指数/科创 50/深证成指/创业板指），"
         "回测基准与相对强弱"
     )),
    ("calendar",     "交易日历",   "collected", "akshare/baostock",         '["trade_calendar"]',
     "开市日判定，缺口检测与点时安全基础"),
    ("shareholders", "股东数据",   "planned",   "待定（东财/巨潮）",          '[]',
     "股东户数/十大股东等，规划中，暂未采集"),
    ("chip_peak",    "筹码分布",   "planned",   "待定（需逐笔/分价成交）",     '[]',
     "筹码峰/成本分布，规划中，暂未采集"),
    ("board", "板块数据", "collected", "同花顺(ThsBoardSource)",
     '["board_dict","board_member","board_bar","board_fund_flow"]',
     "概念/行业板块字典、成分关系、指数与资金流，支撑板块行情页"),
]

# 轻量迁移：给已存在的旧表补列（CREATE TABLE IF NOT EXISTS 不会改既有表结构）
_MIGRATIONS: list[str] = [
    "DROP INDEX IF EXISTS idx_limit_ladder_snapshot_date",
    (
        "ALTER TABLE limit_ladder_snapshot ADD COLUMN IF NOT EXISTS "
        "window_metadata_json VARCHAR DEFAULT '{}'"
    ),
    (
        "UPDATE limit_ladder_snapshot SET window_metadata_json='{}' "
        "WHERE window_metadata_json IS NULL"
    ),
    "ALTER TABLE limit_ladder_snapshot ALTER COLUMN window_metadata_json SET NOT NULL",
    "ALTER TABLE backtest_trade ADD COLUMN IF NOT EXISTS entry_rank INTEGER",
    "ALTER TABLE backtest_trade ADD COLUMN IF NOT EXISTS entry_pick_rank INTEGER",
    "ALTER TABLE backtest_trade ADD COLUMN IF NOT EXISTS entry_pool INTEGER",
    "ALTER TABLE backtest_run ADD COLUMN IF NOT EXISTS score_profile_id VARCHAR",
    "ALTER TABLE backtest_run ADD COLUMN IF NOT EXISTS trade_profile_id VARCHAR",
    "ALTER TABLE backtest_run ADD COLUMN IF NOT EXISTS score_profile_version INTEGER",
    "ALTER TABLE backtest_run ADD COLUMN IF NOT EXISTS profile_version INTEGER",
    "ALTER TABLE backtest_run ADD COLUMN IF NOT EXISTS trade_profile_version INTEGER",
    "ALTER TABLE backtest_run ADD COLUMN IF NOT EXISTS signature VARCHAR",
    "ALTER TABLE backtest_trade ADD COLUMN IF NOT EXISTS exit_detail VARCHAR",
    "ALTER TABLE backtest_trade ADD COLUMN IF NOT EXISTS entry_score DOUBLE",
    "DROP TABLE IF EXISTS watchlist_history",  # M2.7 废除观察池
    "ALTER TABLE score_snapshot ADD COLUMN IF NOT EXISTS sub_scores VARCHAR",
    "DROP TABLE IF EXISTS indicator",    # v2.0 删除指标预计算值表（改动态计算），旧库残留一并清
    "DROP TABLE IF EXISTS score_model",  # v2.0 score_model → score_profile，旧库残留一并清
    # M2.8 数据管理收口：质检问题加状态/严重度/解决时间（FR-DM-4），旧行回填
    "ALTER TABLE data_quality_issue ADD COLUMN IF NOT EXISTS status VARCHAR",
    "ALTER TABLE data_quality_issue ADD COLUMN IF NOT EXISTS severity VARCHAR",
    "ALTER TABLE data_quality_issue ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP",
    # 修复中闭环：绑定异步任务 id，任务失败/中断/重启时据此把 fixing 复位为 open（不留孤儿）
    "ALTER TABLE data_quality_issue ADD COLUMN IF NOT EXISTS fix_task_id VARCHAR",
    "ALTER TABLE data_quality_issue ADD COLUMN IF NOT EXISTS ignore_scope VARCHAR",
    "ALTER TABLE data_quality_issue ADD COLUMN IF NOT EXISTS ignore_active BOOLEAN",
    # 历史 ignored 沿用升级前口径，避免上线后已确认正常的问题突然重新告警。
    (
        "UPDATE data_quality_issue SET ignore_scope=CASE "
        "WHEN issue_type IN ('null_close','ohl_repaired','abnormal_change','adj_jump',"
        "'board_index_gap_daily','board_index_invalid') THEN 'occurrence' ELSE 'object' END "
        "WHERE status='ignored' AND ignore_scope IS NULL"
    ),
    (
        "UPDATE data_quality_issue SET ignore_active=true "
        "WHERE status='ignored' AND ignore_active IS NULL"
    ),
    "UPDATE data_quality_issue SET status='open' WHERE status IS NULL",
    (
        "UPDATE data_quality_issue SET ignore_active=false "
        "WHERE status<>'ignored' AND ignore_active IS NULL"
    ),
    # 严重度映射（DM-D10）：adj_jump=high；ohl_repaired/mv_missing=low；其余(abnormal_change/data_gap/stale)=mid
    (
        "UPDATE data_quality_issue SET severity = CASE "
        "WHEN issue_type='adj_jump' THEN 'high' "
        "WHEN issue_type='ohl_repaired' THEN 'low' "
        "ELSE 'mid' END WHERE severity IS NULL"
    ),
    # qfq 根治：去抖后干净因子独立成列，K线前/后复权改用它（源 adj_factor 带舍入噪声）。
    # 旧库该列为空，下次入库收尾或手动 rebuild-price-factors 会回填；get_bars 期间 COALESCE 回落原始因子。
    "ALTER TABLE daily_bar ADD COLUMN IF NOT EXISTS adj_factor_clean DOUBLE",
    "ALTER TABLE stock_group ADD COLUMN IF NOT EXISTS color VARCHAR",
    "ALTER TABLE stock_group ADD COLUMN IF NOT EXISTS is_default BOOLEAN",
    "UPDATE stock_group SET color='#909399' WHERE color IS NULL",
    "UPDATE stock_group SET is_default=false WHERE is_default IS NULL",
    # 维度说明文案润色（去任务编号/开发口吻）——种子 ON CONFLICT DO NOTHING 不覆盖存量行，故迁移刷新
    "UPDATE data_dimension_registry SET descr='股东户数/十大股东等，规划中，暂未采集' WHERE dimension='shareholders'",
    "UPDATE data_dimension_registry SET descr='筹码峰/成本分布，规划中，暂未采集' WHERE dimension='chip_peak'",
    # 调度系统重构：async_task 加来源标记（任务中心区分 手动/定时·任务名），存量行回填为手动
    "ALTER TABLE async_task ADD COLUMN IF NOT EXISTS trigger_source VARCHAR",
    "ALTER TABLE async_task ADD COLUMN IF NOT EXISTS job_id VARCHAR",
    "ALTER TABLE async_task ADD COLUMN IF NOT EXISTS job_name VARCHAR",
    "UPDATE async_task SET trigger_source='manual' WHERE trigger_source IS NULL",
    "ALTER TABLE async_task ADD COLUMN IF NOT EXISTS chain_id VARCHAR",
    "ALTER TABLE async_task ADD COLUMN IF NOT EXISTS parent_task_id VARCHAR",
    "ALTER TABLE async_task ADD COLUMN IF NOT EXISTS trigger_event_id VARCHAR",
    "ALTER TABLE async_task ADD COLUMN IF NOT EXISTS retry_count INTEGER",
    "ALTER TABLE async_task ADD COLUMN IF NOT EXISTS execution_attempt INTEGER",
    "ALTER TABLE async_task ADD COLUMN IF NOT EXISTS cancel_requested_at TIMESTAMP",
    "UPDATE async_task SET chain_id=id WHERE chain_id IS NULL",
    "UPDATE async_task SET retry_count=0 WHERE retry_count IS NULL",
    "UPDATE async_task SET execution_attempt=1 WHERE execution_attempt IS NULL",
    # 依赖调度：存量任务均为时间触发，新增配置列只补缺失值，不覆盖用户配置。
    "ALTER TABLE scheduled_job ADD COLUMN IF NOT EXISTS trigger_mode VARCHAR",
    "ALTER TABLE scheduled_job ADD COLUMN IF NOT EXISTS dependency_job_id VARCHAR",
    "ALTER TABLE scheduled_job ADD COLUMN IF NOT EXISTS dependency_condition VARCHAR",
    "ALTER TABLE scheduled_job ADD COLUMN IF NOT EXISTS dependency_delay VARCHAR",
    "ALTER TABLE scheduled_job ADD COLUMN IF NOT EXISTS retry_config VARCHAR",
    "UPDATE scheduled_job SET trigger_mode='time' WHERE trigger_mode IS NULL",
    (
        "UPDATE scheduled_job SET dependency_delay='{\"value\":0,\"unit\":\"minute\"}' "
        "WHERE dependency_delay IS NULL"
    ),
    (
        "UPDATE scheduled_job SET retry_config='{\"enabled\":false,\"condition\":\"failure\","
        "\"delay\":{\"value\":5,\"unit\":\"minute\"},\"max_retries\":1}' "
        "WHERE retry_config IS NULL"
    ),
    "ALTER TABLE scheduled_trigger_event ADD COLUMN IF NOT EXISTS trigger_condition VARCHAR",
    "ALTER TABLE scheduled_trigger_event ADD COLUMN IF NOT EXISTS dispatched_at TIMESTAMP",
    # 废弃 daily 复合任务：旧库残留的每日任务记录改标为 update（语义上等价于其首步增量更新）
    "UPDATE async_task SET task_type='update' WHERE task_type='daily'",
    # 成分修复需证明问题检出后发生过新的完整快照，不能只看历史 member_count。
    "ALTER TABLE board_dict ADD COLUMN IF NOT EXISTS member_snapshot_at TIMESTAMP",
    # 存量成员保持 NULL，兼容既有历史计算；只有升级后新发现关系记录首次完整采集业务日。
    "ALTER TABLE board_member ADD COLUMN IF NOT EXISTS first_seen_date DATE",
]


def seed_dimension_registry(client: DuckDBClient | None = None) -> int:
    """幂等 seed 数据维度注册表（DM-D4/D5）；已存在维度不覆盖。返回新插入行数。"""
    client = client or get_client()
    before = client.query_df("SELECT count(*) AS n FROM data_dimension_registry").iloc[0]["n"]
    df = pd.DataFrame(_DIMENSION_SEED,
                      columns=["dimension", "name_cn", "status", "source", "tables", "descr"])
    with client.temp_view(df, "dimseed") as v:
        client.execute(
            f"INSERT INTO data_dimension_registry "
            f"(dimension, name_cn, status, source, tables, descr) "
            f"SELECT dimension, name_cn, status, source, tables, descr FROM {v} "
            f"ON CONFLICT (dimension) DO NOTHING")
    after = client.query_df("SELECT count(*) AS n FROM data_dimension_registry").iloc[0]["n"]
    return int(after) - int(before)


def _primary_key_columns(client: DuckDBClient, table: str) -> set[str]:
    """返回 DuckDB 表主键列集合，用于结构升级前置判断。"""
    rows = client.query_df(f"PRAGMA table_info('{table}')")
    if rows.empty:
        return set()
    return {str(row["name"]) for row in rows.to_dict("records") if bool(row.get("pk"))}


def _migrate_stock_board_correlation_snapshot_keys(client: DuckDBClient) -> None:
    """把旧的当前态主键幂等升级为按 as_of_date 保存的每日快照主键。"""
    expected = {
        "stock_board_correlation": {"code", "board_type", "as_of_date"},
        "stock_board_correlation_state": {"code", "as_of_date"},
    }
    actual = {table: _primary_key_columns(client, table) for table in expected}
    pending = [table for table, columns in expected.items() if actual[table] != columns]
    if not pending:
        return

    with client.transaction():
        if "stock_board_correlation" in pending:
            client.conn.execute("DROP TABLE IF EXISTS stock_board_correlation_pk_new")
            client.conn.execute(
                DDL_STOCK_BOARD_CORRELATION.replace(
                    "CREATE TABLE IF NOT EXISTS stock_board_correlation",
                    "CREATE TABLE stock_board_correlation_pk_new",
                    1,
                )
            )
            client.conn.execute(
                "INSERT INTO stock_board_correlation_pk_new "
                "SELECT code,board_type,board_code,score,corr_20,corr_60,sample_20,sample_60,"
                "confidence,benchmark_code,benchmark_fallback,as_of_date,computed_at,"
                "algorithm_version FROM stock_board_correlation"
            )
            client.conn.execute("DROP TABLE stock_board_correlation")
            client.conn.execute(
                "ALTER TABLE stock_board_correlation_pk_new RENAME TO stock_board_correlation"
            )
        if "stock_board_correlation_state" in pending:
            client.conn.execute("DROP TABLE IF EXISTS stock_board_correlation_state_pk_new")
            client.conn.execute(
                DDL_STOCK_BOARD_CORRELATION_STATE.replace(
                    "CREATE TABLE IF NOT EXISTS stock_board_correlation_state",
                    "CREATE TABLE stock_board_correlation_state_pk_new",
                    1,
                )
            )
            client.conn.execute(
                "INSERT INTO stock_board_correlation_state_pk_new "
                "SELECT code,as_of_date,computed_at,algorithm_version,benchmark_code,"
                "benchmark_fallback,has_industry_champion,has_concept_champion "
                "FROM stock_board_correlation_state"
            )
            client.conn.execute("DROP TABLE stock_board_correlation_state")
            client.conn.execute(
                "ALTER TABLE stock_board_correlation_state_pk_new "
                "RENAME TO stock_board_correlation_state"
            )
    log.info("个股走势关联板块主键已升级为每日快照结构: %s", ",".join(pending))


def init_db(client: DuckDBClient | None = None) -> list[str]:
    """幂等创建全部表与序列（M1 数据底座 + M2 指标），返回已创建的表名列表。"""
    client = client or get_client()
    # 只读连接（如 E2E 夹具、只读分析）不持有写锁、无法执行 DDL；库已由读写进程初始化，跳过。
    if client.read_only:
        return []
    for seq_sql in DDL_SEQUENCES:
        client.execute(seq_sql)
    created: list[str] = []
    all_tables = {**M1_TABLES, **M2_TABLES, **M3_TABLES, **M4_TABLES, **M5_TABLES, **M6_TABLES,
                  **M28_TABLES, **M_TRAINING_TABLES, **M_BOARD_TABLES,
                  **M_STOCK_BOARD_CORRELATION_TABLES, **M_LIMIT_LADDER_TABLES}
    for name, sql in all_tables.items():
        client.execute(sql)
        created.append(name)
        log.debug("表已就绪: %s", name)
    _migrate_stock_board_correlation_snapshot_keys(client)
    for mig in _MIGRATIONS:
        try:
            client.execute(mig)
        except Exception as e:  # noqa: BLE001
            log.warning("迁移跳过: %s (%s)", mig, e)
    for idx_sql in _LIMIT_LADDER_INDEXES:
        client.execute(idx_sql)
    snapshot_metadata_column = client.query_df(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_schema='main' AND table_name='limit_ladder_snapshot' "
        "AND column_name='window_metadata_json'"
    )
    if (
        len(snapshot_metadata_column) != 1
        or snapshot_metadata_column.iloc[0]["is_nullable"] != "NO"
    ):
        raise StorageError(
            "limit_ladder_snapshot.window_metadata_json 升级未完成：要求存在且 NOT NULL"
        )
    try:
        seed_dimension_registry(client)
    except Exception as e:  # noqa: BLE001
        log.warning("维度注册表 seed 跳过: %s", e)
    return created


def list_tables(client: DuckDBClient | None = None) -> list[str]:
    """列出当前库中所有表名。"""
    client = client or get_client()
    df = client.query_df(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_name"
    )
    return df["table_name"].tolist()
