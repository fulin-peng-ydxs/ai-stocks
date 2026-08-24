-- ============================================================================
-- 多租户 RBAC 阶段五（stage5-platform-capabilities）菜单与资源码回填
-- ----------------------------------------------------------------------------
-- 执行时机：
--   - stage5-platform-capabilities.sql 已执行、阶段五代码已部署后执行。
--   - init_pg_db() 也会执行同口径幂等 seed；本文件用于既有库人工升级与留痕。
--
-- 影响范围：
--   - sys_menu：新增 /system/audit、/system/dicts。
--   - sys_resource：新增 audit:view、dict:read、dict:view、dict:type-manage、dict:item-manage。
--   - sys_role_menu/sys_role_resource：tenant_admin 获得审计菜单与 audit:view；system 全量补齐。
--   - sys_user.perm_ver：首次阶段五迁移时 bump 非 system 有角色用户，使新增 baseline dict:read 生效。
--
-- 回滚：
--   - 下线对应前后端入口与 require_perm 后，可删除新增授权、资源和菜单。
--   - perm_ver 自增不可有意义回退，只会要求用户重新登录，属于可接受副作用。
--
-- 关键口径：
--   - dict:read 是登录基线共享读，不写入 normal/tenant_admin 的 role_resource。
--   - dict:read 必须挂 visible='login' 的叶子菜单锚点 /board，不得挂 /system/dicts。
--   - /system/dicts 为 system-only 管理页；非 system 角色不得获得字典管理权限。
--   - 菜单和功能点只补缺失行；现有运行时配置只允许管理员通过管理页面/API 显式覆盖并留审计。
-- ============================================================================

BEGIN;

INSERT INTO sys_menu (id, parent_id, code, title, type, route_path, icon, sort, visible, is_builtin)
VALUES
  ('/system/audit', 'system', '/system/audit', '审计日志', 'leaf', '/system/audit', NULL, 40, 'login', TRUE),
  ('/system/dicts', 'system', '/system/dicts', '数据字典', 'leaf', '/system/dicts', NULL, 50, 'system', TRUE)
ON CONFLICT (id) DO NOTHING;

INSERT INTO sys_resource (id, menu_id, code, name, type, api_method, api_path, sort, is_builtin)
VALUES
  ('audit:view', '/system/audit', 'audit:view', '查看审计日志', 'api', 'GET', '/api/audit', 10000, TRUE),
  ('dict:read', '/board', 'dict:read', '字典消费读（全站基线）', 'api', 'GET', '/api/dict/items/public', 10010, TRUE),
  ('dict:view', '/system/dicts', 'dict:view', '查看数据字典', 'api', 'GET', '/api/dict/types', 10020, TRUE),
  ('dict:type-manage', '/system/dicts', 'dict:type-manage', '维护字典类型', 'api', 'POST', '/api/dict/types', 10030, TRUE),
  ('dict:item-manage', '/system/dicts', 'dict:item-manage', '维护字典项', 'api', 'POST', '/api/dict/items', 10040, TRUE)
ON CONFLICT (id) DO NOTHING;

INSERT INTO sys_role_menu (role_id, menu_id)
VALUES ('tenant_admin', '/system/audit')
ON CONFLICT DO NOTHING;

INSERT INTO sys_role_resource (role_id, resource_id)
VALUES ('tenant_admin', 'audit:view')
ON CONFLICT DO NOTHING;

INSERT INTO sys_role_resource (role_id, resource_id)
SELECT 'system', id
FROM sys_resource
ON CONFLICT DO NOTHING;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM app_config WHERE key = 'migration.stage5_platform_capabilities_v1'
  ) THEN
    UPDATE sys_user u
    SET perm_ver = perm_ver + 1
    WHERE EXISTS (
      SELECT 1
      FROM sys_user_role ur
      JOIN sys_role r ON r.id = ur.role_id
      WHERE ur.user_id = u.id
        AND r.code <> 'system'
    )
      AND NOT EXISTS (
        SELECT 1
        FROM sys_user_role sur
        JOIN sys_role sr ON sr.id = sur.role_id
        WHERE sur.user_id = u.id
          AND (sr.code = 'system' OR sr.kind = 'system')
      );

    INSERT INTO app_config (key, value, updated_at)
    VALUES ('migration.stage5_platform_capabilities_v1', '{"applied":true}', now())
    ON CONFLICT (key) DO UPDATE
      SET value = EXCLUDED.value,
          updated_at = EXCLUDED.updated_at;
  END IF;
END $$;

COMMIT;
