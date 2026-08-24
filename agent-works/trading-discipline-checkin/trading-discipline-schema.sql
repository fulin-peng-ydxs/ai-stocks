-- 交易纪律 T1：PG 业务模型与 RBAC 迁移人工复核 SQL
--
-- 事实源：backend/storage/pg_ddl.py。应用启动通过 init_pg_db() 幂等执行；本文件用于人工复核、
-- 受控应急和发布审计，不替代 Python 启动迁移。
-- 执行时机：部署 T1 后首次启动或既有环境受控重启。要求 PostgreSQL >= 14，内置角色已存在。
-- 影响范围：public schema 新增 trade_discipline_* 私人资产表、索引；新增交易纪律菜单、四资源、
-- normal/tenant_admin/system 展示授权；受影响用户 perm_ver 在同一事务自增。
-- 回滚：默认仅回滚 RBAC，不删除业务表或用户事实；确定从未写入业务事实时才可按 FK 逆序删表。
-- 所有业务外键均以 tenant_id + owner_user_id 开头，禁止跨归属关联；金额统一 NUMERIC。

-- ========== 业务模型（幂等建表）==========

CREATE TABLE IF NOT EXISTS trade_discipline_rule (
    id TEXT, tenant_id TEXT NOT NULL DEFAULT 'default', owner_user_id TEXT NOT NULL DEFAULT 'admin',
    name TEXT, normalized_name TEXT,
    status TEXT NOT NULL DEFAULT 'unpublished', latest_version_no INTEGER,
    next_activation_seq BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CHECK (status IN ('unpublished', 'active', 'archived')),
    CONSTRAINT td_rule_lifecycle_consistency_check
    CHECK ((status='unpublished' AND latest_version_no IS NULL)
        OR (status IN ('active','archived') AND latest_version_no > 0
            AND btrim(coalesce(name,'')) <> '' AND btrim(coalesce(normalized_name,'')) <> '')),
    CHECK (next_activation_seq >= 0),
    PRIMARY KEY (tenant_id, owner_user_id, id)
);

