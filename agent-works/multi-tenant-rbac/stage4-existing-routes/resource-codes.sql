-- ============================================================================
-- 多租户 RBAC 阶段四（stage4-existing-routes）资源码矩阵 —— 既有库一次性回填 + 人读留痕
-- ----------------------------------------------------------------------------
-- 用途：
--   1) 把阶段四为 13 个存量业务路由固化的精确资源码（sys_resource）写入既有 PG 库；
--   2) 为 normal/paid/tenant_admin 内置角色写默认业务授权（sys_role_resource），一次性、
--      ON CONFLICT DO NOTHING，不覆盖管理员在角色页的后续手工调整；
--   3) 为 system 角色幂等补齐全量新资源（角色页「全选+锁定」展示；运行时 system 由
--      perm_resolver 判全量兜底）；
--   4) 回填后对受影响用户（全部非 system 用户）bump perm_ver，让旧 token 失效、强制重登，
--      避免 Redis auth:perms:* 缓存继续按旧权限集服务。
--
-- 权威口径：新装库以 backend/storage/pg_ddl.py 的 seed（_SEED_RESOURCES /
--   _SHARED_RESOURCE_CODES / _BUSINESS_RESOURCE_CODES / _seed_role_grants）为准（阶段四 T2 落地）。
--   本文件是**既有库升级**的一次性脚本 + 矩阵留痕，须与 pg_ddl.py seed 保持一致（发布前校验）。
--
-- 执行时机：
--   - 开发期：T2 完成后在测试 PG 执行，或由迁移/CLI 包装执行；
--   - 上线期：停服（./start.sh stop）→ 备份 PG 权限表 → 部署阶段四代码 → 执行本脚本一次 → 启动。
--   - 必须在阶段四**代码已部署**后执行：baseline 共享读码（layout:view /
--     trade-calendar:view / indicator:registry）由 perm_resolver 对非 system 用户**强制注入**，
--     本脚本只负责 sys_resource 落行 + perm_ver bump；不写 baseline 的 sys_role_resource 授权行。
--
-- 影响范围：sys_resource（+38 行）、sys_role_resource（业务/ system 授权）、sys_user.perm_ver。
--   不改资产表结构，不改行情 DuckDB。
--
-- 回滚：删除本脚本新增资源码（sys_role_resource 随 FK ON DELETE CASCADE 清理）需**同步回滚代码**
--   中对应 require_perm/require_system_perm，否则接口因资源码缺失导致非 system 无法授权。执行过
--   perm_ver bump 的，回滚后相关用户需再登录一次。不涉及不可逆迁移。
--
-- 事务：整脚本单事务提交，保证「资源落行 + 授权 + perm_ver bump」原子，无「授权已变/版本未进」窗口。
-- ============================================================================

-- 约定：sys_resource.id = code（全局唯一）；menu_id = 归属菜单 code（FK→sys_menu.id）。
-- type 一律 'api'（接口级）；api_method/api_path 记录绑定端点（多端点共码时记代表端点）。

BEGIN;

-- ────────────────────────────────────────────────────────────────────────
-- 1) 资源码落行（sys_resource）
--    分三类：A=baseline 登录基线共享读（挂 login 菜单，force-inject，角色页锁定不可反选）；
--            B=可授权业务码（挂 login 菜单，默认授 normal/paid/tenant_admin）；
--            C=system-only（挂 visible='system' 菜单，system_only_resource_ids 自动拦截授非 system）。
-- ────────────────────────────────────────────────────────────────────────

