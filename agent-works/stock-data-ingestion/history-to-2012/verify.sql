-- 用途：复核本次扩展至 2012 年的行情数量、字段配套、日期边界和未解决问题。
-- 范围：DuckDB 内 2011-10-30～2026-10-30 的冻结补采窗口；基线为 2026-11-01。
-- 前置：按 plan.md §3.2 通过 start.sh 安全停后端，再以 read_only=True 打开实际配置库。
-- 全文仅 SELECT，不创建表、不写数据，不涉及 PG 或跨库 JOIN；可重复执行，无需回滚。
-- 数字为交付快照，后续来源修订可能改变数量；不以行数相同代替来源准确性证明。

-- V-SQL-01：逐年行情；code_count 是物理存储代码数，含连续图表代码，不是去重股票池。
SELECT 'V-SQL-01' AS check_id, year(trade_date) AS year,
       count(*) AS bar_count, count(DISTINCT code) AS code_count,
       min(trade_date) AS first_date, max(trade_date) AS last_date
FROM daily_bar
WHERE trade_date BETWEEN DATE '2011-10-30' AND DATE '2026-10-30'
GROUP BY year(trade_date) ORDER BY year;

-- V-SQL-02：逐日 ST 唯一事实及派生因子；完整验收要求异常均为 0。
-- R1 定向修复并完成因子收尾后，实际四项均为 0；不能用源因子兜底代替清洗完成。
SELECT 'V-SQL-02' AS check_id, count(*) AS bar_count,
       count(*) FILTER (WHERE s.code IS NULL OR s.quality IS DISTINCT FROM 'accurate')
           AS missing_or_nonaccurate_st,
       count(*) FILTER (WHERE b.is_st IS DISTINCT FROM s.is_st) AS st_projection_mismatch,
       count(*) FILTER (WHERE b.adj_factor_clean IS NULL) AS missing_clean_factor,
       count(*) FILTER (WHERE coalesce(b.adj_factor_clean,b.adj_factor) IS NULL
                         OR coalesce(b.adj_factor_clean,b.adj_factor)<=0
                         OR NOT isfinite(coalesce(b.adj_factor_clean,b.adj_factor)))
           AS invalid_effective_factor
FROM daily_bar b LEFT JOIN stock_st_status_daily s USING(code,trade_date)
WHERE b.trade_date BETWEEN DATE '2011-10-30' AND DATE '2026-10-30';

-- V-SQL-03：逐年总/流通股本、市值及同日未复权收盘公式；异常计数预期均为 0。
-- 公式容差为此核验采用的 1 元绝对误差，不替代项目完整股本来源/业务质量契约。
SELECT 'V-SQL-03' AS check_id, year(b.trade_date) AS year,
       count(*) FILTER (WHERE s.total_share IS NULL) AS missing_total_share,
       count(*) FILTER (WHERE s.float_share IS NULL) AS missing_float_share,
       count(*) FILTER (WHERE m.total_mv IS NULL) AS missing_total_mv,
       count(*) FILTER (WHERE m.float_mv IS NULL) AS missing_float_mv,
       count(*) FILTER (WHERE abs(m.total_mv-s.total_share*b.close)>1) AS total_formula_mismatch,
       count(*) FILTER (WHERE abs(m.float_mv-s.float_share*b.close)>1) AS float_formula_mismatch
FROM daily_bar b LEFT JOIN stock_share_capital_daily s USING(code,trade_date)
LEFT JOIN daily_metrics m USING(code,trade_date)
WHERE b.trade_date BETWEEN DATE '2011-10-30' AND DATE '2026-10-30'
GROUP BY year(b.trade_date) ORDER BY year;

-- V-SQL-04：上市/摘牌/开市边界及停牌重叠；摘牌日是排他上界，异常计数预期均为 0。
SELECT 'V-SQL-04' AS check_id,
       count(*) FILTER (WHERE b.trade_date<s.list_date OR b.trade_date>=s.delist_date)
           AS outside_lifetime,
       count(*) FILTER (WHERE NOT coalesce(c.is_open,false)) AS outside_open_calendar,
       count(*) FILTER (WHERE p.code IS NOT NULL) AS quote_on_confirmed_suspension
FROM daily_bar b JOIN stock_basic s USING(code)
LEFT JOIN trade_calendar c USING(trade_date)
LEFT JOIN stock_suspension p ON p.code=b.code AND p.trade_date=b.trade_date
WHERE b.trade_date BETWEEN DATE '2011-10-30' AND DATE '2026-10-30';

-- V-SQL-05：六个基准指数的实际可得历史；科创 50 不要求补造 2012 年数据。
SELECT 'V-SQL-05' AS check_id, index_code, count(*) AS bar_count,
       min(trade_date) AS first_date, max(trade_date) AS last_date
FROM index_bar
WHERE trade_date BETWEEN DATE '2011-10-30' AND DATE '2026-10-30'
GROUP BY index_code ORDER BY index_code;

-- V-SQL-06：已有质检台账当前 open/fixing 分类；不新扫描、不关闭或忽略问题。
SELECT 'V-SQL-06' AS check_id, issue_type, status, count(*) AS issue_count
FROM data_quality_issue WHERE status IN ('open','fixing')
GROUP BY issue_type,status ORDER BY issue_type,status;

-- V-SQL-07：R1 修正后的原始字段、因子及成交均价；均价应落在 9.80～10.37 内。
SELECT 'V-SQL-07' AS check_id, code,trade_date,open,high,low,close,volume,amount,
       adj_factor,adj_factor_clean,
       amount/nullif(volume,0) AS average_trade_price
FROM daily_bar WHERE code='000018.SZ' AND trade_date=DATE '2013-06-21';
