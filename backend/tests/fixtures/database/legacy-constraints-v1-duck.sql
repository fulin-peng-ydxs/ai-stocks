-- 已识别的旧结构差异；只在隔离门禁内运行，保留状态表行值。
-- 这些列曾通过无约束 ADD COLUMN 接入，升级需补齐 NOT NULL/CHECK。
ALTER TABLE scheduled_trigger_event ALTER COLUMN dispatch_order DROP NOT NULL;
ALTER TABLE score_profile ALTER COLUMN include_st DROP NOT NULL;
ALTER TABLE score_profile_version ALTER COLUMN include_st DROP NOT NULL;
CREATE TABLE legacy_correlation_state (
    code VARCHAR NOT NULL,
    as_of_date DATE NOT NULL,
    computed_at TIMESTAMP NOT NULL,
    algorithm_version VARCHAR NOT NULL,
    benchmark_code VARCHAR NOT NULL,
    benchmark_fallback BOOLEAN NOT NULL DEFAULT FALSE,
    has_industry_champion BOOLEAN NOT NULL DEFAULT FALSE,
    has_concept_champion BOOLEAN NOT NULL DEFAULT FALSE,
    industry_empty_reason VARCHAR,
    industry_max_sample_20 INTEGER,
    industry_max_sample_60 INTEGER,
    concept_empty_reason VARCHAR,
    concept_max_sample_20 INTEGER,
    concept_max_sample_60 INTEGER,
    PRIMARY KEY (code,as_of_date)
);
INSERT INTO legacy_correlation_state SELECT * FROM stock_board_correlation_state;
DROP TABLE stock_board_correlation_state;
ALTER TABLE legacy_correlation_state RENAME TO stock_board_correlation_state;
