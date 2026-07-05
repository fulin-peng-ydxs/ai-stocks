# 开发计划

## 1. 需求来源与目标

- 需求文档：`agent-works/multi-tenant-rbac/requirement.md`
- 原型文件：
  - `agent-works/multi-tenant-rbac/prototypes/data-dictionary.html`
  - `agent-works/multi-tenant-rbac/prototypes/audit-log.html`
- 设计规范：
  - `DESIGN.md`
  - `agent-works/configurable-layout-system/page-template.md`
  - `agent-works/architecture/system-rbac-tenant.md`
- 功能目标：进入第五阶段，补齐平台能力闭环，包括 R16 注册防滥用配置、R17 日志审计、R18 数据字典，以及 R19 已拆页后的系统设置剩余接入。
- 本次不做：
  - 不做 R22 token 静默刷新。
  - 不做 R23 审计日志自动清理任务；但 R17 已确认的“保留 90 天可配”口径本阶段要保留为配置项、默认查询窗口和页面提示，后续 R23 清理任务复用该配置。
  - 不做 R24 字段级 from/to 变更对比。
  - 不做 R25 第三方登录真实对接。
  - 不做 R26 付费计费与配额消费。
  - 不做 R27 行情行为指纹、滑块挑战、第三方人机校验平台等高强度风控。
  - 不做 R28 中评分方案之外的其他资产公开能力。
  - 不把 `data_dimension_registry` 并入数据字典。
- 计划输出目录：`agent-works/multi-tenant-rbac/stage5-platform-capabilities/`

### 1.1 本次口径修订

- R16 “人机校验”本阶段不引入第三方挑战产品，按现有认证链路落为“登录人机校验（图形验证码）”：`auth.login_captcha_enabled` 控制开关，`auth.captcha_after_fails` 控制触发阈值。若后续要滑块、行为验证码或外部验证码服务，归 R27 或独立安全增强。
- R17 “保留 90 天可配”不等于本阶段自动删除历史数据。本阶段实现 `audit.retention_days` 的配置、读取、默认查询窗口和页面展示；R23 再实现定时清理任务。
- R18 字典类型删除采用服务层禁删有明细类型，数据库外键使用 `ON DELETE RESTRICT` 或默认限制，不使用 `ON DELETE CASCADE`。
- 原型中的琥珀批注和“原型演示”按钮只作为评审说明，正式页面不渲染这些批注按钮。

## 2. 当前项目依据

### 2.1 后端依据

- `backend/config/settings.py`
  - `AuthConfig` 已有 `require_email_code`、`login_captcha_enabled`、`captcha_after_fails`、验证码 TTL、登录/注册/邮箱码/API 限流字段。
  - `get_effective_settings()` 已支持从 PostgreSQL `app_config` 合并有效配置。
- `backend/services/auth_service.py`
  - 当前认证服务使用 `get_settings().auth`，只能读静态配置。
  - 登录、注册、发送邮箱验证码、公配置接口已有 R16 所需消费点，但需要切到有效配置。
- `backend/storage/app_config.py`
  - `CONFIG_GROUPS` 是系统设置白名单和前端动态渲染事实源。
  - 本阶段需要新增认证/防滥用配置组和审计保留期配置组。
- `backend/api/data_admin.py`
  - `/api/data/settings` 已使用 `require_system_perm("data-settings:manage")`，可复用为系统设置保存入口。
- `backend/storage/pg_ddl.py`
  - 集中维护 PostgreSQL DDL、菜单 seed、资源 seed、阶段迁移标记和内置角色授权回填。
  - 本阶段要新增 `audit_log`、`dict_type`、`dict_item`、菜单 `/system/audit`、`/system/dicts`、资源码和 tenant_admin 审计授权回填。
- `backend/auth/deps.py`
  - 已有 `require_perm(code)` 与 `require_system_perm(code)`；资源码元数据可被路由扫描和审计上下文复用。
- `backend/auth/middleware.py`
  - `AuthMiddleware` 对非白名单 `/api/**` 默认拒绝。
  - `SecurityMiddleware` 已有 API 速率限制，本阶段需要记录 429 安全审计。
- `backend/services/async_task.py`、`backend/scheduler/scheduler.py`
  - 已有异步任务、调度任务状态流转，本阶段接入任务审计。

### 2.2 前端依据

- `frontend/src/router/index.ts`
  - 已有静态路由表和系统设置拆分路由，新增页面必须在这里登记。
- `frontend/src/layout/pageRegistry.ts`
  - 是页面布局系统单一事实源，新增业务页面必须登记 `pageKey`、`archetype`、slots、可编辑旋钮和组件配置消费。
- `frontend/src/layout/archetypes.ts`
  - 已有 `list` 与 `master-detail` 原型，可直接承接日志审计页和数据字典页，不需要新增布局原型。
- `frontend/src/layout/components.ts`
  - 已有 `toolbar`、`filter-bar`、`kpi-grid`、`data-table`、`wide-table`、`simple-list`、`detail`、`description-list` 等组件种类，本阶段不新增组件种类。
- `frontend/src/views/ConfigView.vue`
  - 已支持 `/system/config/{score|trade|tech|system}`，系统设置页可通过后端配置组动态渲染字段。
- `frontend/src/views/system/UserManageView.vue`
  - 可作为系统管理页筛选、表格、分页、错误态、重试、`el-dialog` 编辑、按钮权限控制参考。
- `frontend/src/api/data.ts`
  - 已有系统设置接口封装，本阶段新增审计和字典 API 封装。

### 2.3 权限和页面接入依据

- 新页面不会因为新增 Vue 文件自动入侧栏，必须同步：
  - `frontend/src/router/index.ts`
  - `backend/storage/pg_ddl.py` 的 `_SEED_MENU_TREE`
  - `backend/storage/pg_ddl.py` 的 `_SEED_RESOURCES`
  - 后端接口守卫
  - 前端按钮 `v-permission`
  - 默认角色授权决策和已有库回填
- `/system/audit` 属租户管理员可见页面，上级菜单不能是 system-only；服务层必须按租户范围收口。
- `/system/dicts` 属 system-only 页面，菜单 `visible=system`，接口使用 system 守卫。
- 新业务页面必须走 `<LayoutHost>`，不得手写视口高度和并行布局外壳。

## 3. 实施范围

### 3.1 必须实现

| 需求编号 | 需求内容 | 本阶段开发内容 | 对应任务 | 完成标志 |
| --- | --- | --- | --- | --- |
| R16 | 注册防滥用开关化 | 新增认证/防滥用配置组，认证链路读取有效配置；“人机校验”落为登录图形验证码开关和失败阈值 | T2、T3、T10、T12、T13 | 系统管理员保存后登录/注册链路按新配置生效，非法/缺值回退默认 |
| R17 | 日志审计 | 新增审计表、服务、API、审计采集、审计查询页；保留期默认 90 天可配但不自动清理 | T1、T2、T4、T5、T7、T8、T11、T12、T13 | API/任务/安全/配置/字典/RBAC 事件可查；系统管理员全局，租户管理员本租户 |
| R18 | 数据字典 | 新增字典表、默认字典、服务、API、前端维护页、消费端默认值兜底和缓存失效 | T1、T6、T7、T9、T11、T12、T13 | 字典类型/项可维护；停用后新下拉不展示；异常时回退代码默认枚举 |
| R19 | 配置管理已拆页后的系统设置剩余项 | 在 `/system/config/system` 接入 R16 开关和 R17 保留期配置，不新增配置页 | T2、T3、T10、T13 | 系统设置页可展示、保存、读取并消费新增配置项 |
| 页面规范 | 新页面页面设计闭环 | 日志审计和数据字典补页面定位、原型承接、slot、配置层级、维护清单和关键视口验收 | T7、T8、T9、T13 | `pageRegistry`、路由、DESIGN 登记、视口验收和布局契约测试完整 |

### 3.2 可选增强

| 需求编号/增强编号 | 增强内容 | 需求阶段处理状态 | 开发状态 | 对应任务 | 说明 |
| --- | --- | --- | --- | --- | --- |
| R22 | token 静默刷新 | 阶段六体验增强 | 跳过 | - | 本阶段只消费既有登录态，不改 token 刷新策略 |
| R23 | 审计日志保留期自动清理任务 | 阶段六体验增强 | 跳过 | - | 自动删除任务跳过；R17 已确认的 `audit.retention_days=90` 配置和默认查询窗口纳入 T2/T4/T8 |
| R24 | 操作审计字段级变更对比 | 阶段六体验增强 | 跳过 | - | 本阶段只记录操作摘要、目标、结果和脱敏上下文，不记录 from/to 字段级差异 |
| R28 | 其他资产公开能力 | 独立需求，评分方案已在阶段四 B 完成 | 跳过 | - | 本阶段不扩展筛选方案、买卖方案、回测记录等公开能力 |

### 3.3 暂不实现

| 需求编号 | 需求项 | 开发状态 | 不做原因 | 后续触发条件 |
| --- | --- | --- | --- | --- |
| R25 | 第三方登录真实对接 | 跳过 | 本阶段不对接外部 OAuth 或短信服务 | 获取平台资质并单独立项 |
| R26 | 付费角色计费与配额 | 跳过 | 本阶段只沿用已有角色类型，不做商业化消费 | 商业化启动 |
| R27 | 高强度行情防爬 | 跳过 | 本阶段只保留现有接口限流、验证码和审计，不接行为风控 | 出现实际批量爬取或引入风控平台 |
| 遗留项 4 | `data_dimension_registry` 并入数据字典 | 跳过 | 需求明确本期不并入 | 后续重新评估数据维度和枚举边界 |

## 4. 技术方案

### 4.1 整体实现思路

第五阶段按“平台表结构和权限 seed → 运行时配置 → 审计基础服务 → 数据字典基础服务 → 审计埋点 → 前端页面 → 测试与发布”推进。

模块边界：

- 审计和字典均落 PostgreSQL，不与 DuckDB 做跨库 JOIN。
- 审计写入使用 best-effort 服务，任何写入异常只落应用日志，不阻断主业务。
- 字典消费使用稳定 code，label 只用于展示；字典缺失或服务异常时回退代码内置默认枚举。
- R16/R17 配置继续使用 `app_config` 平台级配置，由 `CONFIG_GROUPS` 统一白名单、校验和前端渲染。
- 新页面走 `LayoutHost` 和 `pageRegistry`，不新增布局原型、不新增组件种类、不新增未消费的“假配置”。

### 4.2 数据模型

