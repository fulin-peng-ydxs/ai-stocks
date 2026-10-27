-- 用途：交易纪律默认账户、账户日结及不可变修订的增量结构归档。
-- 权威定义：backend/storage/trade_ledger_schema.py；启动 init_pg_db 幂等执行同一定义。
-- 执行时机：先部署后端结构，再启用新前端；本文件不清理任何历史记录。
-- 影响范围：新增三张 PG 私有表，全部主键、外键和幂等键包含租户与用户归属。
-- 业务重置：单独使用 trade-discipline-reset CLI；须目标指纹、本地环境、停服和 pg_dump 备份。
-- 回滚：未写新数据时可按修订、日结、账户逆序删表；写入后必须先备份及冻结写入，
-- 不得仅回退旧客户端继续写旧打卡表。历史数据恢复见同目录 plan.md 的实际执行记录。
BEGIN;

CREATE TABLE IF NOT EXISTS trade_discipline_account (
    tenant_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    id TEXT NOT NULL DEFAULT 'default',
    initialized_on DATE,
    opening_positions JSONB NOT NULL DEFAULT '[]'::jsonb,
    opening_cash NUMERIC(20,2),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(opening_positions) = 'array'),
    CHECK (opening_cash IS NULL OR opening_cash >= 0),
    PRIMARY KEY (tenant_id, owner_user_id, id)
);
COMMENT ON TABLE trade_discipline_account IS '私人交易账户及真实期初持仓；不从规则预算伪造现金';
COMMENT ON COLUMN trade_discipline_account.id IS '账户标识，初期使用 default 默认账户';
COMMENT ON COLUMN trade_discipline_account.initialized_on IS '账本起算交易日，空表示尚未初始化';
COMMENT ON COLUMN trade_discipline_account.opening_positions IS '期初持仓：股票、股数、总成本及规则分组；金额用十进制字符串';
COMMENT ON COLUMN trade_discipline_account.opening_cash IS '期初现金，空表示未采集，不等同于零';
COMMENT ON COLUMN trade_discipline_account.revision IS '账户乐观修订号，初始化及每次记账后递增';


CREATE TABLE IF NOT EXISTS trade_discipline_ledger_day (
    tenant_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    trade_date DATE NOT NULL,
    current_revision_no INTEGER NOT NULL CHECK (current_revision_no > 0),
    withdrawn BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, owner_user_id, account_id, trade_date),
    FOREIGN KEY (tenant_id, owner_user_id, account_id)
        REFERENCES trade_discipline_account (tenant_id, owner_user_id, id)
);
COMMENT ON TABLE trade_discipline_ledger_day IS '账户交易日日结身份与有效修订指针，撤回保留追溯';
COMMENT ON COLUMN trade_discipline_ledger_day.account_id IS '同一归属下的交易账户标识';
COMMENT ON COLUMN trade_discipline_ledger_day.current_revision_no IS '唯一参与持仓与统计的日结修订号';
COMMENT ON COLUMN trade_discipline_ledger_day.withdrawn IS '是否已撤回，撤回日不参与持仓与统计';


CREATE TABLE IF NOT EXISTS trade_discipline_ledger_revision (
    tenant_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    trade_date DATE NOT NULL,
    revision_no INTEGER NOT NULL CHECK (revision_no > 0),
    request_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    snapshot JSONB NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, owner_user_id, account_id, trade_date, revision_no),
    UNIQUE (tenant_id, owner_user_id, account_id, request_id),
    FOREIGN KEY (tenant_id, owner_user_id, account_id, trade_date)
        REFERENCES trade_discipline_ledger_day
            (tenant_id, owner_user_id, account_id, trade_date)
);
COMMENT ON TABLE trade_discipline_ledger_revision IS '不可变日结事实，含稳定成交身份、规则快照、评价依据和计算版本';
COMMENT ON COLUMN trade_discipline_ledger_revision.account_id IS '同一归属下的交易账户标识';
COMMENT ON COLUMN trade_discipline_ledger_revision.revision_no IS '当日日结修订号';
COMMENT ON COLUMN trade_discipline_ledger_revision.request_id IS '幂等请求标识，同账户不可跨日期复用';
COMMENT ON COLUMN trade_discipline_ledger_revision.payload_hash IS '请求内容摘要，防止同幂等键覆盖不同内容';
COMMENT ON COLUMN trade_discipline_ledger_revision.snapshot IS '有序成交及调整、持仓、资金、规则版本、遗漏及计算结果；confirmed_rule_ids为已确认规则，evaluations.confirmed区分待打卡，缺失沿用旧整日确认口径';

-- 通用归属与时间字段同样登记中文说明，独立执行 SQL 时不依赖目录推导。
COMMENT ON COLUMN trade_discipline_account.tenant_id IS '所属租户，由请求上下文确定';
COMMENT ON COLUMN trade_discipline_account.owner_user_id IS '所属用户，由请求上下文确定';
COMMENT ON COLUMN trade_discipline_account.created_at IS '创建时间';
COMMENT ON COLUMN trade_discipline_account.updated_at IS '最近更新时间';
COMMENT ON COLUMN trade_discipline_ledger_day.tenant_id IS '所属租户，由请求上下文确定';
COMMENT ON COLUMN trade_discipline_ledger_day.owner_user_id IS '所属用户，由请求上下文确定';
COMMENT ON COLUMN trade_discipline_ledger_day.created_at IS '创建时间';
COMMENT ON COLUMN trade_discipline_ledger_day.updated_at IS '最近更新时间';
COMMENT ON COLUMN trade_discipline_ledger_day.trade_date IS '日结所属真实交易日';
COMMENT ON COLUMN trade_discipline_ledger_revision.tenant_id IS '所属租户，由请求上下文确定';
COMMENT ON COLUMN trade_discipline_ledger_revision.owner_user_id IS '所属用户，由请求上下文确定';
COMMENT ON COLUMN trade_discipline_ledger_revision.created_at IS '创建时间';
COMMENT ON COLUMN trade_discipline_ledger_revision.trade_date IS '日结所属真实交易日';
COMMIT;
