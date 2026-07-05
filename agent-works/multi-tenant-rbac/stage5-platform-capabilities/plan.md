# 第五阶段开发计划：平台能力闭环

## 1. 需求来源与目标

### 1.1 需求来源

- 需求文档：`agent-works/multi-tenant-rbac/requirement.md`
- 页面原型：
  - `agent-works/multi-tenant-rbac/prototypes/data-dictionary.html`
  - `agent-works/multi-tenant-rbac/prototypes/audit-log.html`
- 当前阶段分支：`codex/multi-tenant-rbac-stage5`
- 当前阶段输出目录：`agent-works/multi-tenant-rbac/stage5-platform-capabilities/`

### 1.2 本阶段目标

第五阶段进入平台能力补齐，目标是把多租户 RBAC 后续依赖的“配置防滥用、审计可追溯、枚举可治理”做成可上线闭环：

- R16：在已有系统配置页补齐注册防滥用开关，使登录、注册、验证码链路读取运行时配置。
- R17：新增日志审计能力，覆盖 API、安全、任务、配置和关键管理行为，支持系统管理员全局查看、租户管理员查看本租户。
- R18：新增数据字典能力，支持系统管理员维护平台级枚举类型和枚举项，业务消费端具备默认值兜底。
- R19 剩余部分：将 R16 相关开关接入已有 `/system/config/system`，不新增单独配置页。
- 同步前端路由、菜单、权限种子、接口封装、页面布局、空态、错误态和测试。

### 1.3 本阶段不做

- 不实现审计日志导出，页面只保留禁用入口或不展示导出操作。
- 不实现审计日志自动归档、保留周期、冷存储或批量清理策略，该内容归入后续运维能力。
- 不实现 R24 字段级变更差异审计，只记录操作摘要、目标、结果和脱敏上下文。
- 不实现 `data_dimension_registry`，该项按需求文档遗留确认项延后。
- 不把字典服务改造成通用配置中心，首批只覆盖稳定枚举和页面展示所需枚举。

## 2. 当前项目依据

### 2.1 后端现状

- `backend/config/settings.py`
  - `AuthConfig` 已有 `require_email_code`、`login_captcha_enabled`、`captcha_after_fails`、验证码 TTL 和基础限流配置。
  - `get_effective_settings()` 已支持从 PostgreSQL `app_config` 合并运行时配置。
- `backend/services/auth_service.py`
  - 当前初始化使用 `get_settings().auth`，只能读静态 YAML。
  - 登录已包含图形验证码失败次数判断；注册已包含邮箱验证码开关；公共配置接口已返回验证码相关配置。
  - 本阶段要把这些读取切到有效配置，确保系统配置保存后实际生效。
- `backend/storage/app_config.py`
  - `CONFIG_GROUPS` 控制系统设置白名单和前端分组渲染。
  - 当前已有数据源、股票池、成本、TopN、隐藏调度配置组。
  - 本阶段要新增认证/防滥用配置组，并继续复用 `/api/data/settings`。
- `backend/api/data_admin.py`
  - `/api/data/settings` 已由 `data-settings:manage` 保护，适合作为 R16 配置落点。
- `backend/storage/pg_ddl.py`
  - 当前集中维护 PostgreSQL 表结构、菜单种子、资源种子和阶段补丁标记。
  - 本阶段要新增审计表、字典表、菜单、资源码和租户管理员审计授权补丁。
- `backend/auth/deps.py`
  - 已有 `require_perm`、`require_system_perm`，并暴露资源码元数据，可继续用于路由扫描。
- `backend/auth/middleware.py`
  - `AuthMiddleware` 默认拒绝未鉴权业务端点。
  - `SecurityMiddleware` 已做 API 速率限制，本阶段需要补审计记录。
- `backend/services/async_task.py`、`backend/scheduler/scheduler.py`
  - 已有异步任务和调度任务状态流转，本阶段在关键状态变化处补审计事件。