#### 4.2.1 `audit_log`

建议字段：

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

保留期配置：

- `app_config` 新增 `audit.retention_days`，默认 `90`，范围建议 `7..365`。
- 本阶段消费方式：审计查询默认时间窗口为最近 `retention_days`；页面展示当前保留期配置；后续 R23 自动清理任务复用同一配置。
- 本阶段不删除历史数据。

上下文白名单：

- 允许：`request_id`、`permission_code`、`task_id`、`job_id`、`action`、`affected_count`、`rate_limit_rule`、`config_key`、`route`、`profile_ref`、`data_scope` 等脱敏摘要。
- 禁止：原始请求体、响应体、密码、Token、验证码、邮箱验证码、密钥、连接串、个人敏感明文。

#### 4.2.2 `dict_type` / `dict_item`

建议字段：

```sql
CREATE TABLE IF NOT EXISTS dict_type (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    sort INTEGER NOT NULL DEFAULT 100,
    remark TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dict_item (
    id TEXT PRIMARY KEY,
    type_code TEXT NOT NULL REFERENCES dict_type(code) ON DELETE RESTRICT,
    code TEXT NOT NULL,
    label TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    sort INTEGER NOT NULL DEFAULT 100,
    remark TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (type_code, code)
);
```

索引：

- `dict_type(enabled, sort, code)`
- `dict_item(type_code, enabled, sort, code)`

删除策略：

- 服务层阻止删除仍有字典项的类型。
- 数据库外键使用 `ON DELETE RESTRICT` 或默认限制，避免与服务层禁删口径冲突。

首批默认字典：

- `role_type`：`system`、`tenant_admin`、`normal`、`paid`
- `user_status`：`active`、`disabled`、`locked`
- `audit_event_type`：`api`、`task`、`security`、`rbac`、`config`、`dict`
- `audit_result`：`success`、`failed`、`denied`
- 少量稳定业务枚举可在实现时按现有代码确认后加入，但不得改变业务判断。

### 4.3 接口契约

#### 4.3.1 审计接口

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/audit` | `require_perm("audit:view")` | 分页查询审计日志 |
| GET | `/api/audit/summary` | `require_perm("audit:view")` | 当前筛选范围摘要指标 |
| GET | `/api/audit/{id}` | `require_perm("audit:view")` | 单条只读详情 |

查询参数：

- `page`、`page_size`
- `start_time`、`end_time`
- `event_category`、`event_type`
- `result`、`status`
- `resource_code`
- `actor_keyword`
- `target_keyword`
- `tenant_id`：仅系统管理员可用；租户管理员传入时忽略或拒绝，服务层强制当前租户范围。

响应要求：

- 沿用项目 `{code,msg,data}` 包装。
- 列表返回分页元数据。
- 详情返回结构化字段和脱敏 `context`。
- 不提供创建、修改、删除接口。

#### 4.3.2 数据字典接口

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/dict/types` | `require_system_perm("dict:view")` | 查询字典类型 |
| POST | `/api/dict/types` | `require_system_perm("dict:type-manage")` | 新增字典类型 |
| PUT | `/api/dict/types/{code}` | `require_system_perm("dict:type-manage")` | 修改字典类型 |
| DELETE | `/api/dict/types/{code}` | `require_system_perm("dict:type-manage")` | 删除无明细类型 |
| GET | `/api/dict/items` | `require_system_perm("dict:view")` | 管理端按类型查询字典项 |
| GET | `/api/dict/items/public` | `require_perm("dict:read")` | 消费端查询启用项，失败回退默认枚举 |
| POST | `/api/dict/items` | `require_system_perm("dict:item-manage")` | 新增字典项 |
| PUT | `/api/dict/items/{type_code}/{code}` | `require_system_perm("dict:item-manage")` | 修改字典项 |
| DELETE | `/api/dict/items/{type_code}/{code}` | `require_system_perm("dict:item-manage")` | 删除字典项 |

说明：

- 管理端 `/system/dicts` 仅系统管理员可见。
- `dict:read` 不对应菜单入口，是登录基线共享读能力，用于业务页面、审计页筛选项和后续下拉消费；无论采用接口还是服务调用，都必须有默认枚举兜底。
- 类型 code 和字典项 code 创建后不可修改；`PUT` 请求体不接受 code 变更，服务端以路径 code 定位并拒绝试图改 code 的请求。

### 4.4 权限策略

新增资源码：

- `audit:view`
- `dict:read`
- `dict:view`
- `dict:type-manage`
- `dict:item-manage`

菜单策略：

- `/system/audit`
  - 菜单可见性：`login`
  - 默认授权：system 全量；tenant_admin 一次性回填菜单和 `audit:view`
  - 服务层范围：system 全局；tenant_admin 当前租户
- `/system/dicts`
  - 菜单可见性：`system`
  - 默认授权：system 全量
  - 服务层范围：平台级，不按租户分表
- `dict:read`
  - 不对应菜单入口，作为登录用户共享只读资源。
  - 默认按登录基线共享读注入给有角色的非 system 用户；无角色仍 fail-closed。
  - seed 到 `sys_resource` 时 `menu_id` 挂 `/board` 这类 `visible=login` 的既有叶子菜单锚点，推荐沿用 `/board`；不得挂 `/system/dicts` 或任何 `visible=system` 菜单，避免被 system-only 资源判定逻辑误收口。

权限回填：

- 新增阶段五迁移标记，例如 `migration.stage5_platform_capabilities_v1`。
- 对已有 tenant_admin 回填审计菜单和 `audit:view` 时，同事务自增对应用户 `perm_ver`。
- normal、paid 不默认获得审计或字典管理权限，但有角色用户可获得 `dict:read` 共享只读能力。

### 4.5 审计采集方案

API 事件：

- 通过请求完成钩子或轻量中间件记录 `/api/**` 的方法、路径、状态码、耗时、资源码、租户、操作者、结果。
- `/api/audit/**` 做递归保护，避免审计查询自身造成无限写入。
- `require_perm` / `require_system_perm` 在请求上下文中写入 `permission_code`，供审计事件使用。

安全事件：

- 登录成功、登录失败、禁用/锁定用户登录、验证码失败、注册失败、邮箱码限流、429 限流、403 越权、登出 token 吊销。
- 安全事件只记录必要账号标识和风险规则，不记录密码、验证码或 token。

任务事件：

- `AsyncTaskService.create()` 记录任务创建。
- 任务成功、失败、中断、取消、恢复记录状态事件。
- 调度任务触发、跳过、失败记录 `job_id`、`task_id`、状态和错误摘要。

管理行为：

- 系统设置保存。
- 数据字典类型/项新增、修改、删除、启停。
- 用户、角色、菜单、资源、租户等 RBAC 关键管理操作。

字段差异：

- 本阶段不做 from/to 字段级对比；只记录目标、操作、结果、摘要和脱敏上下文。

### 4.6 配置闭环方案

R16 配置：

| 配置项 | 默认值 | 谁定义 | 谁保存 | 谁读取 | 谁消费 | 回退 |
| --- | --- | --- | --- | --- | --- | --- |
| `auth.require_email_code` | `true` | 系统管理员 | `app_config` | `AuthService`、`public_config` | 注册、发送邮箱码 | 静态默认值 |
| `auth.login_captcha_enabled` | `false` | 系统管理员 | `app_config` | `AuthService`、`public_config` | 登录失败后图形验证码挑战 | 静态默认值 |
| `auth.captcha_after_fails` | `3` | 系统管理员 | `app_config` | `AuthService`、`public_config` | 登录失败阈值 | 静态默认值 |
| `auth.login_rate_per_min` | 现有默认 | 系统管理员 | `app_config` | 认证/限流服务 | 登录限流 | 静态默认值 |
| `auth.register_rate_per_hour` | 现有默认 | 系统管理员 | `app_config` | 认证/限流服务 | 注册限流 | 静态默认值 |
| `auth.email_code_rate_per_hour` | 现有默认 | 系统管理员 | `app_config` | 认证/限流服务 | 邮箱码发送限流 | 静态默认值 |

R17 配置：

| 配置项 | 默认值 | 谁定义 | 谁保存 | 谁读取 | 谁消费 | 回退 |
| --- | --- | --- | --- | --- | --- | --- |
| `audit.retention_days` | `90` | 系统管理员 | `app_config` | `AuditService`、审计页 | 默认查询窗口、页面保留期提示、后续清理任务 | `90` |

注意：

- 配置保存必须记录审计，但审计写失败不影响配置保存。
- 配置项不得只保存不消费；`audit.retention_days` 本阶段至少被查询默认时间窗口和页面提示消费。

### 4.7 页面 P8 技术实现：数据字典

- 原型文件：`agent-works/multi-tenant-rbac/prototypes/data-dictionary.html`
- 对应需求：R18
- 路由：`/system/dicts`
- 页面组件：`frontend/src/views/system/DataDictionaryView.vue`
- API：`frontend/src/api/dict.ts`

#### 4.7.1 前端页面设计闭环

页面定位：

- 页面类型：系统管理 master-detail 维护页。
- 用户主流程：系统管理员进入页面 → 左侧选择字典类型 → 右侧维护字典项 → 保存后刷新并使字典缓存失效。
- 是否新页面：是。
- 是否改造已有页面：否。

布局选型：

- 选用原型：`master-detail`
- 选择理由：字典类型是主范围，字典项是从属明细；左列表和右表格都需要各自内滚。
- 是否需要新增布局原型：否，复用 `frontend/src/layout/archetypes.ts` 的 `master-detail`。

Slot 与组件设计：

| 区域 | slotId | 组件种类 | 是否 growMain | 滚动归属 | 是否可重排 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| action | `toolbar` | `toolbar` | 否 | none | 否 | 标题、新建类型、刷新、页面设置入口 |
| main | `typeList` | `simple-list` | 否 | body-y | 否 | 左侧字典类型搜索、类型列表、启停状态、项数量 |
| main | `itemTable` | `data-table` | 是 | body-xy | 否 | 右侧字典项筛选、表格和分页；表体内滚 |
| overlay | `typeDialog` | `form` | 否 | body-y | 否 | 新建/编辑字典类型，使用 `el-dialog` |
| overlay | `itemDialog` | `form` | 否 | body-y | 否 | 新建/编辑字典项，使用 `el-dialog` |
| overlay | `deleteConfirm` | `dialog` | 否 | none | 否 | 删除确认 |
| overlay | `settings` | `settings-drawer` | 否 | body-y | 否 | 页面设置抽屉 |

配置设计：

