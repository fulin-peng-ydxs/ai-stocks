-- 用途：用户授权的本地测试例外，将 default/admin 两个待生效版本提前至 2026-10-16。
-- 执行时机：仅本机 dev/test/local；执行者须加载 .env.local，核对运行档案 PID、
-- 环境及 PG 指纹一致。会话必须显式设置 ai_stocks.local_test_date_action=apply|rollback。
-- 影响：仅下面三个 activation 的 effective_from_trade_date；不改版本、发布时间、
-- 其他归属或既有打卡。正常发布的下一交易日规则不变；不作为启动/升级迁移执行。
-- 趋势规则 v48 与 v49 原同日生效，必须一起提前，避免 10-19 倒退到 v48。
-- 回滚：相同前置核查后将上述会话变量设为 rollback 再执行；恢复为 2026-10-19。
-- apply/rollback 均锁定规则主体，并在发现 10-16 起已有打卡时拒绝执行，避免版本错配。
-- 审计：与日期调整同一事务记录前后日期和测试用途；不删除历史审计。
DO $$
DECLARE
    action_name text := current_setting('ai_stocks.local_test_date_action', true);
    before_date date;
    after_date date;
    target record;
    affected integer;
    existing_date date;
BEGIN
    IF action_name IS NULL OR action_name NOT IN ('apply', 'rollback') THEN
        RAISE EXCEPTION '必须显式指定本地测试 apply 或 rollback';
    END IF;
    before_date := CASE WHEN action_name='apply' THEN DATE '2026-10-19'
                        ELSE DATE '2026-10-16' END;
    after_date := CASE WHEN action_name='apply' THEN DATE '2026-10-16'
                       ELSE DATE '2026-10-19' END;

    FOR target IN SELECT * FROM (VALUES
        ('tdr_151e90378ecf4262ad22edab48e582b8',
         'tda_80b9d439eb744379962ffd70cf0ebdd8', '投资-股息分红', 6, 6, 6),
        ('tdr_b9943a9040d84a4f9577b95e16a35605',
         'tda_1f4cd5c307284d9cad437553a433d77f', '投机-趋势跟随', 48, 48, 49),
        ('tdr_b9943a9040d84a4f9577b95e16a35605',
         'tda_188f97e1a9ad4b30a9b2e86233a98404', '投机-趋势跟随', 49, 49, 49)
    ) AS targets(rule_id, activation_id, rule_name, version_no, event_seq, latest_version_no)
    LOOP
        -- 与发布、打卡共用主体行锁；版本/事件指针发生变化时整批失败。
        PERFORM 1 FROM trade_discipline_rule
        WHERE tenant_id='default' AND owner_user_id='admin' AND id=target.rule_id
          AND name=target.rule_name AND status='active' AND deleted_at IS NULL
          AND latest_version_no=target.latest_version_no
          AND next_activation_seq=target.latest_version_no
        FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION '规则状态已变化：%', target.rule_name;
        END IF;
        IF EXISTS (
            SELECT 1 FROM trade_discipline_checkin
            WHERE tenant_id='default' AND owner_user_id='admin'
              AND rule_id=target.rule_id AND trade_date>=DATE '2026-10-16'
        ) THEN
            RAISE EXCEPTION '已有填报，拒绝改变有效版本：%', target.rule_name;
        END IF;

        -- 只允许有本次操作审计的目标状态幂等跳过，支持审计保留后的重入。
        SELECT effective_from_trade_date INTO existing_date
        FROM trade_discipline_rule_activation
        WHERE tenant_id='default' AND owner_user_id='admin' AND rule_id=target.rule_id
          AND id=target.activation_id AND event_type='publish'
          AND version_no=target.version_no AND event_seq=target.event_seq;
        IF existing_date=after_date AND EXISTS (
            SELECT 1 FROM audit_log WHERE tenant_id='default'
              AND actor_account='codex-local-maintenance' AND target_id=target.activation_id
              AND action='local_test_effective_date_' || action_name
        ) THEN
            CONTINUE;
        END IF;

        -- 精确匹配待调整事件及旧日期，禁止重复执行或误改其他历史版本。
        UPDATE trade_discipline_rule_activation
        SET effective_from_trade_date=after_date
        WHERE tenant_id='default' AND owner_user_id='admin' AND rule_id=target.rule_id
          AND id=target.activation_id AND event_type='publish'
          AND version_no=target.version_no AND event_seq=target.event_seq
          AND effective_from_trade_date=before_date;
        GET DIAGNOSTICS affected = ROW_COUNT;
        IF affected<>1 THEN
            RAISE EXCEPTION '事件不符合预期：%', target.rule_name;
        END IF;

        -- actor_account 标识代理维护操作，owner 只表示数据归属，不冒充用户登录。
        INSERT INTO audit_log (
            id,tenant_id,actor_account,event_category,event_type,resource_code,
            action,target_type,target_id,target_label,result,status,context,changes
        ) VALUES (
            'audit_td_local_date_' || md5(target.activation_id || clock_timestamp()::text),
            'default','codex-local-maintenance','business','trade_discipline',
            'trade-discipline:rule-manage','local_test_effective_date_' || action_name,
            'trade_discipline_rule_activation',target.activation_id,target.rule_name,
            'success','completed',
            jsonb_build_object('reason','用户要求提前至10月16日生效以测试填报',
                               'owner_user_id','admin','version_no',target.version_no),
            jsonb_build_array(jsonb_build_object(
                'field','effective_from_trade_date','before',before_date,'after',after_date))
        );
    END LOOP;
END $$;