### 2.2 前端现状

- `frontend/src/router/index.ts`
  - 已有系统设置拆分路由和系统管理路由，待新增日志审计、数据字典路由。
- `frontend/src/views/ConfigView.vue`
  - 已支持 `/system/config/system` 通过后端配置组动态渲染表单。
  - 本阶段只需补认证/防滥用配置项展示文案和保存体验，不新增页面。
- `frontend/src/views/system/UserManageView.vue`
  - 可作为系统管理页表格、筛选、分页、错误态、弹窗编辑和权限按钮参考。
- `frontend/src/layout/pageRegistry.ts`
  - 页面布局注册集中维护，本阶段要新增日志审计和数据字典页面布局项。
- `frontend/src/api/data.ts`
  - 已有系统设置接口封装。
  - 本阶段新增 `audit.ts`、`dict.ts`，保持 API 模块边界清晰。

### 2.3 既有约束

- 新业务端点必须有 `require_perm` 或 `require_system_perm`，并同步 `sys_resource` 种子和路由扫描测试。
- 新页面必须同步路由、菜单种子、功能点种子、按钮 `v-permission`、默认角色授权决策。
- 用户私有数据需要租户和用户归属条件；本阶段审计查询按租户隔离，数据字典为平台级系统配置，不归属个人。
- 禁止跨库 JOIN；审计和字典均落 PostgreSQL，不与 DuckDB 直接 JOIN。

## 3. 实施范围

### 3.1 需求映射

| 需求 | 本阶段处理方式 | 验收点 |
| --- | --- | --- |
| R16 注册防滥用配置 | 在 `app_config` 白名单新增认证配置组，登录/注册/公共配置读取有效配置 | 系统管理员可保存开关，注册和登录链路即时按配置执行 |
| R17 日志审计 | 新增 PG 审计表、审计服务、查询 API、前端审计页和关键链路埋点 | 系统管理员看全局，租户管理员只看本租户；写审计失败不阻塞主流程 |
| R18 数据字典 | 新增字典类型/字典项表、服务、API、前端维护页和默认字典种子 | 系统管理员可维护字典；消费者缺失或异常时回退默认枚举 |
| R19 系统配置剩余 | 在已有 `/system/config/system` 页面接入 R16 配置项 | 不新增配置页，继续复用已有保存权限 |
| R23/R24/R25 后续能力 | 本阶段只保留扩展点，不实现完整运维策略和字段级差异 | 计划和代码边界清晰，无伪实现 |

### 3.2 页面范围

- 新增页面：`/system/audit`，页面名称“日志审计”。
- 新增页面：`/system/dicts`，页面名称“数据字典”。
- 修改页面：`/system/config/system`，增加注册防滥用配置分组。

### 3.3 接口范围

- 新增审计接口：
  - `GET /api/audit`：分页查询审计日志。
  - `GET /api/audit/summary`：按筛选条件返回统计卡片数据。
  - `GET /api/audit/{id}`：查询单条审计详情。
- 新增数据字典接口：
  - `GET /api/dict/types`：查询字典类型。
  - `POST /api/dict/types`：新增字典类型。
  - `PUT /api/dict/types/{code}`：修改字典类型。
  - `DELETE /api/dict/types/{code}`：删除未被使用或无明细的字典类型。
  - `GET /api/dict/items`：按类型查询字典项。
  - `POST /api/dict/items`：新增字典项。
  - `PUT /api/dict/items/{type_code}/{code}`：修改字典项。
  - `DELETE /api/dict/items/{type_code}/{code}`：删除字典项。
- 复用配置接口：
  - `GET /api/data/settings`
  - `POST /api/data/settings`

## 4. 技术方案

### 4.1 数据库与种子

#### 4.1.1 新增审计表