| 类型 | 字段 | 层级 | 落点 | 说明 |
| --- | --- | --- | --- | --- |
| 布局旋钮 | `density` | page/user | `pageRegistry.editable` | 信息密度 |
| 组件设置 | `itemTable.hiddenColumns` | preset/page/user | `pageRegistry.componentMeta` | 字典项列显隐；默认隐藏备注和更新时间，保证低宽度下操作列可见 |
| 组件设置 | `itemTable.pageSize` | page/user | 页面业务态或组件配置 | 分页大小 |
| 页面记忆 | `selectedTypeCode`、`itemStatusFilter` | user/local | `usePageSettings` 或页面状态 | 记住最近类型和筛选 |

复用与新增判断：

- 复用已有布局：`master-detail`
- 复用已有组件：`LayoutHost`、`PageSettingsDrawer`、`LayoutSettingsSection`、`el-table`、`el-dialog`、`el-pagination`、`el-switch`
- 是否新增组件种类：否
- 是否新增组件配置字段：优先复用 `hiddenColumns`、`pageSize`，如现有字段不支持则不新增假配置
- 是否新增页面专属业务态：是，当前类型、类型搜索词、字典项筛选、弹窗模式、保存 loading

维护清单：

- pageRegistry：新增 `pageKey="data-dictionary"`，路径 `/system/dicts`，原型 `master-detail`
- COMPONENT_CATALOG：不新增
- COMPONENT_FIELD_DEFS：不新增，除非实现时确认已有字段无法承载并同步消费
- componentSchemas：不新增
- 后端 layout_config 字段规则：不新增
- componentPreview：不新增
- DESIGN.md `page-registry` 区块：新增数据字典登记
- RBAC 菜单/功能点：`_SEED_MENU_TREE`、`_SEED_RESOURCES`、接口守卫、`v-permission`、system 默认授权
- 测试：页面路由、pageRegistry、权限按钮、空/加载/错误、弹窗保存、构建和视口验证

验收：

- `cd frontend && npm test`
- `cd frontend && npm run build`
- 视口验证：`1100x620`、`1366x768`、`1440x900`
- 检查无整页滚动、无视口高度硬编码、左右栏各自内滚、弹窗不溢出、设置抽屉分段正常

#### 4.7.2 原型功能点承接表

| 页面功能点 | 对应需求编号 | 需求交互要点 | 技术实现 | 涉及组件/模块 | 数据/API | 状态与异常处理 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 新建类型 | R18 | 顶部主命令打开类型表单 | `el-dialog` 表单，code 格式校验，保存后刷新类型列表 | `DataDictionaryView.vue` | `POST /api/dict/types` | 保存中、保存失败、重复 code | T6、T9、T13 |
| 刷新 | R18 | 重新加载类型和当前字典项 | 调用类型和项查询并保留当前选中类型 | `DataDictionaryView.vue` | `GET /api/dict/types`、`GET /api/dict/items` | loading、服务异常重试 | T9、T13 |
| 类型搜索 | R18 | 左侧按名称/code 过滤 | 前端本地过滤或服务端关键字查询，按数据量实现 | `typeList` slot | `GET /api/dict/types` | 无匹配类型 | T9、T13 |
| 类型选择 | R18 | 切换左侧类型刷新右侧标题、筛选和表格 | `selectedTypeCode` 驱动项查询 | `typeList`、`itemTable` | `GET /api/dict/items?type_code=` | 当前类型被禁用或删除后回到首个可用类型 | T9 |
| 编辑类型 | R18 | 右侧操作打开类型编辑弹窗 | `el-dialog`，code 创建后不可改，编辑态禁用 code 输入 | `typeDialog` | `PUT /api/dict/types/{code}` | 保存失败、权限不足、试图改 code 被拒绝 | T6、T9 |
| 新建/编辑字典项 | R18 | 当前类型下新增或编辑 item | `el-dialog` 表单，创建态填写 code，编辑态禁用 type_code/code，只允许改 label、sort、enabled、remark | `itemDialog` | `POST /api/dict/items`、`PUT /api/dict/items/{type_code}/{code}` | 当前类型缺失、重复 item code、试图改 code 被拒绝 | T6、T9、T13 |
| 状态筛选 | R18 | 全部/启用/停用 | 查询参数或本地过滤 | `filter-bar` | `GET /api/dict/items` | 无结果 | T9 |
| 字典项查询 | R18 | 按 code/label 搜索 | 服务端分页查询 | `filter-bar` | `GET /api/dict/items` | 查询 loading、服务异常 | T6、T9 |
| 字典项表格 | R18 | 展示 code、名称、排序、启用、备注、操作 | `el-table`，表体横向/纵向内滚 | `itemTable` | `GET /api/dict/items` | 空表格、列宽稳定、分页 | T9、T13 |
| 启停字典项 | R18 | switch 切换启用状态 | 调 update 接口，成功后刷新并失效缓存 | `el-switch` | `PUT /api/dict/items/{type_code}/{code}` | 保存失败回滚开关 | T6、T9 |
| 删除字典项 | R18 | 点击删除后确认 | `ElMessageBox.confirm` | `deleteConfirm` | `DELETE /api/dict/items/{type_code}/{code}` | 被引用时阻止或给出明确错误 | T6、T9 |
| 分页 | R18 | 右侧表格分页 | 服务端分页 | `el-pagination` | `GET /api/dict/items` | 页码越界回退最后一页 | T6、T9 |
| 无数据 | R18 | 无类型/无字典项提示新建 | 表格 empty slot 和列表空态 | `app-empty`/表格空态 | - | 不重复渲染多个空态 | T9、T13 |
| 加载失败 | R18 | 显示重试 | 页面错误态 | `el-result` 或统一错误块 | - | 重试恢复，不影响其他页 | T9、T13 |
| 权限不足 | R18 | 非系统管理员不可进入/不可操作 | 菜单不显示，直达路由守卫，按钮 `v-permission` | router、RBAC、directives | `/api/dict/*` | 后端 403 为准 | T1、T7、T11、T13 |

### 4.8 页面 P9 技术实现：日志审计

- 原型文件：`agent-works/multi-tenant-rbac/prototypes/audit-log.html`
- 对应需求：R17
- 路由：`/system/audit`
- 页面组件：`frontend/src/views/system/AuditLogView.vue`
- API：`frontend/src/api/audit.ts`

#### 4.8.1 前端页面设计闭环

页面定位：

- 页面类型：系统管理 list 可观测查询页。
- 用户主流程：进入日志审计 → 查看摘要 → 设置筛选条件 → 查询列表 → 打开单条详情抽屉排障。
- 是否新页面：是。
- 是否改造已有页面：否。

布局选型：

- 选用原型：`list`
- 选择理由：筛选和工具栏控制一张主审计宽表，详情通过只读抽屉承接。
- 是否需要新增布局原型：否，复用 `frontend/src/layout/archetypes.ts` 的 `list`。

Slot 与组件设计：

| 区域 | slotId | 组件种类 | 是否 growMain | 滚动归属 | 是否可重排 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| action | `toolbar` | `toolbar` | 否 | none | 否 | 标题、自动刷新、刷新、禁用导出、页面设置 |
| action | `summary` | `kpi-grid` | 否 | none | 是 | 今日事件、失败/拒绝、安全事件、租户范围 |
| action | `filters` | `filter-bar` | 否 | none | 否 | 时间、事件类型、结果、状态、资源码、关键词 |
| main | `auditTable` | `wide-table` | 是 | body-xy | 否 | 审计宽表和分页，表体横向/纵向内滚 |
| overlay | `detailDrawer` | `detail` | 否 | body-y | 否 | 只读详情抽屉 |
| overlay | `settings` | `settings-drawer` | 否 | body-y | 否 | 页面设置抽屉 |

配置设计：

| 类型 | 字段 | 层级 | 落点 | 说明 |
| --- | --- | --- | --- | --- |
| 布局旋钮 | `density` | page/user | `pageRegistry.editable` | 信息密度 |
| 组件设置 | `auditTable.hiddenColumns` | preset/page/user | `pageRegistry.componentMeta` | 审计表列显隐 |
| 组件设置 | `auditTable.pageSize` | page/user | 页面业务态或组件配置 | 分页大小 |
| 页面记忆 | `autoRefreshEnabled`、`filters` | user/local | `usePageSettings` 或页面状态 | 记住筛选和自动刷新开关 |

复用与新增判断：

- 复用已有布局：`list`
- 复用已有组件：`LayoutHost`、`PageSettingsDrawer`、`LayoutSettingsSection`、`el-table`、`el-drawer`、`el-pagination`、`el-date-picker`
- 是否新增组件种类：否
- 是否新增组件配置字段：优先复用 `hiddenColumns`、`pageSize`
- 是否新增页面专属业务态：是，筛选条件、自动刷新开关、详情抽屉、当前详情

维护清单：

- pageRegistry：新增 `pageKey="audit-log"`，路径 `/system/audit`，原型 `list`
- COMPONENT_CATALOG：不新增
- COMPONENT_FIELD_DEFS：不新增，除非实现时确认已有字段无法承载并同步消费
- componentSchemas：不新增
- 后端 layout_config 字段规则：不新增
- componentPreview：不新增
- DESIGN.md `page-registry` 区块：新增日志审计登记
- RBAC 菜单/功能点：`_SEED_MENU_TREE`、`_SEED_RESOURCES`、接口守卫、tenant_admin 默认回填、system 全量
- 测试：路由、pageRegistry、租户范围、空/加载/错误、详情抽屉、自动刷新、构建和视口验证

验收：

- `cd frontend && npm test`
- `cd frontend && npm run build`
- 视口验证：`1100x620`、`1366x768`、`1440x900`
- 检查无整页滚动、无视口高度硬编码、摘要/筛选不挤压主表、宽表体内横滚、详情抽屉排版清晰

#### 4.8.2 原型功能点承接表

