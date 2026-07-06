# 需求文档：多租户多用户权限体系（multi-tenant-rbac）

> 本文档由 `requirement-closure-designer` 闭环结论 + `requirement-doc-generator` 生成。上游闭环已确认的全部决策、范围划分、页面闭环草案在此「继承并展开」为正式需求，不重新发散。
> 文档内确认状态标记：【已确认】=用户明确拍板；【项目依据】=代码/数据库证据；【推断决策】=按惯例推断并已获用户「采纳建议」；【风险】=需开发期重点防控。

---

## 1. 背景与目标

### 1.1 背景
立项时「复盘啦」是**本地单用户、EOD（收盘后）** 的 A 股趋势龙头研究系统，单进程全栈（FastAPI + Vue3 + 嵌入式 DuckDB 单文件），**无认证、无用户概念、无外部数据库/中间件依赖**。阶段一至阶段四已将其演进为混合持久层、多租户 RBAC、账号登录和用户资产隔离并存的系统。

### 1.2 目标
将系统升级为**公网 SaaS 对外**的**多租户 + RBAC + 账号登录**平台：

- 多人各自拥有私有研究资产，按租户与用户隔离，互不可见。
- 通过角色控制每个人能看哪些**菜单**、用哪些**功能**（按钮 + 接口）。
- **租户**作为数据隔离与计费单元，为后续「付费角色」铺路。
- 安全可控的 Web 登录，抵御暴力破解、越权、常见 Web 攻击与接口滥刷。
- 新增**日志审计**与**数据字典**两项平台能力，并重构**配置管理**为父子菜单。

### 1.3 本次定位级变更（【已确认】，影响全局）
- 系统定位由「本地单用户、无外部依赖」→「**公网多租户、依赖 PostgreSQL + Redis + 反向代理**」。
- 持久层由「纯 DuckDB 单文件」→「**混合：行情留 DuckDB（只读分析）+ 用户资产迁 PostgreSQL（并发写）**」。
- 上线后需同步改写 [CLAUDE.md](../../CLAUDE.md)、[README.md](../../README.md)、`agent-works/architecture/`、`start.sh`/部署脚本，否则后续开发会按旧契约行事（见 R1 / 第 9 章 / 第 12 章）。

---

## 2. 当前项目现状

### 2.1 认证与会话（零基础）
- [backend/main.py](../../backend/main.py) 仅配置 `CORSMiddleware`（允许 `localhost:5173`），**无任何认证/鉴权中间件、无登录接口、无 JWT/session**。
- 统一响应包 `{code, msg, data}`，业务异常 `AIStocksError` 统一捕获返回 HTTP 200。
- 前端 [frontend/src/api/http.ts](../../frontend/src/api/http.ts)：axios 实例 `baseURL:/api`，响应拦截解包 `{code,msg,data}`，**请求不携带任何身份令牌**。

### 2.2 数据归属（私有资产表无归属字段）【项目依据】
- **行情/参考数据（全局只读）**：`stock_basic`、`daily_bar`、`daily_metrics`、`index_bar`、`trade_calendar`、`stock_suspension`、`data_*` 系列等，均无归属字段，是全市场近 5 年共享 reference。
- **用户私有资产表（当前仅 `id` 主键，无 user_id/tenant_id）**：`screen_profile`、`score_profile`、`trade_profile`、`stock_group`、`backtest_run`（及其从表 `backtest_trade/equity/metrics`）、`screen_result`、`score_result`、`score_snapshot*`。
- **已有归属桩**：`training_session.user_id`（注释「预留多用户，本期空」）、`layout_user_config.user_id`（[backend/storage/layout_config.py](../../backend/storage/layout_config.py) `DEFAULT_USER_ID = "local"`）。
- **全局配置层**：`app_config`（点分路径 key-value 覆盖层，[backend/storage/app_config.py](../../backend/storage/app_config.py)）。
- 全部读写经 `storage` 点时安全仓库（[backend/storage/repository.py](../../backend/storage/repository.py) 等），**仅面向 DuckDB**。

### 2.3 菜单与路由（前端硬编码静态数组）【项目依据】
- 侧边菜单唯一数据源 [frontend/src/components/menuConfig.ts](../../frontend/src/components/menuConfig.ts)：静态 `MenuNode[]`，五大组 —— 最新行情 / 策略筛选 / 策略回测 / 盘感训练 / 数据管理 / 系统管理。
- 路由 [frontend/src/router/index.ts](../../frontend/src/router/index.ts)：静态 `RouteRecordRaw[]`，**无路由守卫、无权限元信息**。
- 系统管理现含：配置管理（`/system/config`）+ 布局配置（`/system/layout/*` 三工作区）。

### 2.4 配置管理页（单页多 tab）【项目依据】
- [frontend/src/views/ConfigView.vue](../../frontend/src/views/ConfigView.vue)（1489 行）含 4 个 `el-tab-pane`：**评分规则（score）/ 技术指标（tech）/ 买卖指标（trade）/ 系统设置（system）**。

### 2.5 枚举与字典（几乎无统一收口）【项目依据】
- 前端 [frontend/src/constants/](../../frontend/src/constants/) 仅 `pagination.ts`。
- 后端 `data_dimension_registry`（[backend/storage/ddl.py](../../backend/storage/ddl.py)）是**数据维度登记**，非通用枚举字典。
- 大量枚举（打分方式、评级、指标来源/类型等）散落在各处硬编码，**无统一字典管理**。

### 2.6 已有 RBAC 邻近设施
- 布局系统已有 `layout_field_policy`（管理员收紧/放开「某组件某字段可在哪几层覆盖」）+ preset/page/user 四层（见 [configurable-layout-system 记忆指针]、[DESIGN.md](../../DESIGN.md)）。可作为「管理员配置 + 角色可见性」的设计参照，但权限模型本身需新建。

### 2.7 并发与写库约束【项目依据】【风险】
- DuckDB 嵌入式单文件、**单写进程**；CLAUDE.md 明确「写库全局互斥，同一时间只能跑一个写任务」。多用户并发写会串行、后端无法多进程水平扩展 —— 这是本次必须用混合持久层（R1/R2）化解的根本约束。

### 2.8 阶段五平台能力当前事实（2026-07-05 回写）
- **系统设置**：`/system/config/system` 已从旧单列配置页改为按 `/api/data/settings` 动态渲染配置组；`auth.require_email_code`、`auth.login_captcha_enabled`、`auth.captcha_after_fails`、`audit.retention_days` 已进入 `app_config` 白名单和系统设置页面；配置组与字段由后端 schema 返回说明文案。
- **注册/登录防滥用**：本阶段按“邮箱验证码开关 + 登录图形验证码挑战 + 阈值配置”落地，不接第三方人机挑战服务；公开配置 `/api/auth/public-config` 和注册/登录链路即时消费配置，`auth.login_captcha_enabled=true` 时登录页直接展示图形验证码并提交校验，`auth.captcha_after_fails` 作为后端强制要求验证码的失败次数兜底；登录失败后前端会刷新已展示验证码。
- **日志审计**：已新增 `audit_log`、`/api/audit`、审计查询页 `/system/audit`，覆盖 API、安全、任务、调度、RBAC、配置和字典维护事件；认证中间件横切审计写入已移出事件循环线程，审计写失败降级，不阻断主业务；列表和详情按资源码关联 `sys_resource.name` 输出中文目标说明，摘要接口回传实际 `audit.retention_days` 供页面提示消费。
- **数据字典**：已新增 `dict_type`、`dict_item`、`/api/dict`、数据字典页 `/system/dicts`；管理端 system-only，消费端 `/api/dict/items/public` 通过 `dict:read` 登录基线共享读提供启用项和内置枚举兜底；类型存在但全部停用时返回空列表且不兜底，类型缺失、非法或存储异常时回退内置枚举；审计页已消费 `audit_event_type`、`audit_result`、`audit_status`。
- **权限与菜单**：`/system/audit` 为 `visible=login`，tenant_admin 默认可见并拥有 `audit:view`；`/system/dicts` 为 system-only；`dict:read` 加入 `SHARED_RESOURCE_CODES` 并锚定 `/board` 这类 login 叶子菜单，不能挂 system-only 菜单。

---

## 3. 用户角色与使用场景

| 角色 | 管理/数据范围 | 典型场景 |
| --- | --- | --- |
| **系统管理员（平台方）** | 跨租户全局：用户、角色、菜单定义、功能资源、租户、数据字典、日志审计、**全局行情采集/调度/技术指标/系统设置/布局配置** | 维护权限模型、平台后台离线采集全市场数据、管租户 |
| **租户管理员** | **本租户内**：用户、为用户分配角色（仅限系统管理员预设角色）、查看本租户审计 | 拉人进租户、分配普通/付费角色 |
| **普通用户** | **仅自己的私有资产** + 被授权研究功能（行情/筛选/回测/训练 + 评分规则/买卖指标自配） | 建策略、跑回测、盘感训练、看行情 |
| **付费角色（后续）** | 普通用户 + 套餐解锁的功能/配额 | 本期仅预留角色模型扩展位，不实现计费（R25） |

权限边界关键点【已确认】：
- 「数据管理」「任务调度」「技术指标」「系统设置」「布局配置」「菜单管理」「租户管理」「数据字典」**仅平台系统管理员可见**；普通用户/租户管理员菜单无此组。
- 「评分规则」「买卖指标」属用户资产配置，普通用户可见可编辑**自己的**（保留在「配置管理」父菜单下，靠角色控制子页面可见，见 R19 / 13 章遗留项 1 的确认结论）。
- 行情/指数等全市场数据**全局共享只读**，普通用户不可触发全市场写任务。

---

## 4. 功能范围

### 4.1 必须实现

