-- asset-ownership-refactor · T1B 放开普通用户发布权（C4/R4）SQL 留痕
--
-- 事实源是 backend/storage/pg_ddl.py 的 Python 迁移 `_backfill_asset_publish_open_v1`
-- （marker=migration.asset_publish_open_v2，随后端启动幂等执行）。本文件是等价 SQL + 回滚，
-- 仅供人工复核/应急，不替代迁移执行。所有授权变更与 perm_ver 自增必须同一 PG 事务提交。
--
-- 影响：sys_role_resource（normal/tenant_admin 获得 8 个发布码）+ 受影响用户 perm_ver 自增。
-- 8 个发布码：
--   score-profile:publish-tenant / screen-profile:publish-tenant /
--   trade-profile:publish-tenant / backtest:publish-tenant
--   score-profile:publish-public / screen-profile:publish-public /
--   trade-profile:publish-public / backtest:publish-public
-- 守卫不变：可见性接口仍 owner-only（只能改自己的资产），放开的是「能否发布」。
--
-- 可逆性（确定性基线恢复）：本次是**默认角色策略变更**，发布权在多处 seed（新装 _seed_role_grants、
-- 存量 seed_stage6_asset_visibility、本回填）写入，无法用「本迁移实际新增行」账本覆盖全部来源。
-- 回滚因此把 normal/tenant_admin 恢复到 **C4 前默认策略**：
--   normal       ：无任何发布码（删全部 8）；
--   tenant_admin ：仅保留 4 个 tenant 发布码（删 4 个 public，并补齐 tenant——迁移期间被人工移除也恢复）。
-- 与所有默认策略迁移一致：**不保留迁移后经角色管理页做的人工增删**（这是策略迁移的固有边界，
-- 若角色管理页曾把某发布码删后又加回，回滚仍按默认策略处理）。
-- 并发安全：正向/回滚均先取同一把事务级 advisory lock 串行化；marker 缺失/已存在时整体 no-op；
--           仅当确有增删才 bump perm_ver（与 Python 迁移严格等价）。

-- ========== 正向：授予 8 发布码（幂等，marker 已存在则 no-op）==========
BEGIN;

SELECT pg_advisory_xact_lock(8410010002);

DO $$
DECLARE
    v_changed integer := 0;
    v_n integer;
BEGIN
    IF EXISTS (SELECT 1 FROM app_config WHERE key = 'migration.asset_publish_open_v2') THEN
        RETURN;  -- 已应用，整段 no-op
    END IF;

    INSERT INTO sys_role_resource (role_id, resource_id)
    SELECT ro.role_id, c.code
    FROM (VALUES ('normal'), ('tenant_admin')) AS ro(role_id)
    CROSS JOIN (VALUES
        ('score-profile:publish-tenant'),
        ('screen-profile:publish-tenant'),
        ('trade-profile:publish-tenant'),
        ('backtest:publish-tenant'),
        ('score-profile:publish-public'),
        ('screen-profile:publish-public'),
        ('trade-profile:publish-public'),
        ('backtest:publish-public')
    ) AS c(code)
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
    VALUES ('migration.asset_publish_open_v2', '{"applied":true}', now());
END $$;

COMMIT;

-- ========== 回滚：确定性恢复 C4 前默认策略（marker 缺失则 no-op）==========
-- BEGIN;
--
-- SELECT pg_advisory_xact_lock(8410010002);
--
-- DO $$
-- DECLARE
--     v_changed integer := 0;
--     v_n integer;
-- BEGIN
--     IF NOT EXISTS (SELECT 1 FROM app_config WHERE key = 'migration.asset_publish_open_v2') THEN
--         RETURN;  -- 未应用，整段 no-op
--     END IF;
--
--     -- normal：C4 前无发布码 → 删全部 8
--     DELETE FROM sys_role_resource
--     WHERE role_id = 'normal'
--       AND resource_id IN (
--         'score-profile:publish-tenant', 'screen-profile:publish-tenant',
--         'trade-profile:publish-tenant', 'backtest:publish-tenant',
--         'score-profile:publish-public', 'screen-profile:publish-public',
--         'trade-profile:publish-public', 'backtest:publish-public'
--       );
--     GET DIAGNOSTICS v_n = ROW_COUNT; v_changed := v_changed + v_n;
--
--     -- tenant_admin：C4 前仅有 4 个 tenant 发布码 → 删 4 个 public
--     DELETE FROM sys_role_resource
--     WHERE role_id = 'tenant_admin'
--       AND resource_id IN (
--         'score-profile:publish-public', 'screen-profile:publish-public',
--         'trade-profile:publish-public', 'backtest:publish-public'
--       );
--     GET DIAGNOSTICS v_n = ROW_COUNT; v_changed := v_changed + v_n;
--
--     -- tenant_admin：补齐 4 个 tenant 发布码到基线（若迁移期间被人工移除也一并恢复）
--     INSERT INTO sys_role_resource (role_id, resource_id)
--     SELECT 'tenant_admin', c.code
--     FROM (VALUES
--         ('score-profile:publish-tenant'), ('screen-profile:publish-tenant'),
--         ('trade-profile:publish-tenant'), ('backtest:publish-tenant')
--     ) AS c(code)
--     ON CONFLICT DO NOTHING;
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
--     -- tombstone：留 marker 但标记已回滚，使正向迁移重启后 no-op、发布权不被自动复活
--     -- （若 DELETE marker，当前版本重启→init 重跑正向迁移→marker 缺失→重新授权，回滚被反向覆盖）。
--     UPDATE app_config SET value = '{"applied":false,"rolled_back":true}', updated_at = now()
--     WHERE key = 'migration.asset_publish_open_v2';
-- END $$;
--
-- COMMIT;
--
-- 重新启用发布权（须显式操作，回滚后不会自动恢复）：删除 tombstone 后再跑正向迁移段。
--   DELETE FROM app_config WHERE key = 'migration.asset_publish_open_v2';  -- 然后重跑上面「正向」段