| 页面功能点 | 对应需求编号 | 需求交互要点 | 技术实现 | 涉及组件/模块 | 数据/API | 状态与异常处理 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 自动刷新 | R17 | 开关控制列表定时刷新，不改变筛选 | `setInterval` + 离开页面清理；默认关闭 | `AuditLogView.vue` | `GET /api/audit` | 接口失败时关闭本次 loading，不循环弹错 | T8、T13 |
| 手动刷新 | R17 | 保留筛选条件重新加载 | 重新请求 summary/list | `toolbar` | `GET /api/audit`、`GET /api/audit/summary` | loading、失败重试 | T8 |
| 导出入口禁用 | R17/R23 | 原型有禁用导出，本阶段不实现 | 禁用按钮或不渲染；如渲染则提示后续能力 | `toolbar` | - | 不产生 API 调用 | T8 |
| 摘要指标 | R17 | 今日事件、失败/拒绝、安全事件、租户范围 | KPI grid；跟随筛选或默认范围 | `summary` slot | `GET /api/audit/summary` | summary 失败不阻塞主表，可显示占位 | T4、T8 |
| 时间范围筛选 | R17 | 默认最近 retention_days 或近 N 天 | `el-date-picker`，服务端校验范围 | `filters` | `GET /api/audit` | 开始晚于结束时报错 | T4、T8 |
| 事件类型筛选 | R17/R18 | 接口/任务/安全/权限/配置/字典 | 选项来自字典，失败回退内置枚举 | `filters`、`dictService` | `/api/dict/items/public` 或内置 | 字典异常回退默认 | T6、T8 |
| 结果/状态筛选 | R17/R18 | 成功/失败/拒绝，完成/处理中/异常 | 选项来自字典或内置默认 | `filters` | `GET /api/audit` | 无结果空态 | T6、T8 |
| 关键词筛选 | R17 | 处理人/资源码/目标对象 | 服务端 LIKE/ILIKE 或参数化查询 | `filters` | `GET /api/audit` | 特殊字符参数化，不拼 SQL | T4、T8 |
| 审计宽表 | R17 | 时间、处理人、事件、资源、目标、结果、状态、IP、耗时、错误摘要、操作 | `el-table`，横向内滚，长文本省略 | `auditTable` | `GET /api/audit` | loading、无记录、服务异常、分页 | T4、T8、T13 |
| 分页 | R17 | 服务端分页 | `el-pagination` | `auditTable` | `GET /api/audit` | 页码越界回退 | T4、T8 |
| 详情抽屉 | R17 | 行点击/详情打开只读详情 | `el-drawer`；执行信息、资源信息、错误摘要、事件上下文分组 | `detailDrawer` | `GET /api/audit/{id}` | 详情加载失败可重试，敏感字段不展示 | T4、T8、T13 |
| 无记录 | R17 | 当前筛选无数据 | 表格 empty slot + 重置筛选 | `auditTable` | - | 不重复空态 | T8 |
| 加载失败 | R17 | 显示重试，已发生事件继续服务端写入 | 错误块 + 重试 | `auditTable` | - | 不清空旧筛选 | T8、T13 |
| 权限不足 | R17 | 普通/付费默认不可见；租管只能看本租户 | 菜单授权 + 后端范围过滤 | router、RBAC、AuditService | `/api/audit/*` | 直达无权路由被拦，接口 403 | T1、T4、T7、T11、T12 |
| 低高度退化 | R17 | 1100x620 下仍可用 | action 区固定，主表 grow，表体内滚；抽屉 body 内滚 | LayoutHost | - | 无整页滚动，无按钮重叠 | T8、T13 |

### 4.9 页面 P10 技术实现：系统设置注册防滥用配置

- 原型文件：无新增 HTML 原型；需求文档已说明复用阶段四落地的 `/system/config/system`。
- 对应需求：R16、R19
- 页面组件：`frontend/src/views/ConfigView.vue`
- API：`frontend/src/api/data.ts`
- 页面注册：使用 `pageKey="config-system"`，原型为 `workbench`，路径为 `/system/config/system`；不得继续使用旧
  `config` pageKey，也不得新增写死的页面配置字段。
- 内容布局：系统设置主内容区不得沿用单列纵向卡片堆叠；T10 必须按 DESIGN/page-template 完成配置组的桌面端
  双列/分组布局，窄屏回落单列，关键视口覆盖 `1100x620`、`1366x768`、`1440x900`。
- 组件复用：必须抽取或复用通用配置组表单组件，按后端 `CONFIG_GROUPS` 渲染 bool/enum/int/number 等字段；
  不允许继续把原始 `el-card + el-form` 逻辑散落在 `ConfigView.vue` 内。
- 文案约束：页面不得用可见说明文字解释布局规则、快捷方式或如何使用页面；配置项提示只保留业务含义、影响范围
  和保存失败原因。

| 页面功能点 | 对应需求编号 | 需求交互要点 | 技术实现 | 涉及组件/模块 | 数据/API | 状态与异常处理 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 展示认证/防滥用配置组 | R16/R19 | 系统管理员进入系统设置看到邮箱码、登录图形码、失败阈值、限流阈值 | 后端 `CONFIG_GROUPS` 返回字段，前端通用配置表单组件渲染 bool/int，并在桌面端按组并排 | `ConfigView.vue`、通用配置组表单组件 | `GET /api/data/settings` | 缺字段回退默认说明，加载失败显示错误态和重试入口 | T2、T10 |
| 保存认证配置 | R16/R19 | 修改后保存，登录/注册链路即时消费 | 复用已有保存接口，后端校验白名单和范围，前端保留保存中/成功/失败状态 | `ConfigView.vue`、通用配置组表单组件、`data_admin.py` | `POST /api/data/settings` | 保存失败提示，旧值不丢，字段校验不通过禁止提交 | T2、T3、T10 |
| 展示审计保留期 | R17 | 展示 `audit.retention_days`，说明本阶段用于默认查询窗口 | 作为系统设置字段渲染，和认证配置共享表单组件与布局规则 | `ConfigView.vue`、通用配置组表单组件 | `GET /api/data/settings` | 非法值回退 90，空配置显示空态 | T2、T10 |
| 权限控制 | R16/R17/R19 | 仅系统管理员可编辑系统设置 | 菜单 system-only + `data-settings:manage` 按钮权限 | RBAC、`v-permission` | `/api/data/settings` | 接口 403 为准 | T1、T10、T11 |

页面设计闭环判断：

- 该页面不新增路由、不新增 HTML 原型，但不是单纯字段级扩展；T10 必须补齐系统设置内容区布局整改和组件复用。
- 需要遵循 DESIGN 和 `agent-works/configurable-layout-system/page-template.md`：`config-system` 继续走
  `workbench` 页面原型和 `toolbar/body/settings` 配置层级，主内容区按配置组形成可扫描的并排工作区。
- 必须覆盖空态、加载态、错误态、权限态、保存中、保存成功和保存失败；不得出现字段挤压、按钮溢出、卡片嵌套卡片或
  文本遮挡。
- 本阶段需要验证系统设置页在 `1100x620`、`1366x768`、`1440x900` 下新增字段不挤压、不溢出，并确认桌面端并排、
  窄屏单列的响应式行为。

## 5. 需求与开发内容映射和开发状态

| 范围类别 | 需求编号 | 需求内容/来源 | 计划开发内容 | 对应任务 | 状态 | 偏差判断 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 必须实现 | R16 | 邮箱码/图形码/人机校验开关即时生效，缺值回落默认 | `app_config` 配置组、认证服务有效配置读取、系统设置页渲染、配置审计 | T2、T3、T10、T12、T13 | 进行中 | 一致 | T2/T3 后端配置与认证消费、T10 系统设置页渲染和布局整改已完成；最终验收待 T12/T13 |
| 必须实现 | R17 | API/任务/安全事件采集，可观测查询页，只读不可改，保留 90 天可配 | 审计表、审计服务、查询 API、采集钩子、审计页、`audit.retention_days` 配置和默认查询窗口 | T1、T2、T4、T5、T7、T8、T11、T12、T13 | 进行中 | 一致 | T1/T2/T4/T5 后端审计能力、T7 前端接入、T8 审计查询页已完成；自动清理归 R23，最终验收待 T11/T12/T13 |
| 必须实现 | R18 | 字典类型/项、首批权限枚举、下拉/校验消费、缺失回退默认 | 字典表、默认枚举、服务/API、前端维护页、缓存失效、消费兜底 | T1、T6、T7、T9、T11、T12、T13 | 进行中 | 一致 | T1/T6 后端基础、T7 前端接入、T9 数据字典维护页已完成；页面消费和最终验收待 T11/T12/T13 |
| 必须实现 | R19 | 配置管理已拆父子菜单，注册防滥用开关落系统设置 | 在 `/system/config/system` 接入 R16 和审计保留期配置 | T2、T3、T10、T13 | 进行中 | 一致 | 配置 schema/API/消费、系统设置主内容布局整改和视口验收已完成；最终汇总验收待 T13 |
| 项目约束 | DESIGN/page-template | 新页面必须页面设计闭环、slot、配置层级、维护清单、关键视口验收 | P8/P9 技术实现章节、pageRegistry/DESIGN 登记、视口验证 | T7、T8、T9、T13 | 进行中 | 一致 | P9 日志审计和 P8 数据字典均已完成三档视口截图和交互验证；最终汇总验收待 T13 |
| 项目约束 | system-rbac-tenant | 新页面必须同步路由、菜单、资源、守卫、按钮权限、默认授权 | 审计和字典菜单/资源 seed、接口守卫、租管审计回填、权限测试 | T1、T4、T6、T7、T11、T12、T13 | 进行中 | 一致 | 后端菜单、资源和接口守卫已完成；前端路由、按钮权限和扫描验收待 T7/T11/T13 |
| 可选增强 | R22 | token 静默刷新 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 阶段六体验增强 |
| 可选增强 | R23 | 审计日志保留期自动清理任务 | 暂不实现自动清理；保留期配置纳入 R17 口径 | - | 跳过 | 部分覆盖 | 缺口是定时清理任务，后续复用 `audit.retention_days` |
| 可选增强 | R24 | 字段级变更对比 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 本阶段只做操作摘要和脱敏上下文 |
| 可选增强 | R28 | 评分方案之外的其他资产公开 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 独立需求，不属于阶段五 |
| 暂不实现 | R25 | 第三方登录真实对接 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 仍保持阶段二置灰入口 |
| 暂不实现 | R26 | 付费计费与配额 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 只保留已有 role_type 预留 |
| 暂不实现 | R27 | 高强度行情防爬 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 本阶段不接行为风控平台 |
| 暂不实现 | 遗留项 4 | `data_dimension_registry` 是否并入字典 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 需求明确本期不并入 |

## 6. 详细实施步骤与进度追踪

### 6.1 任务 T1：数据库、菜单、资源码和 SQL 留痕

- 状态：已完成
- 依赖：阶段四 RBAC seed 和 `pg_ddl.py` 现有迁移标记机制。
- 涉及文件/模块：
  - `backend/storage/pg_ddl.py`
  - `backend/auth/constants.py`
  - `agent-works/multi-tenant-rbac/stage5-platform-capabilities/stage5-platform-capabilities.sql`
  - `agent-works/multi-tenant-rbac/stage5-platform-capabilities/resource-codes.sql`