INSERT INTO sys_resource (id, menu_id, code, name, type, api_method, api_path, sort, is_builtin) VALUES
  -- ── A) baseline 登录基线共享读（挂 login 叶子作 FK 锚点；菜单归属仅供角色页分组，运行时由 resolver 强制注入）──
  ('layout:view',          '/board',  'layout:view',          '布局生效配置读（全站基线）',   'api', 'GET',    '/api/layout/effective/{page_key}', 10, TRUE),
  ('trade-calendar:view',  '/board',  'trade-calendar:view',  '交易日历读（全站基线）',       'api', 'GET',    '/api/data/trade-dates',            20, TRUE),
  ('indicator:registry',   '/screen', 'indicator:registry',   '指标目录读（研究基线）',       'api', 'GET',    '/api/indicators/registry',         10, TRUE),

  -- ── B) 每日榜单（/board，login）──
  ('board:view',           '/board',  'board:view',           '查看每日榜单',   'api', 'GET',  '/api/scores/top',      30, TRUE),
  ('board:compute',        '/board',  'board:compute',        '榜单即时计算',   'api', 'GET',  '/api/board/compute',   40, TRUE),
  ('score:run',            '/board',  'score:run',            '评分方案打分',   'api', 'POST', '/api/score-profiles/run', 50, TRUE),
  ('layout:user-config',   '/board',  'layout:user-config',   '保存个人页面偏好', 'api', 'POST', '/api/layout/users/{page_key}', 60, TRUE),

  -- ── B) 策略筛选（/screen，login）──
  ('screen-profile:view',   '/screen', 'screen-profile:view',   '查看筛选方案', 'api', 'GET',    '/api/profiles',        20, TRUE),
  ('screen-profile:save',   '/screen', 'screen-profile:save',   '保存筛选方案', 'api', 'POST',   '/api/profiles',        30, TRUE),
  ('screen-profile:delete', '/screen', 'screen-profile:delete', '删除筛选方案', 'api', 'DELETE', '/api/profiles/{pid}',  40, TRUE),
  ('screen:run',            '/screen', 'screen:run',            '运行策略筛选', 'api', 'POST',   '/api/screen/run',      50, TRUE),

  -- ── B) 个股行情 + 自选分组（/stocks，login）──
  ('stocks:view',                '/stocks', 'stocks:view',                '查看个股行情',   'api', 'GET',    '/api/stocks',                        10, TRUE),
  ('stocks:trade-eval',          '/stocks', 'stocks:trade-eval',          '个股买卖评估',   'api', 'GET',    '/api/stocks/{code}/trade-eval',      20, TRUE),
  ('stock-group:view',           '/stocks', 'stock-group:view',           '查看自选分组',   'api', 'GET',    '/api/stock-groups',                  30, TRUE),
  ('stock-group:create',         '/stocks', 'stock-group:create',         '新建自选分组',   'api', 'POST',   '/api/stock-groups',                  40, TRUE),
  ('stock-group:update',         '/stocks', 'stock-group:update',         '编辑自选分组',   'api', 'PATCH',  '/api/stock-groups/{gid}',            50, TRUE),
  ('stock-group:delete',         '/stocks', 'stock-group:delete',         '删除自选分组',   'api', 'DELETE', '/api/stock-groups/{gid}',            60, TRUE),
  ('stock-group:member-update',  '/stocks', 'stock-group:member-update',  '维护分组成员',   'api', 'POST',   '/api/stock-groups/{gid}/members',    70, TRUE),

  -- ── B) 策略回测（/backtest，login）──
  ('backtest:view',    '/backtest', 'backtest:view',    '查看回测记录',   'api', 'GET',    '/api/backtest/runs',            10, TRUE),
  ('backtest:run',     '/backtest', 'backtest:run',     '运行回测',       'api', 'POST',   '/api/backtest/run',             20, TRUE),
  ('backtest:robust',  '/backtest', 'backtest:robust',  '稳健性测试',     'api', 'POST',   '/api/backtest/robust',          30, TRUE),
  ('backtest:delete',  '/backtest', 'backtest:delete',  '删除回测记录',   'api', 'DELETE', '/api/backtest/runs/{run_id}',   40, TRUE),

  -- ── B) 盘感训练（/training，login）──
  ('training:view',    '/training', 'training:view',    '查看训练记录',   'api', 'GET',    '/api/training/sessions',                10, TRUE),
  ('training:start',   '/training', 'training:start',   '创建训练',       'api', 'POST',   '/api/training/sessions',                20, TRUE),
  ('training:trade',   '/training', 'training:trade',   '训练过程操作',   'api', 'POST',   '/api/training/sessions/{sid}/trade',    30, TRUE),
  ('training:review',  '/training', 'training:review',  '保存训练复盘',   'api', 'PATCH',  '/api/training/sessions/{sid}/review',   40, TRUE),
  ('training:delete',  '/training', 'training:delete',  '删除训练',       'api', 'DELETE', '/api/training/sessions/{sid}',          50, TRUE),

  -- ── C) 配置管理（/system/config，system-only；含评分/买卖方案 API：本阶段页面仍 system-only，
  --        经菜单 visible='system' 自动进 system_only_resource_ids，非 system 授不了；阶段五拆页后移菜单开放）──
  ('score-profile:view',    '/system/config', 'score-profile:view',    '查看评分方案', 'api', 'GET',    '/api/score-profiles',           10, TRUE),
  ('score-profile:save',    '/system/config', 'score-profile:save',    '保存评分方案', 'api', 'POST',   '/api/score-profiles',           20, TRUE),
  ('score-profile:delete',  '/system/config', 'score-profile:delete',  '删除评分方案', 'api', 'DELETE', '/api/score-profiles/{pid}',     30, TRUE),
  ('trade-profile:view',    '/system/config', 'trade-profile:view',    '查看买卖方案', 'api', 'GET',    '/api/trade-profiles',           40, TRUE),
  ('trade-profile:save',    '/system/config', 'trade-profile:save',    '保存买卖方案', 'api', 'POST',   '/api/trade-profiles',           50, TRUE),
  ('trade-profile:delete',  '/system/config', 'trade-profile:delete',  '删除买卖方案', 'api', 'DELETE', '/api/trade-profiles/{pid}',     60, TRUE),
  ('trade-profile:preview', '/system/config', 'trade-profile:preview', '买卖条件试算', 'api', 'POST',   '/api/trade-profiles/preview',   70, TRUE),
  ('config:view',           '/system/config', 'config:view',           '查看系统配置', 'api', 'GET',    '/api/config',                   80, TRUE),
  ('config:reload',         '/system/config', 'config:reload',         '重载系统配置', 'api', 'POST',   '/api/config/reload',            90, TRUE),
  ('indicator:def-manage',  '/system/config', 'indicator:def-manage',  '技术指标定义维护', 'api', 'POST', '/api/indicators/def',         100, TRUE),

  -- ── C) 布局平台配置（system-only）──
  ('layout:preset-manage', '/system/layout/presets',    'layout:preset-manage', '布局预设管理',   'api', 'POST', '/api/layout/presets',            10, TRUE),
  ('layout:page-manage',   '/system/layout/pages',      'layout:page-manage',   '页面布局管理',   'api', 'POST', '/api/layout/pages/{page_key}',   10, TRUE),
  ('layout:field-policy',  '/system/layout/components', 'layout:field-policy',  '组件字段策略',   'api', 'POST', '/api/layout/field-policies',     10, TRUE),

  -- ── C) 数据管理（system-only，整 router 另有 require_system；此处补精确码供扫描/审计）──
  ('data:overview',        '/data/overview', 'data:overview',        '数据概览',     'api', 'GET',    '/api/data/overview',            10, TRUE),
  ('data-status:view',     '/data/overview', 'data-status:view',     '数据状态/更新日志', 'api', 'GET', '/api/data/status',           20, TRUE),
  ('data-quality:view',    '/data/quality',  'data-quality:view',    '数据质量查看', 'api', 'GET',    '/api/data/quality',             10, TRUE),
  ('data-quality:fix',     '/data/quality',  'data-quality:fix',     '数据质量处置', 'api', 'POST',   '/api/data/quality/fix-batch',   20, TRUE),
  ('data-schedule:manage', '/data/schedule', 'data-schedule:manage', '任务调度管理', 'api', 'POST',   '/api/data/schedules',           10, TRUE),
  ('data-source:test',     '/data/schedule', 'data-source:test',     '数据源测试',   'api', 'POST',   '/api/data/sources/test',        20, TRUE),
  ('data-settings:manage', '/data/schedule', 'data-settings:manage', '数据设置保存', 'api', 'POST',   '/api/data/settings',            30, TRUE),
  ('data-task:manage',     '/data/ingest',   'data-task:manage',     '采集任务管理', 'api', 'POST',   '/api/data/tasks',               10, TRUE)