CREATE TABLE IF NOT EXISTS trade_discipline_rule_name_claim (
    tenant_id TEXT NOT NULL DEFAULT 'default', owner_user_id TEXT NOT NULL DEFAULT 'admin',
    normalized_name TEXT NOT NULL, rule_id TEXT NOT NULL, claimed_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (btrim(normalized_name) <> ''),
    PRIMARY KEY (tenant_id, owner_user_id, normalized_name),
    FOREIGN KEY (tenant_id, owner_user_id, rule_id)
        REFERENCES trade_discipline_rule (tenant_id, owner_user_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS trade_discipline_rule_version (
    rule_id TEXT, tenant_id TEXT NOT NULL DEFAULT 'default', owner_user_id TEXT NOT NULL DEFAULT 'admin',
    version_no INTEGER, name TEXT NOT NULL, normalized_name TEXT NOT NULL,
    capital NUMERIC(20, 2) NOT NULL, published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (version_no > 0), CHECK (btrim(name) <> '' AND btrim(normalized_name) <> ''),
    CHECK (capital > 0),
    PRIMARY KEY (tenant_id, owner_user_id, rule_id, version_no),
    FOREIGN KEY (tenant_id, owner_user_id, rule_id)
        REFERENCES trade_discipline_rule (tenant_id, owner_user_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS trade_discipline_stock_rule (
    rule_id TEXT, tenant_id TEXT NOT NULL DEFAULT 'default', owner_user_id TEXT NOT NULL DEFAULT 'admin',
    version_no INTEGER, detail_id TEXT, name TEXT NOT NULL, max_capital NUMERIC(20, 2),
    content TEXT NOT NULL, display_order INTEGER NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (btrim(name) <> '' AND btrim(content) <> ''), CHECK (display_order > 0),
    CHECK (NOT enabled OR (max_capital IS NOT NULL AND max_capital > 0)),
    PRIMARY KEY (tenant_id, owner_user_id, rule_id, version_no, detail_id),
    UNIQUE (tenant_id, owner_user_id, rule_id, version_no, display_order),
    FOREIGN KEY (tenant_id, owner_user_id, rule_id, version_no)
        REFERENCES trade_discipline_rule_version
            (tenant_id, owner_user_id, rule_id, version_no) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS trade_discipline_action_rule (
    rule_id TEXT, tenant_id TEXT NOT NULL DEFAULT 'default', owner_user_id TEXT NOT NULL DEFAULT 'admin',
    version_no INTEGER, detail_id TEXT, name TEXT NOT NULL, action_type TEXT NOT NULL,
    action_subtype TEXT NOT NULL, content TEXT NOT NULL, display_order INTEGER NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (btrim(name) <> '' AND btrim(content) <> ''),
    CHECK ((action_type='buy' AND action_subtype IN ('open_position','add_position'))
        OR (action_type='sell' AND action_subtype IN ('liquidate','do_t'))),
    CHECK (display_order > 0),
    PRIMARY KEY (tenant_id, owner_user_id, rule_id, version_no, detail_id),
    UNIQUE (tenant_id, owner_user_id, rule_id, version_no, action_type, display_order),
    UNIQUE (tenant_id, owner_user_id, rule_id, version_no, detail_id, action_type),
    FOREIGN KEY (tenant_id, owner_user_id, rule_id, version_no)
        REFERENCES trade_discipline_rule_version
            (tenant_id, owner_user_id, rule_id, version_no) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS trade_discipline_rule_draft (
    rule_id TEXT, tenant_id TEXT NOT NULL DEFAULT 'default', owner_user_id TEXT NOT NULL DEFAULT 'admin',
    draft_revision INTEGER NOT NULL DEFAULT 1, proposed_name TEXT, normalized_name TEXT,
    capital NUMERIC(20, 2), source_version_no INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (draft_revision > 0), CHECK (capital IS NULL OR capital >= 0),
    CHECK (source_version_no IS NULL OR source_version_no > 0),
    PRIMARY KEY (tenant_id, owner_user_id, rule_id),
    FOREIGN KEY (tenant_id, owner_user_id, rule_id)
        REFERENCES trade_discipline_rule (tenant_id, owner_user_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, owner_user_id, rule_id, source_version_no)
        REFERENCES trade_discipline_rule_version
            (tenant_id, owner_user_id, rule_id, version_no) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS trade_discipline_draft_stock_rule (
    rule_id TEXT, tenant_id TEXT NOT NULL DEFAULT 'default', owner_user_id TEXT NOT NULL DEFAULT 'admin',
    detail_id TEXT, name TEXT, max_capital NUMERIC(20, 2), content TEXT,
    display_order INTEGER NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (max_capital IS NULL OR max_capital >= 0), CHECK (display_order > 0),
    PRIMARY KEY (tenant_id, owner_user_id, rule_id, detail_id),
    UNIQUE (tenant_id, owner_user_id, rule_id, display_order),
    FOREIGN KEY (tenant_id, owner_user_id, rule_id)
        REFERENCES trade_discipline_rule_draft (tenant_id, owner_user_id, rule_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS trade_discipline_draft_action_rule (
    rule_id TEXT, tenant_id TEXT NOT NULL DEFAULT 'default', owner_user_id TEXT NOT NULL DEFAULT 'admin',
    detail_id TEXT, name TEXT, action_type TEXT, action_subtype TEXT, content TEXT,
    display_order INTEGER NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (action_type IS NULL OR action_type IN ('buy','sell')),
    CHECK (action_subtype IS NULL OR action_subtype IN
        ('open_position','add_position','liquidate','do_t')),
    CHECK (action_type IS NULL OR action_subtype IS NULL
        OR (action_type='buy' AND action_subtype IN ('open_position','add_position'))
        OR (action_type='sell' AND action_subtype IN ('liquidate','do_t'))),
    CHECK (display_order > 0),
    PRIMARY KEY (tenant_id, owner_user_id, rule_id, detail_id),
    UNIQUE (tenant_id, owner_user_id, rule_id, action_type, display_order),
    FOREIGN KEY (tenant_id, owner_user_id, rule_id)
        REFERENCES trade_discipline_rule_draft (tenant_id, owner_user_id, rule_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS trade_discipline_rule_activation (
    id TEXT, tenant_id TEXT NOT NULL DEFAULT 'default', owner_user_id TEXT NOT NULL DEFAULT 'admin',
    rule_id TEXT NOT NULL, event_seq BIGINT NOT NULL, event_type TEXT NOT NULL,
    version_no INTEGER NOT NULL, occurred_at TIMESTAMPTZ NOT NULL, activated_at TIMESTAMPTZ NOT NULL,
    effective_from_trade_date DATE NOT NULL,
    CHECK (event_seq > 0), CHECK (event_type IN ('publish','archive','restore')),
    PRIMARY KEY (tenant_id, owner_user_id, id),
    UNIQUE (tenant_id, owner_user_id, rule_id, event_seq),
    FOREIGN KEY (tenant_id, owner_user_id, rule_id, version_no)
        REFERENCES trade_discipline_rule_version
            (tenant_id, owner_user_id, rule_id, version_no) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS trade_discipline_checkin (
    id TEXT, tenant_id TEXT NOT NULL DEFAULT 'default', owner_user_id TEXT NOT NULL DEFAULT 'admin',
    rule_id TEXT NOT NULL, trade_date DATE NOT NULL, current_revision_no INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'submitted', submitted_at TIMESTAMPTZ NOT NULL,
    submission_source TEXT NOT NULL DEFAULT 'workbench',
    amended_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (current_revision_no > 0), CHECK (status IN ('submitted','amended')),
    CONSTRAINT td_checkin_submission_source_check
    CHECK (submission_source IN ('workbench','quick_no_operation')),
    CONSTRAINT td_checkin_status_time_check
    CHECK ((status='submitted' AND amended_at IS NULL)
        OR (status='amended' AND amended_at IS NOT NULL)),
    PRIMARY KEY (tenant_id, owner_user_id, id),
    UNIQUE (tenant_id, owner_user_id, rule_id, trade_date),
    FOREIGN KEY (tenant_id, owner_user_id, rule_id)
        REFERENCES trade_discipline_rule (tenant_id, owner_user_id, id) ON DELETE RESTRICT
);

ALTER TABLE trade_discipline_checkin
    ADD COLUMN IF NOT EXISTS submission_source TEXT NOT NULL DEFAULT 'workbench';
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname='td_checkin_submission_source_check'
) THEN
    ALTER TABLE trade_discipline_checkin ADD CONSTRAINT td_checkin_submission_source_check
        CHECK (submission_source IN ('workbench','quick_no_operation'));
END IF; END $$;

CREATE TABLE IF NOT EXISTS trade_discipline_checkin_revision (
    checkin_id TEXT, tenant_id TEXT NOT NULL DEFAULT 'default', owner_user_id TEXT NOT NULL DEFAULT 'admin',
    revision_no INTEGER, rule_id TEXT NOT NULL, version_no INTEGER NOT NULL,
    revision_kind TEXT NOT NULL, assessment TEXT NOT NULL, no_operation BOOLEAN NOT NULL,
    violation_detail TEXT, review_note TEXT, created_at TIMESTAMPTZ NOT NULL,
    CHECK (revision_no > 0), CHECK (revision_kind IN ('initial','amendment')),
    CONSTRAINT td_revision_kind_no_check
    CHECK ((revision_kind='initial' AND revision_no=1)
        OR (revision_kind='amendment' AND revision_no>1)),
    CHECK (assessment IN ('complied','breached')),
    CHECK ((assessment='breached' AND btrim(coalesce(violation_detail,'')) <> '')
        OR (assessment='complied' AND violation_detail IS NULL)),
    PRIMARY KEY (tenant_id, owner_user_id, checkin_id, revision_no),
    UNIQUE (tenant_id, owner_user_id, checkin_id, revision_no, rule_id, version_no),
    FOREIGN KEY (tenant_id, owner_user_id, checkin_id)
        REFERENCES trade_discipline_checkin (tenant_id, owner_user_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, owner_user_id, rule_id, version_no)
        REFERENCES trade_discipline_rule_version
            (tenant_id, owner_user_id, rule_id, version_no) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS trade_discipline_reason (
    id TEXT, tenant_id TEXT NOT NULL DEFAULT 'default', owner_user_id TEXT NOT NULL DEFAULT 'admin',
    name TEXT NOT NULL, normalized_name TEXT NOT NULL, is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CHECK (btrim(name) <> '' AND btrim(normalized_name) <> ''),
    CHECK ((is_active AND deleted_at IS NULL) OR (NOT is_active AND deleted_at IS NOT NULL)),
    PRIMARY KEY (tenant_id, owner_user_id, id),
    UNIQUE (tenant_id, owner_user_id, normalized_name)
);

CREATE TABLE IF NOT EXISTS trade_discipline_violation (
    checkin_id TEXT, tenant_id TEXT NOT NULL DEFAULT 'default', owner_user_id TEXT NOT NULL DEFAULT 'admin',
    revision_no INTEGER, reason_code TEXT, reason_id TEXT, reason_name_snapshot TEXT NOT NULL,
    CHECK ((reason_code IS NOT NULL AND reason_id IS NULL)
        OR (reason_code IS NULL AND reason_id IS NOT NULL)),
    CHECK (btrim(reason_name_snapshot) <> ''),
    PRIMARY KEY (tenant_id, owner_user_id, checkin_id, revision_no),
    FOREIGN KEY (tenant_id, owner_user_id, checkin_id, revision_no)
        REFERENCES trade_discipline_checkin_revision
            (tenant_id, owner_user_id, checkin_id, revision_no) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, owner_user_id, reason_id)
        REFERENCES trade_discipline_reason (tenant_id, owner_user_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS trade_discipline_operation (
    id TEXT, tenant_id TEXT NOT NULL DEFAULT 'default', owner_user_id TEXT NOT NULL DEFAULT 'admin',
    checkin_id TEXT NOT NULL, revision_no INTEGER NOT NULL, rule_id TEXT NOT NULL,
    version_no INTEGER NOT NULL, stock_code TEXT NOT NULL, stock_name_snapshot TEXT NOT NULL,
    side TEXT NOT NULL, stock_rule_id TEXT NOT NULL, action_rule_id TEXT NOT NULL,
    price NUMERIC(20,4), quantity NUMERIC(20,4), amount NUMERIC(20,2), fee NUMERIC(20,2),
    operated_at TIMESTAMPTZ, note TEXT, display_order INTEGER NOT NULL,
    CHECK (side IN ('buy','sell')),
    CHECK (btrim(stock_code) <> '' AND btrim(stock_name_snapshot) <> ''),
    CHECK (price IS NULL OR price >= 0), CHECK (quantity IS NULL OR quantity >= 0),
    CHECK (amount IS NULL OR amount >= 0), CHECK (fee IS NULL OR fee >= 0),
    CHECK (display_order > 0),
    PRIMARY KEY (tenant_id, owner_user_id, id),
    UNIQUE (tenant_id, owner_user_id, checkin_id, revision_no, display_order),
    FOREIGN KEY (tenant_id, owner_user_id, checkin_id, revision_no, rule_id, version_no)
        REFERENCES trade_discipline_checkin_revision
            (tenant_id, owner_user_id, checkin_id, revision_no, rule_id, version_no) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, owner_user_id, rule_id, version_no, stock_rule_id)
        REFERENCES trade_discipline_stock_rule
            (tenant_id, owner_user_id, rule_id, version_no, detail_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, owner_user_id, rule_id, version_no, action_rule_id, side)
        REFERENCES trade_discipline_action_rule
            (tenant_id, owner_user_id, rule_id, version_no, detail_id, action_type) ON DELETE RESTRICT
);

DO $$ DECLARE item RECORD; BEGIN
    FOR item IN
        SELECT c.conname FROM pg_constraint c
        WHERE c.conrelid='trade_discipline_rule_name_claim'::regclass AND c.contype='u'
          AND (SELECT array_agg(a.attname ORDER BY k.ordinality)
               FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ordinality)
               JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum)
              = ARRAY['tenant_id','owner_user_id','rule_id']::name[]
    LOOP
        EXECUTE format(
            'ALTER TABLE trade_discipline_rule_name_claim DROP CONSTRAINT %I', item.conname
        );
    END LOOP;
END $$;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint
    WHERE conname='td_rule_lifecycle_consistency_check') THEN
    ALTER TABLE trade_discipline_rule ADD CONSTRAINT td_rule_lifecycle_consistency_check
    CHECK ((status='unpublished' AND latest_version_no IS NULL)
        OR (status IN ('active','archived') AND latest_version_no > 0
            AND btrim(coalesce(name,'')) <> '' AND btrim(coalesce(normalized_name,'')) <> ''));
END IF; END $$;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint
    WHERE conname='td_checkin_status_time_check') THEN
    ALTER TABLE trade_discipline_checkin ADD CONSTRAINT td_checkin_status_time_check
    CHECK ((status='submitted' AND amended_at IS NULL)
        OR (status='amended' AND amended_at IS NOT NULL));
END IF; END $$;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint
    WHERE conname='td_revision_kind_no_check') THEN
    ALTER TABLE trade_discipline_checkin_revision ADD CONSTRAINT td_revision_kind_no_check
    CHECK ((revision_kind='initial' AND revision_no=1)
        OR (revision_kind='amendment' AND revision_no>1));
END IF; END $$;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='td_rule_latest_version_fk') THEN
    ALTER TABLE trade_discipline_rule ADD CONSTRAINT td_rule_latest_version_fk
    FOREIGN KEY (tenant_id, owner_user_id, id, latest_version_no)
    REFERENCES trade_discipline_rule_version (tenant_id, owner_user_id, rule_id, version_no)
    ON DELETE RESTRICT;
END IF; END $$;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='td_checkin_current_revision_fk') THEN
    ALTER TABLE trade_discipline_checkin ADD CONSTRAINT td_checkin_current_revision_fk
    FOREIGN KEY (tenant_id, owner_user_id, id, current_revision_no)
    REFERENCES trade_discipline_checkin_revision (tenant_id, owner_user_id, checkin_id, revision_no)
    DEFERRABLE INITIALLY DEFERRED;
END IF; END $$;

CREATE INDEX IF NOT EXISTS idx_td_rule_owner_status
    ON trade_discipline_rule (tenant_id, owner_user_id, status, updated_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_td_activation_effective
    ON trade_discipline_rule_activation
    (tenant_id, owner_user_id, rule_id, effective_from_trade_date DESC, event_seq DESC);
CREATE INDEX IF NOT EXISTS idx_td_checkin_history
    ON trade_discipline_checkin (tenant_id, owner_user_id, trade_date DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_td_revision_detail
    ON trade_discipline_checkin_revision (tenant_id, owner_user_id, checkin_id, revision_no DESC);
CREATE INDEX IF NOT EXISTS idx_td_operation_stock
    ON trade_discipline_operation (tenant_id, owner_user_id, stock_code, checkin_id, revision_no);
CREATE INDEX IF NOT EXISTS idx_td_violation_reason_name
    ON trade_discipline_violation
    (tenant_id, owner_user_id, lower(reason_name_snapshot), checkin_id, revision_no);

-- ========== RBAC 正向迁移（独立 marker + advisory lock）==========
BEGIN;
SELECT pg_advisory_xact_lock(8410010005);

DO $$
DECLARE
    v_marker jsonb;
BEGIN
    SELECT value::jsonb INTO v_marker FROM app_config
    WHERE key='migration.trade_discipline_default_grants_v1';

    IF v_marker IS NOT NULL THEN
        IF v_marker->>'version' <> '1'
           OR (v_marker->>'applied')::boolean IS DISTINCT FROM TRUE
           OR (v_marker->>'rolled_back')::boolean IS DISTINCT FROM FALSE THEN
            IF (v_marker->>'applied')::boolean IS FALSE
               AND (v_marker->>'rolled_back')::boolean IS TRUE THEN
                RETURN; -- tombstone：普通启动永久 no-op
            END IF;
            RAISE EXCEPTION '交易纪律 RBAC marker 非法，已 fail-closed';
        END IF;
        IF v_marker <> '{"version":1,"applied":true,"rolled_back":false,"inserted_menu_ids":["/trade-discipline"],"inserted_resource_ids":["trade-discipline:view","trade-discipline:rule-manage","trade-discipline:checkin-view","trade-discipline:checkin-submit"],"inserted_role_menus":[["system","/trade-discipline"],["tenant_admin","/trade-discipline"],["normal","/trade-discipline"]],"inserted_role_resources":[["system","trade-discipline:view"],["system","trade-discipline:rule-manage"],["system","trade-discipline:checkin-view"],["system","trade-discipline:checkin-submit"],["tenant_admin","trade-discipline:view"],["tenant_admin","trade-discipline:rule-manage"],["tenant_admin","trade-discipline:checkin-view"],["tenant_admin","trade-discipline:checkin-submit"],["normal","trade-discipline:view"],["normal","trade-discipline:rule-manage"],["normal","trade-discipline:checkin-view"],["normal","trade-discipline:checkin-submit"]]}'::jsonb THEN
            RAISE EXCEPTION '交易纪律 RBAC applied marker 账本结构非法';
        END IF;
        -- applied 重启只核验稳定 id/code，不覆盖或冻结运行期菜单与功能点配置。
        IF NOT EXISTS (
            SELECT 1 FROM sys_menu WHERE id='/trade-discipline' AND code='/trade-discipline'
        ) OR EXISTS (
            SELECT 1 FROM (VALUES
                ('trade-discipline:view'),
                ('trade-discipline:rule-manage'),
                ('trade-discipline:checkin-view'),
                ('trade-discipline:checkin-submit')
            ) AS expected(id)
            WHERE NOT EXISTS (
                SELECT 1 FROM sys_resource r WHERE r.id=expected.id
                AND r.code=expected.id
            )
        ) THEN
            RAISE EXCEPTION '交易纪律 RBAC applied 账本与目标行不一致';
        END IF;
        -- 默认角色授权是迁移初始值，管理员后续可撤销；重启不补回也不失败。
        RETURN;
    END IF;

    IF EXISTS (SELECT 1 FROM sys_menu
               WHERE id='/trade-discipline' OR code='/trade-discipline'
                  OR route_path='/trade-discipline') THEN
        RAISE EXCEPTION '交易纪律菜单身份已被占用，拒绝自动收编';
    END IF;
    IF EXISTS (SELECT 1 FROM sys_resource
               WHERE id IN ('trade-discipline:view','trade-discipline:rule-manage',
                            'trade-discipline:checkin-view','trade-discipline:checkin-submit')
                  OR code IN ('trade-discipline:view','trade-discipline:rule-manage',
                              'trade-discipline:checkin-view','trade-discipline:checkin-submit')) THEN
        RAISE EXCEPTION '交易纪律资源身份已被占用，拒绝自动收编';
    END IF;

    INSERT INTO sys_menu
        (id,parent_id,code,title,type,route_path,icon,sort,visible,is_builtin)
    VALUES ('/trade-discipline',NULL,'/trade-discipline','交易纪律','leaf',
            '/trade-discipline','Checked',50,'login',TRUE);

    INSERT INTO sys_resource
        (id,menu_id,code,name,type,api_method,api_path,sort,is_builtin)
    VALUES
        ('trade-discipline:view','/trade-discipline','trade-discipline:view',
         '查看交易纪律','api','GET','/api/trade-discipline/summary',10,TRUE),
        ('trade-discipline:rule-manage','/trade-discipline','trade-discipline:rule-manage',
         '维护交易规则','api','POST','/api/trade-discipline/rules',20,TRUE),
        ('trade-discipline:checkin-view','/trade-discipline','trade-discipline:checkin-view',
         '查看履约记录','api','GET','/api/trade-discipline/checkins',30,TRUE),
        ('trade-discipline:checkin-submit','/trade-discipline','trade-discipline:checkin-submit',
         '提交履约记录','api','POST','/api/trade-discipline/checkins',40,TRUE);

    INSERT INTO sys_role_menu (role_id,menu_id)
    SELECT role_id,'/trade-discipline' FROM (VALUES ('system'),('tenant_admin'),('normal')) r(role_id);
    INSERT INTO sys_role_resource (role_id,resource_id)
    SELECT r.role_id,p.resource_id
    FROM (VALUES ('system'),('tenant_admin'),('normal')) r(role_id)
    CROSS JOIN (VALUES
        ('trade-discipline:view'),('trade-discipline:rule-manage'),
        ('trade-discipline:checkin-view'),('trade-discipline:checkin-submit')
    ) p(resource_id);

    UPDATE sys_user u SET perm_ver=perm_ver+1
    WHERE u.role_code='system' OR EXISTS (
        SELECT 1 FROM sys_user_role ur WHERE ur.user_id=u.id
        AND ur.role_id IN ('system','tenant_admin','normal')
    );

    INSERT INTO app_config(key,value,updated_at) VALUES (
        'migration.trade_discipline_default_grants_v1',
        '{"version":1,"applied":true,"rolled_back":false,"inserted_menu_ids":["/trade-discipline"],"inserted_resource_ids":["trade-discipline:view","trade-discipline:rule-manage","trade-discipline:checkin-view","trade-discipline:checkin-submit"],"inserted_role_menus":[["system","/trade-discipline"],["tenant_admin","/trade-discipline"],["normal","/trade-discipline"]],"inserted_role_resources":[["system","trade-discipline:view"],["system","trade-discipline:rule-manage"],["system","trade-discipline:checkin-view"],["system","trade-discipline:checkin-submit"],["tenant_admin","trade-discipline:view"],["tenant_admin","trade-discipline:rule-manage"],["tenant_admin","trade-discipline:checkin-view"],["tenant_admin","trade-discipline:checkin-submit"],["normal","trade-discipline:view"],["normal","trade-discipline:rule-manage"],["normal","trade-discipline:checkin-view"],["normal","trade-discipline:checkin-submit"]]}',
        now()
    );
END $$;

COMMIT;

-- ========== 确定性 RBAC 回滚（默认注释；优先使用受控 CLI）==========
-- 推荐命令：
-- python -m backend.cli trade-discipline-rbac rollback \
--   --confirm-marker migration.trade_discipline_default_grants_v1
--
-- 如 CLI 不可用，人工执行下方注释段。必须保留原账本 tombstone；marker 缺失、损坏或不是 applied
-- 时必须停止。删除顺序固定为角色资源 → 角色菜单 → 资源 → 菜单；业务表和用户事实不删除。
--
-- BEGIN;
-- SELECT pg_advisory_xact_lock(8410010005);
-- DO $$
-- DECLARE
--     v_marker jsonb;
-- BEGIN
--     SELECT value::jsonb INTO v_marker FROM app_config
--     WHERE key='migration.trade_discipline_default_grants_v1' FOR UPDATE;
--     IF v_marker IS NULL THEN
--         RAISE EXCEPTION 'marker 不存在，拒绝破坏性回滚';
--     END IF;
--     IF (v_marker->>'applied')::boolean IS FALSE
--        AND (v_marker->>'rolled_back')::boolean IS TRUE THEN
--         RETURN;
--     END IF;
--     IF v_marker->>'version' <> '1'
--        OR (v_marker->>'applied')::boolean IS DISTINCT FROM TRUE
--        OR (v_marker->>'rolled_back')::boolean IS DISTINCT FROM FALSE THEN
--         RAISE EXCEPTION 'marker 非法，拒绝破坏性回滚';
--     END IF;
--     IF v_marker <> '{"version":1,"applied":true,"rolled_back":false,"inserted_menu_ids":["/trade-discipline"],"inserted_resource_ids":["trade-discipline:view","trade-discipline:rule-manage","trade-discipline:checkin-view","trade-discipline:checkin-submit"],"inserted_role_menus":[["system","/trade-discipline"],["tenant_admin","/trade-discipline"],["normal","/trade-discipline"]],"inserted_role_resources":[["system","trade-discipline:view"],["system","trade-discipline:rule-manage"],["system","trade-discipline:checkin-view"],["system","trade-discipline:checkin-submit"],["tenant_admin","trade-discipline:view"],["tenant_admin","trade-discipline:rule-manage"],["tenant_admin","trade-discipline:checkin-view"],["tenant_admin","trade-discipline:checkin-submit"],["normal","trade-discipline:view"],["normal","trade-discipline:rule-manage"],["normal","trade-discipline:checkin-view"],["normal","trade-discipline:checkin-submit"]]}'::jsonb THEN
--         RAISE EXCEPTION 'marker 账本结构非法，拒绝破坏性回滚';
--     END IF;
--     -- 默认授权允许管理员已撤销；只拒绝账本外角色，当前仍存在的账本内同键行会被删除。
--     IF EXISTS (SELECT 1 FROM sys_role_menu WHERE menu_id='/trade-discipline'
--                   AND role_id NOT IN ('system','tenant_admin','normal'))
--        OR EXISTS (SELECT 1 FROM sys_role_resource WHERE resource_id IN (
--              'trade-discipline:view','trade-discipline:rule-manage',
--              'trade-discipline:checkin-view','trade-discipline:checkin-submit')
--              AND role_id NOT IN ('system','tenant_admin','normal')) THEN
--         RAISE EXCEPTION '存在迁移账本外授权，拒绝级联回滚';
--     END IF;
--
--     DELETE FROM sys_role_resource rr USING (
--         SELECT x->>0 AS role_id,x->>1 AS resource_id
--         FROM jsonb_array_elements(v_marker->'inserted_role_resources') x
--     ) ledger WHERE rr.role_id=ledger.role_id AND rr.resource_id=ledger.resource_id;
--     DELETE FROM sys_role_menu rm USING (
--         SELECT x->>0 AS role_id,x->>1 AS menu_id
--         FROM jsonb_array_elements(v_marker->'inserted_role_menus') x
--     ) ledger WHERE rm.role_id=ledger.role_id AND rm.menu_id=ledger.menu_id;
--     DELETE FROM sys_resource r USING jsonb_array_elements_text(
--         v_marker->'inserted_resource_ids') rid WHERE r.id=rid;
--     DELETE FROM sys_menu m USING jsonb_array_elements_text(
--         v_marker->'inserted_menu_ids') mid WHERE m.id=mid;
--
--     UPDATE sys_user u SET perm_ver=perm_ver+1
--     WHERE u.role_code='system' OR EXISTS (
--         SELECT 1 FROM sys_user_role ur WHERE ur.user_id=u.id
--         AND ur.role_id IN ('system','tenant_admin','normal')
--     );
--     UPDATE app_config SET value=(v_marker || '{"applied":false,"rolled_back":true}'::jsonb)::text,
--         updated_at=now() WHERE key='migration.trade_discipline_default_grants_v1';
-- END $$;
-- COMMIT;

-- 仅确认所有 trade_discipline_* 表均无业务事实后，才允许按以下逆序删除；默认禁止执行：
-- DROP TABLE trade_discipline_operation, trade_discipline_violation,
--   trade_discipline_reason, trade_discipline_checkin_revision, trade_discipline_checkin,
--   trade_discipline_rule_activation, trade_discipline_draft_action_rule,
--   trade_discipline_draft_stock_rule, trade_discipline_rule_draft,
--   trade_discipline_action_rule, trade_discipline_stock_rule,
--   trade_discipline_rule_version, trade_discipline_rule_name_claim,
--   trade_discipline_rule CASCADE;