| 需求编号 | 需求项 | 来源/依据 | 验收意图 |
| --- | --- | --- | --- |
| R1 | 混合持久层与基础设施底座（PostgreSQL 资产库 + Redis 状态库 + 反向代理 TLS） | 【已确认】公网 SaaS + 持久层选型 | PG/Redis 接入可用，行情仍走 DuckDB，HTTPS 终结生效 |
| R2 | 双库访问层（行情 DuckDB 只读仓库 + 资产 PG 读写仓库 + 跨库编排） | 【已确认】混合持久层 | 回测/筛选可同时读行情(DuckDB)与方案(PG)，开发契约不破坏 |
| R3 | 存量私有资产数据迁移（DuckDB → PG，归默认租户 + 平台管理员） | 【已确认】隔离边界 | 现存 profiles/分组/回测/训练/布局/app_config 迁移后可正常读写并带归属 |
| R4 | 账号密码登录 + JWT 无状态会话（登录/登出/刷新/权限版本号即时失效） | 【已确认】JWT | 登录得 token，过期/吊销/权限变更后旧 token 失效 |
| R5 | 自助注册 + 注册首人自动建租户并成为租户管理员 | 【已确认】开户模式 | 注册成功自动建租户、首人=租户管理员，邮箱码防滥注 |
| R6 | 第三方登录入口占位（手机/邮件/微信/QQ） | 【已确认】留入口、后续对接 | 登录/注册页有第三方入口（置灰 + 敬请期待提示） |
| R7 | 鉴权中间件 + 请求上下文注入（current_user / current_tenant） | 闭环主链路 | 携带有效 token 的请求注入身份上下文；无/失效 → 401 |
| R8 | 接口级 + 按钮级 RBAC 权限校验 | 【已确认】权限粒度 | 无权调接口 → 403；无权按钮前端不渲染/禁用 |
| R9 | 数据归属与租户隔离（私有表加 tenant_id + owner_user_id，读写自动过滤） | 【已确认】隔离边界 | 用户只能读写本人/本租户数据，跨租户不可见 |
| R10 | 用户管理（CRUD/启停/重置密码/分配角色/关联租户） | 用户诉求 1 | 系统/租户管理员可管理用户全生命周期 |
| R11 | 角色管理（角色 CRUD + 绑定菜单&功能 + 内置角色） | 用户诉求 1、2 | 角色可勾选菜单与功能点，授权即时生效 |
| R12 | 菜单管理（菜单树后端数据化 CRUD） | 用户诉求 3 | 菜单从前端硬编码迁后端表，可增删改排序 |
| R13 | 功能管理（功能点/资源 resource 登记：按钮 + 接口权限码） | 用户诉求 3 | 每个菜单下可登记功能点供角色授权 |
| R14 | 租户管理（租户 CRUD + 指定租户管理员 + 用户归属） | 用户诉求 4 | 系统管理员可管理租户及其管理员 |
| R15 | 安全加固（密码哈希、登录限流/锁定、CSRF/XSS/SQL 注入防护、接口限流反扒） | 用户诉求 6 | 抵御暴力破解/越权/常见 Web 攻击/接口刷取 |
| R16 | 注册防滥用做成开关（落「系统设置」子页面，配置化） | 【已确认】非阻塞项 1 升级 | 邮箱码开关、登录图形验证码开关和后端强制阈值即时生效，缺值回落默认 |
| R17 | 日志审计（接口/任务/安全事件统一采集 + 可观测查询页） | 【已确认】新需求 | 被授权操作/任务/安全事件可在审计页按条件检索 |
| R18 | 数据字典（字典类型 + 字典项；首批权限体系枚举 + 少量稳定业务枚举） | 【已确认】新需求 | 字典项增删停用后下拉/校验即时反映；缺失回落代码默认 |
| R19 | 配置管理拆父子菜单（评分规则/技术指标/买卖指标/系统设置 独立子页面） | 【已确认】新需求；阶段四 R28 已前移落地 | 父菜单 + 4 子页面已按角色可见，系统设置已承载注册防滥用和审计查询窗口配置 |
| R20 | 前端登录态与权限渲染（auth store + http token 注入 + 路由守卫 + v-permission 指令） | 闭环主链路 | 未登录跳登录页，菜单/路由/按钮按权限码动态渲染 |
| R21 | 全部存量功能/接口接入用户体系（鉴权 + 数据过滤逐一覆盖） | 用户诉求 5 | 现有 13 个 API 路由与对应页面全部纳入鉴权与隔离 |

### 4.2 建议实现

| 需求编号 | 需求项 | 来源/依据 | 纳入条件 | 处理状态 |
| --- | --- | --- | --- | --- |
| R22 | token 静默刷新（无感续期，避免操作中断） | 体验增强 | R4 完成后、有空切入即可纳入 | 后续建议 |
| R23 | 审计日志保留期自动清理任务（默认 90 天可配） | 【已确认】审计细则 | R17 落地后纳入，避免审计表无限增长；阶段五已实现 `audit.retention_days=90` 配置、默认查询窗口和页面提示，**未实现自动清理任务** | 后续建议 |
| R24 | 操作审计字段级变更对比（who changed what from→to） | 增强可观测 | R17 基础事件稳定后纳入 | 后续建议 |
| R28 | 资产可见性与自助公开（评分/筛选/买卖/回测等方案：私有 / 同租户共享 / 全体公开 + 加载=自己的∪公开的） | 用户诉求（阶段四 C1 延伸）、遗留项 2 升级 | 评分方案公开能力已在阶段四 R28 分支落地；筛选/买卖/回测等其他资产公开仍后续独立扩展 | 后续建议 |

### 4.3 暂不实现

| 需求编号 | 需求项 | 不做原因 | 后续触发条件 |
| --- | --- | --- | --- |
| R25 | 第三方登录真实对接（手机/邮件/微信/QQ OAuth） | 本期只留入口（R6），对接工作量大、依赖外部资质 | 拿到各平台开发者资质 + 业务需要时 |
| R26 | 付费角色计费与配额 | 本期仅在角色模型预留套餐/配额扩展位，不做交易与计费 | 商业化启动时单独立项 |
| R27 | 高强度行情防爬（行为指纹/风控/验证码挑战体系） | 本期反扒收敛为接口限流 + 异常频次告警 + 审计 | 出现实际批量爬取行情时再升级 |

> R26「预留扩展位」指：角色表预留 `role_type`（system/tenant_admin/normal/paid）与可空 `plan_code`/`quota` 字段，不实现其消费逻辑。
>
> R28「资产可见性与自助公开」指：用户资产（评分/筛选/买卖方案、回测等）在个人私有基础上增加可见性维度（private / tenant / public），读侧从「仅本人」放宽为「本人 ∪ 公开 [∪ 同租户]」，用户可自助把自己的方案公开到同租户或全体。阶段四 R28 已先落地**评分方案**：公开到租户由 `score-profile:publish-tenant` 控制，公开到全体由 `score-profile:publish-public` 控制；非 owner 公开方案只读，可复制为自己的 private；公开方案快照写方案 owner 槽；新用户可见平台内置 public 预设。筛选方案、买卖方案、回测记录等其他资产的公开能力仍后续独立扩展。

---

## 5. 详细功能需求

### R1 混合持久层与基础设施底座
- **功能描述**：引入 PostgreSQL 作为用户资产/权限/审计/字典库，Redis 作为短状态库（限流/验证码/token 黑名单/权限版本号），前置反向代理做 HTTPS 终结与基础防护；行情等只读 reference 仍留 DuckDB。
- **前置条件**：部署环境可提供 PG（>=14 建议）、Redis（>=6 建议）、反代（Nginx/Caddy）。
- **操作流程**：应用启动时分别建立 DuckDB 连接（只读分析）、PG 连接池（资产读写）、Redis 连接；配置项集中到 [config/settings.yaml](../../config/settings.yaml) 并支持环境变量覆盖（连接串、密钥不入库不入码，走环境变量/密钥文件）。
- **输入输出**：连接配置 → 三类存储句柄。
- **校验规则**：启动自检三类存储连通性，任一失败给出明确启动错误（行情 DuckDB 必需；PG 必需；Redis 必需，缺失则降级策略见 R15/R16 但默认必需）。
- **异常情况**：PG/Redis 不可用 → 启动失败并打印诊断；运行期连接中断 → 重试 + 熔断，不静默吞错。
- **权限与数据范围**：基础设施级，无业务权限。
- **对现有功能的影响**：[backend/storage/](../../backend/storage/) 需新增 PG 客户端与仓库；`start.sh`/部署脚本与依赖清单（requirements/pyproject）须新增 PG/Redis 驱动；CLAUDE.md「无外部依赖」表述作废。

### R2 双库访问层
- **功能描述**：建立行情只读仓库（DuckDB）与资产读写仓库（PG）两套，业务编排层跨库组装；保持「防未来函数、防幸存者偏差、复权一致、点时安全」开发契约不变，仅数据落点拆开。
- **操作流程**：筛选/回测等读行情走 DuckDB 仓库；读写方案/分组/结果走 PG 仓库；需要联合时在 `services/` 编排层组装（禁止跨库 JOIN，先各取再内存合并或按主键二次查询，避免 N+1）。
- **校验规则**：复权查询仍统一走 `COALESCE(adj_factor_clean, adj_factor)`（DuckDB 侧不变）；点时安全（≤T 数据）在行情仓库层保证。
- **异常情况**：跨库一致性以「行情只读不变 + 资产事务在 PG」为界，不要求分布式事务（行情不参与写）。
- **对现有功能的影响**：原仅 DuckDB 的 `repository.py` 拆分；回测/筛选/评分服务改为双源读取。【风险】这是最大改造面，需保证迁移后选股/回测结果与迁移前一致（回归测试）。

### R3 存量私有资产数据迁移
- **功能描述**：将 DuckDB 中现存私有资产迁移到 PG，并补 `tenant_id`/`owner_user_id`，全部归「默认租户 + 平台管理员」。
- **迁移对象**：`screen_profile`、`score_profile`、`score_profile_version`、`trade_profile`、`trade_profile_version`、`screen_profile_version`、`stock_group`、`stock_group_member`、`backtest_run`/`backtest_trade`/`backtest_equity`/`backtest_metrics`、`screen_result`、`score_result`、`score_snapshot`/`score_snapshot_meta`、`training_session`/`training_round`/`training_trade`、`layout_user_config`、`app_config`（租户级部分）。
- **校验规则**：迁移前后行数一致、外键完整、归属字段非空；`layout_user_config.user_id="local"` → 映射到平台管理员 user_id。
- **异常情况**：迁移失败可回滚（DuckDB 原表保留只读副本，迁移成功并验证后再停用，不立即删除）。
- **DDL/迁移说明（按 CLAUDE.md 红线）**：迁移脚本默认置于 `agent-works/multi-tenant-rbac/migrate-assets-to-pg.sql` 与配套 Python 迁移命令（建议 `python -m backend.cli migrate-rbac`）；须写明执行时机（PG 表建好后、上线前一次性）、影响范围、回滚方式（保留 DuckDB 原表 + PG 侧可清空重导）。**不可逆点**：上线后用户在 PG 产生新数据即不可简单回退到 DuckDB。
- **对现有功能的影响**：迁移完成后，DuckDB 不再承载这些写表；`app_config` 拆分为平台级（仍可留 DuckDB 或迁 PG，建议迁 PG 统一）与租户级。