在 `backend/storage/pg_ddl.py` 增加 PostgreSQL 表结构：

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    event_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    tenant_id TEXT,
    actor_user_id TEXT,
    actor_account TEXT,
    event_category TEXT NOT NULL,
    event_type TEXT NOT NULL,
    resource_code TEXT,
    action TEXT,
    target_type TEXT,
    target_id TEXT,
    target_label TEXT,
    result TEXT NOT NULL,
    status TEXT NOT NULL,
    ip TEXT,
    method TEXT,
    path TEXT,
    duration_ms INTEGER,
    error_summary TEXT,
    context JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

索引：

- `audit_log(event_time DESC)`
- `audit_log(tenant_id, event_time DESC)`
- `audit_log(event_category, event_time DESC)`
- `audit_log(event_type, event_time DESC)`
- `audit_log(resource_code, event_time DESC)`
- `audit_log(result, event_time DESC)`

审计上下文只允许存脱敏字段，例如 `request_id`、`permission_code`、`task_id`、`job_id`、`action`、`affected_count`、`rate_limit_rule`、`config_key`。禁止保存原始请求体、响应体、密码、Token、验证码、身份证、邮箱验证码明文等敏感内容。

#### 4.1.2 新增字典表

```sql
CREATE TABLE IF NOT EXISTS dict_type (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    sort INTEGER NOT NULL DEFAULT 100,
    remark TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dict_item (
    type_code TEXT NOT NULL REFERENCES dict_type(code) ON DELETE CASCADE,
    code TEXT NOT NULL,
    label TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    sort INTEGER NOT NULL DEFAULT 100,
    remark TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (type_code, code)
);
```

索引：

- `dict_item(type_code, enabled, sort, code)`
- `dict_type(enabled, sort, code)`

首批默认字典类型：

- `role_type`：角色类型。
- `user_status`：用户状态。
- `audit_event_type`：审计事件类型。
- `audit_result`：审计结果。
- 可补入当前页面已经稳定使用且不会造成业务语义漂移的枚举。

#### 4.1.3 菜单与资源码

新增资源码：

- `audit:view`：查看审计日志。
- `dict:view`：查看数据字典。
- `dict:type-manage`：维护字典类型。
- `dict:item-manage`：维护字典项。

菜单策略：

- `/system/audit`：登录可见菜单，默认授予系统管理员和租户管理员。
- `/system/dicts`：系统管理员菜单，默认只授予系统管理员。

种子补丁：

- 在 `pg_ddl.py` 增加阶段五迁移标记，例如 `migration.stage5_platform_capabilities_v1`。
- 回填新增菜单、资源码和租户管理员 `audit:view` 授权。
- 授权变更与 `perm_ver` 自增保持同一 PG 事务。

SQL 留痕：

- 新增 `agent-works/multi-tenant-rbac/stage5-platform-capabilities/stage5-platform-capabilities.sql`。
- 新增 `agent-works/multi-tenant-rbac/stage5-platform-capabilities/resource-codes.sql`。

### 4.2 R16 注册防滥用配置

#### 4.2.1 后端配置组

在 `backend/storage/app_config.py` 的 `CONFIG_GROUPS` 新增认证/防滥用配置组：

- `auth.require_email_code`：注册是否必须邮箱验证码，默认 `true`。
- `auth.login_captcha_enabled`：是否启用登录图形验证码，默认 `false`。
- `auth.captcha_after_fails`：失败多少次后要求验证码，默认 `3`。

可视实际已有字段一并纳入：

- `auth.login_rate_per_min`
- `auth.register_rate_per_hour`
- `auth.email_code_rate_per_hour`

这些字段只作为防滥用阈值，不扩展成完整风控系统。

#### 4.2.2 生效链路

- 将 `AuthService` 中认证配置读取从 `get_settings().auth` 调整为有效配置读取。
- `public_config()` 返回有效配置，保证登录/注册页面与服务端校验一致。
- `login()`、`register()`、`send_email_code()` 使用同一口径的有效配置。
- 如果配置缺失、类型错误或 PG 不可用，回退 `settings.yaml` 默认配置。

