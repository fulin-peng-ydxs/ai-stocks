-- 阶段六其他资产公开能力资源码与默认授权（幂等）
-- 用途：新增筛选方案、买卖方案、回测记录 publish 权限码，并回填 tenant_admin 默认授权。
-- 默认口径：tenant publish 给 tenant_admin/system；public publish 仅 system。normal/paid 需显式授权。

INSERT INTO sys_resource (id, menu_id, code, name, type, api_method, api_path, sort, is_builtin)
VALUES
  ('screen-profile:publish-tenant', '/screen', 'screen-profile:publish-tenant', '租户内公开筛选方案', 'api', 'POST', '/api/profiles/{pid}/visibility', 10000, TRUE),
  ('screen-profile:publish-public', '/screen', 'screen-profile:publish-public', '全体公开筛选方案', 'api', 'POST', '/api/profiles/{pid}/visibility', 10010, TRUE),
  ('trade-profile:publish-tenant', '/system/config/trade', 'trade-profile:publish-tenant', '租户内公开买卖方案', 'api', 'POST', '/api/trade-profiles/{pid}/visibility', 10020, TRUE),
  ('trade-profile:publish-public', '/system/config/trade', 'trade-profile:publish-public', '全体公开买卖方案', 'api', 'POST', '/api/trade-profiles/{pid}/visibility', 10030, TRUE),
  ('backtest:publish-tenant', '/backtest', 'backtest:publish-tenant', '租户内公开回测记录', 'api', 'POST', '/api/backtest/runs/{run_id}/visibility', 10040, TRUE),
  ('backtest:publish-public', '/backtest', 'backtest:publish-public', '全体公开回测记录', 'api', 'POST', '/api/backtest/runs/{run_id}/visibility', 10050, TRUE)
ON CONFLICT (id) DO UPDATE SET
  menu_id = EXCLUDED.menu_id,
  code = EXCLUDED.code,
  name = EXCLUDED.name,
  type = EXCLUDED.type,
  api_method = EXCLUDED.api_method,
  api_path = EXCLUDED.api_path,
  is_builtin = EXCLUDED.is_builtin;

INSERT INTO sys_role_resource (role_id, resource_id)
VALUES
  ('tenant_admin', 'screen-profile:publish-tenant'),
  ('tenant_admin', 'trade-profile:publish-tenant'),
  ('tenant_admin', 'backtest:publish-tenant')
ON CONFLICT DO NOTHING;

DELETE FROM sys_role_resource
WHERE role_id IN ('normal', 'paid')
  AND resource_id IN (
    'screen-profile:publish-tenant',
    'trade-profile:publish-tenant',
    'backtest:publish-tenant',
    'screen-profile:publish-public',
    'trade-profile:publish-public',
    'backtest:publish-public'
  );

DELETE FROM sys_role_resource
WHERE role_id = 'tenant_admin'
  AND resource_id IN (
    'screen-profile:publish-public',
    'trade-profile:publish-public',
    'backtest:publish-public'
  );

UPDATE sys_user u
SET perm_ver = perm_ver + 1
WHERE EXISTS (
  SELECT 1
  FROM sys_user_role ur
  WHERE ur.user_id = u.id
    AND ur.role_id IN ('tenant_admin', 'normal', 'paid')
);

INSERT INTO app_config (key, value, updated_at)
VALUES ('migration.stage6_asset_visibility_v1', '{"applied":true}', now())
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value,
    updated_at = EXCLUDED.updated_at;

-- 回滚说明：
-- 1. 若撤回本阶段 publish 资源码，先删除 sys_role_resource，再删除 sys_resource。
-- 2. 删除或恢复授权后必须 bump 受影响用户 perm_ver，使旧 token 权限快照失效。
