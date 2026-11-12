-- 视觉预设菜单文案专项迁移，仅由维护者确认目标库后人工执行；启动不再自动覆盖旧默认值。
-- AI_STOCKS_MENU_OVERWRITE: EXPLICIT_CONFIRMATION_REQUIRED
-- 前提：完成备份并确认两条内置记录身份。在同一连接先显式执行确认口令：
-- SELECT set_config('ai_stocks.confirm_menu_overwrite', 'CONFIRM_VISUAL_PRESET_LABELS', false);
-- 影响：只改仍保持旧默认名称的内置菜单/资源；自定义名称保留。
-- 重跑：独立 manual marker 存在时不改数据；marker 内保存操作者、before/after 与处理状态。
-- 回退：仅 marker 记录 migrated 且当前仍等于 after 的对象可按 before 人工恢复并记录审计；
-- 不删除 marker，不能覆盖迁移后管理员的再次修改；本文件不自动回退。

BEGIN;
DO $$
DECLARE
    marker_key CONSTANT text := 'migration.visual_preset_labels_manual_v1';
    menu_before jsonb;
    menu_after jsonb;
    resource_before jsonb;
    resource_after jsonb;
    menu_state text := 'preserved';
    resource_state text := 'preserved';
BEGIN
    PERFORM pg_advisory_xact_lock(8410010009);
    IF current_setting('ai_stocks.confirm_menu_overwrite', true)
        IS DISTINCT FROM 'CONFIRM_VISUAL_PRESET_LABELS' THEN
        RAISE EXCEPTION '未设置视觉预设专项迁移确认口令，拒绝修改菜单/资源';
    END IF;
    IF EXISTS (SELECT 1 FROM app_config WHERE key=marker_key) THEN
        RETURN;
    END IF;

    SELECT to_jsonb(m) INTO menu_before FROM sys_menu m
      WHERE id='/system/layout/presets' FOR UPDATE;
    IF menu_before->>'title' = '预设管理'
       AND menu_before->>'code' = '/system/layout/presets'
       AND (menu_before->>'is_builtin')::boolean IS TRUE THEN
        UPDATE sys_menu SET title='视觉预设', updated_at=now()
          WHERE id='/system/layout/presets';
        menu_state := 'migrated';
    END IF;
    SELECT to_jsonb(m) INTO menu_after FROM sys_menu m WHERE id='/system/layout/presets';

    SELECT to_jsonb(r) INTO resource_before FROM sys_resource r
      WHERE id='layout:preset-manage' FOR UPDATE;
    IF resource_before->>'name' = '布局预设管理'
       AND resource_before->>'code' = 'layout:preset-manage'
       AND (resource_before->>'is_builtin')::boolean IS TRUE THEN
        UPDATE sys_resource SET name='视觉预设管理', updated_at=now()
          WHERE id='layout:preset-manage';
        resource_state := 'migrated';
    END IF;
    SELECT to_jsonb(r) INTO resource_after FROM sys_resource r WHERE id='layout:preset-manage';

    INSERT INTO app_config(key,value,updated_at)
    VALUES (marker_key, jsonb_build_object(
        'applied', true, 'actor', current_user, 'applied_at', clock_timestamp(),
        'menu', jsonb_build_object('state',menu_state,'before',menu_before,'after',menu_after),
        'resource', jsonb_build_object(
            'state',resource_state,'before',resource_before,'after',resource_after)
    )::text, now());
END $$;
COMMIT;
