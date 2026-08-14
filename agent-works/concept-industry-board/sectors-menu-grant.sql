-- 板块概念 · 修复：既有库回填 normal/tenant_admin 的 /sectors 菜单授权 SQL 留痕
--
-- 事实源是 backend/storage/pg_ddl.py 的 `_backfill_sector_menu_grants`
-- （marker `migration.sector_menu_grants_v1`，幂等执行，seed_rbac 内调用）。
-- 本文件是等价 SQL + 回滚，仅供人工复核/应急，不替代迁移执行。
-- 所有授权变更与 perm_ver 自增必须同一 PG 事务提交。
--
-- 背景：板块概念 T8 把 /sectors 菜单加进 _BUSINESS_MENU_CODES，但存量库的
-- stage4 菜单回填（migration.stage4_business_grants_v2）早已 applied，不会补授后加入的菜单；
-- T10b 的 sectors_view_v1 迁移只补了资源码 sectors:view、漏了菜单码 /sectors。
-- 结果 normal 有接口权限却看不到「板块行情」菜单入口（路由守卫按授权菜单 fail-closed 重定向）。
--
-- 影响：sys_role_menu（normal/tenant_admin 获得 /sectors）+ 受影响用户 perm_ver 自增。
-- 可逆性：正向段把本次实际插入的角色写入 marker.inserted_roles；回滚只删除这些角色的
-- `/sectors`。历史旧 marker 若没有 inserted_roles，安全回滚必须 no-op，并先从迁移前快照
-- 人工恢复；禁止猜测并删除 normal/tenant_admin 的现存合法授权。

-- ========== 正向：授予 /sectors 菜单（幂等，marker 已存在则 no-op）==========
BEGIN;

SELECT pg_advisory_xact_lock(8410010004);

DO $$
DECLARE
    v_changed integer := 0;
    v_n integer;
    v_inserted_roles text[];
BEGIN
    IF EXISTS (SELECT 1 FROM app_config WHERE key = 'migration.sector_menu_grants_v1') THEN
        RETURN;  -- 已应用，整段 no-op
    END IF;

    SELECT coalesce(array_agg(ro.role_id), ARRAY[]::text[]) INTO v_inserted_roles
    FROM (VALUES ('normal'), ('tenant_admin')) AS ro(role_id)
    WHERE NOT EXISTS (
        SELECT 1 FROM sys_role_menu rm
        WHERE rm.role_id = ro.role_id AND rm.menu_id = '/sectors'
    );

    INSERT INTO sys_role_menu (role_id, menu_id)
    SELECT unnest(v_inserted_roles), '/sectors'
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
    VALUES (
        'migration.sector_menu_grants_v1',
        jsonb_build_object('applied', true, 'inserted_roles', to_jsonb(v_inserted_roles))::text,
        now()
    );
END $$;

COMMIT;

-- ========== 回滚：确定性恢复（marker 缺失则 no-op）==========
-- BEGIN;
--
-- SELECT pg_advisory_xact_lock(8410010004);
--
-- DO $$
-- DECLARE
--     v_changed integer := 0;
--     v_n integer;
--     v_inserted_roles text[];
-- BEGIN
--     IF NOT EXISTS (SELECT 1 FROM app_config WHERE key = 'migration.sector_menu_grants_v1') THEN
--         RETURN;  -- 未应用，整段 no-op
--     END IF;
--
--     SELECT coalesce(array_agg(inserted.role_id), ARRAY[]::text[]) INTO v_inserted_roles
--     FROM app_config cfg
--     CROSS JOIN LATERAL jsonb_array_elements_text(
--         coalesce(cfg.value::jsonb->'inserted_roles', '[]'::jsonb)
--     ) AS inserted(role_id)
--     WHERE cfg.key = 'migration.sector_menu_grants_v1';
--
--     IF NOT EXISTS (
--         SELECT 1 FROM app_config
--         WHERE key = 'migration.sector_menu_grants_v1'
--           AND value::jsonb ? 'inserted_roles'
--     ) THEN
--         RAISE WARNING 'marker 缺少 inserted_roles，拒绝破坏性回滚；请使用迁移前快照';
--         RETURN;
--     END IF;
--
--     DELETE FROM sys_role_menu
--     WHERE role_id = ANY(v_inserted_roles) AND menu_id = '/sectors';
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
--     WHERE key = 'migration.sector_menu_grants_v1';
-- END $$;
--
-- COMMIT;
--
-- 重新启用（须显式操作）：删除 tombstone 后再跑正向段。
--   DELETE FROM app_config WHERE key = 'migration.sector_menu_grants_v1';