#### 4.2.3 配置审计

- `POST /api/data/settings` 保存认证相关配置时记录 `config` 类审计事件。
- 审计上下文只记录配置 key、是否成功、影响数量，不记录敏感配置值。
- 审计写入失败只写应用日志，不影响配置保存。

### 4.3 R17 日志审计

#### 4.3.1 后端模块

新增模块：

- `backend/storage/audit_repository.py`
- `backend/services/audit_service.py`
- `backend/api/audit.py`

服务职责：

- 提供 `record_event()`、`record_api_event()`、`record_security_event()`、`record_task_event()`、`record_config_event()` 等窄入口。
- 内部统一做字段裁剪、上下文脱敏、异常吞吐和日志降级。
- 查询时统一执行权限范围过滤。

查询规则：

- 系统管理员：可按租户、事件类型、结果、资源、时间、关键字筛选全局日志。
- 租户管理员：只能查看 `tenant_id = 当前租户` 的日志，不允许通过参数越权查看其他租户。
- 普通用户和付费用户：默认不授予审计菜单与资源码。

#### 4.3.2 API 审计

实现轻量审计中间件或请求结束钩子：

- 覆盖业务 `/api/**` 请求。
- 记录方法、路径、状态码、耗时、资源码、租户、操作者、结果。
- 对 `/api/audit/**` 做递归保护，避免查询日志产生无限审计写入。
- 请求体和响应体不入库。

资源码来源：

- 在 `require_perm`、`require_system_perm` 鉴权依赖中写入当前请求审计上下文。
- 请求完成后由审计记录读取该资源码。
- 对公开认证接口和中间件拒绝类事件，由调用点显式写入事件类型。

#### 4.3.3 安全事件审计

需要记录：

- 登录成功。
- 登录失败。
- 账号锁定或禁用导致登录失败。
- 验证码失败。
- 邮箱验证码发送频率限制命中。
- 注册失败。
- Token 刷新失败或登出撤销。
- 403 权限拒绝。
- 429 速率限制命中。

安全事件中邮箱、手机号、账号等标识只保留必要展示值；验证码、Token、密码永不记录。

#### 4.3.4 任务事件审计

在以下位置补审计：

- `AsyncTaskService.create()`：任务创建。
- 任务状态变更为成功、失败、中断、取消、恢复时。
- 调度任务触发、跳过、失败时。

上下文字段：

- `task_id`
- `job_id`
- `task_type`
- `status`
- `duration_ms`
- `error_summary`

#### 4.3.5 管理行为审计

在以下高价值服务补显式审计：

- 系统配置保存。
- 数据字典类型/字典项新增、修改、删除、启停。
- 用户、角色、菜单、租户等 RBAC 管理操作。

字段级差异不在本阶段实现，只记录目标和结果。

### 4.4 R18 数据字典

#### 4.4.1 后端模块

新增模块：

- `backend/storage/dict_repository.py`
- `backend/services/dict_service.py`
- `backend/api/dicts.py`

服务规则：

- 类型编码和字典项编码只允许稳定 code 格式，例如小写字母、数字、下划线、短横线。
- 同一类型下 item code 唯一。
- 类型禁用后，默认查询仍可返回类型元数据，但业务消费只使用启用项。
- 删除类型前校验是否存在字典项；若选择级联删除必须在弹窗中明确提示，本阶段优先限制删除。
- 字典变更后记录审计事件。

兜底规则：

- 服务端提供内置默认字典常量。
- 查询字典失败、字典类型缺失或启用项为空时，消费者回退默认常量。
- 前端字典缓存查询失败时不阻断页面主流程，使用本地默认显示。

#### 4.4.2 首批消费者

优先接入不会改变业务判断的展示型枚举：

- 用户状态展示。
- 角色类型展示。
- 审计事件类型展示。
- 审计结果展示。

业务判断仍使用后端稳定 code，不依赖字典 label。

