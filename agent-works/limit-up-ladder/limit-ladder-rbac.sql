-- 连板天梯 RBAC 一次性升级（PostgreSQL）。
-- 与启动 seed 一样只补缺失，不覆盖 sys_menu/sys_resource 的运行时配置；marker 记录本迁移实际插入项，
-- 供 rollback-limit-ladder.sql 后续按账本精确回滚。重复执行及回滚 tombstone 均为 no-op。
DO $$
DECLARE
    marker_key CONSTANT text := 'migration.limit_ladder_rbac_v1';
    marker_value jsonb;
    inserted_menu_ids jsonb := '[]'::jsonb;
    inserted_resource_ids jsonb := '[]'::jsonb;
    inserted_role_menus jsonb := '[]'::jsonb;
    inserted_role_resources jsonb := '[]'::jsonb;
    changed_roles text[] := ARRAY[]::text[];
    role_id text;
BEGIN
    PERFORM pg_advisory_xact_lock(8410010006);

    SELECT value::jsonb INTO marker_value FROM app_config WHERE key = marker_key;
    IF marker_value IS NOT NULL THEN
        IF coalesce((marker_value->>'version')::integer, 0) <> 1 OR NOT coalesce(
            marker_value ? 'applied' AND marker_value ? 'rolled_back' AND (
                (
                    (marker_value->>'applied')::boolean = true
                    AND (marker_value->>'rolled_back')::boolean = false
                ) OR (
                    (marker_value->>'applied')::boolean = false
                    AND (marker_value->>'rolled_back')::boolean = true
                )
            )
            AND jsonb_typeof(marker_value->'inserted_menu_ids') = 'array'
            AND jsonb_typeof(marker_value->'inserted_resource_ids') = 'array'
            AND jsonb_typeof(marker_value->'inserted_role_menus') = 'array'
            AND jsonb_typeof(marker_value->'inserted_role_resources') = 'array',
            false
        ) THEN
            RAISE EXCEPTION '连板天梯 RBAC marker 非法，拒绝继续';
        END IF;
        RETURN;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM sys_menu WHERE id='quotes' AND code='quotes') THEN
        RAISE EXCEPTION '缺少最新行情父菜单 quotes，拒绝创建孤立菜单';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM sys_menu
        WHERE id='/data/ingest' AND code='/data/ingest' AND visible='system'
    ) THEN
        RAISE EXCEPTION '缺少 system 数据采集菜单，无法锚定重算权限';
    END IF;
    IF (
        SELECT count(*) FROM sys_role
        WHERE (id='system' AND code='system' AND kind='system')
           OR (id='tenant_admin' AND code='tenant_admin' AND kind='tenant_admin')
           OR (id='normal' AND code='normal' AND kind='normal')
    ) <> 3 THEN
        RAISE EXCEPTION '内置角色不完整，拒绝写入默认授权';
    END IF;

    IF EXISTS (
        SELECT 1 FROM sys_menu
        WHERE (id='/limit-ladder' OR code='/limit-ladder' OR route_path='/limit-ladder')
          AND NOT (id='/limit-ladder' AND code='/limit-ladder' AND route_path='/limit-ladder')
    ) THEN
        RAISE EXCEPTION '连板天梯菜单身份已被其他节点占用';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM sys_menu WHERE id='/limit-ladder') THEN
        INSERT INTO sys_menu
            (id,parent_id,code,title,type,route_path,icon,sort,visible,is_builtin)
        VALUES
            ('/limit-ladder','quotes','/limit-ladder','连板天梯','leaf',
             '/limit-ladder',NULL,40,'login',TRUE);
        inserted_menu_ids := inserted_menu_ids || jsonb_build_array('/limit-ladder');
    END IF;

    IF EXISTS (
        SELECT 1 FROM sys_resource
        WHERE (id='limit-ladder:view' OR code='limit-ladder:view')
          AND NOT (id='limit-ladder:view' AND code='limit-ladder:view')
    ) OR EXISTS (
        SELECT 1 FROM sys_resource
        WHERE (id='limit-ladder:recompute' OR code='limit-ladder:recompute')
          AND NOT (id='limit-ladder:recompute' AND code='limit-ladder:recompute')
    ) THEN
        RAISE EXCEPTION '连板天梯资源身份已被其他功能点占用';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM sys_resource WHERE id='limit-ladder:view') THEN
        INSERT INTO sys_resource
            (id,menu_id,code,name,type,api_method,api_path,sort,is_builtin)
        VALUES
            ('limit-ladder:view','/limit-ladder','limit-ladder:view','查看连板天梯',
             'api','GET','/api/limit-ladder/{trade_date}',10,TRUE);
        inserted_resource_ids := inserted_resource_ids || jsonb_build_array('limit-ladder:view');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM sys_resource WHERE id='limit-ladder:recompute') THEN
        INSERT INTO sys_resource
            (id,menu_id,code,name,type,api_method,api_path,sort,is_builtin)
        VALUES
            ('limit-ladder:recompute','/data/ingest','limit-ladder:recompute','重算连板天梯',
             'api','POST','/api/limit-ladder/{trade_date}/recompute',10,TRUE);
        inserted_resource_ids := inserted_resource_ids || jsonb_build_array('limit-ladder:recompute');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM sys_resource r
        JOIN sys_menu m ON m.id=r.menu_id
        WHERE r.id='limit-ladder:recompute' AND r.code='limit-ladder:recompute'
          AND m.visible='system'
    ) THEN
        RAISE EXCEPTION '重算资源未锚定 system 菜单，拒绝继续授权';
    END IF;

    FOREACH role_id IN ARRAY ARRAY['system','tenant_admin','normal'] LOOP
        INSERT INTO sys_role_menu (role_id,menu_id)
        VALUES (role_id,'/limit-ladder') ON CONFLICT DO NOTHING;
        IF FOUND THEN
            inserted_role_menus := inserted_role_menus
                || jsonb_build_array(jsonb_build_array(role_id,'/limit-ladder'));
            changed_roles := array_append(changed_roles, role_id);
        END IF;

        INSERT INTO sys_role_resource (role_id,resource_id)
        VALUES (role_id,'limit-ladder:view') ON CONFLICT DO NOTHING;
        IF FOUND THEN
            inserted_role_resources := inserted_role_resources
                || jsonb_build_array(jsonb_build_array(role_id,'limit-ladder:view'));
            changed_roles := array_append(changed_roles, role_id);
        END IF;
    END LOOP;

    INSERT INTO sys_role_resource (role_id,resource_id)
    VALUES ('system','limit-ladder:recompute') ON CONFLICT DO NOTHING;
    IF FOUND THEN
        inserted_role_resources := inserted_role_resources
            || jsonb_build_array(jsonb_build_array('system','limit-ladder:recompute'));
        changed_roles := array_append(changed_roles, 'system');
    END IF;

    IF cardinality(changed_roles) > 0 THEN
        UPDATE sys_user u SET perm_ver=perm_ver+1
        WHERE u.role_code = ANY(changed_roles)
           OR EXISTS (
               SELECT 1 FROM sys_user_role ur
               WHERE ur.user_id=u.id AND ur.role_id=ANY(changed_roles)
           );
    END IF;

    INSERT INTO app_config (key,value,updated_at)
    VALUES (
        marker_key,
        jsonb_build_object(
            'version',1,
            'applied',true,
            'rolled_back',false,
            'inserted_menu_ids',inserted_menu_ids,
            'inserted_resource_ids',inserted_resource_ids,
            'inserted_role_menus',inserted_role_menus,
            'inserted_role_resources',inserted_role_resources
        )::text,
        now()
    );
END $$;
