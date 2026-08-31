-- 迁移：stock_board_correlation / stock_board_correlation_state 主键加入 as_of_date（每日快照）
-- 用途：把「只存当前冠军 + 每股一行」的两张表重建为「按交易日快照」，保留现有行（as_of_date=旧值）。
-- 执行时机：必须停服后执行（DuckDB 单写者，后端持锁无法迁移）。仅对「旧结构（主键不含 as_of_date）」库执行一次；
--           新结构库的主键 CREATE IF NOT EXISTS 已是新定义，无需再迁。
-- 前置：迁移前旧表每股/每类最多一行（当前态）。迁移后主键含 as_of_date，可并存多交易日。
-- 回滚：执行前先备份 data/ai_stocks.duckdb；如需回退，从备份恢复并还原旧结构 DDL。

BEGIN;

CREATE TABLE stock_board_correlation_pk_new (
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
INSERT INTO stock_board_correlation_pk_new
    SELECT code, board_type, board_code, score, corr_20, corr_60, sample_20, sample_60,
           confidence, benchmark_code, benchmark_fallback, as_of_date, computed_at, algorithm_version
    FROM stock_board_correlation;
DROP TABLE stock_board_correlation;
ALTER TABLE stock_board_correlation_pk_new RENAME TO stock_board_correlation;

CREATE TABLE stock_board_correlation_state_pk_new (
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
INSERT INTO stock_board_correlation_state_pk_new
    SELECT code, as_of_date, computed_at, algorithm_version, benchmark_code,
           benchmark_fallback, has_industry_champion, has_concept_champion
    FROM stock_board_correlation_state;
DROP TABLE stock_board_correlation_state;
ALTER TABLE stock_board_correlation_state_pk_new RENAME TO stock_board_correlation_state;

COMMIT;