- 目标：落地平台能力所需表、索引、菜单、资源码、默认授权和可重复执行 SQL 留痕。
- 操作：
  - 新增 `audit_log`、`dict_type`、`dict_item` 表和索引。
  - 新增 `/system/audit`、`/system/dicts` 菜单。
  - 新增 `audit:view`、`dict:read`、`dict:view`、`dict:type-manage`、`dict:item-manage` 资源码。
  - 将 `dict:read` 作为登录基线共享读注入给有角色的非 system 用户。
  - 将 `dict:read` 加入 `SHARED_RESOURCE_CODES`，`sys_resource.menu_id` 锚定 `/board` 这种 `visible=login` 叶子菜单，不挂 `/system/dicts`。
  - 新增 `migration.stage5_platform_capabilities_v1` 迁移标记。
  - 回填 tenant_admin 审计菜单和 `audit:view`，同事务 bump 受影响用户 `perm_ver`。
  - 字典外键使用限制删除，不使用 cascade。
- 产出：后端 DDL/seed 实现和两份 SQL 留痕文件。
- 影响范围：PG schema、内置菜单、内置资源、已有 tenant_admin 授权和会话失效。
- 边界与异常：
  - 重复执行不得重复插入或重复授权。
  - system 角色仍自动拥有全部新增资源。
  - normal/paid 不默认获得审计或字典管理权限。
  - 无角色用户不获得 `dict:read`。
- 验证方式：
  - 后端 DDL 初始化测试。
  - 菜单/资源 seed 测试。
  - tenant_admin 回填和 `perm_ver` bump 测试。
- 完成标准：新库和已有库都能得到一致 seed；重复启动幂等；资源码扫描不报缺失。
- 实际落地情况：已落地 `audit_log`、`dict_type`、`dict_item` 表和索引；已新增 `/system/audit`、`/system/dicts` 菜单和 `audit:view`、`dict:read`、`dict:view`、`dict:type-manage`、`dict:item-manage` 资源码；`dict:read` 已加入登录基线共享读并锚定 `/board`；tenant_admin 审计入口回填与阶段五迁移标记已实现；已生成两份 SQL 留痕并补 T1 专项测试。

### 6.2 任务 T2：R16/R17 运行时配置模型

- 状态：已完成
- 依赖：T1 的 app_config seed 约定；现有 `CONFIG_GROUPS`。
- 涉及文件/模块：
  - `backend/storage/app_config.py`
  - `backend/config/settings.py`
  - `backend/api/data_admin.py`
  - 可能新增/扩展配置校验测试
- 目标：把认证防滥用和审计保留期纳入系统设置配置模型。
- 操作：
  - 在 `CONFIG_GROUPS` 增加认证/防滥用配置项。
  - 增加 `audit.retention_days`，默认 `90`，范围建议 `7..365`。
  - 校验 bool/int 类型、范围和缺省值。
  - 保存时保留旧配置兼容，未知 key 仍拒绝。
- 产出：后端配置白名单和校验规则。
- 影响范围：`GET/POST /api/data/settings`、系统设置页动态字段。
- 边界与异常：
  - 非法值拒绝保存或回退默认，不能写入破坏认证链路的值。
  - `audit.retention_days` 不触发数据删除。
- 验证方式：
  - 配置保存接口测试。
  - 非法值和缺值回退测试。
- 完成标准：新增字段可查询、可保存、可被服务读取，并且没有未消费配置项。
- 实际落地情况：已新增 `AuditConfig.retention_days` 和 `auth`/`audit` 配置白名单；`auth.require_email_code`、`auth.login_captcha_enabled`、`auth.captcha_after_fails`、认证限流字段和 `audit.retention_days` 已支持系统设置查询/保存、类型与范围校验；`AuthService` 已改为读取 `get_effective_settings().auth`，`public-config` 和登录/注册/邮箱码限流链路可消费 app_config 覆盖值；已补 T2 专项测试。

### 6.3 任务 T3：认证链路消费有效配置

- 状态：已完成
- 依赖：T2。
- 涉及文件/模块：
  - `backend/services/auth_service.py`
  - `backend/api/auth.py`
  - `backend/auth/middleware.py`
  - `backend/api/data_admin.py`
- 目标：让 R16 配置实际影响登录、注册、验证码和公共配置接口。
- 操作：
  - 将认证服务配置读取切到 `get_effective_settings().auth` 或封装运行时配置读取器。
  - `public_config()` 返回有效配置。
  - 登录图形验证码和失败阈值按有效配置执行。
  - 注册邮箱验证码按有效配置执行。
  - 保存认证配置时记录 config 审计事件。
- 产出：认证链路配置闭环。
- 影响范围：登录、注册、邮箱验证码、公共配置、限流。
- 边界与异常：
  - PG/app_config 不可用时回退静态默认值。
  - 人机校验不接第三方服务，页面文案明确为“登录图形验证码”。
  - 审计写失败不影响配置保存。
- 验证方式：
  - 关闭 `require_email_code` 后注册不要求邮箱码。
  - 开启 `login_captcha_enabled` 和设置 `captcha_after_fails` 后登录按阈值要求验证码。
  - `/api/auth/public-config` 返回有效值。
- 完成标准：配置展示、保存、读取、消费、回退全链路可验证。
- 实际落地情况：已确认认证服务读取 `get_effective_settings().auth`，`/api/auth/public-config`、登录图形验证码阈值、
  注册邮箱验证码开关和认证限流均消费运行时覆盖配置；已新增 best-effort 审计写入仓库，系统设置保存成功后记录
  `config` 审计事件，仅记录配置 key、影响数量、路由、操作者和上下文摘要，不记录配置值；审计写入失败不影响配置保存。
  已补 `backend/tests/test_stage5_auth_config.py`，覆盖公开配置即时生效、注册链路消费、配置保存审计和审计降级。

### 6.4 任务 T4：审计查询后端闭环

- 状态：已完成
- 依赖：T1、T2。
- 涉及文件/模块：
  - `backend/storage/audit_repository.py`
  - `backend/services/audit_service.py`
  - `backend/api/audit.py`
  - `backend/main.py`
- 目标：提供审计写入、分页查询、摘要指标和详情查询能力。
- 操作：
  - 实现审计 repository。
  - 实现 `AuditService.record_*` 和查询服务。
  - 查询时按系统管理员/租户管理员做范围收口。
  - 默认查询窗口读取 `audit.retention_days`。
  - 实现 `/api/audit`、`/api/audit/summary`、`/api/audit/{id}`。
- 产出：审计基础服务和只读 API。
- 影响范围：新增审计 API、权限扫描、系统管理路由。
- 边界与异常：
  - 租户管理员不得通过参数越权查看其他租户。
  - 审计上下文必须白名单脱敏。
  - 审计 API 本身避免递归写入。
- 验证方式：
  - 系统管理员全局查询测试。
  - 租户管理员本租户查询测试。
  - 详情敏感字段过滤测试。
- 完成标准：审计页所需列表、摘要、详情数据契约稳定。
- 实际落地情况：已扩展 `AuditRepository` 的分页查询、摘要统计和详情读取；已新增 `AuditService`，统一处理
  system 全局/tenant_admin 本租户范围收口、`audit.retention_days` 默认查询窗口和审计上下文白名单脱敏；已新增
  `/api/audit`、`/api/audit/summary`、`/api/audit/{id}` 只读接口并挂 `audit:view`；已在 `backend/main.py` 注册
  审计路由。已补 `backend/tests/test_stage5_audit.py`，覆盖系统管理员全局查询、摘要、详情脱敏、租户管理员越权收口
  和跨租户详情不可见。

### 6.5 任务 T5：审计采集接入

- 状态：已完成
- 依赖：T4。
- 涉及文件/模块：
  - `backend/auth/deps.py`
  - `backend/auth/middleware.py`
  - `backend/services/auth_service.py`
  - `backend/services/async_task.py`
  - `backend/scheduler/scheduler.py`
  - 相关 RBAC 管理服务
- 目标：覆盖 API、安全、任务、配置、字典、RBAC 高价值事件。
- 操作：
  - 在权限依赖中写入当前请求资源码上下文。
  - 请求结束记录 API 事件。
  - 登录/注册/验证码/限流/403/token 吊销记录安全事件。
  - 异步任务和调度任务状态变化记录任务事件。
  - 配置、字典、RBAC 管理操作记录管理事件。
- 产出：审计事件采集闭环。
- 影响范围：横切所有 `/api/**` 请求和关键服务。
- 边界与异常：
  - 审计写入必须 best-effort。
  - 不记录请求体、响应体、密码、token、验证码。
  - 高频 API 事件要避免同步阻塞。
- 验证方式：
  - 成功、失败、403、429、任务完成/失败均能查到审计。
  - 模拟审计写入异常主接口仍成功。
- 完成标准：R17 三类事件和关键管理事件可观察。
- 实际落地情况：已在权限依赖中写入当前请求资源码上下文，并兼容同步端点通过 `request.state` 传回中间件；
  `AuthMiddleware` 已在受控 `/api/**` 请求结束后记录 API 审计事件，包含方法、路径、状态码、耗时、租户、用户和
  resource code，且跳过 `/api/audit` 避免递归；401/403/429 已记录安全审计事件。认证服务已记录登录成功/失败、
  注册成功/邮箱码校验失败、图形验证码发放/校验失败、邮箱验证码发放/限流、refresh 轮换/失败和 logout token 吊销
  安全事件，不记录密码、token、验证码或请求/响应体。异步任务服务已记录创建、启动、完成、中断、失败、续跑和取消请求
  的任务事件；调度任务触发、非交易日跳过、并发跳过和触发异常已记录 `scheduler` 任务审计；系统设置保存的配置审计已在 T3 落地。
  字典领域事件已随 T6 字典服务接入；用户、角色、菜单、资源、租户等 RBAC 管理成功操作已记录 `rbac` 领域审计。
  已补 `backend/tests/test_stage5_audit_collection.py`，覆盖 API、认证拒绝、审计递归跳过、登录失败、任务状态、调度跳过/失败和 RBAC 管理审计。

### 6.6 任务 T6：数据字典后端闭环

- 状态：已完成
- 依赖：T1、T4。
- 涉及文件/模块：
  - `backend/storage/dict_repository.py`
  - `backend/services/dict_service.py`
  - `backend/api/dicts.py`
  - `backend/main.py`