### R4 账号密码登录 + JWT 会话
- **功能描述**：提供登录、登出、刷新、获取当前身份（`/me`）接口；JWT 携带 user_id/tenant_id/role/**权限版本号(perm_ver)**；短期 access token + 较长 refresh token。
- **操作流程**：登录校验账密（哈希比对）→ 签发 access+refresh → 前端存储 → 请求带 access → 过期用 refresh 换新；登出将 token 加入 Redis 黑名单。
- **校验规则**：access token 过期时间短（建议 30~120 分钟，可配）；perm_ver 与服务端（Redis/PG）当前版本不一致 → 视为失效，强制重新拉权限或重登。
- **异常情况**：token 篡改/过期/被吊销/perm_ver 失配 → 401；refresh 失效 → 跳登录。
- **权限与数据范围**：登录公开；`/me` 需有效 token。
- **对现有功能的影响**：所有 `/api/**` 接口默认需鉴权（白名单：登录/注册/健康检查/第三方回调）。

### R5 自助注册 + 自动建租户
- **功能描述**：开放自助注册，注册首人自动创建其专属租户并成为该租户管理员。
- **操作流程**：填写账号/邮箱/密码 → 邮箱验证码校验（受 R16 开关控制）→ 创建用户 + 新建租户 + 绑定租户管理员角色 → 自动登录或跳登录。
- **校验规则**：账号/邮箱唯一；密码强度（受系统设置策略约束）；验证码有效期/次数（Redis）。
- **异常情况**：重复注册、验证码错误/过期、滥注（同 IP 频次限制）→ 明确提示并限流。
- **权限与数据范围**：注册公开；新建租户与用户归属自身。
- **对现有功能的影响**：需存在「默认/平台租户」与「平台系统管理员」初始化逻辑（首次部署 seed）。

### R6 第三方登录入口占位
- **功能描述**：登录/注册页提供 手机号 / 邮箱 / 微信 / QQ 入口按钮，本期**置灰 + "敬请期待" tooltip**，不发起真实 OAuth。
- **校验规则**：点击不报错、不跳转空白；明确告知后续开放。
- **对现有功能的影响**：仅前端入口位与文案；后端预留回调路由占位（不实现逻辑，见 R25）。

### R7 鉴权中间件 + 上下文注入
- **功能描述**：FastAPI 依赖/中间件解析 token，注入 `current_user`、`current_tenant` 到请求上下文，供 `api/`、`services/`、`storage/` 链路使用。
- **操作流程**：请求 → 解析 Authorization → 校验（含黑名单、perm_ver）→ 注入上下文 → 路由处理。
- **校验规则**：白名单接口跳过；非白名单无有效 token → 401。
- **异常情况**：解析异常统一 401，不泄露内部细节。
- **对现有功能的影响**：所有路由经统一入口；数据仓库读写默认从上下文取 tenant_id/owner 自动注入（配合 R9）。

### R8 接口级 + 按钮级 RBAC 校验
- **功能描述**：每个受控接口标注 resource code（功能点），请求时校验当前角色是否拥有该功能；前端按功能码控制按钮显隐/禁用。
- **操作流程**：接口装饰器/依赖声明 `require("resource_code")` → 校验角色-功能映射（来自 PG，缓存于 Redis）；前端 `v-permission="code"` 指令读取 `/me` 返回的功能码集合。
- **校验规则**：后端为准（前端隐藏≠后端放行，双层防护）；功能码集合随 perm_ver 失效刷新。
- **异常情况**：无权 → 接口 403 + 统一文案；前端按钮不渲染或禁用并提示。
- **权限与数据范围**：按角色-功能映射。
- **对现有功能的影响**：现有所有写/敏感接口需逐一打 resource code（R21）。

### R9 数据归属与租户隔离
- **功能描述**：私有资产表增加 `tenant_id` + `owner_user_id`，读写自动按上下文过滤。
- **操作流程**：写入自动填充归属；查询自动追加 `WHERE tenant_id=? AND (owner_user_id=? OR <租户共享策略>)`。
- **校验规则**：默认「个人私有」；是否支持「租户内共享」列为遗留确认项（13 章）。本期按个人私有 + 租户管理员可见本租户为默认推断。
- **异常情况**：跨租户/越权访问 → 查询无结果或 403；禁止前端传 tenant_id 越权（一律从 token 取）。
- **对现有功能的影响**：所有私有资产仓库方法签名/SQL 增加归属过滤；行情等共享表不加。

### R10 用户管理
- **功能描述**：用户增删改查、启用/禁用/锁定、重置密码、分配角色、关联租户。
- **操作流程**：列表（按租户过滤）→ 新建/编辑（账号/邮箱/角色/租户/状态）→ 保存。
- **校验规则**：账号/邮箱唯一；租户管理员只能管本租户用户、只能分配系统管理员预设角色（13 章遗留项 5 确认：本期租管不可自建角色）。
- **异常情况**：禁用/锁定后该用户 token 即时失效（perm_ver/黑名单）。
- **权限与数据范围**：系统管理员全局；租户管理员限本租户。
- **对现有功能的影响**：新增模块。

### R11 角色管理
- **功能描述**：角色 CRUD + 为角色勾选菜单 + 功能点；内置三角色（系统管理员/租户管理员/普通用户）+ 付费角色类型预留。
- **操作流程**：角色列表 → 编辑 → 在菜单&功能树上勾选 → 保存 → 触发相关用户 perm_ver 自增。
- **校验规则**：内置角色不可删除（可调整其权限范围需谨慎，系统管理员超管角色权限锁定）；角色名唯一。
- **异常情况**：删除被用户引用的角色 → 阻止或要求先解绑。
- **权限与数据范围**：系统管理员可管全部角色；租户管理员本期仅分配不自建（遗留项 5）。
- **对现有功能的影响**：新增模块，权限变更联动 R8 缓存失效。

### R12 菜单管理
- **功能描述**：将前端硬编码 `menuConfig` 迁为后端菜单表，支持树形 CRUD、排序、层级、图标、路由路径、可见性元信息。
- **操作流程**：菜单树编辑 → 增删改节点（分组/叶子）→ 保存 → 前端拉取后端菜单按权限渲染。
- **校验规则**：路由路径唯一且需与前端已注册路由对应（非法路由给出告警）；分组节点不导航。
- **异常情况**：删除有子节点的分组 → 阻止或级联确认；删除已被角色引用的菜单 → 提示影响范围。
- **权限与数据范围**：仅系统管理员。
- **对现有功能的影响**：[frontend/src/components/menuConfig.ts](../../frontend/src/components/menuConfig.ts) 由「唯一数据源」改为「后端菜单 + 前端兜底默认」；[frontend/src/components/SideMenu.vue](../../frontend/src/components/SideMenu.vue) 改为消费后端菜单 + 权限过滤。

### R13 功能管理（资源 resource）
- **功能描述**：在菜单节点下登记功能点（按钮级动作 + 对应接口权限码），作为角色授权的最小资源单位。
- **操作流程**：选中菜单 → 维护其功能点（code/名称/类型[按钮|接口]/绑定接口路径）→ 保存。
- **校验规则**：功能码全局唯一、稳定不可复用（与 R8 接口标注一致）；接口路径建议与后端 resource 装饰器对账。
- **异常情况**：删除被角色引用的功能点 → 提示影响。
- **权限与数据范围**：仅系统管理员。
- **对现有功能的影响**：与 R8 接口标注、R11 角色授权形成闭环。

### R14 租户管理
- **功能描述**：租户 CRUD、指定/变更租户管理员、查看租户内用户、启停租户。
- **操作流程**：租户列表 → 新建/编辑（名称/状态/管理员）→ 保存。
- **校验规则**：默认租户/平台租户不可删除；租户停用后其下用户不可登录。
- **异常情况**：删除有用户的租户 → 阻止或要求先迁移/清理。
- **权限与数据范围**：仅系统管理员。
- **对现有功能的影响**：新增模块；与 R5 自动建租户、R9 隔离联动。

### R15 安全加固
- **功能描述**：密码哈希（bcrypt/argon2，禁明文/弱哈希）；登录失败计数 + 阈值锁定（Redis）；接口限流（按 IP/用户/接口维度，Redis 令牌桶）；CSRF/XSS/SQL 注入防护；安全响应头；敏感信息脱敏。
- **校验规则**：限流命中、登录失败、锁定、越权均写审计（R17）；SQL 全部参数化（项目已用参数化查询，延续）。
- **异常情况**：限流命中 → 429 + 友好提示；锁定期内登录 → 明确剩余时间。
- **权限与数据范围**：全局基础能力。
- **对现有功能的影响**：反代层 + 应用层双重；反扒本期收敛为接口限流 + 异常频次审计告警（R27 之外不做行为风控）。

### R16 注册防滥用开关化
- **功能描述**：邮箱验证码（默认开）、登录图形验证码、图形验证码强制阈值做成开关/配置，落「系统设置」子页面；本阶段不接入第三方人机挑战服务。
- **配置化七问**：系统管理员**定义**（系统设置子页）→ 存 `app_config` 平台级（**保存**）→ 注册/登录链路**读取并消费**→ 关闭则跳过对应校验 → 非法值/缺值**回落代码默认**（默认开邮箱码、关图形码、失败 3 次后后端强制兜底）→ 前端开关即时**生效**（下次注册/登录读取新值）。
- **校验规则**：仅系统管理员可改；开关变更记审计。
- **对现有功能的影响**：与 R5/R15 登录注册链路联动。
- **阶段五落地事实**：`auth.require_email_code`、`auth.login_captcha_enabled`、`auth.captcha_after_fails` 已进入配置白名单、`/api/data/settings` 和 `/system/config/system`；`/api/auth/public-config` 与注册/登录链路已消费配置，开启图形验证码后登录页首屏展示，后端对已提交验证码执行校验并保留失败阈值强制兜底，配置保存写入脱敏审计。

### R17 日志审计（新需求）
- **功能描述**：统一采集三类事件并提供只读可观测查询页：①接口事件（所有 `/api` 请求）②任务事件（`async_task` / `scheduled_job` 钩子）③安全事件（登录成败/限流命中/验证码失败/token 吊销/越权 403）。
- **核心字段**【已确认】：时间、处理人、事件类型/分类、资源/接口码、目标对象、目标中文说明、事件结果、事件状态、租户、IP、耗时、错误摘要。
- **事件上下文（脱敏）**：按事件类型补充用于排障和追踪的结构化摘要，例如 `request_id`、`permission_code`、`task_id`、`action`、`affected_count`、`rate_limit_rule`、`config_key` 等；不记录原始请求体、响应体、密码、token、验证码或其他敏感明文。
- **操作流程**：后端统一中间件（接口）+ 任务钩子（任务）+ 安全事件埋点 → best-effort 写 PG 审计表 → 审计页按 时间/处理人/类型/结果/状态/资源/租户 筛选 + 分页查看；类型、结果、状态和租户筛选支持多选，下拉选择后即时查询。
- **校验规则**：审计只读不可改（防篡改）；**不记录请求/响应体**，仅摘要（13 章确认）；`audit.retention_days` 默认 90 天可配，并作为未显式传时间范围时的默认查询窗口，摘要接口回传实际值供页面提示；自动清理任务仍属 R23 后续建议。
- **异常情况**：审计写失败**降级**（落本地日志兜底），绝不阻断主业务；审计写入异步，避免拖慢请求。
- **权限与数据范围**：系统管理员看全局；租户管理员看本租户（13 章确认）。
- **对现有功能的影响**：现有功能靠中间件/钩子自动纳入，不逐接口手写埋点。【风险】审计表高频增长 → 需保留期清理 + 索引/分区。
- **阶段五落地事实**：已新增 `audit_log` 索引、`/api/audit` 查询/摘要/详情、审计页 `/system/audit`、`audit:view` 资源码和 tenant_admin 默认授权；审计列表和详情会展示由 `sys_resource.name` 派生的中文说明；审计筛选下拉已沉淀为 `AppFilterSelect`，默认多选、可搜索、可清空、最多展示 3 个选中标签且溢出提前折叠，选择即查询，系统管理员租户筛选改为 `/api/tenants` 下拉，租户管理员不展示跨租户入口且服务层强制本租户；已覆盖 API、安全、任务、调度、RBAC、配置和字典维护事件。

### R18 数据字典（新需求）
- **功能描述**：以「字典类型 + 字典项（code/label/排序/启用/备注）」统一管理枚举；后端校验枚举合法性引用字典，前端下拉/标签渲染消费字典。
- **首批接入范围**【已确认】：权限体系自身枚举（**角色类型、用户状态、审计事件类型、审计结果、审计状态**）+ 少量稳定业务枚举；其余渐进迁移。
- **不接入**：`indicator_def`（指标原子定义，是统一基座，不塞通用字典）；`data_dimension_registry` 是否并入列遗留项。
- **配置化七问**：系统管理员**定义**（数据字典页）→ 存 PG 字典表（**保存**）→ 后端校验/前端下拉**读取消费**→ 写业务校验值∈字典项（**校验**）→ 字典服务异常/项缺失**回落代码内置默认枚举**（不因字典挂了导致页面空白）→ 字典项变更后前端缓存失效（**生效**）。
- **校验规则**：字典类型 code、同类型内字典项 code 唯一；停用项不再用于新数据但保留历史值显示。
- **异常情况**：缺失字典 → 回落默认；前端字典缓存（启动拉取 + 变更失效，13 章确认）。
- **权限与数据范围**：系统管理员维护，全系统登录用户通过 `dict:read` 消费启用项；无角色用户 fail-closed，不获得 `dict:read`。
- **对现有功能的影响**：渐进改造，现有硬编码枚举逐步引用字典；本期不强制全量替换。
- **阶段五落地事实**：已新增 `dict_type`、`dict_item`、`/api/dict/types`、`/api/dict/items`、`/api/dict/items/public` 和 `/system/dicts`；管理端接口使用 system-only 守卫，`dict:read` 加入登录基线共享读并锚定 `/board`；类型 code、字典项 type/code 创建后不可变，编辑弹窗禁用对应字段，PUT 不提交不可变字段；数据字典右侧状态筛选复用 `AppFilterSelect` 的单选模式，选择启用/停用时传 `enabled=true/false`；消费端类型存在但全部停用时返回空列表且 `fallback=false`，类型缺失、非法或存储异常时回退内置枚举；审计页已消费审计事件类型、审计结果和审计状态字典，角色类型/用户状态仍按渐进迁移处理。

### R19 配置管理拆父子菜单（新需求）
- **功能描述**：将 [ConfigView.vue](../../frontend/src/views/ConfigView.vue) 单页 4 tab 拆为「配置管理」父菜单 + 4 个独立子页面（独立路由 `/system/config/{score|trade|tech|system}`），阶段四 R28 已前移落地为复用同一 ConfigView 的单 tab 模式。
- **子页面权限差异**【已确认】：评分规则、买卖指标 → 用户资产级（普通用户可见可编辑自己的）；技术指标（`indicator_def`）、系统设置（`app_config` 平台参数）→ 仅系统管理员。
- **操作流程**：父菜单展开 → 进入对应子页面 → 各自独立加载与保存。
- **校验规则**：子页面可见性由角色-菜单映射控制（R11/R12）；保留现有配置保存口径（评分/买卖=资产；技术指标/系统设置=平台）。
- **异常情况**：无权子页面不在菜单出现，直达 URL 被路由守卫拦截。
- **对现有功能的影响**：路由新增子路由；菜单树新增父子节点；`/system/config` 重定向到 `/system/config/score`；注册防滥用开关（R16）和审计默认查询窗口配置已落「系统设置」子页面。
- **阶段五落地事实**：`/system/config/system` 已动态消费 `/api/data/settings` 返回的 `CONFIG_GROUPS`，不再依赖指标注册表初始化；配置组按 Tab 分类展示，认证与审计位于同一组，数据采集、股票池与回测分别归类；系统设置页不展示“平台配置”标题；配置组和字段均展示后端 schema 说明，无 `data-settings:manage` 权限显示权限态且不请求设置接口。

### R20 前端登录态与权限渲染
- **功能描述**：新增 Pinia `auth` store（token/用户/租户/角色/菜单/功能码）；`http.ts` 拦截器注入 Authorization + 处理 401/403；路由守卫拦未登录与无权路由；`v-permission` 指令控按钮。
- **操作流程**：登录写 store + 持久化 token → 启动/刷新拉 `/me` → 菜单按后端菜单+功能码过滤渲染 → 路由守卫校验 → 按钮指令控制。
- **校验规则**：401 清登录态跳登录（或静默刷新 R22）；403 提示无权。
- **异常情况**：token 失效、网络错误统一处理；无可见菜单时给占位提示。
- **对现有功能的影响**：[App.vue](../../frontend/src/App.vue)、[SideMenu.vue](../../frontend/src/components/SideMenu.vue)、[router/index.ts](../../frontend/src/router/index.ts)、[http.ts](../../frontend/src/api/http.ts) 均改造。

### R21 全部存量功能接入用户体系
- **功能描述**：现有 13 个 API 路由（[backend/api/](../../backend/api/)：backtest/board/config/indicators/layout/profiles/score_profiles/trade_profiles/stock_groups/stocks/data_tasks/data_admin/training）与对应前端页面，逐一接入鉴权（R7）、接口权限（R8）、数据隔离（R9）。
- **操作流程**：逐路由标 resource code + 接归属过滤；前端逐页接路由守卫 + 按钮指令。
- **校验规则**：行情/指数等只读共享接口仅需登录、不做归属过滤；私有资产接口需归属过滤；全市场写任务（data_admin/data_tasks/调度）仅系统管理员。
- **异常情况**：迁移期保证未改造接口默认拒绝（安全默认 deny）而非默认放行。
- **对现有功能的影响**：全量接口与页面，工作量大，建议分批（见 12 章）。

---

## 6. 数据与接口需求

### 6.1 新增数据表（PostgreSQL，权限/审计/字典）
| 表 | 用途 | 关键字段 |
| --- | --- | --- |
| `sys_tenant` | 租户 | id, name, status, admin_user_id, created_at |
| `sys_user` | 用户 | id, tenant_id, account, email, password_hash, status(启用/禁用/锁定), created_at |
| `sys_role` | 角色 | id, code, name, role_type(system/tenant_admin/normal/paid), plan_code?, quota?, builtin(bool) |
| `sys_menu` | 菜单树 | id, parent_id, code, title, icon, route_path, sort, type(group/leaf), visible |
| `sys_resource` | 功能点/资源 | id, menu_id, code(全局唯一), name, type(button/api), api_path? |
| `sys_user_role` | 用户-角色 | user_id, role_id |
| `sys_role_menu` | 角色-菜单 | role_id, menu_id |
| `sys_role_resource` | 角色-功能 | role_id, resource_id |
| `audit_log` | 审计 | id, ts, actor_user_id, actor_name, tenant_id, event_type, event_category, resource_code, target, result(成功/失败), status, ip, latency_ms, error_msg |
| `dict_type` | 字典类型 | id, code(唯一), name, remark |
| `dict_item` | 字典项 | id, type_code, code, label, sort, enabled, remark |

### 6.2 存量资产表改造（迁 PG 并加归属，R3/R9）
- 对 2.2 节列出的私有资产表统一追加 `tenant_id`、`owner_user_id`，建立 `(tenant_id, owner_user_id)` 索引；`training_session.user_id`、`layout_user_config.user_id` 归一到 owner_user_id 体系。
- `app_config` 拆「平台级」与「租户级」（租户级加 tenant_id）。

### 6.3 行情/参考数据（不变，DuckDB）
- `stock_basic`/`daily_bar`/`daily_metrics`/`index_bar`/`trade_calendar` 等保持全局只读共享，**不加归属字段**。

### 6.4 新增接口（统一前缀 /api，沿用 {code,msg,data}）
- 认证：`POST /api/auth/login`、`POST /api/auth/logout`、`POST /api/auth/refresh`、`POST /api/auth/register`、`GET /api/auth/me`、（占位）`GET /api/auth/oauth/{provider}`。
- 用户：`/api/users`（CRUD/启停/重置密码/分配角色/关联租户）。
- 角色：`/api/roles`（CRUD + 绑菜单/功能）。
- 菜单：`/api/menus`（树 CRUD）。
- 功能：`/api/resources`（CRUD）。
- 租户：`/api/tenants`（CRUD + 指定管理员）。
- 审计：`/api/audit`（查询/筛选/分页，只读；清理为管理员任务）。
- 字典：`/api/dict/types`、`/api/dict/items`（CRUD）、`/api/dict/items?type=xxx`（消费查询，可缓存）。
- 存量接口：全部接鉴权 + resource code + 隔离（R21）。

### 6.5 数据一致性与流转
- 行情只读不参与写事务；资产写在 PG 事务内；跨库不做分布式事务（行情不写）。
- 权限变更 → 自增相关用户 perm_ver（PG 持久 + Redis 缓存）→ 旧 token 失效。
- 审计异步写，失败降级本地日志，不影响主链路。

---

## 7. 页面与交互开发需求

> 前端规范入口：[DESIGN.md](../../DESIGN.md) 与 [page-template.md](../../agent-works/configurable-layout-system/page-template.md)。所有新页面遵循：列表交互规范、禁整页滚动、弹窗/抽屉规范、构建口径（改 `frontend/src` 后 `npm run build` 同步产物）。新页面需走页面设计闭环与维护矩阵。
>
> **页面原型**：每个**新增页面**在同目录 `prototypes/{page-slug}.html` 出一份自包含静态 HTML 原型并在页面条目「原型文件」引用；原型优先复用项目既有前端风格/组件/布局密度（特殊全屏页可按确认的专属风格），「页面布局」描述须与原型一致。**更新页面**按复杂度决定：涉及新增主要区域/布局重排/跨组件联动/复杂表单表格时出更新后或变更区域原型，仅局部小改写「不生成原型」+ 原因即可。原型在需求文档阶段敲定，开发计划只承接、不重复设计。

### 7.1 页面 P1：登录 / 注册页（R4/R5/R6/R16）
- 对应需求编号：R4、R5、R6、R16
- 页面类型：新增页面（全屏独立壳，脱离主框架侧边栏）
- 页面入口：未登录访问任意受控路由 → 路由守卫重定向至 `/login`
- 原型文件：[prototypes/login.html](prototypes/login.html)（自包含静态 HTML，浏览器直开、内置黑/白主题切换）。登录页为全屏独立壳，已确认采用**科技风 + 黑白双主题**专属风格（非主框架 Element Plus 密度），实现以此原型为视觉事实源。
- 页面布局（与原型一致）：**左视觉 / 右表单 分栏壳**。
  - 左=品牌视觉区（科技风动态网格 + 标语，≤768px 隐藏退化为顶部 Logo 带）；右=认证卡（主题切换固定右上、登录·注册 Tab 切换）。
  - 登录态字段：账号/邮箱、密码（含明文切换）、图形验证码（开关开启后显示，失败阈值作为后端强制兜底）、登录按钮、忘记密码占位、第三方占位行。
  - 注册态字段：账号/邮箱、密码、确认密码、邮箱验证码（开关控制，带发送倒计时）、注册按钮。
  - 第三方登录（R6）：手机/邮箱/微信/QQ 四入口**置灰 + 「敬请期待」tooltip**，点击不跳转。
  - 黑白双主题：复用前端 `useTheme()` 切 `html.dark`；原型 `:root`=白、`[data-theme=dark]`=黑，对应实现两套 CSS 变量。
- 数据来源：`/api/auth/login`、`/api/auth/register`、注册防滥用开关来自 `/me` 前的公开配置或登录页专用配置接口
- 权限与可见性：公开

#### 7.1.1 功能点：账号密码登录（R4）
- 默认展示：登录表单；图形验证码按 R16 开关显隐
- 用户操作：输入账密 → 点登录
- 输入与校验：账号/邮箱非空、密码非空；前端基础校验，后端权威校验
- 状态变化：成功写 auth store + 跳首页；失败计数 +1
- 保存/提交/取消：登录成功持久化 token
- 加载状态：登录按钮 loading
- 无数据状态：—
- 错误状态：账密错误/锁定/限流（429）友好提示，锁定显示剩余时间
- 权限不足状态：—（公开）
- 数据刷新：登录后拉 `/me`
- 与其他功能点联动：触发菜单/路由/按钮渲染（P3、R20）
- 验收标准：正确账密登录成功并进入首页；错误达阈值后锁定；限流命中返回 429

#### 7.1.2 功能点：自助注册 + 自动建租户（R5）
- 默认展示：切换到注册态表单
- 用户操作：填账号/邮箱/密码/邮箱验证码 → 注册
- 输入与校验：唯一性 + 密码强度 + 验证码（开关控制）
- 状态变化：成功创建用户 + 新租户 + 绑租户管理员角色
- 错误状态：重复注册、验证码错误/过期、滥注限流提示
- 验收标准：注册成功后该用户为新租户的租户管理员；关闭邮箱码开关后注册跳过验证码

#### 7.1.3 功能点：第三方登录入口占位（R6）
- 默认展示：4 个入口按钮置灰
- 用户操作：hover 显示「敬请期待」；点击无跳转
- 验收标准：入口存在、置灰、不报错、不跳空白

### 7.2 页面 P2：主框架顶栏用户区（R20，更新 [App.vue](../../frontend/src/App.vue)）
- 对应需求编号：R20、R4
- 页面类型：更新页面（顶栏区域）
- 页面入口：登录后全局可见
- 原型文件：不生成原型——仅在现有顶栏右侧局部新增「用户名 · 租户」下拉 + 退出，无布局重排/跨组件联动，属低风险局部更新；以下「页面布局」变更说明为准。
- 页面布局（变更区域）：顶栏右侧新增「当前用户名 · 所属租户」下拉 →（个人信息占位 / 退出登录）；保留区域为现有顶栏其余部分
- 数据来源：auth store（来自 `/me`）
- 权限与可见性：已登录可见
#### 7.2.1 功能点：显示身份 + 退出登录
- 用户操作：点退出 → 清登录态 + token 黑名单 → 跳登录页
- 状态变化：登录态清空
- 错误状态：退出接口失败也强制前端清态
- 验收标准：退出后无法用旧 token 访问受控接口

### 7.3 页面 P3：侧边菜单动态渲染（R12/R20，更新 [SideMenu.vue](../../frontend/src/components/SideMenu.vue) / [menuConfig.ts](../../frontend/src/components/menuConfig.ts)）
- 对应需求编号：R12、R20、R8
- 页面类型：更新（菜单数据源由前端硬编码 → 后端菜单 + 权限过滤）
- 页面布局：保留现有侧边栏结构与交互；数据改由后端菜单树驱动，按当前用户功能码过滤后渲染；前端保留一份默认菜单兜底（后端不可用时）
- 数据来源：`/api/menus`（或 `/me` 内联可见菜单）
- 权限与可见性：按角色-菜单映射
#### 7.3.1 功能点：按权限渲染菜单
- 默认展示：仅渲染有权菜单；无权分组/叶子不出现
- 状态变化：权限变更（perm_ver）后重新拉取刷新
- 无可见菜单：无任何可见菜单时给无权限/无菜单提示。
- 验收标准：普通用户看不到「数据管理/任务调度/技术指标/系统设置/菜单管理/租户管理/数据字典」；系统管理员可见全部

### 7.4 页面 P4：用户管理（R10）
- 对应需求编号：R10
- 页面类型：新增页面（系统管理 → 权限管理 → 用户管理，`/system/users`）
- 页面入口：侧边菜单「系统管理 → 权限管理 → 用户管理」（系统管理员全局、租户管理员限本租户可见）
- 原型文件：[prototypes/user-management.html](prototypes/user-management.html)（自包含静态 HTML，浏览器直开、内置黑/白主题切换、可交互）。**页面布局与交互以此原型为事实源，不再另附草图。**
- 页面布局（对齐原型）：套 LayoutHost 列表原型——页头(标题+[＋新建用户])；工具栏(租户▾[仅系统管理员] / 角色▾ / 状态▾ / 搜索账号·邮箱 / 查询)；主表格 el-table 表体内滚(勾选列 / 账号 / 邮箱 / **角色[多标签]** / 租户 / 状态[启用·禁用·锁定 tag] / 最后登录 / 操作)，操作随状态变化(编辑 / 重置密码 / 启停 / 解锁 / 删除)；分页；新增·编辑走 el-dialog、重置密码独立弹窗。
- 关键交互：**角色多选**——一个用户可挂多个角色、权限取并集（落 `sys_user_role` 关联表）；编辑弹窗内以「可增删角色标签 + 勾选下拉」维护；租户管理员只能在系统预设角色内为本租户用户分配。
- 数据来源：`/api/users`、`/api/roles`、`/api/tenants`、`/api/user-roles`
- 权限与可见性：系统管理员全局；租户管理员限本租户（无租户切换、租户列锁定本租户）
#### 7.4.1 功能点：用户列表查询/分页
- 默认展示：本权限范围用户列表（默认分页规范 [pagination.ts](../../frontend/src/constants/pagination.ts)）
- 输入与校验：筛选条件可空
- 加载/无数据/异常状态：loading / 空列表占位 / 错误重试
- 验收标准：租户管理员只看到本租户用户
#### 7.4.2 功能点：新增/编辑用户
- 用户操作：填表保存；角色区可增删多个角色标签
- 输入与校验：账号/邮箱唯一、密码强度、租户必选、**角色至少一个（多选）**
- 状态变化：保存后列表刷新，角色列展示多标签
- 权限不足状态：租户管理员不可跨租户、不可分配非系统预设角色
- 验收标准：保存成功后用户按所配**多角色权限并集**登录使用
#### 7.4.3 功能点：启停/锁定/重置密码/删除
- 状态变化：禁用/锁定后该用户 token 即时失效
- 错误状态：删除自身/最后一个管理员等给出阻止
- 验收标准：禁用用户立即无法访问受控接口

### 7.5 页面 P5：角色管理（R11，消费 R12/R13 产物）
- 对应需求编号：R11（授权树消费 R12 菜单 / R13 功能点，非在此管理它们）
- 页面类型：新增页面（系统管理 → 权限管理 → 角色管理，`/system/roles`）
- 页面入口：侧边菜单「系统管理 → 权限管理 → 角色管理」（系统管理员；租户管理员本期仅分配不自建）
- 原型文件：[prototypes/role-management.html](prototypes/role-management.html)（自包含静态 HTML，内置黑/白主题；master-detail 布局）。
- 页面布局：master-detail——左「角色列表」（内置系统管理员[超管·权限锁定]/租户管理员/普通用户 + 付费类型预留 + 自建角色，选中态）；右「菜单&功能授权树」（`el-tree show-checkbox`，菜单为父、功能点[按钮/接口]为叶）+ 详情条（角色名/角色码/关联用户数、重命名、全选/清空）+ 底部脏标 [还原][保存并刷新权限]；顶部 [＋新建角色]。超管角色权限树禁用勾选。
- 数据来源：`/api/roles`、`/api/menus`、`/api/resources`
- 权限与可见性：系统管理员可编辑；租户管理员本期仅查看/分配（遗留项 5）
#### 7.5.1 功能点：角色 CRUD
- 输入与校验：角色名/code 唯一；内置角色不可删
- 验收标准：新建角色可被用户分配
#### 7.5.2 功能点：菜单+功能授权
- 用户操作：在树上勾选菜单与功能点 → 保存
- 状态变化：保存后相关用户 perm_ver 自增、权限即时生效
- 验收标准：勾掉某功能后，拥有该角色的用户对应按钮消失、接口返回 403

### 7.6 页面 P6：菜单与功能管理（R12+R13 合页）
- 对应需求编号：R12（菜单树数据化）、R13（功能点/资源登记）——同一工作流「选中菜单→维护其功能点」，合为一页
- 页面类型：新增页面（系统管理 → 权限管理 → 菜单与功能，`/system/menus`）
- 页面入口：侧边菜单「系统管理 → 权限管理 → 菜单与功能」（仅系统管理员）
- 原型文件：[prototypes/menu-resource-management.html](prototypes/menu-resource-management.html)（自包含静态 HTML，内置黑/白主题；master-detail 布局）。
- 页面布局：master-detail——左「菜单树」（分组/叶子节点，拖拽排序、增删，对应现 [menuConfig.ts](../../frontend/src/components/menuConfig.ts) 的 index/title/icon/children）；右上「菜单属性」表单（标题/类型[分组\|叶子]/路由/**图标[图标选择器]**/排序/可见性[登录可见\|system-only]）+ 右下「功能点表」（功能码/名称/类型[按钮\|接口]/绑定接口/操作）+ 底部 [还原][保存]；顶部 [＋新增菜单节点]，节点内 [＋新增子节点][删除节点][＋新增功能点]。
- **图标体系【已确认】**：采用 **Element Plus Icons**（`@element-plus/icons-vue`，项目 Element Plus 配套）；菜单表 `icon` 字段存**图标名**（如 `TrendCharts`/`Setting`），页面用**可搜索的图标网格选择器**选取，不手填任意字符。落地后 [SideMenu.vue](../../frontend/src/components/SideMenu.vue) 由渲染 emoji 改为按图标名渲染 EP 图标组件；存量 menuConfig 的 emoji 需一次性映射为图标名。
- 数据来源：`/api/menus`、`/api/resources`
- 权限与可见性：仅系统管理员
#### 7.6.1 功能点：菜单树 CRUD/排序
- 校验：route_path 唯一且对应前端已注册路由；分组不导航；icon 存 Element Plus 图标名
- 错误状态：删除有子节点/被引用菜单给出阻止或影响提示
- 验收标准：新增叶子菜单 + 授权后即在对应角色菜单出现
#### 7.6.2 功能点：功能点（资源）登记
- 校验：功能码全局唯一不可复用
- 验收标准：登记的功能点可在角色管理被勾选并对接口生效