### 4.5 前端实现

#### 4.5.1 API 封装

新增：

- `frontend/src/api/audit.ts`
- `frontend/src/api/dict.ts`

要求：

- 类型定义与后端响应一致。
- 查询参数显式建模，不在组件内拼散乱对象。
- 错误处理交给页面状态，不在 API 层吞异常。

#### 4.5.2 路由与页面注册

修改：

- `frontend/src/router/index.ts`
- `frontend/src/layout/pageRegistry.ts`

新增路由：

- `/system/audit`：`AuditLogView.vue`
- `/system/dicts`：`DataDictionaryView.vue`

页面布局：

- 使用 `LayoutHost` 接入页面布局系统。
- 注册稳定页面 key，支持后续布局配置。
- 页面结构参考原型，不把原型批注按钮带入正式业务交互。

#### 4.5.3 日志审计页

新增 `frontend/src/views/system/AuditLogView.vue`。

布局：

- 顶部统计区：总事件、失败事件、拒绝事件、平均耗时等。
- 筛选区：时间范围、事件类型、结果、租户、操作者、资源码、关键字。
- 主表格：时间、事件、操作者、租户、资源、目标、结果、耗时、IP、操作。
- 详情区域：只读详情抽屉或详情面板，重点优化排版，采用分组描述、时间线和脱敏上下文结构化展示。

交互：

- 查询、重置、刷新。
- 自动刷新可作为明确开关，默认关闭。
- 导出不实现；如展示入口必须禁用并有简短提示。
- 空态和错误态必须是页面状态，不混入业务数据。

权限：

- 页面进入依赖菜单和 `audit:view`。
- 无写操作按钮。

#### 4.5.4 数据字典页

新增 `frontend/src/views/system/DataDictionaryView.vue`。

布局：

- 左侧字典类型列表：搜索、启用状态、排序、新建、编辑。
- 右侧字典项表格：按当前类型展示 code、label、sort、enabled、remark、actions。
- 新增/编辑统一使用居中弹窗，禁止使用抽屉编辑。
- 删除使用确认弹窗，明确影响范围。

交互：

- 类型切换自动加载字典项。
- 新增/编辑类型。
- 新增/编辑/删除/启停字典项。
- 保存后刷新当前类型和字典项，清理前端字典缓存。
- 空态和错误态明确区分页面真实状态和原型说明。

权限：

- `dict:view`：查看。
- `dict:type-manage`：类型新增、编辑、删除、启停。
- `dict:item-manage`：字典项新增、编辑、删除、启停。

#### 4.5.5 系统配置页

修改 `frontend/src/views/ConfigView.vue`：

- `/system/config/system` 展示认证/防滥用配置组。
- 优化系统设置页说明文案，避免只描述数据源、股票池等旧配置。
- 保存成功后提示配置已更新，并依赖后端有效配置即时生效。

### 4.6 测试方案

#### 4.6.1 后端测试

新增或扩展：

- `backend/tests/test_stage5_auth_config.py`
  - `app_config` 覆盖 `require_email_code` 后注册链路按有效配置执行。
  - `login_captcha_enabled`、`captcha_after_fails` 对登录验证码要求生效。
  - `public-config` 返回有效配置。
- `backend/tests/test_stage5_audit.py`
  - 审计事件可写入、分页查询、详情查询。
  - 系统管理员可查全局。
  - 租户管理员只能查本租户。
  - 审计写入异常不阻断主流程。
  - 上下文不保存密码、Token、验证码等敏感字段。
- `backend/tests/test_stage5_dicts.py`
  - 字典类型和字典项 CRUD。
  - 重复 code 拒绝。
  - 禁用项不进入业务启用项查询。
  - 字典缺失或异常时回退默认值。
- `backend/tests/test_stage5_resource_codes.py`
  - 新增路由均有精确权限依赖。
  - `audit:view` 授予租户管理员。
  - 字典管理资源只授予系统管理员。
  - 新增菜单和资源码种子完整。
