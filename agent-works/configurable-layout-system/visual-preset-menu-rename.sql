-- 视觉预设菜单文案专项迁移（与 backend/storage/pg_ddl.py 启动迁移等价）。
-- 用途：把仍保持旧内置默认值的菜单和功能点名称更新为“视觉预设”。
-- 执行时机：部署包含 migration.visual_preset_labels_v1 的版本时由后端启动自动执行；
--           仅在无法启动应用迁移时人工执行本文件。
-- 影响范围：sys_menu./system/layout/presets、sys_resource.layout:preset-manage、迁移 marker。
-- 安全边界：只修改 is_builtin=true 且仍为旧默认文案的记录；管理员自定义名称保持不变。

BEGIN;
SELECT pg_advisory_xact_lock(8410010009);

UPDATE sys_menu
SET title = '视觉预设', updated_at = now()
WHERE id = '/system/layout/presets'
  AND is_builtin IS TRUE
  AND title = '预设管理'
  AND NOT EXISTS (
    SELECT 1 FROM app_config WHERE key = 'migration.visual_preset_labels_v1'
  );

UPDATE sys_resource
SET name = '视觉预设管理', updated_at = now()
WHERE id = 'layout:preset-manage'
  AND is_builtin IS TRUE
  AND name = '布局预设管理'
  AND NOT EXISTS (
    SELECT 1 FROM app_config WHERE key = 'migration.visual_preset_labels_v1'
  );

INSERT INTO app_config (key, value, updated_at)
VALUES (
  'migration.visual_preset_labels_v1',
  '{"applied":true,"source":"manual-sql"}',
  now()
)
ON CONFLICT (key) DO NOTHING;

COMMIT;

-- 回滚说明：自动迁移 marker 会记录每个对象是 migrated、already_current、preserved_custom 还是 missing。
-- 仅 states.menu/resource=migrated 且当前仍为上述新默认文案时，才可人工恢复旧文案；
-- 管理员在迁移后再次改名时禁止自动回滚。回滚后保留 marker 并写 rolled_back=true，避免重启反向覆盖。