### 7.7 页面 P7：租户管理（R14）
- 对应需求编号：R14
- 页面类型：新增页面（系统管理 → 权限管理 → 租户管理，`/system/tenants`）
- 页面入口：侧边菜单「系统管理 → 权限管理 → 租户管理」（仅系统管理员）
- 原型文件：[prototypes/tenant-management.html](prototypes/tenant-management.html)（自包含静态 HTML，内置黑/白主题；套 LayoutHost 列表原型）。
- 页面布局：页头 [＋新建租户] + 工具栏(状态▾/搜索租户名/查询)；表格(租户名[内置标记]\|租户ID\|状态(tag)\|租户管理员\|用户数\|创建时间\|操作)；操作 编辑/查看用户/启停/删除（内置默认租户删除置灰）；编辑 el-dialog(租户名/租户ID[系统生成不可改]/管理员[从该租户用户指定]/状态段选)。「查看用户」跳「用户管理」并按该租户过滤。
- 数据来源：`/api/tenants`、`/api/users`
- 权限与可见性：仅系统管理员
#### 7.7.1 功能点：租户 CRUD + 指定管理员 + 启停
- 校验：默认/平台租户不可删；停用租户其下用户不可登录
- 验收标准：停用租户后该租户用户登录被拒

### 7.8 页面 P8：数据字典（R18）
- 对应需求编号：R18
- 页面类型：新增页面（系统管理 → 数据字典）
- 页面入口：侧边菜单（仅系统管理员）
- 原型文件：[prototypes/data-dictionary.html](prototypes/data-dictionary.html)（阶段五新增页面原型，已按下方「页面布局」落地）。
- 页面布局：
  - 布局事实源：对齐 `prototypes/data-dictionary.html`，采用 master-detail 管理页结构，首屏直接进入字典维护工作台。
  - 页面区域：页头为标题 + 主命令区（新建类型、刷新、主题/设置入口）；主体左栏为「字典类型」检索列表；主体右栏为当前类型详情与字典项维护区。
  - 主次关系：字典类型是主导航和数据范围，字典项是当前主对象下的明细编辑区；切换左侧类型会刷新右侧标题、筛选条件、表格数据和分页。
  - 核心模块与数据区：左栏展示类型名称、code、启停状态和字典项数量；右栏顶部展示当前类型标题、编辑类型、新建字典项；字典项表格列为 code、名称、排序、启用、备注、操作，表体内部横向滚动，操作列单行展示编辑/删除，启停用开关表达状态变化。
  - 弹窗/设置入口：新建/编辑字典类型和字典项统一进入居中 el-dialog 弹窗，参考用户管理页交互；弹窗 footer 固定承载取消/保存，不使用抽屉做编辑。
  - 关键状态与退化：覆盖类型列表无数据、字典项无数据、查询无结果、字典服务异常、保存中、保存失败、权限不足；字典服务异常时管理端给出重试，消费端按 R18 规则回落代码默认枚举。
  - 图示要求：已存在 HTML 原型，不再另画 Mermaid、ASCII 草图或线框图。
