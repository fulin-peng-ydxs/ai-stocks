-- 板块概念 · T10b：既有库回填 sectors:view 授权（R22 后端部分）SQL 留痕
--
-- 事实源是 backend/storage/pg_ddl.py 的 seed（`_seed_role_grants` 经
-- BUSINESS_RESOURCE_CODES 对新库授予 normal/tenant_admin；`_backfill_*` 迁移对存量库幂等执行）。
-- 本文件是等价 SQL + 回滚，仅供人工复核/应急，不替代迁移执行。
-- 所有授权变更与 perm_ver 自增必须同一 PG 事务提交。
--
-- 影响：sys_role_resource（normal/tenant_admin 获得 sectors:view）+ 受影响用户 perm_ver 自增。
--   sectors:view：GET /api/sectors*（板块行情列表/详情，板块概念 R22/T8）
-- 守卫：require_perm('sectors:view')；无授权用户接口 403 fail-closed、菜单不可见。
--
-- 可逆性（确定性基线恢复）：回滚基线 = 执行前快照中 normal/tenant_admin 已持有的
-- `sectors:view` 授权（即回滚只删除本回填新增的 `sectors:view` 授权行，不触碰其他既有授权）。
-- 与 asset-publish-open 同构：marker 仅作幂等标记，不依赖 marker 内容。
--
-- 并发安全：正向/回滚均先取同一把事务级 advisory lock 串行化；marker 缺失/已存在时整体 no-op；
--           仅当确有增删才 bump perm_ver。

-- ========== 正向：授予 sectors:view（幂等，marker 已存在则 no-op）==========
BEGIN;

SELECT pg_advisory_xact_lock(8410010003);

DO $$
DECLARE
    v_changed integer := 0;
    v_n integer;
BEGIN
    IF EXISTS (SELECT 1 FROM app_config WHERE key = 'migration.sectors_view_v1') THEN
        RETURN;  -- 已应用，整段 no-op
    END IF;

    -- 资源行：_SEED_RESOURCES 已加 sectors:view（id=code），此处幂等补齐既有库缺行
    INSERT INTO sys_resource (id, menu_id, code, name, type, api_method, api_path, sort, is_builtin)
    SELECT 'sectors:view', '/sectors', 'sectors:view', '查看板块行情', 'api', 'GET', '/api/sectors', 9990, TRUE
    WHERE NOT EXISTS (SELECT 1 FROM sys_resource WHERE id = 'sectors:view');

    INSERT INTO sys_role_resource (role_id, resource_id)
    SELECT ro.role_id, 'sectors:view'
    FROM (VALUES ('normal'), ('tenant_admin')) AS ro(role_id)
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    v_changed := v_changed + v_n;

    IF v_changed > 0 THEN
        UPDATE sys_user u SET perm_ver = perm_ver + 1
        WHERE EXISTS (
            SELECT 1 FROM sys_user_role ur
            WHERE ur.user_id = u.id AND ur.role_id IN ('normal', 'tenant_admin')
        );
    END IF;

    INSERT INTO app_config (key, value, updated_at)
    VALUES ('migration.sectors_view_v1', '{"applied":true}', now());
END $$;

COMMIT;

-- ========== 回滚：确定性恢复（marker 缺失则 no-op）==========
-- BEGIN;
--
-- SELECT pg_advisory_xact_lock(8410010003);
--
-- DO $$
-- DECLARE
--     v_changed integer := 0;
--     v_n integer;
-- BEGIN
--     IF NOT EXISTS (SELECT 1 FROM app_config WHERE key = 'migration.sectors_view_v1') THEN
--         RETURN;  -- 未应用，整段 no-op
--     END IF;
--
--     -- 删除本回填新增的 sectors:view 授权（normal/tenant_admin）
--     DELETE FROM sys_role_resource
--     WHERE role_id IN ('normal', 'tenant_admin') AND resource_id = 'sectors:view';
--     GET DIAGNOSTICS v_n = ROW_COUNT; v_changed := v_changed + v_n;
--
--     IF v_changed > 0 THEN
--         UPDATE sys_user u SET perm_ver = perm_ver + 1
--         WHERE EXISTS (
--             SELECT 1 FROM sys_user_role ur
--             WHERE ur.user_id = u.id AND ur.role_id IN ('normal', 'tenant_admin')
--         );
--     END IF;
--
--     -- tombstone：留 marker 但标记已回滚，使正向迁移重启后 no-op、权限不被自动复活
--     UPDATE app_config SET value = '{"applied":false,"rolled_back":true}', updated_at = now()
--     WHERE key = 'migration.sectors_view_v1';
-- END $$;
--
-- COMMIT;
--
-- 重新启用（须显式操作）：删除 tombstone 后再跑正向段。
--   DELETE FROM app_config WHERE key = 'migration.sectors_view_v1';
