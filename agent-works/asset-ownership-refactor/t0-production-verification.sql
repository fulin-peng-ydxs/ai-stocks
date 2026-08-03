-- T0 生产只读核验脚本（R14 系统内置段数据验收 / 发布门禁）
-- 用途：在生产 PG 上以只读方式核实三类预设的 owner/is_preset/visibility 分布，
--       确认 R14 严格条件（is_preset AND visibility='public' AND 平台槽）命中数量，
--       并探针「is_preset 但非平台槽 / 非 public」是否存在泄露风险。
-- 口径：与 plan §6.0 本地/dev 核验一致（GROUP BY is_preset,visibility + 平台槽严格命中/泄露探针）。
-- 平台槽：PUBLIC_BOARD_OWNER = ('default','admin')（backend/storage/pg_ddl.py）。
-- 执行：psql "<生产连接串>" -f t0-production-verification.sql   （纯 SELECT，只读，不写库）

-- ── 1) 三类预设 owner/is_preset/visibility 分布 ────────────────────────────
SELECT 'score_profile' AS table_name, is_preset, visibility, tenant_id, owner_user_id, count(*) AS cnt
FROM score_profile GROUP BY is_preset, visibility, tenant_id, owner_user_id
UNION ALL
SELECT 'screen_profile', is_preset, visibility, tenant_id, owner_user_id, count(*)
FROM screen_profile GROUP BY is_preset, visibility, tenant_id, owner_user_id
UNION ALL
SELECT 'trade_profile', is_preset, visibility, tenant_id, owner_user_id, count(*)
FROM trade_profile GROUP BY is_preset, visibility, tenant_id, owner_user_id
ORDER BY 1, 2 DESC, 3, 4, 5;

-- ── 2) R14 严格条件命中数（系统内置段实际返回数）────────────────────────────
-- 期望：命中数 = 平台槽 AND is_preset AND public 的行数；筛选段是否常态空、买卖段实际几条在此确认。
SELECT 'score_profile' AS table_name, count(*) AS r14_hits
FROM score_profile
WHERE is_preset AND visibility = 'public' AND (tenant_id, owner_user_id) = ('default', 'admin')
UNION ALL
SELECT 'screen_profile', count(*)
FROM screen_profile
WHERE is_preset AND visibility = 'public' AND (tenant_id, owner_user_id) = ('default', 'admin')
UNION ALL
SELECT 'trade_profile', count(*)
FROM trade_profile
WHERE is_preset AND visibility = 'public' AND (tenant_id, owner_user_id) = ('default', 'admin');

-- ── 3) 泄露探针：is_preset 但【非平台槽 或 非 public】的行 ──────────────────
-- 期望 0；若非 0，说明存在被严格条件挡住的 private/非平台槽 preset（须零泄露，核查归属）。
SELECT 'score_profile' AS table_name, id, tenant_id, owner_user_id, visibility
FROM score_profile
WHERE is_preset AND NOT (visibility = 'public' AND (tenant_id, owner_user_id) = ('default', 'admin'))
UNION ALL
SELECT 'screen_profile', id, tenant_id, owner_user_id, visibility
FROM screen_profile
WHERE is_preset AND NOT (visibility = 'public' AND (tenant_id, owner_user_id) = ('default', 'admin'))
UNION ALL
SELECT 'trade_profile', id, tenant_id, owner_user_id, visibility
FROM trade_profile
WHERE is_preset AND NOT (visibility = 'public' AND (tenant_id, owner_user_id) = ('default', 'admin'));

-- ── 4) M-1 性能拐点：公开回测/公开方案真实规模（只读计数）──────────────────
-- 用于评估带 q 搜索「全量解析 opaque ref + Python 过滤」在生产数据量下的成本。
SELECT (SELECT count(*) FROM backtest_run WHERE visibility IN ('tenant', 'public')) AS visible_backtest_runs,
       (SELECT count(*) FROM score_profile  WHERE visibility IN ('tenant', 'public')) AS visible_score_profiles,
       (SELECT count(*) FROM screen_profile WHERE visibility IN ('tenant', 'public')) AS visible_screen_profiles,
       (SELECT count(*) FROM trade_profile  WHERE visibility IN ('tenant', 'public')) AS visible_trade_profiles;