- 数据来源：`/api/dict/types`、`/api/dict/items`
- 权限与可见性：仅系统管理员维护
#### 7.8.1 功能点：字典类型/项 CRUD + 启停
- 校验：类型 code、同类型项 code 唯一；类型 code 和字典项 type/code 创建后不可修改，编辑态禁用对应输入并且 PUT 不提交不可变字段。
- 状态变化：项变更后前端字典缓存失效、下拉即时反映
- 无数据/异常状态：无类型或无字典项时提示新建；字典服务异常时消费端回落默认枚举
- 验收标准：新增/停用一个字典项后，相关下拉与后端校验即时反映

### 7.9 页面 P9：日志审计（R17）
- 对应需求编号：R17
- 页面类型：新增页面（系统管理 → 日志审计，只读可观测）
- 页面入口：侧边菜单（系统管理员全局；租户管理员本租户）
- 原型文件：[prototypes/audit-log.html](prototypes/audit-log.html)（阶段五新增页面原型，已按下方「页面布局」落地）。
- 页面布局：
  - 布局事实源：对齐 `prototypes/audit-log.html`，采用 list 可观测页面结构。
  - 页面区域：首屏由标题工具区、摘要指标、筛选工具栏、审计表格和详情抽屉组成；标题工具区包含自动刷新、刷新和导出禁用态。
  - 主次关系：摘要指标提示当前权限范围内的近期态势，筛选条件决定表格数据范围，审计表格是主工作区，详情抽屉承接单条事件的只读详情。
  - 核心模块与数据区：摘要指标展示今日事件、失败/拒绝、安全事件、租户范围；筛选工具栏承载时间范围、处理人/关键词、事件类型、结果、状态、资源码等组合条件；审计表格列为时间、处理人、事件类型、资源/接口、目标、结果、状态、IP、耗时、错误摘要、操作，宽表在窄视口使用表体横向滚动，长文本单行省略并通过详情抽屉承接。
  - 弹窗/抽屉/设置入口：行点击或详情操作打开右侧只读抽屉；抽屉顶部展示目标对象、时间、处理人和事件标签，中部用「执行信息」「资源信息」两组信息卡展示关键字段，底部展示事件摘要、错误摘要和事件上下文（脱敏）；详情不展示原始请求体、响应体、密码、token、验证码等敏感内容。
  - 权限与退化：系统管理员看到全局事件；租户管理员页面结构不变，但数据范围自动限定为本租户，不展示跨租户切换入口；自动刷新只重新加载列表，不改变筛选条件；导出本阶段不实现，按钮禁用或不渲染。
  - 关键状态与退化：覆盖首次加载、筛选中、无记录、服务异常可重试、权限不足、自动刷新开关状态、详情抽屉打开/关闭。
  - 图示要求：已存在 HTML 原型，不再另画 Mermaid、ASCII 草图或线框图。