ON CONFLICT (id) DO NOTHING;

-- ────────────────────────────────────────────────────────────────────────
-- 2) 默认业务授权（sys_role_resource）：normal / paid / tenant_admin ← _BUSINESS_RESOURCE_CODES
--    仅一次性 ON CONFLICT DO NOTHING；baseline（A 类）不写授权行（resolver 强制注入）；
--    system-only（C 类）不授非 system。tenant_admin 得业务码但仍不含数据管理/系统配置/布局平台/角色菜单租户管理。
-- ────────────────────────────────────────────────────────────────────────

INSERT INTO sys_role_resource (role_id, resource_id)
SELECT r.id, code
FROM (VALUES ('normal'), ('paid'), ('tenant_admin')) AS r(id)
CROSS JOIN (VALUES
  ('board:view'), ('board:compute'), ('score:run'), ('layout:user-config'),
  ('screen-profile:view'), ('screen-profile:save'), ('screen-profile:delete'), ('screen:run'),
  ('stocks:view'), ('stocks:trade-eval'),
  ('stock-group:view'), ('stock-group:create'), ('stock-group:update'), ('stock-group:delete'), ('stock-group:member-update'),
  ('backtest:view'), ('backtest:run'), ('backtest:robust'), ('backtest:delete'),
  ('training:view'), ('training:start'), ('training:trade'), ('training:review'), ('training:delete')
) AS b(code)
ON CONFLICT DO NOTHING;