- 目标：实现字典类型、字典项、默认枚举、消费兜底和缓存失效。
- 操作：
  - 实现字典 CRUD。
  - 实现 code 格式、唯一性、启停校验。
  - 类型 code 和字典项 code 创建后不可修改；`PUT /api/dict/types/{code}` 与 `PUT /api/dict/items/{type_code}/{code}` 的请求体不接受 code/type_code 变更。
  - 实现默认字典种子和 `get_enabled_items(type_code)`。
  - 字典缺失/异常时回退内置枚举。
  - 字典变更后记录审计并返回可让前端失效缓存的版本或时间戳。
- 产出：字典后端服务、API 和专项测试。
- 影响范围：系统管理字典页、审计页枚举展示、后续下拉消费。
- 边界与异常：
  - 停用项不用于新数据，但历史值显示不丢 label。
  - 删除有明细的类型要阻止。
  - 编辑类型或字典项时 code 字段后端拒绝变更，前端编辑弹窗禁用 code 输入。
  - 不把 `indicator_def` 和 `data_dimension_registry` 混入本期。
- 验证方式：
  - CRUD、重复 code、code 不可修改、禁用项、缺失回退、服务异常回退测试。
- 完成标准：R18 后端能力可被页面和消费端稳定使用。
- 实际落地情况：已新增 `DictRepository`、`DictService` 和 `/api/dict` 路由并在 `backend/main.py` 注册；已实现字典类型和字典项 CRUD、code 格式校验、唯一性校验、类型/字典项 code 创建后不可修改、禁删有明细类型、启用项消费接口和内置枚举兜底；`dict:read` 消费端只返回启用项，管理端接口保持 system-only；字典类型/项新增、修改、删除已接入 best-effort `dict` 审计事件。已补 `backend/tests/test_stage5_dicts.py`，覆盖 CRUD、重复 code、不可变 code、禁用项过滤、共享只读基线能力、缺失/异常兜底和审计写入。

### 6.7 任务 T7：前端基础接入、路由、布局登记和 API 封装

- 状态：已完成
- 依赖：T1、T4、T6。
- 涉及文件/模块：
  - `frontend/src/router/index.ts`
  - `frontend/src/layout/pageRegistry.ts`
  - `frontend/src/api/audit.ts`
  - `frontend/src/api/dict.ts`
  - `frontend/src/views/system/AuditLogView.vue`
  - `frontend/src/views/system/DataDictionaryView.vue`
  - `frontend/src/router/__tests__/stage5-routes.spec.ts`
  - `DESIGN.md`
- 目标：为两张新页面建立前端可导航、可配置、可测试的基础。
- 操作：
  - 新增 `/system/audit`、`/system/dicts` 静态路由。
  - 新增 `audit-log`、`data-dictionary` 页面 registry。
  - 新增审计和字典 API 类型封装。
  - 在 DESIGN page-registry 区块登记两张页面。
  - 确认菜单 seed path 与前端 route path 一致。
- 产出：前端基础接入代码。
- 影响范围：路由守卫、侧边菜单、页面布局配置。
- 边界与异常：
  - 不新增布局原型。
  - 不新增页面不消费的组件配置字段。
- 验证方式：
  - pageRegistry 测试。
  - router 解析测试。
  - layout-contract 测试。
- 完成标准：两张页面能被路由和布局系统识别。
- 实际落地情况：已新增 `/system/audit`、`/system/dicts` 静态路由，路由名分别为 `audit-log`、`data-dictionary`，与 T1 菜单 seed 路径保持一致；已在 `pageRegistry` 登记审计日志 `list` 页和数据字典 `master-detail` 页，并同步 `DESIGN.md` page-registry 区块。已新增 `frontend/src/api/audit.ts`、`frontend/src/api/dict.ts`，按后端 `/api/audit`、`/api/dict` 实际字段封装类型和调用函数。为保证路由构建可用，已新增两张最小 LayoutHost 壳页面，仅承接页面标题、设置抽屉和基础 slot 区域；审计表格、筛选、详情抽屉、字典 CRUD 等业务功能仍归 T8/T9，未在 T7 提前实现。已补 router 解析测试和 pageRegistry 专项断言，并通过 `npm run test -- --run src/layout/__tests__/pageRegistry.spec.ts src/layout/__tests__/layout-contract.spec.ts src/router/__tests__/stage5-routes.spec.ts`。

### 6.8 任务 T8：日志审计前端页面

- 状态：已完成
- 依赖：T4、T7。
- 涉及文件/模块：
  - `frontend/src/views/system/AuditLogView.vue`
  - `frontend/src/views/system/__tests__/AuditLogView.spec.ts`
  - `frontend/src/layout/pageRegistry.ts`
  - `frontend/src/layout/componentConfig.ts`
  - `backend/storage/layout_config.py`
- 目标：按原型实现日志审计只读可观测页。
- 操作：
  - 实现标题工具区、自动刷新、刷新、禁用导出、摘要指标。
  - 实现筛选栏、服务端分页、审计宽表。
  - 实现只读详情抽屉，分组展示执行信息、资源信息、错误摘要、脱敏上下文。
  - 实现 loading、无记录、服务异常、权限不足、低高度退化。
  - 租户管理员页面不展示跨租户切换入口。
- 产出：`AuditLogView.vue` 和页面测试。
- 影响范围：系统管理日志审计页面。
- 边界与异常：
  - 不实现导出。
  - 不展示原型批注或原型演示按钮。
  - 自动刷新离开页面必须清理定时器。
- 验证方式：
  - 页面单测覆盖筛选、刷新、空态、错误态、详情抽屉。
  - 视口 `1100x620`、`1366x768`、`1440x900` 截图/交互验证。
- 完成标准：页面功能点承接表全部可观察，排版无重叠。
- 实际落地情况：已按 `audit-log.html` 承接日志审计页面，完成标题工具区、自动刷新、手动刷新、禁用导出入口、摘要指标、筛选栏、服务端分页、审计宽表、只读详情抽屉、loading、无记录、服务异常、权限不足、低高度退化和租户管理员不展示租户过滤入口。事件类型和结果选项优先消费 `/api/dict/items/public`，失败回退内置枚举；默认时间不强制前端传参，由后端 `audit.retention_days=90` 默认窗口收口，页面摘要提示“默认最近 90 天”。审计表 `auditTable` 已接入 `wide-table` 的 `pageSize` 和 `hiddenColumns` 组件配置，并同步前端 `componentConfig` 与后端 `layout_config` 字段白名单，避免设置保存被拒。已补 `AuditLogView.spec.ts` 覆盖加载、查询、空态、错误重试、详情抽屉、权限态、租户管理员无跨租户入口和自动刷新清理。浏览器验证使用 5181 专用端口，截图保存在被 Git 忽略的 `agent-works/multi-tenant-rbac/stage5-platform-capabilities/screenshots/t8-audit-*.png`，三档视口 `1100x620`、`1366x768`、`1440x900` 均无整页横/纵向溢出、无关键区域重叠，详情抽屉和页面设置抽屉已验证。

### 6.9 任务 T9：数据字典前端页面

- 状态：已完成
- 依赖：T6、T7。
- 涉及文件/模块：
  - `frontend/src/views/system/DataDictionaryView.vue`
  - `frontend/src/views/system/__tests__/DataDictionaryView.spec.ts`
- 目标：按原型实现数据字典 master-detail 维护页。
- 操作：
  - 实现类型搜索、类型列表、类型选择。
  - 实现字典项状态筛选、搜索、查询、分页和表格。
  - 新建/编辑类型和字典项统一用 `el-dialog`。
  - 实现启停、删除确认、保存失败回滚、缓存失效。
  - 实现 loading、无数据、查询无结果、服务异常、权限不足、低高度退化。
- 产出：`DataDictionaryView.vue` 和页面测试。
- 影响范围：系统管理数据字典页面。
- 边界与异常：
  - 禁止使用抽屉做编辑。
  - 不展示原型批注或原型演示按钮。
  - 同一区域不能重复渲染多个空态。
- 验证方式：
  - 页面单测覆盖主从联动、弹窗、保存失败、空/错/重试和权限按钮。
  - 视口 `1100x620`、`1366x768`、`1440x900` 截图/交互验证。
- 完成标准：页面功能点承接表全部可观察，弹窗编辑符合用户管理页交互。
- 实际落地情况：已按 `data-dictionary.html` 承接数据字典 master-detail 维护页，完成标题工具区、新建类型、刷新、类型搜索、类型列表、类型选择、字典项状态筛选、关键字查询、服务端分页、字典项表格、新建/编辑类型弹窗、新建/编辑字典项弹窗、启停、删除确认、loading、空态、错误重试和权限不足状态。编辑类型弹窗禁用类型 code，编辑字典项弹窗禁用 type_code 和 item code；保存时不向 PUT 请求提交不可变 code 字段。`itemTable` 已登记 `data-table` 的 `pageSize` 和 `hiddenColumns` 组件配置，默认隐藏备注和更新时间列，保证低宽度下常用操作列不被遮挡；备注和更新时间可通过设置抽屉列显隐打开。已同步 `DESIGN.md`，补 `DataDictionaryView.spec.ts` 覆盖主从加载、类型切换、筛选透传、新建/编辑 code 不可变、错误重试和 system-only 权限态。浏览器验证使用 5181 专用端口，截图保存在被 Git 忽略的 `agent-works/multi-tenant-rbac/stage5-platform-capabilities/screenshots/t9-dict-*.png`，三档视口 `1100x620`、`1366x768`、`1440x900` 均无整页横/纵向溢出；已验证新建类型弹窗、编辑类型 code 禁用、设置抽屉“字典项表/每页条数/列显隐”可见。

### 6.10 任务 T10：系统设置页接入 R16/R17 配置和布局复用整改

- 状态：已完成
- 依赖：T2、T3。
- 涉及文件/模块：
  - `frontend/src/views/ConfigView.vue`
  - 通用配置组表单组件，例如 `frontend/src/components/config/ConfigGroupForm.vue`
  - `frontend/src/api/data.ts`
  - 相关前端测试
- 目标：在 `/system/config/system` 展示并保存认证防滥用配置和审计保留期配置，并完成系统设置页内容区的
  DESIGN 合规布局和组件复用整改。