- 数据来源：`/api/audit`
- 权限与可见性：系统管理员全局；租户管理员限本租户
#### 7.9.1 功能点：审计查询/筛选/分页
- 默认展示：近 N 天事件倒序；N 来自 `audit.retention_days`，默认 90 天，未传 `start_time/end_time` 时由后端收口，页面摘要提示使用 `/api/audit/summary` 回传的实际值。
- 输入与校验：时间范围/多条件组合
- 加载/无记录/异常状态：loading / 无记录占位 / 错误重试
- 数据刷新：手动查询或自动刷新（可选）
- 验收标准：任一被授权操作、任务、安全事件（含限流命中/越权 403）发生后可按条件检索到；审计只读不可编辑

### 7.10 页面 P10：配置管理父子菜单重构（R19/R16）
- 对应需求编号：R19、R16
- 页面类型：更新（[ConfigView.vue](../../frontend/src/views/ConfigView.vue) 单页 4 tab → 父菜单 + 4 子页面）
- 页面入口：系统管理 → 配置管理（父）→ 评分规则 / 技术指标 / 买卖指标 / 系统设置
- 原型文件：无新增 HTML 原型；阶段四 R28 前移落地时复用现有 ConfigView 布局和 `LayoutHost`，通过路由 meta 固定单 tab。
- 页面布局：变更区域=菜单/路由拆分；保留区域=各 tab 原有内容逻辑留在 ConfigView，不改其内部主体布局
  ```
  系统管理
  └ 配置管理(父)
     ├ 评分规则   (/system/config/score)  ← 用户资产级
     ├ 技术指标   (/system/config/tech)   ← 仅系统管理员
     ├ 买卖指标   (/system/config/trade)  ← 用户资产级
     └ 系统设置   (/system/config/system) ← 仅系统管理员(含注册防滥用开关)
  ```
- 数据来源：系统设置子页通过 `/api/data/settings` 读取 `CONFIG_GROUPS` 和当前配置；注册防滥用开关、图形验证码强制阈值、审计默认查询窗口读写 `app_config` 平台级配置。
- 权限与可见性：子页面按角色-菜单映射控制（评分/买卖对普通用户开放，技术指标/系统设置仅系统管理员）
#### 7.10.1 功能点：4 子页面拆分与路由
- 状态变化：各子页面独立加载/保存，互不影响
- 权限不足状态：无权子页面不在菜单出现，直达 URL 被守卫拦截
- 验收标准：原 4 tab 功能在 4 子页面完整可用；普通用户仅见评分规则/买卖指标
#### 7.10.2 功能点：系统设置 - 注册防滥用开关（R16）
- 用户操作：系统管理员切换邮箱码、登录图形验证码开关，调整图形验证码强制失败次数和审计默认查询窗口 → 保存
- 状态变化：保存后注册/登录链路即时读取新值
- 输入与校验：仅系统管理员；字段类型和范围由 `CONFIG_GROUPS` 暴露并由后端白名单校验；非法值拒绝或回落默认
- 验收标准：关闭邮箱码后注册无需验证码；开启图形码后登录页出现并校验图形验证码，登录失败达到阈值后后端强制要求验证码；审计默认查询窗口按配置生效

---

## 8. 边界条件与异常场景

- **未登录/越权**：受控接口默认 deny；前端隐藏 + 后端 403 双层。
- **token 边界**：过期/篡改/吊销/perm_ver 失配 → 401；refresh 失效 → 跳登录。
- **权限变更即时性**：角色/用户权限变更 → perm_ver 自增使旧 token 失效（避免长期持旧权限）。
- **并发写**：多用户并发写私有资产由 PG 承载（连接池 + 事务），化解 DuckDB 单写瓶颈；全市场写任务仍受 DuckDB 全局互斥，仅平台管理员触发。
- **跨租户隔离**：tenant_id 一律从 token 取，禁止前端传参越权。
- **审计可靠性**：审计写失败降级，不阻断主业务；异步写防拖慢。
- **字典缺失**：消费端回落代码默认枚举，不空白。
- **迁移异常**：R3 迁移失败可回滚（DuckDB 原表保留）；上线后产生新数据即不可逆。
- **数据量**：审计表/资产表随用户增长，需索引、分页、保留期清理；行情大表查询仍走 DuckDB。
- **限流/锁定**：429/锁定友好提示，避免误伤正常用户。

---

## 9. 性能、安全与兼容性要求

- **性能**：行情分析查询保留 DuckDB 列存优势；资产/审计走 PG 索引；审计异步写 + 批量；权限码集合 Redis 缓存避免每请求查库；避免 N+1（跨库二次查询批量化）。
- **安全**【已确认 公网 SaaS】：
  - 传输：反代 HTTPS/TLS 终结；安全响应头（HSTS/CSP/X-Frame-Options 等）。
  - 认证：密码强哈希（bcrypt/argon2）、JWT 短期 + 刷新 + 黑名单 + perm_ver。
  - 防攻击：CSRF、XSS（前端转义 + CSP）、SQL 注入（参数化，延续现状）、越权（强制服务端校验 + tenant 从 token 取）。
  - 反扒（本期范围）：接口限流（IP/用户/接口维度，Redis 令牌桶）+ 登录失败锁定 + 异常频次审计告警；高强度行为风控列 R27 暂不做。
  - 敏感数据：密码/密钥不入日志、不入审计体；连接串/密钥走环境变量。
- **并发控制**：PG 承载资产并发写支持后端水平扩展；Redis 共享短状态保证多实例一致；DuckDB 全局写仅平台后台单点离线执行。
- **兼容性**：Node `^18||>=20`、Python `>=3.11`、Vite ^5、Vue ^3.4、Element Plus ^2.7（延续 CLAUDE.md 版本约束）；新增 PG 驱动（如 psycopg/asyncpg）与 Redis 客户端需纳入依赖清单与版本约束。

---

## 10. 业务亮点与优化建议

- **统一审计可观测**：接口/任务/安全三类事件一处采集，反扒与越权天然可观测，运营与安全排障受益（已纳入 R17）。
- **数据字典治理**：枚举集中治理，降低前后端枚举漂移（已纳入 R18，渐进接入）。
- **权限版本号即时失效**：相比纯长效 JWT，安全性显著提升（已纳入 R4）。
- 【后续建议，不扩大本期范围】：审计字段级变更对比（R24）、SSO/第三方登录（R25）、付费配额（R26）、行情行为风控（R27）。

---

## 11. 验收标准

| 需求编号 | 验收标准 | 验证方式 |
| --- | --- | --- |
| R1 | PG/Redis/反代接入可用，行情仍走 DuckDB，HTTPS 生效 | 启动自检 + 部署联调 |
| R2 | 回测/筛选迁移后结果与迁移前一致（同参数同输出） | 回归对比测试 |
| R3 | 存量资产迁移后行数/外键/归属完整，可正常读写 | 迁移校验脚本 + 抽样核对 |
| R4 | 正确账密得 token；过期/吊销/perm_ver 失配后旧 token 401 | 接口测试 |
| R5 | 注册成功自动建租户且首人为租户管理员；邮箱码开关生效 | 端到端测试 |
| R6 | 第三方入口存在、置灰、不报错不跳空白 | 页面核查 |
| R7 | 无/失效 token 访问受控接口 401，有效 token 注入上下文 | 接口测试 |
| R8 | 无权接口 403；无权按钮前端不渲染/禁用 | 接口 + 页面测试 |
| R9 | 用户仅能读写本人/本租户资产，跨租户不可见 | 多账号交叉测试 |
| R10 | 用户全生命周期可管；禁用即时失效；租管限本租户 | 页面 + 接口测试 |
| R11 | 角色绑菜单/功能保存后即时生效（按钮消失/接口 403） | 端到端测试 |
| R12 | 菜单后端 CRUD；新增授权菜单出现在对应角色 | 页面测试 |
| R13 | 功能点登记后可被角色勾选并对接口生效 | 端到端测试 |
| R14 | 租户 CRUD；停用租户其用户登录被拒 | 页面 + 接口测试 |
| R15 | 暴力破解锁定、限流 429、注入/XSS 防护、密码哈希 | 安全测试 |
| R16 | 系统设置开关切换后注册/登录校验即时变化；缺值回落默认；审计默认查询窗口按 `audit.retention_days` 生效 | `test_stage5_config_t2.py`、`test_stage5_auth_config.py`、`test_stage5_audit.py`、`ConfigView.system.spec.ts` |
| R17 | 操作/任务/安全事件（含限流/403）可按条件检索；只读不可改；system 全局、tenant_admin 本租户收口 | `test_stage5_audit.py`、`test_stage5_audit_collection.py`、`test_stage5_resource_codes.py`、`AuditLogView.spec.ts`、三档视口验证 |
| R18 | 字典项增删停用后下拉/校验即时反映；缺失回落默认；字典管理 system-only，`dict:read` 登录基线共享读 | `test_stage5_dicts.py`、`test_stage5_resource_codes.py`、`DataDictionaryView.spec.ts`、三档视口验证 |
| R19 | 配置 4 子页面功能完整；普通用户仅见评分规则/买卖指标；系统设置动态配置组可展示、保存和权限拦截 | 路由/pageRegistry/layout-contract 测试、`ConfigView.system.spec.ts`、`npm run build`、三档视口验证 |
| R20 | 未登录跳登录；菜单/路由/按钮按权限码渲染 | 页面测试 |
| R21 | 现有 13 路由与页面全部接鉴权+隔离；未改造接口默认 deny | 全量回归 |
| R22 | token 临期静默续期，操作不中断 | 体验测试（建议） |
| R23 | 超保留期审计自动清理；阶段五已先落 `audit.retention_days` 配置和默认查询窗口 | 定时任务核查（建议）；配置消费已由阶段五后端/页面测试覆盖 |
| R24 | 关键变更可见 from→to | 审计核查（建议） |

---

## 12. 建议开发顺序

> 本需求跨「基础设施 / 后端权限 / 前端权限 / 存量接入 / 新增能力」多模块，规模大、依赖明显，必须分阶段。后续可按阶段继续拆出复杂模块的专属需求文档/开发计划。