-- ────────────────────────────────────────────────────────────────────────
-- 3) system 角色幂等补齐全量新资源（角色页「全选+锁定」展示；运行时 system 由 resolver 判全量兜底）。
--    包含 baseline 与 system-only 码；仅 system 角色。
-- ────────────────────────────────────────────────────────────────────────

INSERT INTO sys_role_resource (role_id, resource_id)
SELECT 'system', id FROM sys_resource
ON CONFLICT DO NOTHING;

-- ────────────────────────────────────────────────────────────────────────
-- 4) perm_ver bump：受影响 = 全部非 system 用户（新增业务授权 + baseline 强制注入均改变其有效权限集）。
--    与上文授权写入同事务，提交后旧 token 因 perm_ver 不匹配 401，强制重登；发布步骤须 best-effort 清 Redis auth:perms:*。
-- ────────────────────────────────────────────────────────────────────────

UPDATE sys_user
SET perm_ver = perm_ver + 1, updated_at = now()
WHERE id IN (
  SELECT DISTINCT ur.user_id
  FROM sys_user_role ur
  JOIN sys_role r ON r.id = ur.role_id
  WHERE r.code <> 'system'
);

COMMIT;

-- ============================================================================
-- 附：动态 scope 自守卫端点（不落 sys_resource，由函数体按 payload scope 内部守卫，扫描测试白名单）
--   POST /api/layout/reset —— scope=user → 当前用户（layout:user-config 语义）；scope=page → require_system()。
--   见 backend/api/layout.py:reset_layout_config；T8 需对每个 scope 分支专项测试。
--
-- 附：阶段四资源码统计
--   baseline 基线共享读（A）: 3   —— layout:view / trade-calendar:view / indicator:registry
--   可授权业务码（B）      : 24  —— board(3)+layout:user-config(1)+screen(4)+stocks/group(7)+backtest(4)+training(5)
--   system-only（C）       : 21  —— config/score/trade/indicator(10)+layout平台(3)+data(8)
--   合计新增 sys_resource   : 48
-- ============================================================================