- 操作：
  - 保持 `/system/config/system`、`config-system` 和 `workbench` 页面注册不变，不新增路由和原型。
  - 抽取或复用通用配置组表单组件，按后端 `CONFIG_GROUPS` 渲染 bool/enum/int/number 字段、校验信息和保存状态。
  - 将系统设置主内容区调整为桌面端双列/分组工作区，窄屏回落单列；不得继续沿用旧单列纵向卡片堆叠。
  - 优化系统设置业务提示，覆盖认证、防滥用和审计配置的影响范围，但不添加解释页面布局或使用方法的可见文案。
  - 覆盖空态、加载态、错误态、权限态、保存中、保存成功、保存失败和字段校验失败。
  - 保存成功后提示配置已更新。
  - 保存失败保留旧值和错误提示。
- 产出：系统设置页字段接入、通用配置组表单组件、系统设置页布局整改和对应前端测试。
- 影响范围：系统设置页面。
- 边界与异常：
  - 不新增页面、不新增 HTML 原型、不新增伪造的 pageRegistry 组件字段。
  - 不改变评分/技术/买卖配置子页。
  - 不把认证和审计配置写死在前端；字段来源继续以 `CONFIG_GROUPS` 和设置接口为准。
- 验证方式：
  - 前端单测覆盖新增配置组渲染、字段类型、保存、保存失败、空态、错误态和权限态。
  - 运行 `npm run build`。
  - 关键视口 `1100x620`、`1366x768`、`1440x900` 验证新增字段不溢出、不遮挡，桌面端并排、窄屏单列。
- 完成标准：R16/R17 配置能展示、保存、读取、消费。
- 实际落地情况：已新增 `frontend/src/components/config/ConfigGroupForm.vue`，按 `/api/data/settings` 返回的 `CONFIG_GROUPS` 动态渲染 bool、enum、int、number 字段、默认值、覆盖标记和范围信息；`ConfigView.vue` 的 `/system/config/system` 已改为配置组并排工作区，不再使用旧单列 `el-card` 堆叠。system 页初始化已从指标注册表依赖中拆出，只加载登录态和系统设置接口；无 `data-settings:manage` 权限时显示权限态且不请求设置接口。保存逻辑只提交差量字段，保存成功提示“配置已更新”，保存失败保留当前编辑值并展示错误态；空配置显示空态。已补 `ConfigView.system.spec.ts` 覆盖动态渲染、system 页不加载指标注册表、差量保存、保存失败保留值、越界数值钳定保存、空态和权限态。浏览器验证使用 5181 专用端口，截图保存在被 Git 忽略的 `agent-works/multi-tenant-rbac/stage5-platform-capabilities/screenshots/t10-config-system-*.png`，三档视口 `1100x620`、`1366x768`、`1440x900` 均无整页横/纵向溢出；桌面端配置组已并排展示，系统设置抽屉可打开。

### 6.11 任务 T11：权限扫描和菜单授权测试

- 状态：已完成
- 依赖：T1、T4、T6、T7。
- 涉及文件/模块：
  - `backend/tests/test_stage5_resource_codes.py`
  - `backend/tests/test_stage4_menu_guard.py`
  - 相关 RBAC 测试
- 目标：确保新增页面、接口、按钮权限没有断链。
- 操作：
  - 扩展路由扫描测试，覆盖 `/api/audit` 和 `/api/dict`。
  - 测试 tenant_admin 拥有审计菜单和 `audit:view`。
  - 测试 normal/paid 默认无审计和字典管理菜单，但具备 `dict:read` 共享只读能力。
  - 测试字典菜单和接口 system-only。
  - 测试无角色用户不获得 `dict:read`。
  - 测试 `dict:read` 挂 `visible=login` 菜单锚点、加入 `SHARED_RESOURCE_CODES`、角色页 baseline_locked 不可反选。
  - 测试菜单 path 与前端 route path 对齐。
- 产出：权限和菜单守卫测试。
- 影响范围：RBAC seed、路由扫描。
- 边界与异常：
  - `require_system_perm` 既要 system 守卫又要保留资源码元数据。
  - tenant_admin 审计范围由服务层兜底，不靠前端隐藏。
- 验证方式：
  - `python -m pytest backend/tests/test_stage5_resource_codes.py -q`
  - `python -m pytest backend/tests/test_stage4_menu_guard.py -q`
- 完成标准：新增 API 无裸露端点，默认角色授权符合需求。
- 实际落地情况：已新增 `backend/tests/test_stage5_resource_codes.py`，集中覆盖阶段五 `/api/audit`、`/api/dict`
  路由精确资源码扫描、`require_system_perm` system-only 元数据、tenant_admin 审计菜单和 `audit:view`、normal/paid
  默认无审计和字典管理入口但具备 `dict:read`、字典管理接口 system-only、无角色用户 `dict:read` fail-closed、
  `dict:read` 挂 `/board` 且 `visible=login`、`SHARED_RESOURCE_CODES` 与 `baseline_locked` 契约，以及
  `/system/audit`、`/system/dicts` 菜单路径与前端 router/pageRegistry 对齐。已按约束先停后台服务再验证，
  `python -m pytest backend/tests/test_stage5_resource_codes.py backend/tests/test_stage4_menu_guard.py -q` 通过
  `10 passed`，仅有 FastAPI `on_event` 既有弃用警告；验证完成后已重启后端服务。

### 6.12 任务 T12：后端业务测试

- 状态：待开始
- 依赖：T2、T3、T4、T5、T6、T11。
- 涉及文件/模块：
  - `backend/tests/test_stage5_auth_config.py`
  - `backend/tests/test_stage5_audit.py`
  - `backend/tests/test_stage5_dicts.py`
  - 相关既有测试
- 目标：覆盖 R16/R17/R18 后端闭环。
- 操作：
  - 补认证配置有效读取测试。
  - 补审计写入、查询、范围、脱敏、降级测试。
  - 补字典 CRUD、唯一性、禁用、兜底测试。
  - 补审计保留期配置默认查询窗口测试。
- 产出：后端阶段五测试。
- 影响范围：后端 CI/本地测试基线。
- 边界与异常：
  - 测试不得依赖真实敏感数据。
  - 审计降级测试要模拟写失败。
- 验证方式：
  - `python -m pytest backend/tests/test_stage5_auth_config.py -q`
  - `python -m pytest backend/tests/test_stage5_audit.py -q`
  - `python -m pytest backend/tests/test_stage5_dicts.py -q`
  - `python -m pytest backend/tests/test_stage5_resource_codes.py -q`
- 完成标准：阶段五后端专项测试通过，并不破坏阶段四权限基线。
- 实际落地情况：待实施。

### 6.13 任务 T13：前端测试、构建和视口验证

- 状态：待开始
- 依赖：T7、T8、T9、T10。
- 涉及文件/模块：
  - `frontend/src/views/system/__tests__/AuditLogView.spec.ts`
  - `frontend/src/views/system/__tests__/DataDictionaryView.spec.ts`
  - 相关 pageRegistry/router/layout 测试
- 目标：验证页面、权限按钮、布局契约和构建。
- 操作：
  - 补审计页和字典页 Vitest。
  - 补系统设置新增配置组测试。
  - 跑前端测试和 build。
  - 使用专用端口 `5181` 做 `1100x620`、`1366x768`、`1440x900` 视口验证。
- 产出：前端测试结果和视口验证结论。
- 影响范围：前端页面和布局系统。
- 边界与异常：
  - 改过 `frontend/src` 后必须 `npm run build`。
  - 不抢占用户日常 `5173`。
  - 宽表靠表体内滚，不通过整页滚动兜底。
- 验证方式：
  - `cd frontend && npm run test -- --run`
  - `cd frontend && npm run build`
  - 浏览器截图/交互验证三档视口。
- 完成标准：测试和 build 通过，页面无重叠、无视口高度硬编码、无布局契约失败。
- 实际落地情况：待实施。

### 6.14 任务 T14：开发留痕、业务核查和计划状态回写

- 状态：待开始
- 依赖：T12、T13。
- 涉及文件/模块：
  - `agent-works/multi-tenant-rbac/stage5-platform-capabilities/development-trace.md`
  - `agent-works/multi-tenant-rbac/stage5-platform-capabilities/business-audit.md`
  - 本 `plan.md`
- 目标：完成阶段五文档闭环和真实状态回写。
- 操作：
  - 记录实际落地文件、接口、表、资源码、页面和测试结果。
  - 按业务链路核查 R16/R17/R18/R19 是否闭环。
  - 更新本计划任务状态、实际落地情况、测试具体完成情况和遗留缺口。
- 产出：开发留痕、业务核查和更新后的计划。
- 影响范围：agent-works 文档。
- 边界与异常：
  - 只记录真实已落地事实，不提前把任务批量标为完成。
  - 如测试未跑或失败，必须写原因和风险。
- 验证方式：
  - 文档自查。
  - Git diff 复核。
- 完成标准：开发过程、验证结果和业务闭环可追踪。
- 实际落地情况：待实施。

## 7. 数据库与 SQL 计划

| SQL 文件路径 | 用途 | 执行时机 | 影响范围 | 回滚方式或不可回滚原因 |
| --- | --- | --- | --- | --- |
| `agent-works/multi-tenant-rbac/stage5-platform-capabilities/stage5-platform-capabilities.sql` | 记录 `audit_log`、`dict_type`、`dict_item`、索引、默认字典、`app_config` 新增配置项 | 开发实现时同步生成；生产发布前随 `init_pg_db()` 幂等逻辑或人工迁移执行 | 新增 PG 表、索引、默认枚举和配置 key | 未产生业务数据前可 drop 新表并删除 config key；产生审计/字典数据后 drop 会丢历史，回滚应优先保留表并下线入口 |
| `agent-works/multi-tenant-rbac/stage5-platform-capabilities/resource-codes.sql` | 记录新增菜单、资源码、角色授权、tenant_admin 审计回填、`perm_ver` bump | 表结构就绪后、应用发布前执行；也由启动 seed 幂等保障 | `sys_menu`、`sys_resource`、`sys_role_menu`、`sys_role_resource`、用户 `perm_ver` | 可删除新增菜单/资源和授权关系；`perm_ver` 自增不可有意义回退，但只会要求用户重新登录，属于可接受副作用 |

SQL 约束：

- 所有 seed 使用 `ON CONFLICT` 或等效幂等逻辑。
- 字典项外键不得使用 `ON DELETE CASCADE`。
- 新增配置项必须有默认值和校验范围。
- 审计表只新增，不改写既有业务表。
- 回滚前必须确认是否已有审计日志或用户维护的字典项；已有数据时不建议 drop 表。

## 8. 测试与验证计划