**阶段一：持久层与基础设施底座（前置，所有后续依赖）** — ✅ **已完成（2026-06）**
- 覆盖需求：R1、R2、R3
- 目标：PG/Redis/反代接入，双库访问层建成，存量资产迁移完成并回归一致。
- 依赖原因：无 PG/双库则用户体系与隔离无处落地；R3 不可逆，须先稳。
- 里程碑：迁移后回测/筛选结果与迁移前一致；三类存储启动自检通过。
- **开发文档**：[stage1-foundation/plan.md](stage1-foundation/plan.md)（T1–T4 + §8 实际落地校准）。
- **产物/留痕**：迁移说明 [stage1-foundation/migrate-assets-to-pg.md](stage1-foundation/migrate-assets-to-pg.md)、反代/TLS 模板 [stage1-foundation/deploy-reverse-proxy.md](stage1-foundation/deploy-reverse-proxy.md)；代码见 `backend/storage/{pg_client,redis_client,pg_ddl,asset_repository}.py`、`backend/services/migrate_rbac.py`、CLI `migrate-rbac`。
- **落地结论**：11 域资产全迁 PG（复合主键 `(tenant_id,owner_user_id,业务键)`）；行情留 DuckDB；`app_config` 迁 PG 平台层；经三轮代码评审整改（写侧 PK → 读侧 JOIN 归属 → 训练逐语句归属），全量 215 passed，`migrate-rbac --recreate --apply` 字段/行数/归属/外键全绿。隔离铁律已沉淀进 [CLAUDE.md](../../CLAUDE.md)「资产归属与隔离」。

**阶段二：认证与鉴权内核** — ✅ **完成**（T1–T10 全落地，分支 `feat/multi-tenant-rbac-stage2`）
- 覆盖需求：R4、R7、R15（基础部分）、R20（登录态与守卫骨架）；并入 R5、R6、R16（基础）
- 目标：登录/注册（R5 并入）、JWT、鉴权中间件、上下文注入、前端登录态。
- 依赖原因：是 RBAC 与隔离的运行时前提。
- 里程碑：可登录、受控接口需 token、未登录跳登录页。**均达成**。
- **落地结论**：后端 `backend/auth/*`（JWT/bcrypt/Redis 短状态/纯 ASGI 中间件默认 deny/上下文不回落/`require_system` 角色守卫）+ `auth_service`/`api·auth`(9 端点)/`user_repository`；前端登录态骨架（authToken/store/拦截器/守卫/顶栏用户区+退出）+ 登录页（科技风·黑白双主题，承接原型）。经**两轮 Codex 评审整改**（指标写守卫/context 不回落/layout 归属/Redis fail-closed/jwt 启动校验 等，均复现后修）。全量 **266 passed** + 前端 vitest 85 passed（含 layout-contract）+ `npm run build` 通过。认证九条铁律已沉淀进 [CLAUDE.md](../../CLAUDE.md)「认证与鉴权」。
- **开发文档**：[stage2-auth-kernel/plan.md](stage2-auth-kernel/plan.md)（T1–T10，各任务落地/评审留痕在内）。
- **页面原型**：登录/注册页 [prototypes/login.html](prototypes/login.html)（科技风 · 黑白双主题，对应需求 7.1）。

**阶段三：RBAC 与租户管理（权限主体）** — ✅ **完成**（T1–T17 全落地，分支 `feat/multi-tenant-rbac-stage3`，过 Codex 多轮复审）
- 覆盖需求：R5、R8（机制+新管理接口，存量 13 路由精确码属阶段四 R21）、R9、R10、R11、R12、R13、R14
- 目标：用户/角色/菜单/功能/租户全套管理 + 接口级/按钮级校验 + 数据隔离。
- 依赖原因：依赖阶段一数据层与阶段二认证。
- 里程碑：多账号交叉验证隔离与授权即时生效。**达成**——后端全量 `pytest` 398 passed（含跨租户 404/越权 403/bump 全触发点/system 全授权不变式）、前端 `build` 绿 + `vitest` 118 passed（含权限指令/SideMenu fail-closed/管理页 error+retry 回归）、4 页 preview 双主题×三档视口自验。落地要点：瘦令牌 + PG 权威 perm_ver 闸门 + 授权变更同事务原子 bump 强制重登；require_perm 精确码（user 接口）/require_system 硬守卫（role/menu/resource/tenant 接口）二分；前端 v-permission + SideMenu/路由守卫 fail-closed。
- **页面原型**（4 个新增管理页，已就绪，见 §7.4–7.7）：用户管理 [prototypes/user-management.html](prototypes/user-management.html)、角色管理 [prototypes/role-management.html](prototypes/role-management.html)（master-detail 权限树）、菜单与功能管理 [prototypes/menu-resource-management.html](prototypes/menu-resource-management.html)（R12+R13 合页 master-detail）、租户管理 [prototypes/tenant-management.html](prototypes/tenant-management.html)。均复用 Element Plus 视觉 + 黑白双主题；归入「系统管理 → 权限管理」子组（`/system/users|roles|menus|tenants`）。R8 按钮级/接口级为横切、R9 隔离为后端，不单独出原型。**视口/响应式（对齐 DESIGN §8）**：1440×900 为验收视口无溢出；宽表在窄视口**体内横滚**（列不压成竖排），master-detail 窄视口右栏保底宽 + 体内横滚，弹窗宽度自适应 `min(px, 92vw)`、正文 max-height 内滚、标签不换行。原型均在 560/700/1440 三档核验过。
- **开发产物索引**（阶段三实际落地，路径相对本文件所在 `agent-works/multi-tenant-rbac/`）：
  - **开发计划 + 全程留痕 + Codex 三轮复审整改清单**：[stage3-rbac-tenant/plan.md](stage3-rbac-tenant/plan.md)（§4.6 实现口径修订、§4.6.1 复审整改清单、§6 T1–T17 任务与状态、§11 里程碑达成）。
  - **DDL 留痕**：[stage3-rbac-tenant/rbac-schema.sql](stage3-rbac-tenant/rbac-schema.sql)（六表复合主键 + FK/索引 + seed，人读兜底；实际随 `init_pg_db()` 启动幂等执行）。
  - **页面原型**：`prototypes/{user,role,menu-resource,tenant}-management.html`（4 页，见上）；`stage3-rbac-tenant/page-test-screenshots/`（preview 5181 双主题×三档视口验收截图）。
  - **后端实现**（源码事实源）：`backend/auth/`（perm_resolver 多角色并集 + 瘦令牌 + require_perm/require_system 守卫）、`backend/api/{users,roles,menus,resources,tenants}.py`（4 套管理接口）、`backend/storage/pg_ddl.py`（六表 + `_SEED_RESOURCES`/`_SEED_MENUS` + `_seed_role_grants`）、各域仓库；测试 `backend/tests/test_rbac_{users,roles,menus,resources,tenants}.py` + `test_auth_middleware.py`。
  - **前端实现**：`frontend/src/views/system/{UserManage,RoleManage,MenuResource,TenantManage}View.vue` + `PermissionTree.vue`、`components/SideMenu.vue`（fail-closed）、`directives/permission.ts`（v-permission）、`utils/permission.ts`（hasPermission/resolveMenuGuard）、`api/{user,role,menu,tenant}.ts`；测试 `views/system/__tests__/manage-error-states.spec.ts`、`directives/__tests__/permission.spec.ts`、`components/__tests__/SideMenu.spec.ts`。
  - **文档治理回写**（T17）：`CLAUDE.md`（补「细粒度 RBAC（阶段三内核）」铁律 6 条 + 阶段状态）、`DESIGN.md §9`（4 管理页 + IconPicker 登记）、本文件 §12（本段）、项目记忆 `multi-tenant-rbac-pivot.md`。
  - **验收基线**：后端 `pytest` 398 passed / 前端 `npm run build` 绿 + `vitest` 118 passed。commit 序列 `7aaddb3`（T11–T16）→ `d313c1b`/`99bca3a`/`ce3b863`（Codex 三轮整改）→ `626fc42`（T17 文档治理）。

**阶段四 A：存量功能全量接入** — ✅ **完成**（T1–T10 全落地，分支 `codex/multi-tenant-rbac-stage4`）
- 覆盖需求：R8（存量接口精确码）、R9（存量资产隔离复核 + 公共榜单 C1）、R20（全量按钮/路由接入）、R21（13 路由全量接入）
- 目标：现有 13 路由与页面逐一接鉴权 + resource code + 隔离。**达成**——48 资源码固化(resource-codes.sql/pg_ddl seed)；后端逐端点 `require_perm`(可授权业务)/`require_system_perm`(system-only 硬守卫)接入，补 `layout/validate` 裸露端点；baseline 三码(layout:view/trade-calendar:view/indicator:registry)由 `perm_resolver` 对有角色非 system 用户强制注入、角色页置灰不可反选、无角色 fail-closed；`POST /layout/reset` 动态 scope 自守卫；每日榜单按 C1 平台公共只读特例、个人方案仍私有；前端业务页 v-permission 真实生效 + 系统页前向兼容接入。
- 依赖原因：依赖阶段三权限模型稳定。
- 里程碑：全量回归，未改造接口默认 deny 不漏。**达成**——路由扫描证「所有非白名单 /api 端点有守卫、13 模块每端点有精确码、唯一豁免动态 scope /layout/reset」；跨账号隔离 + baseline 共享读/不可反选 + system-only tenant_admin 403 + 硬守卫不降级全测。
- **验收基线**：后端 `pytest` **452 passed**（含 Codex 复审整改新增 3 board 公共闭环用例）、前端 `npm run build`(vue-tsc+vite)绿 + `vitest` **186 passed**。
- **开发自审查（2026-07-04，首轮）**：首轮仅把榜单页问题当作「文档偏离 F1」（误判为 `score:run` vs `board:view` 命名不一致），**未实测普通用户态**，结论过度自证清白。
- **Codex 二次复审整改（2026-07-04）**：外部复审推翻首轮"仅文档小瑕"结论，查出并已整改 3 实缺陷——**P1（严重）**：每日榜单页对**所有非 system 用户不可用**（三重断链：`BoardView` 主加载调 `listScoreProfiles`→`/score-profiles` 需 `score-profile:view`=system-only 且不在业务码集→403；即便放权，`ScoreProfileRepo.list()` 按调用者归属过滤、普通用户无自建方案、预设归 `PUBLIC_BOARD_OWNER`→空；run 同理 404）。`/board` 又是 `SAFE_HOME`，等于普通用户主页白屏。**修**：`board.py` 新增 `GET /api/board/profiles` + `POST /api/board/run`（均 `board:view`，读公共预设方案+公共评分、只暴露 `is_preset`、全员共享一份），`BoardView` 改接——补齐 C1 公共榜单闭环，配「榜单」角色只需 `board:view`。**P2（中）**：业务页 onMounted 次级列表读（Screen `screen-profile:view`、Stocks/StockDetail `stock-group:view`）未按自身 view 码门控，部分授权自定义角色进页被次级加载 403 卡住主体。**修**：加 `hasPermission` 守卫优雅降级（Backtest 早已 try/catch 降级、Training 用自身 `training:view`）。**P3（低）**：文档漂移——`role_repository.baseline_resource_ids()` 死代码 + `constants.py`/其 docstring 谎称"set_grants 保存时并入 baseline"（实际唯一权威是 `perm_resolver.resolve` 运行时注入），`resource-codes.sql` "+38 行"与文末"48"矛盾。**修**：删死代码、订正注释、"+38"→"+48"。回归：后端 **452 passed**、前端 **186 passed** + build 绿。教训：自审不能只验"端点有码"，须实建普通用户角色跑真实页面加载链路。仍留 1 低风险项：score/trade profile 有意用 `require_perm`（非硬守卫，靠 system-only 菜单拦截授权，阶段五拆页迁移路径）。
- **开发产物索引**（相对 `agent-works/multi-tenant-rbac/`）：计划+全程留痕 [stage4-existing-routes/plan.md](stage4-existing-routes/plan.md)（§6 T1–T10 + §5 需求映射 + §4.3 资源码矩阵含 F1 注）；资源码矩阵/既有库回填 SQL [stage4-existing-routes/resource-codes.sql](stage4-existing-routes/resource-codes.sql)；C1 决议依据 [stage4-existing-routes/c1-board-ownership-options.md](stage4-existing-routes/c1-board-ownership-options.md)。后端测试 `backend/tests/test_stage4_{resource_codes,systemonly,board,layout,menu_guard}.py`；前端测试 `frontend/src/{directives,views}/**/{stage4-button-permission,permission-tree,stage4-permissions}.spec.ts`；权限依赖元数据/守卫 `backend/auth/deps.py`（`require_perm`/`require_system_perm`）、`backend/auth/perm_resolver.py`（baseline 强制注入）、`backend/auth/constants.py`（`SHARED_/BUSINESS_RESOURCE_CODES`）。
- **文档治理回写（T10 + 自审 + Codex 复审整改增量）**：`CLAUDE.md`（补「存量业务路由全量接入（阶段四已落地）」铁律 + 榜单页 `board:view` 闭环[复审 P1]+ 次级加载降级[复审 P2]）、`README.md`（架构段+生产入口段标阶段四已落地）、[agent-works/architecture/platform.md](../architecture/platform.md)（认证声明 + 风险表更新为阶段四已落地）、`plan.md`（§4.3 矩阵 board/score:run 行 + §6.6 边界随复审更新）、`resource-codes.sql`（board 块注释随复审更新、"+48"）、本文件 §12（本段）、项目记忆 `multi-tenant-rbac-pivot.md`/`MEMORY.md`（榜单页条 + 复审整改条）。`DESIGN.md` 无变更（阶段四不新增页面、不重排布局，§9 页面登记无需新增）。
- **后续承接**：本阶段只保留公共榜单特例作为 R21 基线；评分方案通用公开能力已由阶段四 B（R28）承接。

