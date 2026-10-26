-- 用途：恢复历史默认视觉预设的启用状态，与 LayoutConfigRepo 启动修复等价。
-- 执行时机：应用启动自动修复；仅不能启动应用时人工执行，不需要重复执行。
-- 影响范围：仅 layout_preset.key=balanced 且 enabled=false 的行；
-- enabled 固定为 true，updated_at 记录修复时间，不修改名称、视觉 token 或自定义预设。
-- 前置条件：平台布局配置已迁移至 PostgreSQL。
-- 回滚：默认预设是强制可用的兜底，当前版本不支持回滚为停用；
-- 如需恢复旧规则，须先回退前后端约束，再根据迁移前备份恢复该行状态。
BEGIN;
UPDATE layout_preset
SET enabled = true, updated_at = now()
WHERE key = 'balanced' AND enabled = false;
COMMIT;