- 单元测试：
  - 计划：覆盖配置读取、字典服务、审计服务脱敏和回退。
  - 具体完成情况：T1-T6 后端专项已覆盖配置读取、认证配置消费、审计脱敏、审计采集、字典兜底；本轮验证 `backend/tests/test_stage5_*.py` 相关用例通过。
- 接口测试：
  - 计划：覆盖 `/api/audit`、`/api/dict/*`、`/api/data/settings`、`/api/auth/public-config`。
  - 具体完成情况：已覆盖 `/api/audit`、`/api/dict/types`、`/api/dict/items`、`/api/dict/items/public`、`/api/data/settings`、`/api/auth/public-config`；页面 API 封装待 T7。
- 页面/交互测试：
  - 计划：审计页筛选/分页/详情/自动刷新/错误重试；字典页主从联动/弹窗/启停/删除/缓存失效；系统设置页新增配置。
  - 具体完成情况：日志审计页已完成筛选/分页/详情/自动刷新/错误重试和三档视口验证；数据字典页已完成主从联动、弹窗、筛选、启停、删除确认、错误重试、权限态和三档视口验证；系统设置页已完成新增配置组动态渲染、并排布局、保存失败、空态、权限态和三档视口验证。
- 权限与数据范围测试：
  - 计划：system 全局审计和字典；tenant_admin 仅本租户审计；normal/paid 默认无审计和字典；后端接口 403 为准。
  - 具体完成情况：已覆盖 system 全局审计查询、tenant_admin 本租户审计收口、字典管理 system-only、`dict:read` 登录基线共享读、normal/paid 默认无审计/字典管理授权和无角色 fail-closed。
- 回归测试：
  - 计划：阶段四资源码扫描、菜单守卫、登录基线共享读、ConfigView 既有 score/trade/tech/system 子页不回归。
  - 具体完成情况：已跑阶段四菜单守卫和资源码回归；前端 `pageRegistry.spec.ts` 与 `npm run build` 通过。
- 异常与边界测试：
  - 计划：审计写失败不阻断主链路；PG/app_config 缺失回退默认；字典服务异常回退默认枚举；非法配置拒绝或回退；页码越界处理。
  - 具体完成情况：已覆盖配置审计写失败降级、非法配置拒绝、字典服务异常兜底、审计详情脱敏、租户越权不可见、重复 code/code 不可变和禁删有明细类型。
- 图示与原型一致性验证：
  - 计划：核对 `data-dictionary.html` 的新建类型、刷新、类型搜索、编辑类型、新建字典项、状态筛选、查询、分页、弹窗、无数据、加载失败；核对 `audit-log.html` 的自动刷新、刷新、禁用导出、摘要指标、筛选、查询/重置、分页、详情抽屉、无记录、加载失败。
  - 具体完成情况：P9 日志审计页和 P8 数据字典页均已完成原型逐项承接和浏览器截图/交互验证；最终汇总复核待 T13。
- 配置闭环验证：
  - 计划：验证配置项能展示、保存、读取、实际影响认证链路、非法值回退、`audit.retention_days` 被审计默认查询窗口消费。
  - 具体完成情况：已验证配置项可经 `/api/data/settings` 展示/保存，`/api/auth/public-config` 和注册链路即时消费，非法值拒绝，`audit.retention_days` 被审计默认查询窗口消费。
- 需求映射验证：
  - 计划：逐项检查 R16/R17/R18/R19 是否有任务、状态、验证方式；R22/R23/R24/R25/R26/R27/R28 是否标跳过和原因。
  - 具体完成情况：已同步 R16/R17/R18/R19 当前状态为进行中或已完成子任务；R22/R23/R24/R25/R26/R27/R28 仍按计划标记跳过并说明原因。
- 页面功能点验证：
  - 计划：逐项检查 4.7.2、4.8.2、4.9 功能点是否有技术实现、任务编号、状态处理和异常处理。
  - 具体完成情况：4.8.2 日志审计功能点已在 T8 落地并由单测、构建和三档视口验证覆盖；4.7.2 数据字典功能点已在 T9 落地并由单测、构建和三档视口验证覆盖；4.9 系统设置功能点已在 T10 落地并由单测、构建和三档视口验证覆盖。

建议命令：

```bash
python -m pytest backend/tests/test_stage5_auth_config.py -q
python -m pytest backend/tests/test_stage5_audit.py -q
python -m pytest backend/tests/test_stage5_dicts.py -q
python -m pytest backend/tests/test_stage5_resource_codes.py -q
python -m pytest backend/tests/test_stage4_menu_guard.py -q

cd frontend && npm run test -- --run
cd frontend && npm run build
```

页面验证：

- 使用专用端口 `5181`，不占用日常 `5173`。
- 验证视口：`1100x620`、`1366x768`、`1440x900`。
- 验证内容：无整页滚动、无硬编码视口高度、无文本重叠、宽表体内滚、弹窗/抽屉 body 内滚、页面设置抽屉可打开。

## 9. 发布与回滚

- 发布前检查：
  - PG 备份完成。
  - 新 DDL/seed 在测试库幂等通过。
  - 新资源码和菜单 seed 与前端路由一致。
  - tenant_admin 审计授权回填影响范围已确认。
  - 后端阶段五测试通过。
  - 前端测试和 build 通过。
  - 三档视口验证通过。
- 发布步骤：
  1. 合并后端 DDL/seed 和服务代码。
  2. 在发布前或应用启动时执行幂等 PG 初始化。
  3. 发布后端，确认 `/api/health`、配置、审计、字典接口可用。
  4. 发布前端构建产物。
  5. 用 system 管理员验证系统设置、数据字典、日志审计。
  6. 用 tenant_admin 验证只看到本租户审计。
  7. 用 normal/paid 验证默认不可见审计和字典。
- 配置或环境变量：
  - 本阶段不新增必需环境变量。
  - 新增 `app_config` 平台配置：认证防滥用字段、`audit.retention_days`。
- 回滚方案：
  - 前端回滚：还原前端产物，侧栏不再展示新页面入口。
  - 后端回滚：回退 API 和服务代码；保留新增表不影响旧代码。
  - 权限回滚：删除新增菜单/资源和授权关系；已 bump 的 `perm_ver` 不回退，用户重新登录即可。
  - 数据回滚：已有审计日志和字典项不建议删除；如必须删除，需先备份并确认业务接受历史不可恢复。

## 10. 风险、假设与待确认项

### 10.1 风险

| 风险 | 影响 | 处理 |
| --- | --- | --- |
| 审计表增长快 | 查询变慢、PG 存储增长 | 本阶段加索引、分页、默认 retention 查询窗口；R23 再做自动清理 |
| 审计写入拖慢主链路 | 登录/接口/任务延迟 | 审计服务 best-effort，失败降级应用日志，不阻断主流程 |
| 审计泄露敏感信息 | 安全风险 | 上下文白名单，禁止原始 body、密码、token、验证码入库 |
| 租户管理员审计越权 | 可见其他租户操作 | 服务层强制 tenant_id 范围，不信任前端参数 |
| 字典 label 被用于业务判断 | 业务语义漂移 | 业务判断只使用稳定 code，label 仅展示 |
| 字典表删除策略冲突 | 误删字典项 | 数据库限制删除，服务层禁删有明细类型 |
| 认证配置运行时读取依赖 PG | 登录链路受 PG 波动影响 | 读取失败回退静态默认值 |
| 页面布局不符合规范 | 页面可用性差或测试失败 | 按 page-template 补 slot、维护清单、关键视口验收 |
| 新资源码漏 seed 或漏守卫 | 页面不可见或接口裸露 | 路由扫描、菜单守卫和资源码测试覆盖 |

### 10.2 假设

- R16 “人机校验”本阶段等同于登录失败后的图形验证码挑战，不接第三方滑块或行为验证码。
- R17 保留期配置本阶段用于默认查询窗口和页面展示，不执行自动删除。
- 数据字典首批消费以权限体系和审计展示枚举为主，不强制迁移全量业务枚举。
- 审计 API 递归保护允许跳过 `/api/audit/**` 的 API 事件，或用内部标记防止重复写入；实现时选择不造成无限写入的方案。
- 当前阶段不需要数据库 MCP 直接读取线上结构；以代码 DDL 和需求文档为依据。

### 10.3 待确认项

| 待确认项 | 是否阻塞 | 当前处理 | 触发时机 |
| --- | --- | --- | --- |
| 是否需要独立第三方人机校验服务 | 否 | 本阶段不做，按图形验证码挑战落地 | 用户明确要求滑块/行为验证码时 |
| 少量稳定业务枚举具体名单 | 否 | 先做权限体系枚举和审计枚举，其他枚举实现时按现有代码确认后少量纳入 | T6 实施前后 |
| 审计 API 是否记录自身查询事件 | 否 | 默认做递归保护，避免无限写入 | T4/T5 实现时 |
| 审计保留期配置是否在系统设置页展示为独立分组 | 否 | 推荐放“审计设置”分组，字段为 `audit.retention_days` | T2/T10 实施时 |

## 11. 整改后自审结果

| 审查项 | 结果 | 说明 |
| --- | --- | --- |
| auto-plan-dev 固定结构 | 通过 | 已补 1-10 章，并保留第 5 章“需求与开发内容映射和开发状态” |
| 需求到任务可追踪 | 通过 | R16/R17/R18/R19、页面规范和 RBAC 约束均映射到任务、状态、偏差判断 |
| 可选/后续项完整映射 | 通过 | R22/R23/R24/R25/R26/R27/R28 均标注跳过、原因和阶段 |
| R23 口径 | 通过 | 自动清理跳过，但 R17 的 90 天可配纳入配置、默认查询窗口和页面提示 |
| R16 人机校验口径 | 通过 | 明确本阶段等同图形验证码挑战，不接第三方挑战 |
| 页面设计闭环 | 通过 | P8/P9 已补页面定位、原型选择、slot、配置层级、维护清单和三档视口验收 |
| 原型功能点承接 | 通过 | P8/P9 原型操作入口、状态、弹窗/抽屉、分页、权限、低高度退化均映射到任务 |
| SQL 执行和回滚 | 通过 | 已补 SQL 路径、用途、执行时机、影响范围和回滚口径 |
| dict 删除策略冲突 | 通过 | 已改为 `ON DELETE RESTRICT`/默认限制，并由服务层禁删有明细类型 |
| 测试验证计划 | 通过 | 已补后端、前端、权限、异常、原型一致性、配置闭环和需求映射验证 |
