-- 连板天梯 PostgreSQL 专项回滚脚本。
-- 前置条件：应用版本已停止创建/读取连板天梯任务，已完成 PG 备份并人工确认永久回退。
-- 影响范围：只回滚两份 migration marker 记录为本功能实际插入的 RBAC 和审计账本对象。
-- 安全边界：pending outbox、账本外授权/子菜单/资源引用、共享审计键复用均会 fail-closed。
-- DuckDB 默认保留：快照和 ST 历史是可重算事实；如需永久删除，按文末注释在 DuckDB 单独执行。

BEGIN;

DO $$
DECLARE
    rbac_key CONSTANT text := 'migration.limit_ladder_rbac_v1';
    audit_key CONSTANT text := 'migration.limit_ladder_audit_ledger_v1';
    rbac_marker jsonb;
    audit_marker jsonb;
    pair jsonb;
    item text;
    changed_roles text[] := ARRAY[]::text[];
BEGIN
    PERFORM pg_advisory_xact_lock(8410010006);
    PERFORM pg_advisory_xact_lock(8410010007);

    SELECT value::jsonb INTO rbac_marker FROM app_config WHERE key=rbac_key;
    SELECT value::jsonb INTO audit_marker FROM app_config WHERE key=audit_key;

    IF rbac_marker IS NULL OR coalesce((rbac_marker->>'version')::integer,0) <> 1
        OR NOT coalesce((rbac_marker->>'applied')::boolean, false)
        OR coalesce((rbac_marker->>'rolled_back')::boolean, true)
        OR jsonb_typeof(rbac_marker->'inserted_menu_ids') IS DISTINCT FROM 'array'
        OR jsonb_typeof(rbac_marker->'inserted_resource_ids') IS DISTINCT FROM 'array'
        OR jsonb_typeof(rbac_marker->'inserted_role_menus') IS DISTINCT FROM 'array'
        OR jsonb_typeof(rbac_marker->'inserted_role_resources') IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION '连板天梯 RBAC marker 缺失、已回滚或非法，拒绝继续';
    END IF;
    IF audit_marker IS NULL OR coalesce((audit_marker->>'version')::integer,0) <> 1
        OR NOT coalesce((audit_marker->>'applied')::boolean, false)
        OR coalesce((audit_marker->>'rolled_back')::boolean, true)
        OR jsonb_typeof(audit_marker->'created') IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION '连板天梯审计账本 marker 缺失、已回滚或非法，拒绝继续';
    END IF;

    IF to_regclass(current_schema() || '.limit_ladder_audit_outbox') IS NOT NULL
       AND EXISTS (SELECT 1 FROM limit_ladder_audit_outbox WHERE status='pending') THEN
        RAISE EXCEPTION '仍有未投递的连板天梯审计 outbox，拒绝回滚';
    END IF;

    FOR item IN SELECT jsonb_array_elements_text(rbac_marker->'inserted_resource_ids') LOOP
        IF item='limit-ladder:view' AND NOT EXISTS (
            SELECT 1 FROM sys_resource
            WHERE id=item AND code=item AND menu_id='/limit-ladder'
              AND name='查看连板天梯' AND type='api' AND api_method='GET'
              AND api_path='/api/limit-ladder/{trade_date}'
              AND sort=10 AND is_builtin=true
        ) OR item='limit-ladder:recompute' AND NOT EXISTS (
            SELECT 1 FROM sys_resource
            WHERE id=item AND code=item AND menu_id='/data/ingest'
              AND name='重算连板天梯' AND type='api' AND api_method='POST'
              AND api_path='/api/limit-ladder/{trade_date}/recompute'
              AND sort=10 AND is_builtin=true
        ) OR item NOT IN ('limit-ladder:view','limit-ladder:recompute') THEN
            RAISE EXCEPTION '资源 % 身份已变化或不在迁移白名单，拒绝回滚', item;
        END IF;
        IF EXISTS (
            SELECT 1 FROM sys_role_resource rr
            WHERE rr.resource_id=item
              AND NOT EXISTS (
                  SELECT 1 FROM jsonb_array_elements(rbac_marker->'inserted_role_resources') x
                  WHERE x->>0=rr.role_id AND x->>1=rr.resource_id
              )
        ) THEN
            RAISE EXCEPTION '资源 % 存在账本外角色授权，拒绝回滚', item;
        END IF;
    END LOOP;
    FOR item IN SELECT jsonb_array_elements_text(rbac_marker->'inserted_menu_ids') LOOP
        IF item <> '/limit-ladder' OR NOT EXISTS (
            SELECT 1 FROM sys_menu
            WHERE id=item AND code=item AND parent_id='quotes'
              AND title='连板天梯' AND type='leaf' AND route_path=item
              AND icon IS NULL AND sort=40 AND visible='login' AND is_builtin=true
        ) THEN
            RAISE EXCEPTION '菜单 % 身份已变化或不在迁移白名单，拒绝回滚', item;
        END IF;
        IF EXISTS (
            SELECT 1 FROM sys_role_menu rm
            WHERE rm.menu_id=item
              AND NOT EXISTS (
                  SELECT 1 FROM jsonb_array_elements(rbac_marker->'inserted_role_menus') x
                  WHERE x->>0=rm.role_id AND x->>1=rm.menu_id
              )
        ) OR EXISTS (SELECT 1 FROM sys_menu WHERE parent_id=item)
          OR EXISTS (
              SELECT 1 FROM sys_resource r WHERE r.menu_id=item
                AND NOT (r.id IN (
                    SELECT jsonb_array_elements_text(rbac_marker->'inserted_resource_ids')
                ))
          ) THEN
            RAISE EXCEPTION '菜单 % 存在账本外授权或子节点，拒绝回滚', item;
        END IF;
    END LOOP;

    FOR pair IN SELECT value FROM jsonb_array_elements(
        rbac_marker->'inserted_role_resources'
    ) WITH ORDINALITY AS e(value, ordinality) ORDER BY ordinality DESC LOOP
        DELETE FROM sys_role_resource
        WHERE role_id=pair->>0 AND resource_id=pair->>1;
        IF FOUND THEN changed_roles := array_append(changed_roles, pair->>0); END IF;
    END LOOP;
    FOR pair IN SELECT value FROM jsonb_array_elements(
        rbac_marker->'inserted_role_menus'
    ) WITH ORDINALITY AS e(value, ordinality) ORDER BY ordinality DESC LOOP
        DELETE FROM sys_role_menu WHERE role_id=pair->>0 AND menu_id=pair->>1;
        IF FOUND THEN changed_roles := array_append(changed_roles, pair->>0); END IF;
    END LOOP;
    FOR item IN SELECT jsonb_array_elements_text(rbac_marker->'inserted_resource_ids') LOOP
        DELETE FROM sys_resource WHERE id=item AND code=item;
        IF NOT FOUND AND EXISTS (SELECT 1 FROM sys_resource WHERE id=item OR code=item) THEN
            RAISE EXCEPTION '资源 % 身份已变化，拒绝回滚', item;
        END IF;
    END LOOP;
    FOR item IN SELECT jsonb_array_elements_text(rbac_marker->'inserted_menu_ids') LOOP
        DELETE FROM sys_menu WHERE id=item AND code=item AND route_path=item;
        IF NOT FOUND AND EXISTS (SELECT 1 FROM sys_menu WHERE id=item OR code=item) THEN
            RAISE EXCEPTION '菜单 % 身份已变化，拒绝回滚', item;
        END IF;
    END LOOP;

    IF cardinality(changed_roles) > 0 THEN
        UPDATE sys_user u SET perm_ver=perm_ver+1
        WHERE u.role_code=ANY(changed_roles)
           OR EXISTS (
               SELECT 1 FROM sys_user_role ur
               WHERE ur.user_id=u.id AND ur.role_id=ANY(changed_roles)
           );
    END IF;

    IF coalesce((audit_marker->'created'->>'audit_column')::boolean,false)
       AND EXISTS (
           SELECT 1 FROM audit_log a WHERE a.source_event_key IS NOT NULL
             AND NOT EXISTS (
                 SELECT 1 FROM limit_ladder_audit_outbox o
                 WHERE o.source_event_key=a.source_event_key
             )
       ) THEN
        RAISE EXCEPTION 'audit_log.source_event_key 已被其他业务复用，拒绝删除';
    END IF;

    IF coalesce((audit_marker->'created'->>'outbox_table')::boolean,false) THEN
        DROP TABLE IF EXISTS limit_ladder_audit_outbox;
    END IF;
    IF coalesce((audit_marker->'created'->>'ledger_table')::boolean,false) THEN
        DROP TABLE IF EXISTS limit_ladder_task_ledger;
    END IF;
    IF coalesce((audit_marker->'created'->>'audit_index')::boolean,false) THEN
        DROP INDEX IF EXISTS uq_audit_log_source_event_key;
    END IF;
    IF coalesce((audit_marker->'created'->>'audit_column')::boolean,false) THEN
        ALTER TABLE audit_log DROP COLUMN IF EXISTS source_event_key;
    END IF;

    UPDATE app_config
    SET value=jsonb_set(
            jsonb_set(value::jsonb,'{applied}','false'::jsonb),
            '{rolled_back}','true'::jsonb
        )::text,
        updated_at=now()
    WHERE key IN (rbac_key,audit_key);
END $$;

COMMIT;

-- 验证：两个 marker 均为 applied=false/rolled_back=true；迁移实际创建的 PG 对象不存在。
-- 默认不要删除 DuckDB 数据。如已备份且确认永久清除，请在停止后端并独占 DuckDB 写锁后单独执行：
-- BEGIN TRANSACTION;
-- DROP TABLE IF EXISTS limit_ladder_snapshot_aggregate;
-- DROP TABLE IF EXISTS limit_ladder_snapshot_concept;
-- DROP TABLE IF EXISTS limit_ladder_snapshot_stock;
-- DROP TABLE IF EXISTS limit_ladder_snapshot_state;
-- DROP TABLE IF EXISTS limit_ladder_snapshot;
-- DROP TABLE IF EXISTS stock_st_status_history;
-- DROP TABLE IF EXISTS stock_st_status_daily;
-- COMMIT;
