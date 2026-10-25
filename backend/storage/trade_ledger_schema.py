"""私人交易账本 DDL。日结修订不可变，当前指针与记账结果同事务推进。"""

LEDGER_DDL = {
    "trade_discipline_account": """
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
""",
    "trade_discipline_ledger_day": """
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
""",
    "trade_discipline_ledger_revision": """
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
COMMENT ON COLUMN trade_discipline_ledger_revision.snapshot IS '有序成交及调整、期初期末持仓、资金、规则版本、遗漏事项、核验来源及计算结果';
""",
}

LEDGER_PK = {
    "trade_discipline_account": ["tenant_id", "owner_user_id", "id"],
    "trade_discipline_ledger_day": ["tenant_id", "owner_user_id", "account_id", "trade_date"],
    "trade_discipline_ledger_revision": [
        "tenant_id", "owner_user_id", "account_id", "trade_date", "revision_no",
    ],
}
