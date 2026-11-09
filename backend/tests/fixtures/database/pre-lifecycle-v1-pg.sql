-- 冻结兼容基线 pre-lifecycle-v1；仅用于门禁随机数据库，禁止执行于业务库。
-- 基于接入统一生命周期前的完整结构，保留已支持补列的旧形态；未来新增字段须有升级路径。
-- 本文件不随 database gate --refresh-contract 更新，禁止以新装结构覆盖历史基线。
--
-- PostgreSQL database dump
--



SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', 'public', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--



--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS 'standard public schema';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: app_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.app_config (
    key text NOT NULL,
    value text,
    updated_at timestamp without time zone
);


--
-- Name: async_task; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.async_task (
    id text NOT NULL,
    task_type text NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    status text NOT NULL,
    progress double precision DEFAULT 0 NOT NULL,
    message text,
    result jsonb,
    trigger_source text,
    job_id text,
    job_name text,
    chain_id text,
    parent_task_id text,
    trigger_event_id text,
    retry_count integer DEFAULT 0 NOT NULL,
    execution_attempt integer DEFAULT 1 NOT NULL,
    cancel_requested_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT async_task_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'done'::text, 'failed'::text, 'interrupted'::text])))
);


--
-- Name: audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_log (
    id text NOT NULL,
    event_time timestamp with time zone DEFAULT now() NOT NULL,
    tenant_id text,
    actor_user_id text,
    actor_account text,
    event_category text NOT NULL,
    event_type text NOT NULL,
    resource_code text,
    action text,
    target_type text,
    target_id text,
    target_label text,
    result text NOT NULL,
    status text NOT NULL,
    ip text,
    method text,
    path text,
    duration_ms integer,
    error_summary text,
    context jsonb DEFAULT '{}'::jsonb NOT NULL,
    changes jsonb DEFAULT '[]'::jsonb NOT NULL,
    source_event_key text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: backtest_equity; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backtest_equity (
    run_id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    trade_date date NOT NULL,
    equity double precision,
    cash double precision,
    position_value double precision,
    n_positions integer,
    drawdown double precision,
    benchmark_equity double precision
);


--
-- Name: backtest_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backtest_metrics (
    run_id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    total_return double precision,
    annual_return double precision,
    max_drawdown double precision,
    max_dd_days integer,
    annual_vol double precision,
    sharpe double precision,
    calmar double precision,
    sortino double precision,
    win_rate double precision,
    profit_factor double precision,
    avg_hold_days double precision,
    n_trades integer,
    benchmark_return double precision,
    excess_return double precision,
    hit_rate_by_grade text,
    extra text
);


--
-- Name: backtest_run; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backtest_run (
    id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    kind text,
    profile_id text,
    model_id text,
    score_profile_id text,
    trade_profile_id text,
    score_profile_version integer,
    profile_version integer,
    trade_profile_version integer,
    signature text,
    date_start date,
    date_end date,
    params text,
    status text,
    detail text,
    visibility text DEFAULT 'private'::text NOT NULL,
    published_at timestamp without time zone,
    published_by text,
    created_at timestamp without time zone,
    finished_at timestamp without time zone,
    CONSTRAINT backtest_run_publish_consistency_check CHECK ((((visibility = 'private'::text) AND (published_at IS NULL) AND (published_by IS NULL)) OR (visibility = ANY (ARRAY['tenant'::text, 'public'::text])))),
    CONSTRAINT backtest_run_visibility_check CHECK ((visibility = ANY (ARRAY['private'::text, 'tenant'::text, 'public'::text])))
);


--
-- Name: backtest_trade; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backtest_trade (
    run_id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    seq integer NOT NULL,
    code text,
    entry_date date,
    entry_price double precision,
    exit_date date,
    exit_price double precision,
    exit_reason text,
    exit_detail text,
    shares bigint,
    return_pct double precision,
    pnl double precision,
    hold_days integer,
    grade text,
    entry_score double precision,
    entry_rank integer,
    entry_pick_rank integer,
    entry_pool integer
);


--
-- Name: board_watchlist; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.board_watchlist (
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    board_code text NOT NULL,
    board_name text NOT NULL,
    board_type text NOT NULL,
    added_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: data_source_health; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_source_health (
    source text NOT NULL,
    is_up boolean NOT NULL,
    last_test_at timestamp with time zone NOT NULL,
    last_success_at timestamp with time zone,
    failure_reason text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: dict_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dict_item (
    id text NOT NULL,
    type_code text NOT NULL,
    code text NOT NULL,
    label text NOT NULL,
    color text,
    enabled boolean DEFAULT true NOT NULL,
    sort integer DEFAULT 100 NOT NULL,
    remark text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: dict_type; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dict_type (
    id text NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    sort integer DEFAULT 100 NOT NULL,
    remark text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: layout_field_policy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.layout_field_policy (
    component_kind text NOT NULL,
    field text NOT NULL,
    allowed_layers text,
    updated_at timestamp without time zone
);


--
-- Name: layout_page_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.layout_page_config (
    page_key text NOT NULL,
    preset_key text,
    config text,
    schema_version integer,
    updated_at timestamp without time zone
);


--
-- Name: layout_preset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.layout_preset (
    key text NOT NULL,
    name text,
    description text,
    config text,
    enabled boolean,
    is_builtin boolean,
    schema_version integer,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: layout_user_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.layout_user_config (
    user_id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    page_key text NOT NULL,
    config text,
    schema_version integer,
    updated_at timestamp without time zone
);


--
-- Name: limit_ladder_audit_outbox; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.limit_ladder_audit_outbox (
    command_id text NOT NULL,
    event_type text NOT NULL,
    source_event_key text NOT NULL,
    payload jsonb NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    retry_count integer DEFAULT 0 NOT NULL,
    next_retry_at timestamp with time zone,
    last_error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    delivered_at timestamp with time zone,
    CONSTRAINT limit_ladder_audit_outbox_event_type_check CHECK ((event_type = ANY (ARRAY['requested'::text, 'running'::text, 'succeeded'::text, 'failed'::text, 'interrupted'::text]))),
    CONSTRAINT limit_ladder_audit_outbox_retry_count_check CHECK ((retry_count >= 0)),
    CONSTRAINT limit_ladder_audit_outbox_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'delivered'::text])))
);


--
-- Name: limit_ladder_task_ledger; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.limit_ladder_task_ledger (
    command_id text NOT NULL,
    task_id text,
    trade_date date NOT NULL,
    source text NOT NULL,
    actor_kind text NOT NULL,
    tenant_id text,
    actor_user_id text,
    actor_account text NOT NULL,
    trigger_tenant_id text,
    trigger_user_id text,
    trigger_account text,
    request_ip text,
    request_method text,
    request_path text,
    request_id text,
    status text NOT NULL,
    rule_version text NOT NULL,
    result_summary jsonb,
    retry_count integer DEFAULT 0 NOT NULL,
    last_error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT limit_ladder_task_ledger_actor_kind_check CHECK ((actor_kind = ANY (ARRAY['system'::text, 'user'::text]))),
    CONSTRAINT limit_ladder_task_ledger_check CHECK ((((actor_kind = 'system'::text) AND (tenant_id IS NULL) AND (actor_user_id IS NULL) AND (actor_account = 'system:limit-ladder'::text)) OR ((actor_kind = 'user'::text) AND (tenant_id IS NOT NULL) AND (actor_user_id IS NOT NULL)))),
    CONSTRAINT limit_ladder_task_ledger_retry_count_check CHECK ((retry_count >= 0)),
    CONSTRAINT limit_ladder_task_ledger_source_check CHECK ((source = ANY (ARRAY['auto_first_load'::text, 'auto_invalid_refresh'::text, 'admin_recompute'::text]))),
    CONSTRAINT limit_ladder_task_ledger_status_check CHECK ((status = ANY (ARRAY['requested'::text, 'running'::text, 'succeeded'::text, 'failed'::text, 'interrupted'::text])))
);


--
-- Name: scheduled_job; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scheduled_job (
    id text NOT NULL,
    name text NOT NULL,
    task_type text NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    freq_type text,
    freq_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    trigger_mode text DEFAULT 'time'::text NOT NULL,
    dependency_job_id text,
    dependency_order integer,
    dependency_condition text,
    dependency_delay jsonb DEFAULT '{"unit": "minute", "value": 0}'::jsonb NOT NULL,
    retry_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    trading_day_only boolean DEFAULT false NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    last_run_at timestamp with time zone,
    last_task_id text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT scheduled_job_trigger_mode_check CHECK ((trigger_mode = ANY (ARRAY['time'::text, 'dependency'::text])))
);


--
-- Name: scheduled_job_dependency; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scheduled_job_dependency (
    upstream_job_id text NOT NULL,
    downstream_job_id text NOT NULL,
    dependency_order integer NOT NULL
);


--
-- Name: scheduled_trigger_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scheduled_trigger_event (
    id text NOT NULL,
    chain_id text,
    source_task_id text NOT NULL,
    source_attempt integer DEFAULT 1 NOT NULL,
    source_status text NOT NULL,
    target_job_id text NOT NULL,
    trigger_kind text NOT NULL,
    trigger_condition text,
    retry_count integer DEFAULT 0 NOT NULL,
    dispatch_order integer DEFAULT 0 NOT NULL,
    due_at timestamp with time zone NOT NULL,
    dispatched_at timestamp with time zone,
    status text NOT NULL,
    task_id text,
    job_snapshot jsonb DEFAULT '{}'::jsonb NOT NULL,
    message text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT scheduled_trigger_event_status_check CHECK ((status = ANY (ARRAY['waiting'::text, 'dispatching'::text, 'dispatched'::text, 'cancelled'::text, 'exhausted'::text, 'failed'::text]))),
    CONSTRAINT scheduled_trigger_event_trigger_kind_check CHECK ((trigger_kind = ANY (ARRAY['dependency'::text, 'retry'::text])))
);


--
-- Name: score_profile; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.score_profile (
    id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    name text,
    version integer,
    items text,
    grade_thresholds text,
    include_st boolean DEFAULT true NOT NULL,
    is_preset boolean,
    visibility text DEFAULT 'private'::text NOT NULL,
    published_at timestamp without time zone,
    published_by text,
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    CONSTRAINT score_profile_publish_consistency_check CHECK ((((visibility = 'private'::text) AND (published_at IS NULL) AND (published_by IS NULL)) OR (visibility = ANY (ARRAY['tenant'::text, 'public'::text])))),
    CONSTRAINT score_profile_visibility_check CHECK ((visibility = ANY (ARRAY['private'::text, 'tenant'::text, 'public'::text])))
);


--
-- Name: score_profile_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.score_profile_version (
    id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    version integer NOT NULL,
    name text,
    items text,
    grade_thresholds text,
    include_st boolean DEFAULT true NOT NULL,
    saved_at timestamp without time zone
);


--
-- Name: score_result; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.score_result (
    trade_date date NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    model_id text NOT NULL,
    code text NOT NULL,
    total_score double precision,
    sub_scores text,
    rank integer,
    grade text,
    buy_point text,
    risk_flags text
);


--
-- Name: score_snapshot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.score_snapshot (
    trade_date date NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    profile_id text NOT NULL,
    profile_version integer NOT NULL,
    code text NOT NULL,
    total_score double precision,
    grade text,
    rank integer,
    sub_scores text
);


--
-- Name: score_snapshot_meta; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.score_snapshot_meta (
    trade_date date NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    profile_id text NOT NULL,
    profile_version integer NOT NULL,
    computed_at timestamp without time zone,
    stale boolean,
    n_codes integer
);


--
-- Name: screen_profile; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screen_profile (
    id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    name text,
    version integer,
    expression text,
    params text,
    is_preset boolean,
    visibility text DEFAULT 'private'::text NOT NULL,
    published_at timestamp without time zone,
    published_by text,
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    CONSTRAINT screen_profile_publish_consistency_check CHECK ((((visibility = 'private'::text) AND (published_at IS NULL) AND (published_by IS NULL)) OR (visibility = ANY (ARRAY['tenant'::text, 'public'::text])))),
    CONSTRAINT screen_profile_visibility_check CHECK ((visibility = ANY (ARRAY['private'::text, 'tenant'::text, 'public'::text])))
);


--
-- Name: screen_profile_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screen_profile_version (
    id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    version integer NOT NULL,
    name text,
    expression text,
    saved_at timestamp without time zone
);


--
-- Name: screen_result; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screen_result (
    run_date date NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    profile_id text NOT NULL,
    code text NOT NULL,
    hit boolean,
    matched text,
    snapshot text
);


--
-- Name: stock_group; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stock_group (
    id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    name text,
    group_date date,
    description text,
    color text,
    is_default boolean,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: stock_group_member; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stock_group_member (
    group_id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    code text NOT NULL,
    add_date date,
    note text
);


--
-- Name: storage_migration; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.storage_migration (
    marker text NOT NULL,
    state text NOT NULL,
    details jsonb DEFAULT '{}'::jsonb NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT storage_migration_state_check CHECK ((state = ANY (ARRAY['applied'::text, 'rolled_back'::text])))
);


--
-- Name: sys_menu; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sys_menu (
    id text NOT NULL,
    parent_id text,
    code text NOT NULL,
    title text NOT NULL,
    type text DEFAULT 'leaf'::text NOT NULL,
    route_path text,
    icon text,
    sort integer DEFAULT 0 NOT NULL,
    visible text DEFAULT 'login'::text NOT NULL,
    is_builtin boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone
);


--
-- Name: sys_resource; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sys_resource (
    id text NOT NULL,
    menu_id text NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    type text DEFAULT 'api'::text NOT NULL,
    api_method text,
    api_path text,
    sort integer DEFAULT 0 NOT NULL,
    is_builtin boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone
);


--
-- Name: sys_role; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sys_role (
    id text NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    kind text DEFAULT 'custom'::text NOT NULL,
    is_builtin boolean DEFAULT false NOT NULL,
    is_locked boolean DEFAULT false NOT NULL,
    description text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone
);


--
-- Name: sys_role_menu; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sys_role_menu (
    role_id text NOT NULL,
    menu_id text NOT NULL
);


--
-- Name: sys_role_resource; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sys_role_resource (
    role_id text NOT NULL,
    resource_id text NOT NULL
);


--
-- Name: sys_tenant; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sys_tenant (
    id text NOT NULL,
    name text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    admin_user_id text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    deleted_at timestamp without time zone
);


--
-- Name: sys_user; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sys_user (
    id text NOT NULL,
    tenant_id text NOT NULL,
    account text NOT NULL,
    email text,
    password_hash text,
    role_code text DEFAULT 'normal'::text NOT NULL,
    perm_ver integer DEFAULT 0 NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    last_login_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    deleted_at timestamp without time zone
);


--
-- Name: sys_user_role; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sys_user_role (
    user_id text NOT NULL,
    role_id text NOT NULL,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: task_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_log (
    id bigint NOT NULL,
    task_id text NOT NULL,
    seq integer NOT NULL,
    ts timestamp with time zone NOT NULL,
    level text NOT NULL,
    message text NOT NULL,
    CONSTRAINT task_log_level_check CHECK ((level = ANY (ARRAY['info'::text, 'warn'::text, 'warning'::text, 'error'::text])))
);


--
-- Name: task_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.task_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: task_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.task_log_id_seq OWNED BY public.task_log.id;


--
-- Name: trade_discipline_account; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_discipline_account (
    tenant_id text NOT NULL,
    owner_user_id text NOT NULL,
    id text DEFAULT 'default'::text NOT NULL,
    initialized_on date,
    opening_positions jsonb DEFAULT '[]'::jsonb NOT NULL,
    opening_cash numeric(20,2),
    revision integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT trade_discipline_account_opening_cash_check CHECK (((opening_cash IS NULL) OR (opening_cash >= (0)::numeric))),
    CONSTRAINT trade_discipline_account_opening_positions_check CHECK ((jsonb_typeof(opening_positions) = 'array'::text)),
    CONSTRAINT trade_discipline_account_revision_check CHECK ((revision >= 0))
);


--
-- Name: TABLE trade_discipline_account; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.trade_discipline_account IS '私人交易账户及真实期初持仓；不从规则预算伪造现金';


--
-- Name: COLUMN trade_discipline_account.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_account.id IS '账户标识，初期使用 default 默认账户';


--
-- Name: COLUMN trade_discipline_account.initialized_on; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_account.initialized_on IS '账本起算交易日，空表示尚未初始化';


--
-- Name: COLUMN trade_discipline_account.opening_positions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_account.opening_positions IS '期初持仓：股票、股数、总成本及规则分组；金额用十进制字符串';


--
-- Name: COLUMN trade_discipline_account.opening_cash; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_account.opening_cash IS '期初现金，空表示未采集，不等同于零';


--
-- Name: COLUMN trade_discipline_account.revision; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_account.revision IS '账户乐观修订号，初始化及每次记账后递增';


--
-- Name: trade_discipline_action_rule; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_discipline_action_rule (
    rule_id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    version_no integer NOT NULL,
    detail_id text NOT NULL,
    name text NOT NULL,
    action_type text NOT NULL,
    action_subtype text NOT NULL,
    action_subtype_label text,
    content text NOT NULL,
    display_order integer NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    CONSTRAINT td_action_subtype_nonblank_check CHECK ((btrim(action_subtype) <> ''::text)),
    CONSTRAINT td_action_type_check CHECK ((action_type = ANY (ARRAY['buy'::text, 'sell'::text]))),
    CONSTRAINT trade_discipline_action_rule_check CHECK (((btrim(name) <> ''::text) AND (btrim(content) <> ''::text))),
    CONSTRAINT trade_discipline_action_rule_display_order_check CHECK ((display_order > 0))
);


--
-- Name: COLUMN trade_discipline_action_rule.action_subtype_label; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_action_rule.action_subtype_label IS '发布版本的买卖类型名称快照；旧版本为空时按旧编码兼容展示，不跟随字典改名';


--
-- Name: trade_discipline_action_subtype; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_discipline_action_subtype (
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    normalized_name text NOT NULL,
    name text NOT NULL,
    action_type text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT trade_discipline_action_subtype_action_type_check CHECK ((action_type = ANY (ARRAY['buy'::text, 'sell'::text]))),
    CONSTRAINT trade_discipline_action_subtype_name_check CHECK ((btrim(name) <> ''::text))
);


--
-- Name: trade_discipline_checkin; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_discipline_checkin (
    id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    rule_id text NOT NULL,
    trade_date date NOT NULL,
    current_revision_no integer NOT NULL,
    status text DEFAULT 'submitted'::text NOT NULL,
    submission_source text DEFAULT 'workbench'::text NOT NULL,
    submitted_at timestamp with time zone NOT NULL,
    amended_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT td_checkin_status_time_check CHECK ((((status = 'submitted'::text) AND (amended_at IS NULL)) OR ((status = 'amended'::text) AND (amended_at IS NOT NULL)))),
    CONSTRAINT td_checkin_submission_source_check CHECK ((submission_source = ANY (ARRAY['workbench'::text, 'quick_no_operation'::text]))),
    CONSTRAINT trade_discipline_checkin_current_revision_no_check CHECK ((current_revision_no > 0)),
    CONSTRAINT trade_discipline_checkin_status_check CHECK ((status = ANY (ARRAY['submitted'::text, 'amended'::text])))
);


--
-- Name: trade_discipline_checkin_revision; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_discipline_checkin_revision (
    checkin_id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    revision_no integer NOT NULL,
    rule_id text NOT NULL,
    version_no integer NOT NULL,
    revision_kind text NOT NULL,
    assessment text NOT NULL,
    no_operation boolean NOT NULL,
    violation_detail text,
    review_note text,
    created_at timestamp with time zone NOT NULL,
    violation_items jsonb,
    peak_positions integer,
    CONSTRAINT td_revision_assessment_check CHECK ((assessment = ANY (ARRAY['complied'::text, 'partial'::text, 'breached'::text]))),
    CONSTRAINT td_revision_kind_no_check CHECK ((((revision_kind = 'initial'::text) AND (revision_no = 1)) OR ((revision_kind = 'amendment'::text) AND (revision_no > 1)))),
    CONSTRAINT td_revision_violation_detail_check CHECK ((((assessment = ANY (ARRAY['partial'::text, 'breached'::text])) AND (btrim(COALESCE(violation_detail, ''::text)) <> ''::text)) OR ((assessment = 'complied'::text) AND (violation_detail IS NULL)))),
    CONSTRAINT td_revision_violation_items_check CHECK (((jsonb_typeof(violation_items) = 'array'::text) AND (violation_items <@ '["missed_buy", "missed_sell", "other"]'::jsonb) AND (jsonb_array_length(violation_items) <= 3))),
    CONSTRAINT trade_discipline_checkin_revision_peak_positions_check CHECK ((peak_positions >= 0)),
    CONSTRAINT trade_discipline_checkin_revision_revision_kind_check CHECK ((revision_kind = ANY (ARRAY['initial'::text, 'amendment'::text]))),
    CONSTRAINT trade_discipline_checkin_revision_revision_no_check CHECK ((revision_no > 0))
);


--
-- Name: COLUMN trade_discipline_checkin_revision.violation_items; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_checkin_revision.violation_items IS '未履约事项多选：missed_buy应买未买、missed_sell应卖未卖、other买卖操作未履约；NULL为旧记录未采集，空数组为未填事项，不计入成交';


--
-- Name: COLUMN trade_discipline_checkin_revision.peak_positions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_checkin_revision.peak_positions IS '用户确认的当日最大同时持仓股票数，含之前持仓；空表示旧记录未采集';


--
-- Name: trade_discipline_draft_action_rule; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_discipline_draft_action_rule (
    rule_id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    detail_id text NOT NULL,
    name text,
    action_type text,
    action_subtype text,
    action_subtype_label text,
    content text,
    display_order integer NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    CONSTRAINT td_draft_action_subtype_nonblank_check CHECK (((action_subtype IS NULL) OR (btrim(action_subtype) <> ''::text))),
    CONSTRAINT trade_discipline_draft_action_rule_action_type_check CHECK (((action_type IS NULL) OR (action_type = ANY (ARRAY['buy'::text, 'sell'::text])))),
    CONSTRAINT trade_discipline_draft_action_rule_display_order_check CHECK ((display_order > 0))
);


--
-- Name: COLUMN trade_discipline_draft_action_rule.action_subtype_label; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_draft_action_rule.action_subtype_label IS '草稿的买卖类型名称快照，由服务端从字典或原明细生成，禁止信任客户端标签';


--
-- Name: trade_discipline_draft_stock_rule; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_discipline_draft_stock_rule (
    rule_id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    detail_id text NOT NULL,
    name text,
    max_capital numeric(20,2),
    content text,
    checklist_items jsonb DEFAULT '[]'::jsonb NOT NULL,
    display_order integer NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    price_min numeric(20,4),
    price_max numeric(20,4),
    st_filter text DEFAULT 'any'::text NOT NULL,
    loss_filter text DEFAULT 'any'::text NOT NULL,
    st_risk_filter text DEFAULT 'any'::text NOT NULL,
    CONSTRAINT trade_discipline_draft_stock_rule_checklist_items_check CHECK ((jsonb_typeof(checklist_items) = 'array'::text)),
    CONSTRAINT trade_discipline_draft_stock_rule_display_order_check CHECK ((display_order > 0)),
    CONSTRAINT trade_discipline_draft_stock_rule_loss_filter_check CHECK ((loss_filter = ANY (ARRAY['any'::text, 'exclude'::text, 'only'::text]))),
    CONSTRAINT trade_discipline_draft_stock_rule_max_capital_check CHECK (((max_capital IS NULL) OR (max_capital >= (0)::numeric))),
    CONSTRAINT trade_discipline_draft_stock_rule_price_bounds CHECK (((price_min IS NULL) OR (price_max IS NULL) OR (price_min <= price_max))),
    CONSTRAINT trade_discipline_draft_stock_rule_price_max_check CHECK ((price_max > (0)::numeric)),
    CONSTRAINT trade_discipline_draft_stock_rule_price_min_check CHECK ((price_min > (0)::numeric)),
    CONSTRAINT trade_discipline_draft_stock_rule_st_filter_check CHECK ((st_filter = ANY (ARRAY['any'::text, 'exclude'::text, 'only'::text]))),
    CONSTRAINT trade_discipline_draft_stock_rule_st_risk_filter_check CHECK ((st_risk_filter = ANY (ARRAY['any'::text, 'exclude'::text, 'only'::text])))
);


--
-- Name: COLUMN trade_discipline_draft_stock_rule.content; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_draft_stock_rule.content IS '草稿选股规则补充说明，保留原文换行';


--
-- Name: COLUMN trade_discipline_draft_stock_rule.checklist_items; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_draft_stock_rule.checklist_items IS '草稿人工检查项，与正式版本同结构；发布前允许空正文，旧文本不自动拆分';


--
-- Name: COLUMN trade_discipline_draft_stock_rule.price_min; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_draft_stock_rule.price_min IS '买入成交价下限（元、原始价、含边界），空表示不限';


--
-- Name: COLUMN trade_discipline_draft_stock_rule.price_max; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_draft_stock_rule.price_max IS '买入成交价上限（元、原始价、含边界），空表示不限';


--
-- Name: COLUMN trade_discipline_draft_stock_rule.st_filter; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_draft_stock_rule.st_filter IS '买入时ST条件：any不限、exclude排除、only仅限';


--
-- Name: COLUMN trade_discipline_draft_stock_rule.loss_filter; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_draft_stock_rule.loss_filter IS '买入时亏损条件：any不限、exclude排除、only仅限；事实由用户确认';


--
-- Name: COLUMN trade_discipline_draft_stock_rule.st_risk_filter; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_draft_stock_rule.st_risk_filter IS '买入时ST风险条件：any不限、exclude排除、only仅限；事实由用户确认';


--
-- Name: trade_discipline_ledger_day; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_discipline_ledger_day (
    tenant_id text NOT NULL,
    owner_user_id text NOT NULL,
    account_id text NOT NULL,
    trade_date date NOT NULL,
    current_revision_no integer NOT NULL,
    withdrawn boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT trade_discipline_ledger_day_current_revision_no_check CHECK ((current_revision_no > 0))
);


--
-- Name: TABLE trade_discipline_ledger_day; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.trade_discipline_ledger_day IS '账户交易日日结身份与有效修订指针，撤回保留追溯';


--
-- Name: COLUMN trade_discipline_ledger_day.account_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_ledger_day.account_id IS '同一归属下的交易账户标识';


--
-- Name: COLUMN trade_discipline_ledger_day.current_revision_no; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_ledger_day.current_revision_no IS '唯一参与持仓与统计的日结修订号';


--
-- Name: COLUMN trade_discipline_ledger_day.withdrawn; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_ledger_day.withdrawn IS '是否已撤回，撤回日不参与持仓与统计';


--
-- Name: trade_discipline_ledger_revision; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_discipline_ledger_revision (
    tenant_id text NOT NULL,
    owner_user_id text NOT NULL,
    account_id text NOT NULL,
    trade_date date NOT NULL,
    revision_no integer NOT NULL,
    request_id text NOT NULL,
    payload_hash text NOT NULL,
    snapshot jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT trade_discipline_ledger_revision_revision_no_check CHECK ((revision_no > 0)),
    CONSTRAINT trade_discipline_ledger_revision_snapshot_check CHECK ((jsonb_typeof(snapshot) = 'object'::text))
);


--
-- Name: TABLE trade_discipline_ledger_revision; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.trade_discipline_ledger_revision IS '不可变日结事实，含稳定成交身份、规则快照、评价依据和计算版本';


--
-- Name: COLUMN trade_discipline_ledger_revision.account_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_ledger_revision.account_id IS '同一归属下的交易账户标识';


--
-- Name: COLUMN trade_discipline_ledger_revision.revision_no; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_ledger_revision.revision_no IS '当日日结修订号';


--
-- Name: COLUMN trade_discipline_ledger_revision.request_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_ledger_revision.request_id IS '幂等请求标识，同账户不可跨日期复用';


--
-- Name: COLUMN trade_discipline_ledger_revision.payload_hash; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_ledger_revision.payload_hash IS '请求内容摘要，防止同幂等键覆盖不同内容';


--
-- Name: COLUMN trade_discipline_ledger_revision.snapshot; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_ledger_revision.snapshot IS '有序成交及调整、持仓、资金、规则版本、遗漏及计算结果；confirmed_rule_ids为已确认规则，evaluations.confirmed区分待打卡，缺失沿用旧整日确认口径';


--
-- Name: trade_discipline_operation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_discipline_operation (
    id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    checkin_id text NOT NULL,
    revision_no integer NOT NULL,
    rule_id text NOT NULL,
    version_no integer NOT NULL,
    stock_code text NOT NULL,
    stock_name_snapshot text NOT NULL,
    side text NOT NULL,
    stock_rule_id text NOT NULL,
    action_rule_id text NOT NULL,
    price numeric(20,4),
    quantity numeric(20,4),
    amount numeric(20,2),
    fee numeric(20,2),
    operated_at timestamp with time zone,
    note text,
    compliance_status text,
    display_order integer NOT NULL,
    selection_facts jsonb,
    checklist_results jsonb,
    CONSTRAINT td_operation_compliance_status_check CHECK (((compliance_status IS NULL) OR (compliance_status = ANY (ARRAY['complied'::text, 'breached'::text])))),
    CONSTRAINT trade_discipline_operation_amount_check CHECK (((amount IS NULL) OR (amount >= (0)::numeric))),
    CONSTRAINT trade_discipline_operation_check CHECK (((btrim(stock_code) <> ''::text) AND (btrim(stock_name_snapshot) <> ''::text))),
    CONSTRAINT trade_discipline_operation_checklist_results_check CHECK ((jsonb_typeof(checklist_results) = 'array'::text)),
    CONSTRAINT trade_discipline_operation_display_order_check CHECK ((display_order > 0)),
    CONSTRAINT trade_discipline_operation_fee_check CHECK (((fee IS NULL) OR (fee >= (0)::numeric))),
    CONSTRAINT trade_discipline_operation_price_check CHECK (((price IS NULL) OR (price >= (0)::numeric))),
    CONSTRAINT trade_discipline_operation_quantity_check CHECK (((quantity IS NULL) OR (quantity >= (0)::numeric))),
    CONSTRAINT trade_discipline_operation_side_check CHECK ((side = ANY (ARRAY['buy'::text, 'sell'::text])))
);


--
-- Name: COLUMN trade_discipline_operation.selection_facts; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_operation.selection_facts IS '操作时点事实快照：is_st、st_as_of_date为服务端逐日ST数据；loss_status和st_risk_status为用户是/否/未知确认，null旧记录未采集';


--
-- Name: COLUMN trade_discipline_operation.checklist_results; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_operation.checklist_results IS '买入逐项人工核对快照：item_id属于所选版本规则、status为yes符合/no不符合/unknown未知；空表示未记录或不适用';


--
-- Name: trade_discipline_reason; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_discipline_reason (
    id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    name text NOT NULL,
    normalized_name text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT trade_discipline_reason_check CHECK (((btrim(name) <> ''::text) AND (btrim(normalized_name) <> ''::text))),
    CONSTRAINT trade_discipline_reason_check1 CHECK (((is_active AND (deleted_at IS NULL)) OR ((NOT is_active) AND (deleted_at IS NOT NULL))))
);


--
-- Name: trade_discipline_rule; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_discipline_rule (
    id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    name text,
    normalized_name text,
    status text DEFAULT 'unpublished'::text NOT NULL,
    latest_version_no integer,
    next_activation_seq bigint DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT td_rule_lifecycle_consistency_check CHECK ((((status = 'unpublished'::text) AND (latest_version_no IS NULL)) OR ((status = ANY (ARRAY['active'::text, 'archived'::text])) AND (latest_version_no > 0) AND (btrim(COALESCE(name, ''::text)) <> ''::text) AND (btrim(COALESCE(normalized_name, ''::text)) <> ''::text)))),
    CONSTRAINT trade_discipline_rule_next_activation_seq_check CHECK ((next_activation_seq >= 0)),
    CONSTRAINT trade_discipline_rule_status_check CHECK ((status = ANY (ARRAY['unpublished'::text, 'active'::text, 'archived'::text])))
);


--
-- Name: trade_discipline_rule_activation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_discipline_rule_activation (
    id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    rule_id text NOT NULL,
    event_seq bigint NOT NULL,
    event_type text NOT NULL,
    version_no integer NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    activated_at timestamp with time zone NOT NULL,
    effective_from_trade_date date NOT NULL,
    CONSTRAINT trade_discipline_rule_activation_event_seq_check CHECK ((event_seq > 0)),
    CONSTRAINT trade_discipline_rule_activation_event_type_check CHECK ((event_type = ANY (ARRAY['publish'::text, 'archive'::text, 'restore'::text])))
);


--
-- Name: trade_discipline_rule_draft; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_discipline_rule_draft (
    rule_id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    draft_revision integer DEFAULT 1 NOT NULL,
    proposed_name text,
    normalized_name text,
    capital numeric(20,2),
    source_version_no integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    max_positions integer,
    restrict_financial_report_months boolean DEFAULT false NOT NULL,
    CONSTRAINT trade_discipline_rule_draft_capital_check CHECK (((capital IS NULL) OR (capital >= (0)::numeric))),
    CONSTRAINT trade_discipline_rule_draft_draft_revision_check CHECK ((draft_revision > 0)),
    CONSTRAINT trade_discipline_rule_draft_max_positions_check CHECK ((max_positions > 0)),
    CONSTRAINT trade_discipline_rule_draft_source_version_no_check CHECK (((source_version_no IS NULL) OR (source_version_no > 0)))
);


--
-- Name: COLUMN trade_discipline_rule_draft.max_positions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_rule_draft.max_positions IS '本套规则允许同时持有的不同股票数量上限，空表示不限';


--
-- Name: COLUMN trade_discipline_rule_draft.restrict_financial_report_months; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_rule_draft.restrict_financial_report_months IS '财报月份交易限制草稿开关，发布后按版本生效；默认关闭';


--
-- Name: trade_discipline_rule_name_claim; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_discipline_rule_name_claim (
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    normalized_name text NOT NULL,
    rule_id text NOT NULL,
    claimed_name text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT trade_discipline_rule_name_claim_normalized_name_check CHECK ((btrim(normalized_name) <> ''::text))
);


--
-- Name: trade_discipline_rule_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_discipline_rule_version (
    rule_id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    version_no integer NOT NULL,
    name text NOT NULL,
    normalized_name text NOT NULL,
    capital numeric(20,2) NOT NULL,
    published_at timestamp with time zone DEFAULT now() NOT NULL,
    max_positions integer,
    restrict_financial_report_months boolean DEFAULT false NOT NULL,
    CONSTRAINT trade_discipline_rule_version_capital_check CHECK ((capital > (0)::numeric)),
    CONSTRAINT trade_discipline_rule_version_check CHECK (((btrim(name) <> ''::text) AND (btrim(normalized_name) <> ''::text))),
    CONSTRAINT trade_discipline_rule_version_max_positions_check CHECK ((max_positions > 0)),
    CONSTRAINT trade_discipline_rule_version_version_no_check CHECK ((version_no > 0))
);


--
-- Name: COLUMN trade_discipline_rule_version.max_positions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_rule_version.max_positions IS '本套规则允许同时持有的不同股票数量上限，空表示不限';


--
-- Name: COLUMN trade_discipline_rule_version.restrict_financial_report_months; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_rule_version.restrict_financial_report_months IS '限制财报月份交易：3/7/9月各选股分组成本不超过分配资金的一半，月末最后交易日清仓，4/8/10月禁止持仓；默认关闭';


--
-- Name: trade_discipline_stock_rule; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_discipline_stock_rule (
    rule_id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    version_no integer NOT NULL,
    detail_id text NOT NULL,
    name text NOT NULL,
    max_capital numeric(20,2),
    content text,
    checklist_items jsonb DEFAULT '[]'::jsonb NOT NULL,
    display_order integer NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    price_min numeric(20,4),
    price_max numeric(20,4),
    st_filter text DEFAULT 'any'::text NOT NULL,
    loss_filter text DEFAULT 'any'::text NOT NULL,
    st_risk_filter text DEFAULT 'any'::text NOT NULL,
    CONSTRAINT trade_discipline_stock_rule_check CHECK (((NOT enabled) OR ((max_capital IS NOT NULL) AND (max_capital > (0)::numeric)))),
    CONSTRAINT trade_discipline_stock_rule_checklist_items_check CHECK ((jsonb_typeof(checklist_items) = 'array'::text)),
    CONSTRAINT trade_discipline_stock_rule_display_order_check CHECK ((display_order > 0)),
    CONSTRAINT trade_discipline_stock_rule_loss_filter_check CHECK ((loss_filter = ANY (ARRAY['any'::text, 'exclude'::text, 'only'::text]))),
    CONSTRAINT trade_discipline_stock_rule_name_required CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT trade_discipline_stock_rule_price_bounds CHECK (((price_min IS NULL) OR (price_max IS NULL) OR (price_min <= price_max))),
    CONSTRAINT trade_discipline_stock_rule_price_max_check CHECK ((price_max > (0)::numeric)),
    CONSTRAINT trade_discipline_stock_rule_price_min_check CHECK ((price_min > (0)::numeric)),
    CONSTRAINT trade_discipline_stock_rule_st_filter_check CHECK ((st_filter = ANY (ARRAY['any'::text, 'exclude'::text, 'only'::text]))),
    CONSTRAINT trade_discipline_stock_rule_st_risk_filter_check CHECK ((st_risk_filter = ANY (ARRAY['any'::text, 'exclude'::text, 'only'::text])))
);


--
-- Name: COLUMN trade_discipline_stock_rule.content; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_stock_rule.content IS '选股规则补充说明，保留原文换行，不参与逐项自动判定';


--
-- Name: COLUMN trade_discipline_stock_rule.checklist_items; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_stock_rule.checklist_items IS '版本化人工检查项：item_id稳定标识、category为选股分类字典编码、category_label分类名称快照；旧other读取兼容技术形态、text条件、display_order顺序；空数组表示未配置';


--
-- Name: COLUMN trade_discipline_stock_rule.price_min; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_stock_rule.price_min IS '买入成交价下限（元、原始价、含边界），空表示不限';


--
-- Name: COLUMN trade_discipline_stock_rule.price_max; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_stock_rule.price_max IS '买入成交价上限（元、原始价、含边界），空表示不限';


--
-- Name: COLUMN trade_discipline_stock_rule.st_filter; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_stock_rule.st_filter IS '买入时ST条件：any不限、exclude排除、only仅限';


--
-- Name: COLUMN trade_discipline_stock_rule.loss_filter; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_stock_rule.loss_filter IS '买入时亏损条件：any不限、exclude排除、only仅限；事实由用户确认';


--
-- Name: COLUMN trade_discipline_stock_rule.st_risk_filter; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_discipline_stock_rule.st_risk_filter IS '买入时ST风险条件：any不限、exclude排除、only仅限；事实由用户确认';


--
-- Name: trade_discipline_violation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_discipline_violation (
    checkin_id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    revision_no integer NOT NULL,
    reason_code text,
    reason_id text,
    reason_name_snapshot text NOT NULL,
    CONSTRAINT trade_discipline_violation_check CHECK ((((reason_code IS NOT NULL) AND (reason_id IS NULL)) OR ((reason_code IS NULL) AND (reason_id IS NOT NULL)))),
    CONSTRAINT trade_discipline_violation_reason_name_snapshot_check CHECK ((btrim(reason_name_snapshot) <> ''::text))
);


--
-- Name: trade_profile; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_profile (
    id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    name text,
    version integer,
    buy_tree text,
    sell_tree text,
    backstop text,
    is_preset boolean,
    visibility text DEFAULT 'private'::text NOT NULL,
    published_at timestamp without time zone,
    published_by text,
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    CONSTRAINT trade_profile_publish_consistency_check CHECK ((((visibility = 'private'::text) AND (published_at IS NULL) AND (published_by IS NULL)) OR (visibility = ANY (ARRAY['tenant'::text, 'public'::text])))),
    CONSTRAINT trade_profile_visibility_check CHECK ((visibility = ANY (ARRAY['private'::text, 'tenant'::text, 'public'::text])))
);


--
-- Name: trade_profile_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_profile_version (
    id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    version integer NOT NULL,
    name text,
    buy_tree text,
    sell_tree text,
    backstop text,
    saved_at timestamp without time zone
);


--
-- Name: training_round; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_round (
    session_id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    seq integer NOT NULL,
    code text,
    start_date date,
    end_date date,
    window_days integer,
    base_factor double precision,
    price_limit_pct double precision,
    cursor_date date,
    cursor_idx integer,
    status text,
    cash double precision,
    pos_shares bigint,
    pos_cost double precision,
    pos_avg_price double precision,
    pending text,
    realized_pnl double precision,
    round_return double precision,
    benchmark_return double precision,
    final_equity double precision
);


--
-- Name: training_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_session (
    id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    mode text,
    range_start date,
    range_end date,
    n_rounds integer,
    window_days integer,
    initial_capital double precision,
    filters text,
    fee_enabled boolean,
    status text,
    cur_round integer,
    total_return double precision,
    score double precision,
    grade text,
    win_rate double precision,
    max_drawdown double precision,
    n_trades integer,
    review_note text,
    created_at timestamp without time zone,
    completed_at timestamp without time zone
);


--
-- Name: training_trade; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_trade (
    session_id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    round_seq integer NOT NULL,
    seq integer NOT NULL,
    side text,
    decide_date date,
    fill_date date,
    rel_day integer,
    price double precision,
    hands integer,
    shares bigint,
    amount double precision,
    fee double precision,
    pnl double precision,
    return_pct double precision,
    reason text,
    auto_close boolean
);


--
-- Name: user_preference; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_preference (
    tenant_id text DEFAULT 'default'::text NOT NULL,
    owner_user_id text DEFAULT 'admin'::text NOT NULL,
    scope text NOT NULL,
    page_key text DEFAULT ''::text NOT NULL,
    pref_key text NOT NULL,
    value text NOT NULL,
    schema_version integer DEFAULT 1 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: task_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_log ALTER COLUMN id SET DEFAULT nextval('public.task_log_id_seq'::regclass);


--
-- Name: app_config app_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_config
    ADD CONSTRAINT app_config_pkey PRIMARY KEY (key);


--
-- Name: async_task async_task_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.async_task
    ADD CONSTRAINT async_task_pkey PRIMARY KEY (id);


--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);


--
-- Name: backtest_equity backtest_equity_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_equity
    ADD CONSTRAINT backtest_equity_pkey PRIMARY KEY (tenant_id, owner_user_id, run_id, trade_date);


--
-- Name: backtest_metrics backtest_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_metrics
    ADD CONSTRAINT backtest_metrics_pkey PRIMARY KEY (tenant_id, owner_user_id, run_id);


--
-- Name: backtest_run backtest_run_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_run
    ADD CONSTRAINT backtest_run_pkey PRIMARY KEY (tenant_id, owner_user_id, id);


--
-- Name: backtest_trade backtest_trade_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_trade
    ADD CONSTRAINT backtest_trade_pkey PRIMARY KEY (tenant_id, owner_user_id, run_id, seq);


--
-- Name: board_watchlist board_watchlist_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_watchlist
    ADD CONSTRAINT board_watchlist_pkey PRIMARY KEY (tenant_id, owner_user_id, board_code);


--
-- Name: data_source_health data_source_health_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_source_health
    ADD CONSTRAINT data_source_health_pkey PRIMARY KEY (source);


--
-- Name: dict_item dict_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dict_item
    ADD CONSTRAINT dict_item_pkey PRIMARY KEY (id);


--
-- Name: dict_item dict_item_type_code_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dict_item
    ADD CONSTRAINT dict_item_type_code_code_key UNIQUE (type_code, code);


--
-- Name: dict_type dict_type_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dict_type
    ADD CONSTRAINT dict_type_code_key UNIQUE (code);


--
-- Name: dict_type dict_type_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dict_type
    ADD CONSTRAINT dict_type_pkey PRIMARY KEY (id);


--
-- Name: layout_field_policy layout_field_policy_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.layout_field_policy
    ADD CONSTRAINT layout_field_policy_pkey PRIMARY KEY (component_kind, field);


--
-- Name: layout_page_config layout_page_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.layout_page_config
    ADD CONSTRAINT layout_page_config_pkey PRIMARY KEY (page_key);


--
-- Name: layout_preset layout_preset_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.layout_preset
    ADD CONSTRAINT layout_preset_pkey PRIMARY KEY (key);


--
-- Name: layout_user_config layout_user_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.layout_user_config
    ADD CONSTRAINT layout_user_config_pkey PRIMARY KEY (user_id, page_key);


--
-- Name: limit_ladder_audit_outbox limit_ladder_audit_outbox_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.limit_ladder_audit_outbox
    ADD CONSTRAINT limit_ladder_audit_outbox_pkey PRIMARY KEY (command_id, event_type);


--
-- Name: limit_ladder_audit_outbox limit_ladder_audit_outbox_source_event_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.limit_ladder_audit_outbox
    ADD CONSTRAINT limit_ladder_audit_outbox_source_event_key_key UNIQUE (source_event_key);


--
-- Name: limit_ladder_task_ledger limit_ladder_task_ledger_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.limit_ladder_task_ledger
    ADD CONSTRAINT limit_ladder_task_ledger_pkey PRIMARY KEY (command_id);


--
-- Name: scheduled_job_dependency scheduled_job_dependency_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_job_dependency
    ADD CONSTRAINT scheduled_job_dependency_pkey PRIMARY KEY (upstream_job_id, downstream_job_id);


--
-- Name: scheduled_job scheduled_job_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_job
    ADD CONSTRAINT scheduled_job_pkey PRIMARY KEY (id);


--
-- Name: scheduled_trigger_event scheduled_trigger_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_trigger_event
    ADD CONSTRAINT scheduled_trigger_event_pkey PRIMARY KEY (id);


--
-- Name: score_profile score_profile_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.score_profile
    ADD CONSTRAINT score_profile_pkey PRIMARY KEY (tenant_id, owner_user_id, id);


--
-- Name: score_profile_version score_profile_version_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.score_profile_version
    ADD CONSTRAINT score_profile_version_pkey PRIMARY KEY (tenant_id, owner_user_id, id, version);


--
-- Name: score_result score_result_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.score_result
    ADD CONSTRAINT score_result_pkey PRIMARY KEY (tenant_id, owner_user_id, trade_date, model_id, code);


--
-- Name: score_snapshot_meta score_snapshot_meta_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.score_snapshot_meta
    ADD CONSTRAINT score_snapshot_meta_pkey PRIMARY KEY (tenant_id, owner_user_id, trade_date, profile_id, profile_version);


--
-- Name: score_snapshot score_snapshot_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.score_snapshot
    ADD CONSTRAINT score_snapshot_pkey PRIMARY KEY (tenant_id, owner_user_id, trade_date, profile_id, profile_version, code);


--
-- Name: screen_profile screen_profile_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screen_profile
    ADD CONSTRAINT screen_profile_pkey PRIMARY KEY (tenant_id, owner_user_id, id);


--
-- Name: screen_profile_version screen_profile_version_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screen_profile_version
    ADD CONSTRAINT screen_profile_version_pkey PRIMARY KEY (tenant_id, owner_user_id, id, version);


--
-- Name: screen_result screen_result_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screen_result
    ADD CONSTRAINT screen_result_pkey PRIMARY KEY (tenant_id, owner_user_id, run_date, profile_id, code);


--
-- Name: stock_group_member stock_group_member_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stock_group_member
    ADD CONSTRAINT stock_group_member_pkey PRIMARY KEY (tenant_id, owner_user_id, group_id, code);


--
-- Name: stock_group stock_group_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stock_group
    ADD CONSTRAINT stock_group_pkey PRIMARY KEY (tenant_id, owner_user_id, id);


--
-- Name: storage_migration storage_migration_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storage_migration
    ADD CONSTRAINT storage_migration_pkey PRIMARY KEY (marker);


--
-- Name: sys_menu sys_menu_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_menu
    ADD CONSTRAINT sys_menu_code_key UNIQUE (code);


--
-- Name: sys_menu sys_menu_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_menu
    ADD CONSTRAINT sys_menu_pkey PRIMARY KEY (id);


--
-- Name: sys_resource sys_resource_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_resource
    ADD CONSTRAINT sys_resource_code_key UNIQUE (code);


--
-- Name: sys_resource sys_resource_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_resource
    ADD CONSTRAINT sys_resource_pkey PRIMARY KEY (id);


--
-- Name: sys_role sys_role_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_role
    ADD CONSTRAINT sys_role_code_key UNIQUE (code);


--
-- Name: sys_role_menu sys_role_menu_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_role_menu
    ADD CONSTRAINT sys_role_menu_pkey PRIMARY KEY (role_id, menu_id);


--
-- Name: sys_role sys_role_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_role
    ADD CONSTRAINT sys_role_pkey PRIMARY KEY (id);


--
-- Name: sys_role_resource sys_role_resource_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_role_resource
    ADD CONSTRAINT sys_role_resource_pkey PRIMARY KEY (role_id, resource_id);


--
-- Name: sys_tenant sys_tenant_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_tenant
    ADD CONSTRAINT sys_tenant_pkey PRIMARY KEY (id);


--
-- Name: sys_user sys_user_account_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_user
    ADD CONSTRAINT sys_user_account_key UNIQUE (account);


--
-- Name: sys_user sys_user_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_user
    ADD CONSTRAINT sys_user_pkey PRIMARY KEY (id);


--
-- Name: sys_user_role sys_user_role_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_user_role
    ADD CONSTRAINT sys_user_role_pkey PRIMARY KEY (user_id, role_id);


--
-- Name: task_log task_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_log
    ADD CONSTRAINT task_log_pkey PRIMARY KEY (id);


--
-- Name: task_log task_log_task_id_seq_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_log
    ADD CONSTRAINT task_log_task_id_seq_key UNIQUE (task_id, seq);


--
-- Name: trade_discipline_account trade_discipline_account_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_account
    ADD CONSTRAINT trade_discipline_account_pkey PRIMARY KEY (tenant_id, owner_user_id, id);


--
-- Name: trade_discipline_action_rule trade_discipline_action_rule_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_action_rule
    ADD CONSTRAINT trade_discipline_action_rule_pkey PRIMARY KEY (tenant_id, owner_user_id, rule_id, version_no, detail_id);


--
-- Name: trade_discipline_action_rule trade_discipline_action_rule_tenant_id_owner_user_id_rule__key1; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_action_rule
    ADD CONSTRAINT trade_discipline_action_rule_tenant_id_owner_user_id_rule__key1 UNIQUE (tenant_id, owner_user_id, rule_id, version_no, detail_id, action_type);


--
-- Name: trade_discipline_action_rule trade_discipline_action_rule_tenant_id_owner_user_id_rule_i_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_action_rule
    ADD CONSTRAINT trade_discipline_action_rule_tenant_id_owner_user_id_rule_i_key UNIQUE (tenant_id, owner_user_id, rule_id, version_no, action_type, display_order);


--
-- Name: trade_discipline_action_subtype trade_discipline_action_subtype_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_action_subtype
    ADD CONSTRAINT trade_discipline_action_subtype_pkey PRIMARY KEY (tenant_id, owner_user_id, normalized_name);


--
-- Name: trade_discipline_checkin trade_discipline_checkin_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_checkin
    ADD CONSTRAINT trade_discipline_checkin_pkey PRIMARY KEY (tenant_id, owner_user_id, id);


--
-- Name: trade_discipline_checkin_revision trade_discipline_checkin_revi_tenant_id_owner_user_id_check_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_checkin_revision
    ADD CONSTRAINT trade_discipline_checkin_revi_tenant_id_owner_user_id_check_key UNIQUE (tenant_id, owner_user_id, checkin_id, revision_no, rule_id, version_no);


--
-- Name: trade_discipline_checkin_revision trade_discipline_checkin_revision_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_checkin_revision
    ADD CONSTRAINT trade_discipline_checkin_revision_pkey PRIMARY KEY (tenant_id, owner_user_id, checkin_id, revision_no);


--
-- Name: trade_discipline_checkin trade_discipline_checkin_tenant_id_owner_user_id_rule_id_tr_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_checkin
    ADD CONSTRAINT trade_discipline_checkin_tenant_id_owner_user_id_rule_id_tr_key UNIQUE (tenant_id, owner_user_id, rule_id, trade_date);


--
-- Name: trade_discipline_draft_action_rule trade_discipline_draft_action_rule_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_draft_action_rule
    ADD CONSTRAINT trade_discipline_draft_action_rule_pkey PRIMARY KEY (tenant_id, owner_user_id, rule_id, detail_id);


--
-- Name: trade_discipline_draft_action_rule trade_discipline_draft_action_tenant_id_owner_user_id_rule__key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_draft_action_rule
    ADD CONSTRAINT trade_discipline_draft_action_tenant_id_owner_user_id_rule__key UNIQUE (tenant_id, owner_user_id, rule_id, action_type, display_order);


--
-- Name: trade_discipline_draft_stock_rule trade_discipline_draft_stock__tenant_id_owner_user_id_rule__key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_draft_stock_rule
    ADD CONSTRAINT trade_discipline_draft_stock__tenant_id_owner_user_id_rule__key UNIQUE (tenant_id, owner_user_id, rule_id, display_order);


--
-- Name: trade_discipline_draft_stock_rule trade_discipline_draft_stock_rule_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_draft_stock_rule
    ADD CONSTRAINT trade_discipline_draft_stock_rule_pkey PRIMARY KEY (tenant_id, owner_user_id, rule_id, detail_id);


--
-- Name: trade_discipline_ledger_day trade_discipline_ledger_day_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_ledger_day
    ADD CONSTRAINT trade_discipline_ledger_day_pkey PRIMARY KEY (tenant_id, owner_user_id, account_id, trade_date);


--
-- Name: trade_discipline_ledger_revision trade_discipline_ledger_revis_tenant_id_owner_user_id_accou_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_ledger_revision
    ADD CONSTRAINT trade_discipline_ledger_revis_tenant_id_owner_user_id_accou_key UNIQUE (tenant_id, owner_user_id, account_id, request_id);


--
-- Name: trade_discipline_ledger_revision trade_discipline_ledger_revision_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_ledger_revision
    ADD CONSTRAINT trade_discipline_ledger_revision_pkey PRIMARY KEY (tenant_id, owner_user_id, account_id, trade_date, revision_no);


--
-- Name: trade_discipline_operation trade_discipline_operation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_operation
    ADD CONSTRAINT trade_discipline_operation_pkey PRIMARY KEY (tenant_id, owner_user_id, id);


--
-- Name: trade_discipline_operation trade_discipline_operation_tenant_id_owner_user_id_checkin__key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_operation
    ADD CONSTRAINT trade_discipline_operation_tenant_id_owner_user_id_checkin__key UNIQUE (tenant_id, owner_user_id, checkin_id, revision_no, display_order);


--
-- Name: trade_discipline_reason trade_discipline_reason_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_reason
    ADD CONSTRAINT trade_discipline_reason_pkey PRIMARY KEY (tenant_id, owner_user_id, id);


--
-- Name: trade_discipline_reason trade_discipline_reason_tenant_id_owner_user_id_normalized__key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_reason
    ADD CONSTRAINT trade_discipline_reason_tenant_id_owner_user_id_normalized__key UNIQUE (tenant_id, owner_user_id, normalized_name);


--
-- Name: trade_discipline_rule_activation trade_discipline_rule_activat_tenant_id_owner_user_id_rule__key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_rule_activation
    ADD CONSTRAINT trade_discipline_rule_activat_tenant_id_owner_user_id_rule__key UNIQUE (tenant_id, owner_user_id, rule_id, event_seq);


--
-- Name: trade_discipline_rule_activation trade_discipline_rule_activation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_rule_activation
    ADD CONSTRAINT trade_discipline_rule_activation_pkey PRIMARY KEY (tenant_id, owner_user_id, id);


--
-- Name: trade_discipline_rule_draft trade_discipline_rule_draft_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_rule_draft
    ADD CONSTRAINT trade_discipline_rule_draft_pkey PRIMARY KEY (tenant_id, owner_user_id, rule_id);


--
-- Name: trade_discipline_rule_name_claim trade_discipline_rule_name_claim_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_rule_name_claim
    ADD CONSTRAINT trade_discipline_rule_name_claim_pkey PRIMARY KEY (tenant_id, owner_user_id, normalized_name);


--
-- Name: trade_discipline_rule trade_discipline_rule_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_rule
    ADD CONSTRAINT trade_discipline_rule_pkey PRIMARY KEY (tenant_id, owner_user_id, id);


--
-- Name: trade_discipline_rule_version trade_discipline_rule_version_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_rule_version
    ADD CONSTRAINT trade_discipline_rule_version_pkey PRIMARY KEY (tenant_id, owner_user_id, rule_id, version_no);


--
-- Name: trade_discipline_stock_rule trade_discipline_stock_rule_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_stock_rule
    ADD CONSTRAINT trade_discipline_stock_rule_pkey PRIMARY KEY (tenant_id, owner_user_id, rule_id, version_no, detail_id);


--
-- Name: trade_discipline_stock_rule trade_discipline_stock_rule_tenant_id_owner_user_id_rule_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_stock_rule
    ADD CONSTRAINT trade_discipline_stock_rule_tenant_id_owner_user_id_rule_id_key UNIQUE (tenant_id, owner_user_id, rule_id, version_no, display_order);


--
-- Name: trade_discipline_violation trade_discipline_violation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_violation
    ADD CONSTRAINT trade_discipline_violation_pkey PRIMARY KEY (tenant_id, owner_user_id, checkin_id, revision_no);


--
-- Name: trade_profile trade_profile_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_profile
    ADD CONSTRAINT trade_profile_pkey PRIMARY KEY (tenant_id, owner_user_id, id);


--
-- Name: trade_profile_version trade_profile_version_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_profile_version
    ADD CONSTRAINT trade_profile_version_pkey PRIMARY KEY (tenant_id, owner_user_id, id, version);


--
-- Name: training_round training_round_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_round
    ADD CONSTRAINT training_round_pkey PRIMARY KEY (tenant_id, owner_user_id, session_id, seq);


--
-- Name: training_session training_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_session
    ADD CONSTRAINT training_session_pkey PRIMARY KEY (tenant_id, owner_user_id, id);


--
-- Name: training_trade training_trade_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_trade
    ADD CONSTRAINT training_trade_pkey PRIMARY KEY (tenant_id, owner_user_id, session_id, round_seq, seq);


--
-- Name: user_preference user_preference_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_preference
    ADD CONSTRAINT user_preference_pkey PRIMARY KEY (tenant_id, owner_user_id, scope, page_key, pref_key);


--
-- Name: idx_async_task_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_async_task_status_created ON public.async_task USING btree (status, created_at DESC);


--
-- Name: idx_async_task_type_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_async_task_type_status ON public.async_task USING btree (task_type, status);


--
-- Name: idx_audit_log_category_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_category_time ON public.audit_log USING btree (event_category, event_time DESC);


--
-- Name: idx_audit_log_event_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_event_time ON public.audit_log USING btree (event_time DESC);


--
-- Name: idx_audit_log_resource_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_resource_time ON public.audit_log USING btree (resource_code, event_time DESC);


--
-- Name: idx_audit_log_result_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_result_time ON public.audit_log USING btree (result, event_time DESC);


--
-- Name: idx_audit_log_tenant_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_tenant_time ON public.audit_log USING btree (tenant_id, event_time DESC);


--
-- Name: idx_audit_log_type_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_type_time ON public.audit_log USING btree (event_type, event_time DESC);


--
-- Name: idx_backtest_run_visibility; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_run_visibility ON public.backtest_run USING btree (visibility, tenant_id, owner_user_id);


--
-- Name: idx_dict_item_type_enabled_sort; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dict_item_type_enabled_sort ON public.dict_item USING btree (type_code, enabled, sort, code);


--
-- Name: idx_dict_type_enabled_sort; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dict_type_enabled_sort ON public.dict_type USING btree (enabled, sort, code);


--
-- Name: idx_layout_user_config_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_layout_user_config_owner ON public.layout_user_config USING btree (tenant_id, owner_user_id);


--
-- Name: idx_limit_ladder_outbox_delivery; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_limit_ladder_outbox_delivery ON public.limit_ladder_audit_outbox USING btree (status, next_retry_at, created_at);


--
-- Name: idx_schedule_dependency_downstream; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_schedule_dependency_downstream ON public.scheduled_job_dependency USING btree (downstream_job_id);


--
-- Name: idx_scheduled_event_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scheduled_event_due ON public.scheduled_trigger_event USING btree (status, due_at);


--
-- Name: idx_scheduled_event_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scheduled_event_target ON public.scheduled_trigger_event USING btree (target_job_id, created_at DESC);


--
-- Name: idx_scheduled_job_enabled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scheduled_job_enabled ON public.scheduled_job USING btree (enabled, trigger_mode);


--
-- Name: idx_score_profile_visibility; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_score_profile_visibility ON public.score_profile USING btree (visibility, tenant_id, owner_user_id);


--
-- Name: idx_screen_profile_visibility; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_screen_profile_visibility ON public.screen_profile USING btree (visibility, tenant_id, owner_user_id);


--
-- Name: idx_sys_menu_parent_sort; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sys_menu_parent_sort ON public.sys_menu USING btree (parent_id, sort);


--
-- Name: idx_sys_resource_menu; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sys_resource_menu ON public.sys_resource USING btree (menu_id);


--
-- Name: idx_sys_role_menu_menu; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sys_role_menu_menu ON public.sys_role_menu USING btree (menu_id);


--
-- Name: idx_sys_role_resource_resource; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sys_role_resource_resource ON public.sys_role_resource USING btree (resource_id);


--
-- Name: idx_sys_user_role_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sys_user_role_role ON public.sys_user_role USING btree (role_id);


--
-- Name: idx_task_log_task_seq; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_log_task_seq ON public.task_log USING btree (task_id, seq);


--
-- Name: idx_task_log_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_log_ts ON public.task_log USING btree (ts);


--
-- Name: idx_td_activation_effective; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_td_activation_effective ON public.trade_discipline_rule_activation USING btree (tenant_id, owner_user_id, rule_id, effective_from_trade_date DESC, event_seq DESC);


--
-- Name: idx_td_checkin_history; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_td_checkin_history ON public.trade_discipline_checkin USING btree (tenant_id, owner_user_id, trade_date DESC, updated_at DESC);


--
-- Name: idx_td_operation_stock; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_td_operation_stock ON public.trade_discipline_operation USING btree (tenant_id, owner_user_id, stock_code, checkin_id, revision_no);


--
-- Name: idx_td_revision_detail; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_td_revision_detail ON public.trade_discipline_checkin_revision USING btree (tenant_id, owner_user_id, checkin_id, revision_no DESC);


--
-- Name: idx_td_rule_owner_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_td_rule_owner_status ON public.trade_discipline_rule USING btree (tenant_id, owner_user_id, status, updated_at DESC) WHERE (deleted_at IS NULL);


--
-- Name: idx_td_violation_reason_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_td_violation_reason_name ON public.trade_discipline_violation USING btree (tenant_id, owner_user_id, lower(reason_name_snapshot), checkin_id, revision_no);


--
-- Name: idx_trade_profile_visibility; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_profile_visibility ON public.trade_profile USING btree (visibility, tenant_id, owner_user_id);


--
-- Name: uq_async_task_trigger_event; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_async_task_trigger_event ON public.async_task USING btree (trigger_event_id) WHERE (trigger_event_id IS NOT NULL);


--
-- Name: uq_audit_log_source_event_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_audit_log_source_event_key ON public.audit_log USING btree (source_event_key) WHERE (source_event_key IS NOT NULL);


--
-- Name: uq_limit_ladder_active_trade_date; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_limit_ladder_active_trade_date ON public.limit_ladder_task_ledger USING btree (trade_date) WHERE (status = ANY (ARRAY['requested'::text, 'running'::text]));


--
-- Name: uq_limit_ladder_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_limit_ladder_task_id ON public.limit_ladder_task_ledger USING btree (task_id) WHERE (task_id IS NOT NULL);


--
-- Name: uq_sys_menu_code_normalized; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_sys_menu_code_normalized ON public.sys_menu USING btree (lower(btrim(code)));


--
-- Name: uq_sys_role_code_normalized; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_sys_role_code_normalized ON public.sys_role USING btree (lower(btrim(code)));


--
-- Name: uq_sys_role_name_normalized; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_sys_role_name_normalized ON public.sys_role USING btree (lower(btrim(name)));


--
-- Name: uq_sys_tenant_name_normalized; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_sys_tenant_name_normalized ON public.sys_tenant USING btree (lower(btrim(name)));


--
-- Name: uq_sys_user_account_normalized; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_sys_user_account_normalized ON public.sys_user USING btree (lower(btrim(account)));


--
-- Name: uq_sys_user_email_normalized; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_sys_user_email_normalized ON public.sys_user USING btree (lower(btrim(email))) WHERE (email IS NOT NULL);


--
-- Name: dict_item dict_item_type_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dict_item
    ADD CONSTRAINT dict_item_type_code_fkey FOREIGN KEY (type_code) REFERENCES public.dict_type(code) ON DELETE RESTRICT;


--
-- Name: limit_ladder_audit_outbox limit_ladder_audit_outbox_command_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.limit_ladder_audit_outbox
    ADD CONSTRAINT limit_ladder_audit_outbox_command_id_fkey FOREIGN KEY (command_id) REFERENCES public.limit_ladder_task_ledger(command_id) ON DELETE RESTRICT;


--
-- Name: sys_menu sys_menu_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_menu
    ADD CONSTRAINT sys_menu_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.sys_menu(id) ON DELETE RESTRICT;


--
-- Name: sys_resource sys_resource_menu_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_resource
    ADD CONSTRAINT sys_resource_menu_id_fkey FOREIGN KEY (menu_id) REFERENCES public.sys_menu(id) ON DELETE RESTRICT;


--
-- Name: sys_role_menu sys_role_menu_menu_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_role_menu
    ADD CONSTRAINT sys_role_menu_menu_id_fkey FOREIGN KEY (menu_id) REFERENCES public.sys_menu(id) ON DELETE CASCADE;


--
-- Name: sys_role_menu sys_role_menu_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_role_menu
    ADD CONSTRAINT sys_role_menu_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.sys_role(id) ON DELETE CASCADE;


--
-- Name: sys_role_resource sys_role_resource_resource_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_role_resource
    ADD CONSTRAINT sys_role_resource_resource_id_fkey FOREIGN KEY (resource_id) REFERENCES public.sys_resource(id) ON DELETE CASCADE;


--
-- Name: sys_role_resource sys_role_resource_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_role_resource
    ADD CONSTRAINT sys_role_resource_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.sys_role(id) ON DELETE CASCADE;


--
-- Name: sys_user_role sys_user_role_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_user_role
    ADD CONSTRAINT sys_user_role_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.sys_role(id) ON DELETE RESTRICT;


--
-- Name: sys_user_role sys_user_role_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sys_user_role
    ADD CONSTRAINT sys_user_role_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.sys_user(id) ON DELETE CASCADE;


--
-- Name: task_log task_log_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_log
    ADD CONSTRAINT task_log_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.async_task(id) ON DELETE CASCADE;


--
-- Name: trade_discipline_checkin td_checkin_current_revision_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_checkin
    ADD CONSTRAINT td_checkin_current_revision_fk FOREIGN KEY (tenant_id, owner_user_id, id, current_revision_no) REFERENCES public.trade_discipline_checkin_revision(tenant_id, owner_user_id, checkin_id, revision_no) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trade_discipline_rule td_rule_latest_version_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_rule
    ADD CONSTRAINT td_rule_latest_version_fk FOREIGN KEY (tenant_id, owner_user_id, id, latest_version_no) REFERENCES public.trade_discipline_rule_version(tenant_id, owner_user_id, rule_id, version_no) ON DELETE RESTRICT;


--
-- Name: trade_discipline_action_rule trade_discipline_action_rule_tenant_id_owner_user_id_rule__fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_action_rule
    ADD CONSTRAINT trade_discipline_action_rule_tenant_id_owner_user_id_rule__fkey FOREIGN KEY (tenant_id, owner_user_id, rule_id, version_no) REFERENCES public.trade_discipline_rule_version(tenant_id, owner_user_id, rule_id, version_no) ON DELETE RESTRICT;


--
-- Name: trade_discipline_checkin_revision trade_discipline_checkin_revi_tenant_id_owner_user_id_chec_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_checkin_revision
    ADD CONSTRAINT trade_discipline_checkin_revi_tenant_id_owner_user_id_chec_fkey FOREIGN KEY (tenant_id, owner_user_id, checkin_id) REFERENCES public.trade_discipline_checkin(tenant_id, owner_user_id, id) ON DELETE RESTRICT;


--
-- Name: trade_discipline_checkin_revision trade_discipline_checkin_revi_tenant_id_owner_user_id_rule_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_checkin_revision
    ADD CONSTRAINT trade_discipline_checkin_revi_tenant_id_owner_user_id_rule_fkey FOREIGN KEY (tenant_id, owner_user_id, rule_id, version_no) REFERENCES public.trade_discipline_rule_version(tenant_id, owner_user_id, rule_id, version_no) ON DELETE RESTRICT;


--
-- Name: trade_discipline_checkin trade_discipline_checkin_tenant_id_owner_user_id_rule_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_checkin
    ADD CONSTRAINT trade_discipline_checkin_tenant_id_owner_user_id_rule_id_fkey FOREIGN KEY (tenant_id, owner_user_id, rule_id) REFERENCES public.trade_discipline_rule(tenant_id, owner_user_id, id) ON DELETE RESTRICT;


--
-- Name: trade_discipline_draft_action_rule trade_discipline_draft_action_tenant_id_owner_user_id_rule_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_draft_action_rule
    ADD CONSTRAINT trade_discipline_draft_action_tenant_id_owner_user_id_rule_fkey FOREIGN KEY (tenant_id, owner_user_id, rule_id) REFERENCES public.trade_discipline_rule_draft(tenant_id, owner_user_id, rule_id) ON DELETE CASCADE;


--
-- Name: trade_discipline_draft_stock_rule trade_discipline_draft_stock__tenant_id_owner_user_id_rule_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_draft_stock_rule
    ADD CONSTRAINT trade_discipline_draft_stock__tenant_id_owner_user_id_rule_fkey FOREIGN KEY (tenant_id, owner_user_id, rule_id) REFERENCES public.trade_discipline_rule_draft(tenant_id, owner_user_id, rule_id) ON DELETE CASCADE;


--
-- Name: trade_discipline_ledger_day trade_discipline_ledger_day_tenant_id_owner_user_id_accoun_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_ledger_day
    ADD CONSTRAINT trade_discipline_ledger_day_tenant_id_owner_user_id_accoun_fkey FOREIGN KEY (tenant_id, owner_user_id, account_id) REFERENCES public.trade_discipline_account(tenant_id, owner_user_id, id);


--
-- Name: trade_discipline_ledger_revision trade_discipline_ledger_revis_tenant_id_owner_user_id_acco_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_ledger_revision
    ADD CONSTRAINT trade_discipline_ledger_revis_tenant_id_owner_user_id_acco_fkey FOREIGN KEY (tenant_id, owner_user_id, account_id, trade_date) REFERENCES public.trade_discipline_ledger_day(tenant_id, owner_user_id, account_id, trade_date);


--
-- Name: trade_discipline_operation trade_discipline_operation_tenant_id_owner_user_id_checkin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_operation
    ADD CONSTRAINT trade_discipline_operation_tenant_id_owner_user_id_checkin_fkey FOREIGN KEY (tenant_id, owner_user_id, checkin_id, revision_no, rule_id, version_no) REFERENCES public.trade_discipline_checkin_revision(tenant_id, owner_user_id, checkin_id, revision_no, rule_id, version_no) ON DELETE RESTRICT;


--
-- Name: trade_discipline_operation trade_discipline_operation_tenant_id_owner_user_id_rule_i_fkey1; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_operation
    ADD CONSTRAINT trade_discipline_operation_tenant_id_owner_user_id_rule_i_fkey1 FOREIGN KEY (tenant_id, owner_user_id, rule_id, version_no, action_rule_id, side) REFERENCES public.trade_discipline_action_rule(tenant_id, owner_user_id, rule_id, version_no, detail_id, action_type) ON DELETE RESTRICT;


--
-- Name: trade_discipline_operation trade_discipline_operation_tenant_id_owner_user_id_rule_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_operation
    ADD CONSTRAINT trade_discipline_operation_tenant_id_owner_user_id_rule_id_fkey FOREIGN KEY (tenant_id, owner_user_id, rule_id, version_no, stock_rule_id) REFERENCES public.trade_discipline_stock_rule(tenant_id, owner_user_id, rule_id, version_no, detail_id) ON DELETE RESTRICT;


--
-- Name: trade_discipline_rule_activation trade_discipline_rule_activat_tenant_id_owner_user_id_rule_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_rule_activation
    ADD CONSTRAINT trade_discipline_rule_activat_tenant_id_owner_user_id_rule_fkey FOREIGN KEY (tenant_id, owner_user_id, rule_id, version_no) REFERENCES public.trade_discipline_rule_version(tenant_id, owner_user_id, rule_id, version_no) ON DELETE RESTRICT;


--
-- Name: trade_discipline_rule_draft trade_discipline_rule_draft_tenant_id_owner_user_id_rule__fkey1; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_rule_draft
    ADD CONSTRAINT trade_discipline_rule_draft_tenant_id_owner_user_id_rule__fkey1 FOREIGN KEY (tenant_id, owner_user_id, rule_id, source_version_no) REFERENCES public.trade_discipline_rule_version(tenant_id, owner_user_id, rule_id, version_no) ON DELETE RESTRICT;


--
-- Name: trade_discipline_rule_draft trade_discipline_rule_draft_tenant_id_owner_user_id_rule_i_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_rule_draft
    ADD CONSTRAINT trade_discipline_rule_draft_tenant_id_owner_user_id_rule_i_fkey FOREIGN KEY (tenant_id, owner_user_id, rule_id) REFERENCES public.trade_discipline_rule(tenant_id, owner_user_id, id) ON DELETE CASCADE;


--
-- Name: trade_discipline_rule_name_claim trade_discipline_rule_name_cl_tenant_id_owner_user_id_rule_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_rule_name_claim
    ADD CONSTRAINT trade_discipline_rule_name_cl_tenant_id_owner_user_id_rule_fkey FOREIGN KEY (tenant_id, owner_user_id, rule_id) REFERENCES public.trade_discipline_rule(tenant_id, owner_user_id, id) ON DELETE CASCADE;


--
-- Name: trade_discipline_rule_version trade_discipline_rule_version_tenant_id_owner_user_id_rule_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_rule_version
    ADD CONSTRAINT trade_discipline_rule_version_tenant_id_owner_user_id_rule_fkey FOREIGN KEY (tenant_id, owner_user_id, rule_id) REFERENCES public.trade_discipline_rule(tenant_id, owner_user_id, id) ON DELETE RESTRICT;


--
-- Name: trade_discipline_stock_rule trade_discipline_stock_rule_tenant_id_owner_user_id_rule_i_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_stock_rule
    ADD CONSTRAINT trade_discipline_stock_rule_tenant_id_owner_user_id_rule_i_fkey FOREIGN KEY (tenant_id, owner_user_id, rule_id, version_no) REFERENCES public.trade_discipline_rule_version(tenant_id, owner_user_id, rule_id, version_no) ON DELETE RESTRICT;


--
-- Name: trade_discipline_violation trade_discipline_violation_tenant_id_owner_user_id_checkin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_violation
    ADD CONSTRAINT trade_discipline_violation_tenant_id_owner_user_id_checkin_fkey FOREIGN KEY (tenant_id, owner_user_id, checkin_id, revision_no) REFERENCES public.trade_discipline_checkin_revision(tenant_id, owner_user_id, checkin_id, revision_no) ON DELETE RESTRICT;


--
-- Name: trade_discipline_violation trade_discipline_violation_tenant_id_owner_user_id_reason__fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_discipline_violation
    ADD CONSTRAINT trade_discipline_violation_tenant_id_owner_user_id_reason__fkey FOREIGN KEY (tenant_id, owner_user_id, reason_id) REFERENCES public.trade_discipline_reason(tenant_id, owner_user_id, id) ON DELETE RESTRICT;


--
-- PostgreSQL database dump complete
--
