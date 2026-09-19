-- 清理孤立用户偏好：回测参数残留。
-- 用途：删除 scope=feature / page_key=backtest / pref_key=params 的历史记录。
--   回测参数已改为会话态，前后端均不再读写该键，属迁移遗留的孤儿数据。
-- 执行时机：任意时刻；只命中该孤立键，不影响任何在用偏好。
-- 影响范围：user_preference 表 2 行（debug_tenant/debug_normal、default/debug_system）。
-- 回滚方式：见文末 INSERT 语句，按主键冲突时覆盖写回。

BEGIN;

DELETE FROM user_preference
WHERE scope = 'feature'
  AND page_key = 'backtest'
  AND pref_key = 'params';

COMMIT;

-- 回滚：恢复被删除的两行原始值。
-- INSERT INTO user_preference
--   (tenant_id, owner_user_id, scope, page_key, pref_key, value, schema_version, updated_at)
-- VALUES
--   ('debug_tenant', 'debug_normal', 'feature', 'backtest', 'params',
--    '{"kind":"strategy","dateStart":"2024-01-01","dateEnd":"2024-12-31","profileId":"","scoreProfileId":"avr_WyJzY29yZV9wcm9maWxlIiwiZGVidWdfdGVuYW50IiwiZGVidWdfbm9ybWFsIiwic2NvcmVfdHJlbmQiXQ","tradeProfileId":"avr_WyJ0cmFkZV9wcm9maWxlIiwiZGVidWdfdGVuYW50IiwiZGVidWdfbm9ybWFsIiwidHJhZGVfdHJlbmRfdHJhZGUiXQ","topN":10,"initCap":1000000,"industryOn":false,"industryPct":20}',
--    1, now()),
--   ('default', 'debug_system', 'feature', 'backtest', 'params',
--    '{"kind":"strategy","dateStart":"2024-01-01","dateEnd":"2024-12-31","profileId":"","scoreProfileId":"avr_WyJzY29yZV9wcm9maWxlIiwiZGVmYXVsdCIsImFkbWluIiwiZGVmYXVsdCJd","tradeProfileId":"avr_WyJ0cmFkZV9wcm9maWxlIiwiZGVmYXVsdCIsImFkbWluIiwibWE1X3B1bGxiYWNrIl0","topN":10,"initCap":1000000,"industryOn":false,"industryPct":20}',
--    1, now())
-- ON CONFLICT (tenant_id, owner_user_id, scope, page_key, pref_key)
-- DO UPDATE SET value = EXCLUDED.value, schema_version = EXCLUDED.schema_version, updated_at = now();