- 扩展现有菜单守卫测试：
  - 租户管理员可看到日志审计菜单。
  - 普通用户/付费用户默认看不到日志审计和数据字典。

#### 4.6.2 前端测试

新增或扩展 Vitest：

- 审计页：
  - 初始加载、筛选、重置、刷新。
  - 空态、错误态、重试。
  - 详情展示为只读，事件上下文结构化展示。
- 数据字典页：
  - 类型列表和字典项联动。
  - 新增/编辑使用 `el-dialog`，不使用抽屉。
  - 权限按钮按 `v-permission` 控制。
  - 空态、错误态、重试。
- 系统配置页：
  - 后端返回认证配置组时能正确渲染布尔、数字输入。
  - 保存认证配置调用已有保存接口。
- 路由和页面注册：
  - 新页面路由可解析。
  - 页面布局 key 注册完整。

#### 4.6.3 构建与验证命令

后端：

```bash
python -m pytest backend/tests/test_stage5_auth_config.py -q
python -m pytest backend/tests/test_stage5_audit.py -q
python -m pytest backend/tests/test_stage5_dicts.py -q
python -m pytest backend/tests/test_stage5_resource_codes.py -q
python -m pytest backend/tests/test_stage4_menu_guard.py -q
```

前端：

```bash
cd frontend && npm run test -- --run
cd frontend && npm run build
```

页面验证：

- 使用专用端口 `5181` 做页面截图/交互验证。
- 验证 `/system/audit` 和 `/system/dicts` 在桌面宽度下无重叠、表格可用、弹窗正常。
- 验证移动或窄屏下筛选区、表格、详情区不挤压错位。

## 5. 执行任务拆分

### T1. 数据库、菜单、资源码和 SQL 留痕

状态：待开始

改动文件：

- `backend/storage/pg_ddl.py`
- `backend/auth/constants.py`
- `agent-works/multi-tenant-rbac/stage5-platform-capabilities/stage5-platform-capabilities.sql`
- `agent-works/multi-tenant-rbac/stage5-platform-capabilities/resource-codes.sql`

任务：

- 新增 `audit_log`、`dict_type`、`dict_item` 表结构和索引。
- 新增菜单 `/system/audit`、`/system/dicts`。
- 新增资源码 `audit:view`、`dict:view`、`dict:type-manage`、`dict:item-manage`。
- 系统管理员默认拥有全部新增资源。
- 租户管理员默认拥有 `audit:view` 和审计菜单。
- 新增阶段五迁移标记和回填逻辑。
- 输出 SQL 留痕文件。

验收：

- 初始化或迁移后表、菜单、资源码存在。
- 重复执行初始化不报错、不重复授权。
- 租户管理员 `perm_ver` 在授权回填时同步更新。

### T2. R16 运行时认证配置

状态：待开始

改动文件：

- `backend/storage/app_config.py`
- `backend/services/auth_service.py`
- `backend/api/auth.py`
- `backend/api/data_admin.py`
- `frontend/src/views/ConfigView.vue`

任务：

- 增加认证/防滥用配置组。
- 登录、注册、验证码、公共配置读取有效配置。
- 配置保存后记录配置审计。
- 系统配置页展示新增配置组并保持通用表单体验。

验收：

- 关闭 `require_email_code` 后注册不再要求邮箱验证码。
- 开启 `login_captcha_enabled` 后登录按失败次数要求验证码。
- `/api/auth/public-config` 返回与系统配置一致的有效值。
- 配置异常时回退默认值，不导致认证接口 500。

### T3. 审计后端查询闭环

状态：待开始

改动文件：

- `backend/storage/audit_repository.py`
- `backend/services/audit_service.py`
- `backend/api/audit.py`
- `backend/main.py`

任务：