**阶段四 B：评分方案公开能力与配置拆页前移** — ✅ **完成**（分支 `codex/stage4-public-profile-visibility`，提交 `d8bf27a`）
- 覆盖需求：R28（评分方案可见性与自助公开）、R19（配置管理拆父子菜单前移落地）、R20/R21 延续（榜单页与配置页权限闭环）。
- 目标：把阶段四 A 的“平台公共榜单特例”收敛进通用可见评分方案模型。**达成**——`score_profile.visibility=private|tenant|public`；`GET /api/score-profiles` 与 `GET /api/board/profiles` 返回自己的、同租户公开、全体公开和平台内置预设；前端用 opaque `profile_ref` 定位真实 owner；非 owner 公开方案只读并可复制为自己的 private，复制目标已存在时拒绝覆盖；`POST /api/board/run` 按可见方案、日期、版本读取 fresh 快照，缺失或 stale 时由 `board:view` 触发受控物化，结果写方案 owner 的 `score_snapshot` 槽，物化按 owner/profile/version/date 加 PG advisory lock；`force=true` 才要求 `board:compute`。回测页和 `/board/compute` 同步透传/解析 `profile_ref`，可使用他人公开评分方案。
- 配置管理拆页：`/system/config` 改为父菜单，`/system/config/score` 评分规则和 `/system/config/trade` 买卖指标为业务可授权子页，`/system/config/tech` 技术指标和 `/system/config/system` 系统设置仍 system-only；`/score-profiles` 仅兼容重定向到 `/system/config/score`，不作为菜单入口。评分方案公开范围由当前状态标签下拉设置，不再平铺“租户公开/全体公开”按钮。
- **验收基线**：阶段四 B 开发中执行后端公开方案/榜单/RBAC 专项 **73 passed**；配置拆页后 RBAC seed 专项 **42 passed**；复审整改后后端阶段四关联专项 **60 passed**，前端 `npm run build` 通过，前端权限/布局相关测试 **155 passed**；后端 `/api/health=200`。
- **Codex 复审整改（2026-07-04）**：已补阶段四内置角色存量库一次性 backfill 并 bump `perm_ver`；`score-profile:publish-tenant` 默认仅给 `tenant_admin/system`，normal/paid 需显式授权；公开榜单读穿透物化加入 PG advisory lock + meta upsert；回测页、回测服务、回测引擎和 `/board/compute` 扩散 `profile_ref` 契约；复制公开方案禁止覆盖当前用户已有同 id 方案。
- **开发产物索引**（相对 `agent-works/multi-tenant-rbac/`）：计划和实施记录 [stage4-public-profile-visibility/plan.md](stage4-public-profile-visibility/plan.md)；评分方案 DDL/兼容迁移 SQL [stage4-public-profile-visibility/score-profile-visibility.sql](stage4-public-profile-visibility/score-profile-visibility.sql)；配置拆页和资源码回填 SQL [stage4-public-profile-visibility/resource-codes.sql](stage4-public-profile-visibility/resource-codes.sql)。核心实现：`backend/scoring/score_profile.py`、`backend/scoring/snapshot.py`、`backend/api/score_profiles.py`、`backend/api/board.py`、`backend/services/backtest_service.py`、`backend/backtest/engine.py`、`backend/storage/pg_ddl.py`、`frontend/src/views/BoardView.vue`、`frontend/src/views/BacktestView.vue`、`frontend/src/views/ConfigView.vue`、`frontend/src/router/index.ts`。测试：`backend/tests/test_score_profile_visibility_api.py`、`backend/tests/test_score_profile.py`、`backend/tests/test_stage4_board.py`、`backend/tests/test_backtest.py`、`backend/tests/test_rbac_{schema,menus,me}.py`。
- **仍未覆盖**：筛选方案、买卖方案、回测记录等其他资产的公开能力；公开审批流、公开市场、收藏/搜索/运营推荐；审计/数据字典/注册防滥用开关页。

**阶段五：平台能力新增与重构** — ✅ **完成**（分支 `codex/multi-tenant-rbac-stage5`，T1–T13 已提交）
- 覆盖需求：R16、R17、R18，以及 R19 中尚未实现的注册防滥用开关落页细节。
- 目标：注册防滥用开关、日志审计、数据字典。**达成**——系统设置已承载认证防滥用与审计窗口配置；日志审计和数据字典后端、菜单、资源码、页面、测试和视口验证均已落地。
- 依赖原因：审计/字典依赖用户与权限上下文；配置重构依赖菜单数据化。
- 里程碑：审计可检索、字典即时生效、配置子页面按角色可见。**达成**——`/api/audit` 支持列表/摘要/详情，tenant_admin 仅本租户；`/api/dict` 管理端 system-only、公共消费 `dict:read`；`/system/config/system` 动态配置组并排展示和保存。
- **页面原型**：数据字典 [prototypes/data-dictionary.html](prototypes/data-dictionary.html)、日志审计 [prototypes/audit-log.html](prototypes/audit-log.html)。系统设置注册防滥用开关复用阶段四已落地的 `/system/config/system` 页面，不单独新增原型。
- **开发计划与 SQL 归档**：[stage5-platform-capabilities/plan.md](stage5-platform-capabilities/plan.md)、[stage5-platform-capabilities/stage5-platform-capabilities.sql](stage5-platform-capabilities/stage5-platform-capabilities.sql)、[stage5-platform-capabilities/resource-codes.sql](stage5-platform-capabilities/resource-codes.sql)。
- **后端实现索引**：`backend/storage/pg_ddl.py`（`audit_log`/`dict_type`/`dict_item`、阶段五 seed、`dict:read` baseline）、`backend/services/audit_service.py`、`backend/storage/audit_repository.py`、`backend/services/dict_service.py`、`backend/storage/dict_repository.py`、`backend/api/audit.py`、`backend/api/dicts.py`、`backend/storage/app_config.py`、`backend/api/data_admin.py`、`backend/services/auth_service.py`。
- **前端实现索引**：`frontend/src/views/system/AuditLogView.vue`、`frontend/src/views/system/DataDictionaryView.vue`、`frontend/src/views/ConfigView.vue`、`frontend/src/components/AppFilterSelect.vue`、`frontend/src/components/config/ConfigGroupForm.vue`、`frontend/src/api/{audit,dict,data}.ts`、`frontend/src/router/index.ts`、`frontend/src/layout/pageRegistry.ts`。
- **验收基线**：阶段五初版后端专项 `33 passed`（`test_stage5_config_t2.py`、`test_stage5_auth_config.py`、`test_stage5_audit.py`、`test_stage5_audit_collection.py`、`test_stage5_dicts.py`、`test_stage5_resource_codes.py`），前端全量 `npm run test -- --run` 为 `21 passed` 测试文件、`212 passed` 用例，`npm run build` 通过。缺陷整改复测：后端认证/审计/字典/DDL 专项 `38 passed`，前端审计/字典/系统设置/登录验证码/AppFilterSelect/阶段五路由专项 `30 passed`，`npm run build` 通过；`/system/audit`、`/system/dicts`、`/system/config/system` 在 5181 预览下完成三档视口截图、审计目标关键词查询、数据字典状态筛选、分页、目标中文说明、系统设置分类 Tab 和页面可见错误态复核；登录图形验证码开启即展示、提交即校验由单测和后端 API 回归覆盖。
- **范围边界回写**：R23 自动清理任务未纳入阶段五；阶段五只实现 `audit.retention_days=90` 配置、后端默认查询窗口和页面提示。R24 字段级 from→to、R22 静默刷新、R25/R26/R27 仍按后续建议或暂不实现处理。

**阶段六：体验增强（建议项）**
- 覆盖需求：R22、R23、R24
- 目标：静默刷新、审计保留期清理、字段级变更对比。
- 里程碑：长操作不被 token 过期打断、审计表可控增长。

**独立需求（排期待定，非上述任一阶段的既定内容）**
- R28 其他资产公开能力：评分方案已完成；筛选方案、买卖方案、回测记录等其他资产是否支持 `private/tenant/public` 仍待独立设计和排期。

> 文档治理收尾（贯穿/收口）：同步改写 CLAUDE.md、README、architecture、start.sh/部署脚本（定位与依赖变更），避免后续 AI 按旧契约行事。

---

## 13. 遗留确认项

| 项 | 影响 | 当前默认（已采纳建议/推断） |
| --- | --- | --- |
| 1. 配置管理 IA | 普通用户会在「系统管理→配置管理」下看到评分规则/买卖指标两子页 | 【已确认】保留在配置管理下，靠角色控子页面可见，最省改动 |
| 2. 资产共享粒度 | 是否支持「租户内共享资产」还是纯个人私有 | 【已确认→R28】评分方案已支持 `private/tenant/public`；筛选方案、买卖方案、回测记录等其他资产仍按个人私有，后续独立评估 |
| 3. 审计保留期/范围 | 审计表增长与隐私 | 【已确认】保留 90 天可配、仅记摘要不记请求/响应体、租管看本租户 |
| 4. `data_dimension_registry` 是否并入数据字典 | 字典接入边界 | 【待定】本期不并入，维持现状，后续评估 |
| 5. 租户管理员能否自建角色 | 角色管理权限边界 | 【已确认】本期仅分配系统管理员预设角色，不可自建 |
| 6. 第三方登录入口形式 | 登录页交互 | 【已确认】置灰按钮 + 敬请期待 tooltip |
| 7. 反扒强度 | 安全投入 | 【已确认】本期接口限流 + 异常频次告警 + 审计；行为风控（R27）暂不做 |
| 8. PG/Redis 具体版本与驱动选型 | 依赖清单 | 【待定】建议 PG>=14、Redis>=6、驱动 psycopg/asyncpg + redis-py，开发期定稿 |
