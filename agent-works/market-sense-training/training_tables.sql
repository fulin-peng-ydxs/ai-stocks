-- 盘感训练表归档（与 backend/storage/ddl.py 内嵌建表语句一致）
-- 实际建表由后端启动时 init_db() 幂等执行（CREATE TABLE IF NOT EXISTS）；本文件仅供审阅/人工核验。
-- 回滚：DROP TABLE IF EXISTS training_trade; training_round; training_session;（无外部依赖，可安全回滚）

CREATE TABLE IF NOT EXISTS training_session (
    id              VARCHAR PRIMARY KEY,
    user_id         VARCHAR,
    mode            VARCHAR,               -- single | multi
    range_start     DATE,
    range_end       DATE,
    n_rounds        INTEGER,
    window_days     INTEGER,
    initial_capital DOUBLE,
    filters         VARCHAR,               -- JSON
    fee_enabled     BOOLEAN,
    status          VARCHAR,               -- running | completed | aborted
    cur_round       INTEGER,
    total_return    DOUBLE,
    score           DOUBLE,
    grade           VARCHAR,
    win_rate        DOUBLE,
    max_drawdown    DOUBLE,
    n_trades        INTEGER,
    review_note     VARCHAR,
    created_at      TIMESTAMP,
    completed_at    TIMESTAMP
);

CREATE TABLE IF NOT EXISTS training_round (
    session_id      VARCHAR,
    seq             INTEGER,
    code            VARCHAR,
    start_date      DATE,
    end_date        DATE,
    window_days     INTEGER,
    base_factor     DOUBLE,
    price_limit_pct DOUBLE,
    cursor_date     DATE,
    cursor_idx      INTEGER,
    status          VARCHAR,               -- pending | running | done
    cash            DOUBLE,
    pos_shares      BIGINT,
    pos_cost        DOUBLE,
    pos_avg_price   DOUBLE,
    pending         VARCHAR,               -- JSON {side,hands,reason} 或空
    realized_pnl    DOUBLE,
    round_return    DOUBLE,
    benchmark_return DOUBLE,
    final_equity    DOUBLE,
    PRIMARY KEY (session_id, seq)
);

CREATE TABLE IF NOT EXISTS training_trade (
    session_id      VARCHAR,
    round_seq       INTEGER,
    seq             INTEGER,
    side            VARCHAR,               -- buy | sell
    decide_date     DATE,
    fill_date       DATE,
    rel_day         INTEGER,
    price           DOUBLE,
    hands           INTEGER,
    shares          BIGINT,
    amount          DOUBLE,
    fee             DOUBLE,
    pnl             DOUBLE,
    return_pct      DOUBLE,
    reason          VARCHAR,
    auto_close      BOOLEAN,
    PRIMARY KEY (session_id, round_seq, seq)
);