- 实现审计写入、查询、汇总、详情。
- 实现系统管理员全局范围和租户管理员租户范围。
- 审计服务统一脱敏、裁剪上下文。
- 审计写入失败降级到应用日志。

验收：

- 审计查询支持分页和筛选。
- 租户管理员无法通过参数查询其他租户日志。
- 审计上下文没有敏感明文。
- 审计写入异常不影响主业务响应。

### T4. 审计埋点接入

状态：待开始

改动文件：

- `backend/auth/deps.py`
- `backend/auth/middleware.py`
- `backend/services/auth_service.py`
- `backend/services/async_task.py`
- `backend/scheduler/scheduler.py`
- 相关 RBAC 管理服务文件

任务：

- 鉴权依赖写入当前请求资源码上下文。
- API 请求完成后记录方法、路径、状态码、耗时、资源码、结果。
- 登录、注册、验证码、限流、403、Token 撤销记录安全事件。
- 异步任务和调度任务状态变化记录任务事件。
- 配置、字典、RBAC 高价值管理操作记录管理事件。

验收：

- 成功、失败、拒绝、限流均有可查询审计记录。
- 审计 API 本身不会造成递归写入。
- 主链路不因审计服务异常失败。

### T5. 数据字典后端闭环

状态：待开始

改动文件：

- `backend/storage/dict_repository.py`
- `backend/services/dict_service.py`
- `backend/api/dicts.py`
- `backend/main.py`

任务：

- 实现字典类型和字典项 CRUD。
- 实现默认字典种子和启用项查询。
- 实现字典缺失/异常兜底。
- 变更时记录审计事件。

验收：

- code 唯一性和格式校验生效。
- 禁用项不作为业务启用项返回。
- 删除有明细的类型被阻止或有明确确认策略。
- 字典服务异常时消费者能回退默认枚举。

### T6. 前端路由、API 和页面注册

状态：待开始

改动文件：

- `frontend/src/router/index.ts`
- `frontend/src/layout/pageRegistry.ts`
- `frontend/src/api/audit.ts`
- `frontend/src/api/dict.ts`

任务：

- 新增审计和字典 API 类型封装。
- 新增 `/system/audit`、`/system/dicts` 路由。
- 新增页面布局注册项。
- 确认菜单 path 与前端 route path 一致。

验收：

- 路由可解析。
- 页面布局系统能识别新增页面。
- API 类型与后端响应契约一致。

### T7. 日志审计前端页面

状态：待开始

改动文件：

- `frontend/src/views/system/AuditLogView.vue`
- 可能新增局部组件或测试文件

任务：

- 按原型实现统计、筛选、表格和详情。
- 优化详情排版，事件基础信息、目标、执行结果、事件上下文分组展示。
- 实现空态、错误态、重试。
- 自动刷新作为明确开关，默认关闭。
- 导出入口不实现或保持禁用。

验收：

- 页面只读，无误导性编辑操作。
- 详情展示直观，脱敏上下文可读。
- 窄屏和桌面下无明显重叠。

### T8. 数据字典前端页面

状态：待开始

改动文件：

- `frontend/src/views/system/DataDictionaryView.vue`
- 可能新增局部组件或测试文件

任务：

- 按原型实现左类型、右字典项的主从布局。
- 新增/编辑类型和字典项均使用 `el-dialog`。
- 实现搜索、启停、排序、删除确认。
- 保存后刷新当前数据并清理字典缓存。
- 实现空态、错误态、重试。

验收：

- 无抽屉编辑交互。
- 操作按钮带对应 `v-permission`。
- 删除和禁用有明确反馈。

### T9. 自动化测试与权限扫描

状态：待开始

改动文件：

- `backend/tests/test_stage5_auth_config.py`
- `backend/tests/test_stage5_audit.py`
- `backend/tests/test_stage5_dicts.py`
- `backend/tests/test_stage5_resource_codes.py`
- `frontend/src/views/system/__tests__/AuditLogView.spec.ts`
- `frontend/src/views/system/__tests__/DataDictionaryView.spec.ts`
- 相关既有测试文件

任务：

- 覆盖 R16、R17、R18 后端行为。
- 覆盖新增路由权限和菜单授权。
- 覆盖前端页面主路径、错误态、空态和权限按钮。
- 确保阶段四既有权限测试不回归。

验收：

- 后端新增测试通过。
- 前端 Vitest 通过。
- `npm run build` 通过。

### T10. 开发留痕与业务闭环核查

状态：待开始

改动文件：

- `agent-works/multi-tenant-rbac/development-trace.md` 或同功能目录内留痕文件
- `agent-works/multi-tenant-rbac/business-audit.md` 或同功能目录内核查文件

任务：

- 开发完成后更新本阶段开发留痕。
- 按多租户 RBAC 业务链路核查审计、字典、配置是否闭环。
- 记录未实现项和后续阶段风险。

验收：

- 文档能说明本阶段改了什么、为什么、如何验证。
- 风险项与需求文档遗留确认项一致。

## 6. 实施顺序

1. T1：先落数据库、菜单、资源码和 SQL 留痕，保证后续接口有权限基础。
2. T2：接入 R16 运行时认证配置，复用已有配置页。
3. T3：实现审计后端查询闭环。
4. T5：实现数据字典后端闭环。
5. T4：在认证、鉴权、任务、配置、字典、RBAC 操作中补审计埋点。
6. T6：补前端 API、路由和页面布局注册。
7. T7：实现日志审计页。
8. T8：实现数据字典页。
9. T9：补测试并跑后端、前端验证。
10. T10：输出开发留痕和业务闭环核查。

说明：T3 和 T5 可并行开发，但 T4 依赖 T3 的审计服务稳定；T7/T8 依赖 T6 和对应后端接口契约。

## 7. 风险与处理

| 风险 | 影响 | 处理 |
| --- | --- | --- |
| 审计量增长快 | PG 表增长、查询变慢 | 本阶段加索引、分页和筛选；保留后续归档/清理扩展点 |
| 审计写入影响主链路 | 登录、配置、任务等核心操作失败 | 审计服务内部吞异常并写应用日志，主链路不回滚 |
| 审计记录泄露敏感信息 | 安全风险 | 统一上下文白名单，禁止原始请求体和敏感字段入库 |
| 租户管理员审计越权 | 可看到其他租户操作 | 查询服务强制追加当前租户条件，系统管理员才允许全局 |
| 字典 label 被误用于业务判断 | 业务逻辑漂移 | 业务判断只使用稳定 code，字典只负责展示和管理 |
| 认证配置运行时读取增加 PG 依赖 | 登录链路受 PG 波动影响 | 读取失败回退静态默认值；只在认证入口读取有效配置 |
| 新菜单和资源码漏 seed | 页面不可见或接口 403 | 路由扫描测试、菜单守卫测试和 SQL 留痕同时覆盖 |

## 8. 验收清单

- [ ] 系统管理员可以在 `/system/config/system` 修改注册防滥用配置。
- [ ] 登录、注册、验证码接口按系统配置即时生效。
- [ ] 审计日志能记录 API、安全、任务、配置、字典和关键 RBAC 操作。
- [ ] 审计写入失败不会阻塞业务接口。
- [ ] 系统管理员可查看全局审计。
- [ ] 租户管理员只能查看本租户审计。
- [ ] 数据字典类型和字典项可维护，且使用弹窗编辑。
- [ ] 字典服务异常或字典项缺失时业务展示有默认值兜底。
- [ ] 新增页面路由、菜单、资源码、按钮权限、默认授权决策完整。
- [ ] 空态、错误态、重试态在审计页和字典页可见且不混入原型说明。
- [ ] 后端阶段五测试通过。
- [ ] 前端 Vitest 和 `npm run build` 通过。
- [ ] SQL 留痕、开发留痕和业务闭环核查完成。

