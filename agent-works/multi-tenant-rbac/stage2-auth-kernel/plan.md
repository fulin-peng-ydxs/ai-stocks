# 开发计划：阶段二 — 认证与鉴权内核

> 上游需求：[../requirement.md](../requirement.md) 第 12 章「建议开发顺序 · 阶段二」。
> 覆盖需求：**R4（账密登录+JWT）、R7（鉴权中间件+上下文注入）、R15 基础部分（密码哈希/登录失败锁定/接口限流/安全头）、R20 骨架（前端登录态与路由守卫）**，并入 **R5（自助注册+自动建租户）**、**R6（第三方入口占位）**、**R16 基础（图形验证码 + 开关消费钩子）**、**R8 最小切片（system 角色粗粒度守卫，闭合注册越权窗口）**。
> 前置：阶段一（混合持久层 PG/Redis + 双库 + 迁移）已完成（见 [../stage1-foundation/plan.md](../stage1-foundation/plan.md)）。
> 本阶段是 RBAC（阶段三）与数据隔离运行时透传的前提；完成后系统从"无认证"切换到"默认需登录"。

---

## 1. 需求来源与目标

- **需求文档**：[../requirement.md](../requirement.md)（R4/R5/R6/R7/R8 最小切片/R15/R16/R20，页面 P1 登录注册页 7.1、P2 顶栏用户区 7.2）。
- **功能目标**：
  1. 可登录/登出/刷新/获取当前身份（`/api/auth/*`），JWT 携带 `user_id/tenant_id/role/perm_ver`，access 短期 + refresh 长期，登出入 Redis 黑名单。
  2. FastAPI **应用级鉴权中间件**（机制性默认 deny，非逐路由 Depends）：解析校验 token（含黑名单 + perm_ver，Redis fail-closed）→ 注入 `current_user/current_tenant` 上下文 → 非白名单无有效 token 一律 **401**；系统级接口再叠 `require_role("system")`。
  3. 安全基础：密码 bcrypt 哈希、登录失败计数+锁定、接口限流（Redis 令牌桶）、安全响应头、图形验证码。
  4. 自助注册自动建租户并绑定租户管理员（最小角色模型，完整 RBAC 留阶段三）。
  5. 前端登录态闭环：`auth` store + axios 拦截器（注 Authorization / 处理 401·403·429）+ 路由守卫（未登录跳 `/login`）+ 顶栏用户区/退出。
  6. **登录/注册页**：全屏独立壳，**科技风**视觉，**黑/白双主题**，第三方入口占位置灰。
- **本次不做**（见 §3.3）：**R8 完整 resource code / 按钮级 RBAC**（本阶段仅做 system 角色粗粒度守卫，见 §3.1）、菜单/角色/功能/租户管理页（R10–R14，阶段三）、存量接口全量打 resource code + 隔离透传（R21，阶段四）、日志审计/数据字典/配置拆页（R17–R19，阶段五）、真实邮件 SMTP 投递与真实第三方 OAuth、静默刷新（R22）。
- **计划输出目录**：`agent-works/multi-tenant-rbac/stage2-auth-kernel/`。

---

## 2. 当前项目依据

> 全部经本次调研核实，作为计划落点。

**后端**
- 应用装配 [backend/main.py](../../../backend/main.py)：`create_app()` 注册 CORS（已 `allow_headers=["*"]`，放行 Authorization）+ 14 个业务路由 + SPA 回退；启动期 `_check_storages` 三库自检并 `init_pg_db()`。**auth 鉴权中间件将在此挂载（机制性默认 deny），`require_role("system")` 角色守卫作为路由依赖叠加在系统级接口上——不回退到逐路由鉴权依赖**。
- 异常体系 [backend/common/exceptions.py](../../../backend/common/exceptions.py)：`AIStocksError(code,msg)` 基类 + NotFound/Validation 等；[main.py](../../../backend/main.py) 的 `@app.exception_handler(AIStocksError)` 当前**统一返回 HTTP 200 + 业务 code**。→ 认证需真实 `401/403/429`，本阶段引入带 `http_status` 的认证类异常（见 §4.2）。
- 响应封装 [backend/api/response.py](../../../backend/api/response.py)：`{code,msg,data}`，`ok()/err()`，沿用。
- 配置 [backend/config/settings.py](../../../backend/config/settings.py)：pydantic v2 `Settings`，已有 `PostgresConfig/RedisConfig`，密码/DSN 走环境变量（`AI_STOCKS_PG_*`/`AI_STOCKS_REDIS_*`）。→ 新增 `auth/security` 段同款口径（JWT 密钥走环境变量）。
- PG 骨架 [backend/storage/pg_ddl.py](../../../backend/storage/pg_ddl.py)：`sys_tenant`（id/name/status/admin_user_id）、`sys_user`（id/tenant_id/account/email/password_hash/status，`UNIQUE(account)`）**最小骨架**已建；`init_pg_db()` 幂等建表 + `seed_default_tenant()` seed 默认租户 `default` + 管理员 `admin`（**password_hash 当前为 NULL**）；`recreate_asset_tables()`/`asset_pk_mismatches()` 为升级路径。
- Redis 客户端 [backend/storage/redis_client.py](../../../backend/storage/redis_client.py)：`get_redis_client()` + `ping`，阶段一仅建底座，**本阶段首次承载业务**（黑名单/perm_ver/失败计数/限流/验证码）。
- 资产仓库归属：阶段一各仓库归属默认 `default/admin`（[CLAUDE.md](../../../CLAUDE.md)「资产归属与隔离」），本阶段建立上下文后改为**取请求上下文归属；HTTP 请求链缺上下文直接报错（不回落 admin），仅 CLI/后台/迁移经 `system_context()` 显式用 default/admin**（R7→R9 桥接的最小版，全量透传留阶段四）。
- 长任务底座 [backend/services/async_task.py](../../../backend/services/async_task.py)、调度 `scheduler/`：本阶段不改，审计钩子留阶段五。

**前端**
- 请求层 [frontend/src/api/client.ts](../../../frontend/src/api/client.ts)：axios 实例 `baseURL:/api`，响应拦截仅按业务 `code!==0` 提示。→ R20 需补 **请求拦截注 Authorization** + **响应拦截处理 HTTP 401/403/429**。（注：需求 R20 提及的 `http.ts` 即本文件）
- 主题机制 [frontend/src/composables/useTheme.ts](../../../frontend/src/composables/useTheme.ts)：`initTheme/toggleTheme/useTheme`，切 `html.dark` 类 + localStorage `ai-stocks-theme` + `prefers-color-scheme` 兜底。**登录页黑白双主题直接复用，不另造**。
- 预设体系 [frontend/src/layout/presets.ts](../../../frontend/src/layout/presets.ts) + [__tests__/presets.spec.ts](../../../frontend/src/layout/__tests__/presets.spec.ts)：`LAYOUT_PRESETS` 含 `technology` 预设，每预设维护 `light/dark` token 对等（[DESIGN.md](../../../DESIGN.md) §「新增或调整预设必须维护 light/dark 并过 presets.spec.ts」）。登录页科技风取该预设的色彩语汇。
- 入口 [frontend/src/main.ts](../../../frontend/src/main.ts)：`initTheme()`/`initLayoutPreset()` 挂载前执行；Pinia 已装配。
- 路由 [frontend/src/router/index.ts](../../../frontend/src/router/index.ts)：`createWebHistory`，13+ 业务路由，**无 `/login`、无守卫**。→ 新增 `/login`（`meta.public`）+ 全局 `beforeEach` 守卫。
- 主框架 [frontend/src/App.vue](../../../frontend/src/App.vue)：含顶栏（已用 useTheme），→ 顶栏右侧加用户区/退出；登录页需脱离主框架壳渲染。
- store 目录 [frontend/src/stores/](../../../frontend/src/stores/)：现仅 `stockSet.ts`，→ 新增 `auth.ts`。
- 前端规范：[DESIGN.md](../../../DESIGN.md)、[page-template.md](../../../agent-works/configurable-layout-system/page-template.md)（列表/弹窗/禁整页滚动/构建口径：改 `frontend/src` 后 `npm run build` 同步产物）。

**约束（来自 CLAUDE.md / 阶段一沉淀）**
- psycopg3 **同步** + 占位符 `%s`；禁 async 化、禁 ORM、禁跨库 JOIN。
- 资产隔离三铁律（复合主键 / 读侧 JOIN 带归属 / 每条增删改带归属）——本阶段新建的 `sys_*` 为平台/权限元数据（自然键，**不带 owner 归属**，但 `sys_user` 带 `tenant_id` 用于租户范围过滤）。
- 密钥/密码不入库不入码不入日志（JWT secret、管理员初始密码走环境变量）。

---

## 3. 实施范围

### 3.1 必须实现
- **R4** 登录/登出/刷新/`/me` + JWT（access+refresh，载 user_id/tenant_id/role/perm_ver）+ 登出黑名单。
- **R7** **鉴权中间件**（应用级、机制性默认 deny）+ 上下文注入（contextvar）+ 白名单 + 非白名单无有效 token 一律 401。
- **R8 最小切片（粗粒度角色守卫）**：`require_role("system")` 闸门，把**全市场写 / 平台配置**类系统级接口（`data_admin`/`data_tasks`/调度/技术指标 `indicators` 写/系统设置 `config` 平台段/布局配置 `layout` preset·page·component）限定 `system` 角色——**关闭公开注册带来的越权窗口**（见 §10 风险 P0）。注：这是 R8 的最小粗粒度版（仅按角色 tier，不做 resource code 细粒度），完整 R8 仍在阶段三。
- **R15 基础**：bcrypt 密码哈希；登录失败计数+阈值锁定（Redis）；接口限流（Redis 令牌桶，按 IP/账号维度）；安全响应头；图形验证码（登录失败阈值后触发）。
- **R20 骨架**：`auth` store（token/user/tenant/role 持久化）+ axios 拦截（注 token / 401 清态跳登录 / 403 提示 / 429 提示）+ 路由守卫（公开白名单放行，其余未登录跳 `/login`）。`/me` 返回身份（含 role），**菜单/功能码本阶段为空**，SideMenu 仍用静态 menuConfig（见 §4.7 兼容策略）。
- **页面 P1** 登录/注册页（科技风 + 黑白双主题 + 第三方占位）。
- **页面 P2** 顶栏用户区 + 退出登录。

### 3.2 可选增强（本阶段并入，因登录页完整性需要）
- **R5** 自助注册 + 自动建租户 + 绑定租户管理员（最小角色模型：注册用户 `role_code='tenant_admin'` 落 `sys_user`）。
- **R6** 第三方入口占位（置灰 + 「敬请期待」tooltip + 后端回调路由占位 404/未实现）。
- **R16 基础**：注册/登录链路读取「防滥用开关」，**默认值对齐需求 R16**——**邮箱验证码默认开、图形验证码默认关**（图形码登录失败阈值后按其开关触发）；可视化开关页留阶段五 R19。邮箱验证码**生成+Redis 存+校验**就绪，但**投递本阶段降级为 dev 日志打印**——⚠️ **此为开发态降级，不满足公网注册防滥用验收；生产公网放量前必须接真实 SMTP**（见 §3.3 / §9）。

### 3.3 暂不实现（留后续阶段）
- **接口级 resource code 细粒度 RBAC（R8 完整版）、`v-permission` 按钮级、`/me` 功能码集合的消费**——阶段三（本阶段仅做 §3.1 的粗粒度角色 tier 守卫）。
- 用户/角色/菜单/功能/租户管理页与全套 `sys_role/sys_menu/sys_resource/sys_user_role/...` 表及管理接口（R10–R14）——阶段三。
- 菜单后端数据化与 SideMenu 动态渲染（R12，P3）——阶段三（本阶段 SideMenu 不改，仍前端硬编码）。
- 存量 14 路由全量打 resource code + 归属上下文全量透传（R21）——阶段四（本阶段仅建上下文与最小桥接）。
- 日志审计（R17）、数据字典（R18）、配置拆父子菜单（R19）——阶段五。
- 真实邮件 SMTP 投递、真实第三方 OAuth、静默刷新（R22）。

---

## 4. 技术方案

### 4.1 整体思路与模块边界
请求链路（本阶段后）：
```
浏览器 → axios(注 Authorization) → FastAPI
   → [限流中间件] → [安全头中间件]
   → [鉴权中间件 auth_middleware]  ← 机制性默认 deny：路径在白名单则放行；否则必须有有效 token
        ├ 解析 JWT → 校验签名/过期 → 查黑名单(Redis,fail-closed) → 校验 perm_ver(Redis/PG)
        ├ set ContextVar(current_user, current_tenant)，请求结束清理
        └ 失败 → 401 / Redis 不可用 → 503（鉴权关键不放行）
   → 路由处理（系统级路由再过 require_role("system") 依赖）
   → services / 领域引擎 → 资产仓库(归属取上下文；HTTP 请求链缺上下文=报错,不回落 admin)
```
> 默认 deny 是**机制**不是约定：用应用级中间件按路径白名单统一拦截，新增路由无需记得"挂依赖"即默认受保护；另加路由扫描测试兜底（§8）。`require_role` 作为路由依赖叠加在系统级接口上。

新增后端模块（对齐现有 `storage/`·`services/`·`api/` 分层）：
| 模块 | 文件 | 职责 |
| --- | --- | --- |
| 安全原语 | `backend/auth/security.py` | 密码哈希(bcrypt)/校验、密码强度校验 |
| 令牌 | `backend/auth/jwt_tokens.py` | 签发/校验 access·refresh，编解码 claims |
| 短状态 | `backend/auth/session_store.py` | Redis：token 黑名单、perm_ver 缓存、登录失败计数+锁定、验证码、限流令牌桶；**鉴权关键操作 fail-closed** |
| 上下文 | `backend/auth/context.py` | `ContextVar[current_user/current_tenant]` + `get_current_owner()`（**请求链缺上下文抛错**）+ `system_context()`（CLI/后台/迁移显式用 default/admin） |
| 鉴权中间件 | `backend/auth/middleware.py` | **auth 中间件（机制性默认 deny + 白名单 + 上下文注入）** + 限流 + 安全响应头 |
| 角色守卫 | `backend/auth/deps.py` | `require_role("system")` 路由依赖（粗粒度，叠加在系统级接口） |
| 用户仓库 | `backend/storage/user_repository.py` | `sys_user/sys_tenant` 读写（PG，%s），账号/邮箱查、状态、perm_ver 自增、注册建租户事务 |
| 认证服务 | `backend/services/auth_service.py` | 编排 login/logout/refresh/register/me（调上述 + 用户仓库 + 验证码/限流） |
| 认证路由 | `backend/api/auth.py` | `/api/auth/*` 薄层（参数校验 + 调 service + 响应包装） |

新增前端：`stores/auth.ts`、`views/LoginView.vue`、`api/auth.ts`、`composables/usePublicAuthConfig.ts`（拉登录页开关）；改造 `api/client.ts`、`router/index.ts`、`App.vue`、`main.ts`。

### 4.2 关键契约决策（已定，低风险可推断；不认可在开发前提出）
| 项 | 决策 | 理由 |
| --- | --- | --- |
| 认证异常 HTTP 码 | 新增 `AuthError(401)`/`ForbiddenError(403)`/`RateLimitError(429)`，基类带 `http_status`；改 `exception_handler` 用 `getattr(exc,'http_status',200)` 作 status_code，**业务异常仍 200**，仅认证类用真实码 | R4/R7/R15 明确要求 401/403/429；前端按 HTTP status 分流 |
| 角色模型（本阶段） | `sys_user` 加 `role_code TEXT`（`system`/`tenant_admin`/`normal`，常量见 `backend/auth/constants.py`）；**不建** `sys_role/sys_user_role`。**角色来源明确**：seed `admin`=`system`；自助注册用户=`tenant_admin`（其新租户管理员）；`normal` 用户本阶段**无创建入口**（阶段三用户管理页才建）；`paid`/`plan_code`/`quota`（需求 6.1）**本阶段不做** | 阶段二只需 JWT 携带 role + 粗粒度 tier；完整 RBAC 表与多角色是阶段三，避免提前建半套 |
| 默认 deny 机制 | **应用级 auth 中间件**按路径白名单拦截（非约定式逐 router 挂依赖）+ 路由扫描测试兜底 | 新增路由默认受保护，结构上不可漏挂（评审 P1） |
| 角色守卫粒度 | 系统级/全市场写接口叠加 `require_role("system")`；用户私有资产接口仅需登录（靠 R9 归属隔离） | 关闭注册越权窗口（评审 P0）；非系统接口的隔离由上下文归属保证 |
| 阶段三衔接 | 阶段三引入 `sys_role/sys_user_role` 后，`role_code` **1:1 映射**进 `sys_role.code`（`system`/`tenant_admin`/`normal` 直接对应内置角色，再补 `paid`），用户-角色迁入 `sys_user_role`；additive，admin→system 不丢 | 升级可加列/加表，不破坏阶段二数据 |
| perm_ver 落点 | PG `sys_user.perm_ver INT DEFAULT 0` 为权威 + Redis 缓存；权限/状态变更自增 | R4/R8 即时失效；阶段二变更点=禁用/锁定/改密 |
| JWT 库与密钥 | `PyJWT` HS256；密钥 `AI_STOCKS_JWT_SECRET`（环境变量，缺失时启动报错不用默认弱密钥）；access 默认 60min、refresh 默认 14d，均可配 | 同步栈轻量；密钥不入码（CLAUDE.md） |
| 密码哈希 | `bcrypt`（经 `passlib[bcrypt]` 或直接 `bcrypt`）；禁明文/弱哈希（R15） | 成熟、无需 GPU 资源；argon2 亦可，择一 |
| 管理员初始密码 | seed `admin` 密码取 `AI_STOCKS_ADMIN_PASSWORD`（缺失则生成随机并打印到启动日志一次 + 标记需改密），不写死 | 不入码；首次部署可控 |
| 上下文取值 | **HTTP 请求链路缺上下文 = 直接报错**（500/拒绝），**不回落 admin**——避免把上下文注入 bug 掩盖成默认管理员越权（评审 P1）；仅 **CLI/后台任务/迁移**经显式 `system_context()` 用 `default/admin` | 请求链已由中间件保证有上下文；回落只属离线任务 |
| Redis 故障语义 | 鉴权关键操作（黑名单/perm_ver 校验）Redis 不可用时 **fail-closed**（拒绝/503，不放行），保住"登出旧 token 失效"里程碑；限流 Redis 失败 fail-open + 告警（防滥用非安全闸） | Redis 是启动硬依赖；放行会废掉吊销保证（评审 P1） |
| 限流维度 | IP + 账号 双维度令牌桶（Redis），阈值可配；命中 429 | R15 |
| 登录页开关来源 | 公开接口 `GET /api/auth/public-config`（无需 token，返回是否要图形/邮箱验证码），登录页加载时拉取 | R16 链路读取；不暴露敏感配置 |

### 4.3 登录/注册页（P1）技术实现

- **原型文件**：[../prototypes/login.html](../prototypes/login.html)（需求 7.1 已敲定，科技风 · 黑白双主题，浏览器直开切换查看）。本计划承接该原型做技术实现，**不重复设计、不替换原型**；如实现中发现原型与组件能力/约束冲突，列入 §10 待确认项，不擅自改原型。
- **实现要点**：登录页是**全屏独立壳**，脱离主框架 SideMenu/顶栏——路由打 `meta.public/meta.fullscreen`，[App.vue](../../../frontend/src/App.vue) 按 `route.meta.fullscreen` 决定是否套主框架；黑白双主题复用 `useTheme()` 切 `html.dark`，颜色全用 CSS 变量（`:root` 浅 + `html.dark` 深两套，与原型一致、与 DESIGN.md token 规范对齐，不引第三方动画库）；左栏科技风网格/标语用纯 CSS/SVG。承接原型的区域/操作入口/状态/响应式退化见下表。

#### 4.3.1 页面功能点技术实现（承接需求 7.1）

| 页面功能点 | 需求编号 | 需求交互要点 | 技术实现 | 涉及组件/模块 | 数据/API | 状态与异常处理 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 账号密码登录 | R4(7.1.1) | 输入账密→登录→成功跳首页/失败计数 | 表单校验非空→`auth.login()`→写 store+持久化→`router.replace(redirect||'/')` | LoginView 登录 Tab、auth store、api/auth | `POST /api/auth/login`→`GET /api/auth/me` | 按钮 loading；401 账密错；锁定显剩余时间；429 限流提示 | T8 |
| 图形验证码 | R15/R16(7.1.1) | 失败阈值后显隐 | 登录失败 N 次后 public-config/登录响应标记需验证码→显示图样→提交带 captcha_id+code | LoginView、session_store | `GET /api/auth/captcha`(图)、login 带 captcha | 验证码错/过期友好提示并刷新图 | T6/T8 |
| 自助注册+建租户 | R5(7.1.2) | 填账号/邮箱/密码/邮箱码→注册 | 切注册 Tab→校验唯一/强度/确认/邮箱码→`auth.register()`→成功为新租户租管→自动登录或跳登录 | LoginView 注册 Tab、auth_service.register（建用户+建租户+绑 role_code 事务） | `POST /api/auth/register`、`POST /api/auth/send-email-code` | 重复注册/验证码错过期/滥注 429 提示；邮箱码开关关时隐藏该项 | T8/T4 |
| 邮箱验证码发送 | R5/R16(7.1.2) | 点发送→倒计时 | 生成 6 位码存 Redis(TTL)→**dev 日志打印**(SMTP 待基建)→前端 60s 倒计时禁用 | session_store、auth_service | `POST /api/auth/send-email-code` | 频次限流 429；倒计时内禁点 | T6/T8 |
| 第三方入口占位 | R6(7.1.3) | 4 入口置灰 hover「敬请期待」 | 4 个 disabled 按钮 + el-tooltip；点击 `@click.prevent` 无跳转 | LoginView | 无（后端 `GET /api/auth/oauth/{provider}` 占位返回未实现） | 点击不报错不跳空白 | T8 |
| 主题切换(黑白) | 用户要求 | 右上切换 + 记忆 | 复用 `useTheme().toggleTheme()`；登录页独立可切，刷新保持 | LoginView、useTheme | localStorage | — | T8 |
| 登录态联动 | R20(7.1.1) | 登录后触发后续渲染 | login 成功后 store 就绪，守卫放行→主框架顶栏用户区显示（P2） | auth store、App.vue | `/me` | token 失效统一 401 处理 | T7/T9 |

### 4.4 顶栏用户区（P2，更新页）
- **原型文件**：需求 7.2 标注**不生成原型**（仅顶栏右侧局部新增用户下拉 + 退出，无布局重排/跨组件联动），本计划继承该判断，按变更说明实现。
- 顶栏右侧（[App.vue](../../../frontend/src/App.vue)）新增「用户名 · 所属租户」下拉 →（个人信息占位 / 退出登录）；退出调 `auth.logout()`（请求 `/api/auth/logout` 入黑名单 → 失败也强制前端清态 → 跳 `/login`）。数据来自 auth store（`/me`）。已登录可见。

### 4.5 鉴权与上下文（R7 + R8 最小切片）落地方式
- **默认 deny 用机制不用约定**：采用**应用级 auth 中间件**（Starlette `BaseHTTPMiddleware`）统一拦截——路径命中白名单则放行；否则必须携带有效 token，解析校验后 `set` 上下文，缺/无效 → 401。新增路由无需"记得挂依赖"即默认受保护。**另加路由扫描测试**（§8）断言：除白名单外所有 `/api/**` 路由都经鉴权，防漏网。限流/安全头也走中间件链（对所有请求含白名单生效）。
- **上下文**：`contextvars.ContextVar` 中间件内 `set`、请求结束清理；`get_current_owner()` 在 **HTTP 请求链缺上下文时抛错**（不回落 admin，避免注入 bug 变成默认管理员越权）；资产仓库归属取值入口改为 `get_current_owner()`；**CLI/后台任务/迁移**经显式 `system_context()` 用 `default/admin`（阶段一脚本/调度由此兼容，不破存量）。
- **白名单**：`/api/health`、`/api/auth/login`、`/api/auth/register`、`/api/auth/refresh`、`/api/auth/captcha`、`/api/auth/send-email-code`、`/api/auth/public-config`、`/api/auth/oauth/*`(占位)、SPA 静态。**非白名单默认需 token**。
- **R8 最小角色守卫**：系统级/全市场写接口（`data_admin`/`data_tasks`/调度/`indicators` 写/`config` 平台段/`layout` preset·page·component）叠加 `require_role("system")` 依赖 → 非 system 角色 403。**关闭自助注册越权窗口**（评审 P0）。用户私有资产接口（profiles/score·trade_profile/stock_group/backtest/training/board/screen/stocks）仅需登录，跨租户/owner 由 R9 归属隔离保证。
- 注：本阶段授权为「登录 + 粗粒度角色 tier」两档；**resource code 细粒度校验（R8 完整版）留阶段三**。存量 14 路由全量经中间件鉴权（公开仅 auth/health；§10.2 已确认），其中系统级再叠 `require_role`。

### 4.7 R20 登录态与菜单兼容策略（避免与阶段三冲突）
- `/me` 本阶段返回 `{user, tenant, role}`，**`menus`/`permissions(功能码)` 字段返回空数组（占位，不省略键）**——前端可据此预留消费位但本阶段不依赖。
- **SideMenu 本阶段不改**：仍消费前端静态 `menuConfig.ts`（保持现状），不接后端菜单、不按功能码过滤；菜单数据化与权限过滤是阶段三（R12/P3）。
- **过渡兼容**：阶段二登录后菜单表现 = 现状静态菜单（所有已登录用户看到同一套前端菜单）；系统级页面的越权由后端 `require_role` 兜底（前端能点进但接口 403）。阶段三切后端菜单 + `v-permission` 后，前端按角色隐藏，与后端校验形成双层。**此兼容口径须在 T10 文档写明**，避免阶段三误判为回归。

### 4.6 前端页面设计闭环与维护闭环（承接 [DESIGN.md](../../../DESIGN.md) §5.2 / §7.4）

> **关键判断**：DESIGN §7.1「所有 **registry 业务页面**必须走 `LayoutHost`」、§9「新增页面必须登记否则 `pageRegistry.spec.ts` 失败」是面向**主框架内 registry 业务页**的规则。**登录页（P1）是全屏独立认证壳，不属于 registry/LayoutHost 体系**——故 archetype 选型 / Slot / `settings-drawer` overlay / `pageRegistry` 登记 / DESIGN §9 登记**均不适用**；但页面结构、滚动归属、响应式、构建与视口验收等闭环要素仍须满足。P2 仅改应用外壳顶栏，同样不涉及 registry 页面闭环。

**P1 登录页 · 设计闭环（DESIGN §5.2 七项）**

| 计划项 | 内容 |
| --- | --- |
| 页面定位 | 全屏独立认证壳；主流程=登录 / 注册切换；**新增页面** |
| 布局选型 | **不适用 archetype**（不走 LayoutHost）；自定义「左视觉 / 右认证卡」分栏壳，原型 [../prototypes/login.html](../prototypes/login.html)；**不新增布局原型** |
| Slot 与组件设计 | 不适用 LayoutHost slot；原生分栏 + Element Plus 表单组件（`el-input`/`el-button`/`el-tooltip`），主区无成长表、**无整页滚动**（卡片定高，超出卡内滚），无可重排区。**契约硬约束**：`LoginView.vue` 在 `src/views/` 下会被 `layout-contract.spec.ts` 扫描——**禁用 `vh/dvh` 高度、禁手写 `.v-page/.v-grow/.v-scroll`**；全屏用 `position:fixed;inset:0`（或 `height:100%` 继承 `html,body{height:100%}` 链）实现，类名用自定义 `.login-*` |
| 配置设计 | 仅「黑/白主题」走 `useTheme` + `localStorage`（与全站一致）；**无布局旋钮 / 组件设置 / 页面记忆**，故无配置中心/设置抽屉接入 |
| 复用与新增判断 | 复用 `useTheme`、Element Plus、axios 拦截；新增 `LoginView.vue` + `usePublicAuthConfig`；**不新增组件种类 / 组件配置字段 / registry 业务态** |
| 维护清单 | 同步 [router/index.ts](../../../frontend/src/router/index.ts)（新增 `/login`，`meta.public/fullscreen`）+ [App.vue](../../../frontend/src/App.vue)（按 `route.meta.fullscreen` 决定是否套主框架壳）；**不入 `pageRegistry`、不登记 DESIGN §9、无 `settings-drawer`**（非 registry 页，理由见上） |
| 验收项 | `npm test`（**`pageRegistry.spec.ts` + `layout-contract.spec.ts` 均绿**——非 registry 路由不破前者；LoginView 不踩 vh/`.v-page` 红线不破后者）、`npm run build`（vue-tsc）、关键视口 `1440×900` / `1366×768` / `1100×620` + `≤768px` 左栏退化、**无整页滚动**、黑白两套 token 对等 |

**维护闭环（DESIGN §7.4「新页面」行）**：常规新页面须同步 `脚手架 / pageRegistry.ts / router/index.ts / DESIGN §9` 并过 `pageRegistry.spec.ts`/`layout-contract.spec.ts`。登录页因**不走 LayoutHost**，仅同步 `router/index.ts` + `App.vue` 壳判断、**不入 pageRegistry/§9**。两条前端契约均已核实其判定逻辑：`pageRegistry.spec.ts` 只校验 registry 页（非 registry 路由不纳入，无需排除）；`layout-contract.spec.ts` 扫 `src/views/**` 全量源码卡「无 vh 高度 / 无手写 `.v-page·.v-grow·.v-scroll`」——**LoginView 按上表契约硬约束实现即天然通过**，不需要为认证壳加豁免（详见 §8 与待确认 2）。

**P2 顶栏（App.vue 外壳更新）**：改应用外壳顶栏区，非 registry 页面，**不涉及 archetype/pageRegistry/§9 闭环**；维护=`App.vue` + `auth` store；验收=登录后顶栏显示身份、退出清态跳登录、`build` 通过。

---

## 5. 需求与开发内容映射和开发状态

| 需求编号 | 需求内容/来源 | 计划开发内容 | 对应任务 | 状态 | 偏差判断 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| R4 | 账密登录+JWT+登出黑名单+/me | jwt_tokens/security/session_store/auth_service/api·auth | T2,T3,T4 | **已完成** | 一致 | |
| R7 | 鉴权中间件(机制性默认deny)+上下文注入+白名单 | auth/middleware(中间件式拦截+注上下文)·context·deps，main 挂载，仓库取上下文(请求链不回落) | T5 | **已完成** | 一致 | 默认deny用中间件机制+路由扫描测试兜底 |
| R8（最小切片） | 系统级/全市场写接口 `require_role("system")` 粗粒度守卫 | auth/deps.require_system + data_admin/tasks整router+indicators/config/layout平台写端点 | T5 | **已完成** | 部分覆盖 | 仅角色tier守卫(关注册越权窗口)；resource code细粒度留阶段三 |
| R15 | 密码哈希/失败锁定/限流/安全头/验证码 | security 哈希、session_store 计数·令牌桶(鉴权关键fail-closed)、middleware 头、图形验证码 | T2,T3,T6 | **已完成** | 部分覆盖 | CSRF/XSS 靠参数化+安全头+SPA，行为风控(R27)不做 |
| R20 | auth store+http 拦截+路由守卫+菜单/按钮 | stores/auth、client 拦截、router 守卫、App 顶栏；/me 菜单/功能码空、SideMenu 静态(§4.7) | T7,T9 | **已完成** | 部分覆盖 | `v-permission` 按钮级+后端菜单(R8/R12)留阶段三；本阶段登录态/守卫骨架+菜单兼容策略 |
| R5 | 自助注册+自动建租户+绑租管 | auth_service.register（用户+租户+role_code='tenant_admin' 事务）、user_repository | T4,T8 | **已完成** | 一致 | 最小角色模型（role_code）；越权窗口由 R8 最小切片闭合 |
| R6 | 第三方入口占位 | LoginView 置灰按钮+tooltip，后端 oauth 占位路由 | T4,T8 | **已完成** | 一致 | |
| R16 | 注册防滥用开关化 | 登录链路读开关(默认邮箱码开/图形码关，对齐需求)、图形验证码、邮箱码 gen/verify | T6,T8 | **已完成** | 部分覆盖 | 可视化开关页留阶段五 R19；**邮件投递 dev 日志=开发态降级，生产放量前须接 SMTP** |
| P1 登录页 | 7.1 登录/注册页 | LoginView 科技风+黑白主题，承接原型 prototypes/login.html，过 layout-contract 契约 | T8 | **已完成** | 一致 | 原型已在需求 7.1 敲定 |
| P2 顶栏用户区 | 7.2 顶栏用户区 | App.vue 用户下拉+退出 | T9 | **已完成** | 一致 | |
| —（技术依赖） | sys_user 扩展+seed 密码 | T1 数据层 | T1 | **已完成** | 超范围(必要技术依赖) | 无对应业务 R 编号，为 R4/R5 落地前置，理由：JWT 需 perm_ver/role/可校验密码 |
| —（技术依赖） | 认证异常 401/403/429 契约 | exceptions 扩展(T2)+handler 改造(T4) | T4 | **已完成** | 超范围(必要技术依赖) | R4/R7/R15 要求真实 HTTP 码 |

---

## 6. 详细实施步骤与进度追踪

> 顺序按依赖：T1 数据层 → T2 安全原语 → T3 Redis 短状态 → T4 认证服务+接口 → T5 鉴权中间件+上下文+角色守卫 → T6 安全加固 → T7 前端登录态 → T8 登录页 → T9 顶栏 → T10 测试+文档。

### 6.1 任务 T1：数据层 — sys_user/sys_tenant 扩展 + seed 密码
- 状态：**已完成**（commit 待提交）。落地：`backend/auth/{__init__,constants,security}.py` 新增；`pg_ddl.py` DDL_SYS_USER 加 role_code/perm_ver/last_login_at、`init_pg_db` 幂等 ALTER + email 部分唯一索引、`seed_default_tenant` 提升 admin 为 system 并补初始密码（env `AI_STOCKS_ADMIN_PASSWORD` 或随机+告警，幂等不覆盖已设密码）；`requirements.txt`/`pyproject.toml` 加 bcrypt/PyJWT；SQL 留痕 [auth-schema.sql](auth-schema.sql)。验证：init_pg_db 冒烟（列/索引/admin=system/密码往返均 OK）+ 全量 **215 passed** 无回归。
- 依赖：阶段一（PG 已就绪）
- 涉及文件/模块：[backend/storage/pg_ddl.py](../../../backend/storage/pg_ddl.py)、`backend/auth/constants.py`(新)、迁移 SQL（§7）
- 目标：`sys_user` 具备认证所需字段并能 seed 可登录的管理员。
- 操作：`sys_user` 加 `role_code TEXT DEFAULT 'normal'`、`perm_ver INT NOT NULL DEFAULT 0`、`last_login_at TIMESTAMP`、`email UNIQUE`（部分唯一/允许空）；`init_pg_db` 内幂等 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`（additive）；`seed_default_tenant` 给 admin 设 `role_code='system'` + 用 `AI_STOCKS_ADMIN_PASSWORD` 写 `password_hash`（缺失则随机生成并日志告警一次）；定义内置角色码常量。
- 产出：可登录的 admin；扩展后的 `sys_user`；常量模块；迁移 SQL 文件。
- 影响范围：仅 `sys_*`；不动资产表与行情。
- 边界与异常：列已存在时 ADD COLUMN IF NOT EXISTS 跳过；email 唯一需允许多 NULL（用部分唯一索引 `WHERE email IS NOT NULL`）；旧 seed 的 admin 无密码→本任务补。
- 验证方式：`init_pg_db` 重复执行幂等；查 `sys_user` 列齐全；admin `password_hash` 非空、`role_code='system'`。
- 完成标准：admin 可被 T4 登录校验通过。

### 6.2 任务 T2：安全原语 — 密码哈希 + JWT
- 状态：**已完成**（commit 待提交）。落地：`security.check_strength`（长度+字母数字）；`jwt_tokens.issue_access/issue_refresh/decode`（claims sub/tenant_id/role/perm_ver/typ/jti/iat/exp，HS256，typ 门禁）；`settings.AuthConfig`（algorithm/access_ttl_min=60/refresh_ttl_days=14/min_password_len=8）+ `jwt_secret()` 走 `AI_STOCKS_JWT_SECRET`（无弱默认，缺失抛 ConfigError）；`settings.yaml` 加 auth 段；`exceptions` 加 `AuthError(401)/ForbiddenError(403)/RateLimitError(429)` + base `http_status`（提前落地，jwt.decode 需 AuthError；handler 映射仍 T4）。验证：新增 test_auth_security(6)+test_auth_jwt(8) 全过（往返/错误密码/强度/过期/篡改/伪造密钥/类型门禁/缺密钥 ConfigError），全量 **229 passed**。
- 依赖：T1
- 涉及文件/模块：`backend/auth/security.py`、`backend/auth/jwt_tokens.py`、[backend/config/settings.py](../../../backend/config/settings.py)、[config/settings.yaml](../../../config/settings.yaml)、[requirements.txt](../../../requirements.txt)/[pyproject.toml](../../../pyproject.toml)
- 目标：可哈希/校验密码、签发/校验 JWT。
- 操作：加依赖 `PyJWT`、`bcrypt`(或 `passlib[bcrypt]`)；`security.hash_password/verify_password/check_strength`；`jwt_tokens.issue_access/issue_refresh/decode`（claims: user_id/tenant_id/role/perm_ver/typ/exp/jti）；settings 增 `auth` 段（access_ttl_min/refresh_ttl_days）+ secret 走 `AI_STOCKS_JWT_SECRET`（缺失启动报错）。
- 产出：两个原语模块 + 配置项 + 依赖声明。
- 影响范围：新增依赖；settings 扩展。
- 边界与异常：secret 缺失→明确启动错误（不用默认弱密钥）；token 篡改/过期→`decode` 抛 `AuthError`。
- 验证方式：单测 哈希往返、错误密码拒绝、token 签发→解码一致、过期 token 拒绝、篡改拒绝。
- 完成标准：单测全过。

### 6.3 任务 T3：Redis 短状态消费
- 状态：**已完成**（commit 待提交）。落地：`backend/auth/session_store.py`——token 黑名单 `revoke_jti`/`is_jti_revoked`、perm_ver 缓存 `cache/get_cached/invalidate`、登录失败 `record_login_failure`/`login_failure_count`/`clear` + 锁定 `lock_account`/`is_locked`/`lock_remaining`、图形验证码 `save/take_captcha`（一次性消费）、邮箱码 `save/verify_email_code`、限流 `rate_limit_ok`（固定窗口）；键均带 TTL；**鉴权关键（黑名单/perm_ver）Redis 故障异常上抛=fail-closed，限流 fail-open+告警**（setex 改现代 `set(ex=)`）。conftest 加 `redis_cli` 夹具。验证：test_auth_session_store(6) 全过（黑名单/perm_ver 缓存/失败计数+锁定/验证码一次性/邮箱码/限流窗口），全量 **235 passed**。
- 依赖：T2
- 涉及文件/模块：`backend/auth/session_store.py`、[backend/storage/redis_client.py](../../../backend/storage/redis_client.py)
- 目标：黑名单/perm_ver 缓存/登录失败计数+锁定/验证码/限流令牌桶。
- 操作：键设计 `auth:bl:{jti}`(TTL=token 剩余寿命)、`auth:pv:{user_id}`、`auth:fail:{account}`(计数+TTL)、`auth:lock:{account}`、`auth:captcha:{cid}`(TTL)、`auth:emailcode:{email}`(TTL)、`rl:{scope}:{key}`(令牌桶)；提供 add/check 方法；perm_ver 缓存未命中回查 PG 并回填。
- 产出：session_store 模块。
- 影响范围：Redis 首次承载业务键（命名带 `auth:`/`rl:` 前缀避免冲突）。
- 边界与异常：Redis 不可用→**鉴权关键(黑名单/perm_ver) fail-closed 拒绝、限流 fail-open+告警**（§10.2 已决策）；TTL 必设避免无限增长。
- 验证方式：单测 计数+锁定阈值、黑名单命中、令牌桶限流、验证码校验+过期。
- 完成标准：单测全过；键均有 TTL。

### 6.4 任务 T4：认证服务 + 接口 + 异常契约
- 状态：**已完成**（commit 待提交）。落地：`user_repository`（account/email/id 查、update_last_login、bump_perm_ver via RETURNING、register_tenant_and_admin 事务=建租户+租管+回填）；`auth_service`（login 验密+失败计数+锁定+限流+可选图形码 / refresh 轮换+黑名单+perm_ver 校验 / logout 拉黑 jti / register 强度+邮箱码+唯一性+自动登录 / claims_from_bearer / me[§4.7 空菜单] / issue_captcha[SVG] / send_email_code[dev日志] / public_config）；`api/auth.py` 9 端点；`main` 注册路由 + **exception_handler 改按 `http_status` 出码**（业务仍 200，认证类 401/403/429）；AuthConfig 补登录/注册安全阈值 + settings.yaml。验证：test_auth_service(8)+test_auth_api(4) 全过（注册建租管/登录成败/锁定/刷新轮换/登出吊销/HTTP 401 映射/oauth 占位），全量 **247 passed**。
- 依赖：T1,T2,T3
- 涉及文件/模块：`backend/services/auth_service.py`、`backend/storage/user_repository.py`、`backend/api/auth.py`、[backend/common/exceptions.py](../../../backend/common/exceptions.py)、[backend/main.py](../../../backend/main.py)
- 目标：`/api/auth/login|logout|refresh|register|me|captcha|send-email-code|public-config|oauth/{provider}(占位)` 可用。
- 操作：扩展异常（`AuthError 401`/`ForbiddenError 403`/`RateLimitError 429`，基类带 `http_status`），改 `exception_handler` 按 `http_status` 出码；`user_repository` 账号/邮箱查、状态校验、perm_ver 自增、`register` 事务（建用户+建租户+绑 role_code）；`auth_service` 编排登录（验密+失败计数+锁定+签 token）、刷新（验 refresh+黑名单+换新）、登出（access·refresh 入黑名单）、注册、me；`api/auth.py` 薄层 + 注册到 main。
- 产出：auth 服务/仓库/路由；异常契约；main 挂载。
- 影响范围：main 新增 1 路由；异常 handler 行为对认证类变化（业务类不变）。
- 边界与异常：禁用/锁定用户登录→明确提示；重复账号/邮箱→冲突提示；refresh 失效→401 跳登录；注册建租户事务失败整体回滚。
- 验证方式：接口测试 登录成功/失败/锁定/限流429、刷新换新、登出后旧 token 401、注册建租户+租管、me 返回身份。
- 完成标准：全部接口契约符合 §4.2/§6.4。

### 6.5 任务 T5：鉴权中间件（机制性默认 deny）+ 上下文 + 角色守卫
- 状态：**已完成**（commit 待提交）。落地：`auth/context.py`（ContextVar + `get_current_owner()` 无上下文回落 default/admin + `system_context()`）；`auth/middleware.py`（**纯 ASGI 中间件**，白名单外强制有效 token→注上下文，缺/无效 401、Redis/存储不可用 503 fail-closed；OPTIONS/白名单放行）；`auth/deps.py::require_system`（非 system 403）；`main` 挂 AuthMiddleware（CORS 外层）+ data_admin/data_tasks 整 router 门禁 + indicators/config/layout 平台写端点门禁；**10 个资产仓库归属默认改 `get_current_owner()`**（向后兼容：无上下文=default/admin，认证请求=token 归属）。验证：test_auth_middleware——白名单放行/无 token 401/坏 token 401/tenant_admin 访系统级 403/system 通过/**上下文隔离(tenant_admin 看不到 admin 预设)**/路由扫描机制；修复被中间件影响的既有 test_api（补 system token，揭示原 skip 实为 401 掩盖）+ test_layout_config（平台端点补 token）；conftest 设测试 JWT 密钥。
- **Codex 评审整改（5 项，均已复现属实并修）**：①【P0】indicators **PATCH** 启停/分类漏 `require_system`（首轮 grep 漏 patch）→ 补门禁；②【P0】`get_current_owner` 请求链缺上下文仍回落 admin → 加 `_in_request` 标记，请求链内缺上下文**报错**（非请求路径才回落 default/admin），中间件对每请求置标记；③【P1】layout `/reset` 的 `scope=page`（平台写）未守卫 → 端点内按 scope 条件 `require_system()`；④【P1】Redis 故障抛 `redis.RedisError` 而中间件只接 AuthError/StorageError → 中间件 except 补 `redis.RedisError`，fail-closed 503 稳定；⑤【P2】JWT 密钥「启动报错」未落地 → `_check_storages` 启动自检加 `jwt_secret()`。新增 test_auth_context(3)+中间件回归(indicators PATCH 403/reset page 403/Redis 503)。复查所有 patch/put 端点确认无其它平台写漏网。全量 260 passed。
- **Codex 二轮评审整改（3 项，均复现属实）**：①【P1】用户级 layout 接口(get/save/reset-user/effective)信任前端 `userId`→可读写他人配置；改为一律 `get_current_owner()[1]` 派生当前用户、忽略前端传值（PG 直查回归证明 `userId=admin` 被忽略、写入当前用户名下）；②【P1】白名单 `/api/auth/me·/logout·/refresh` 绕过中间件的 Redis fail-closed→新增 `ServiceUnavailableError(503)`，session_store 鉴权关键 Redis 错误经 `_critical` 装饰器统一翻译为它（异常处理器按 http_status 出 503），并加 app 级 `redis.RedisError` 兜底处理器，中间件同步捕获→任何路径 Redis 故障均 503；③【P2】`/me` 固定契约 `{user, tenant, role, menus, permissions}`（补 HTTP 契约测试，防 T7 漂移）。全量 **263 passed**（0 skip）。
- **Codex 阶段验收评审整改（T8–T10 完成后，4 项均复现属实）**：①【P0】**注册页缺邮箱输入框**——模板只渲染账号/密码/确认密码/邮箱验证码，但 `onRegister`/`onSendEmailCode` 读 `form.email`，邮箱码默认开→**默认配置下注册永远失败**。修：注册态补独立「邮箱」输入框（绑 `form.email`，置于确认密码与邮箱码间），账号占位注册态改「账号」。preview 实测注册态 5 字段齐全。②【P1】**system 守卫覆盖不足**——`GET /api/config`、`GET /data/status`、`GET /data/update-logs`（在 stocks.py 非 data_admin router 故 T5 gate 漏网）、`GET /layout/field-policies` 只需登录不需 system，tenant_admin 可越权读平台数据。修：4 端点补 `require_system`；**并复核确认** `/data/trade-dates`(全站日历)、`/layout/presets|pages|effective`(页面渲染)是普通用户依赖，**不 gate**（防误伤）。真实 tenant_admin token 实测：4 个→403、3 个共享读→200。③【P2】**登录失败提示被吞**——client 拦截器 401 分支只 `redirectToLogin()`，已在 /login 时该函数判重直接 return→账密错误无提示。修：登录页内 401 弹后端 msg（会话失效的 401 仍跳登录）。真实 401 实测弹「账号或密码错误」。④【P2】**测试假阳性**——角色守卫只抽查 2 路径、路由扫描只验无 token 401、不验 tenant_admin→403。补参数化回归 `test_system_only_reads_forbidden_for_tenant_admin`(4 项 403)+`test_user_shared_reads_not_forbidden_for_tenant_admin`(3 项反向不误 gate)。全量 **273 passed**（+7）、前端 vitest 85、build 通过。
- 依赖：T4
- 涉及文件/模块：`backend/auth/middleware.py`、`backend/auth/context.py`、`backend/auth/deps.py`、[backend/main.py](../../../backend/main.py)、资产仓库归属取值入口（[asset_repository.py](../../../backend/storage/asset_repository.py) 及各域仓库 `__init__` 默认）、系统级路由文件（`api/data_admin.py`/`data_tasks.py`/`indicators.py`/`config.py`/`layout.py`）
- 目标：机制性默认 deny + 上下文可被仓库读取 + 系统级接口角色守卫 + 请求链缺上下文不回落 admin。
- 操作：
  1. `context.py`：ContextVar + `get_current_owner()`（**请求链缺上下文抛错**，不回落 admin）+ `system_context()` 上下文管理器（CLI/后台/迁移显式 default/admin）。
  2. `middleware.py` **auth 中间件**：路径白名单放行；否则解析 token→校验签名/过期/黑名单(**fail-closed**)/perm_ver→`set` 上下文，缺/无效→401、Redis 不可用→503。请求结束清理上下文。
  3. `deps.require_role("system")`：读上下文 role，非 system→403；叠加到系统级/全市场写路由（data_admin/data_tasks/调度/indicators 写/config 平台段/layout preset·page·component）。
  4. 各资产仓库归属缺省改为 `get_current_owner()`（不改签名）；阶段一 CLI/调度入口包 `system_context()`。
- 产出：auth 中间件 + 上下文 + 角色守卫 + 仓库取值改造 + 系统级路由加守卫。
- 影响范围：所有 `/api/**` 经中间件鉴权；系统级路由加角色闸；仓库默认归属取值入口。
- 边界与异常：HTTP 请求缺上下文=报错（暴露注入 bug，不静默回落）；CLI/后台经 `system_context()` 正常；Redis 不通鉴权链 503。
- 验证方式：无 token 访问受控接口 401；非 system 角色访问 data_admin 等 403；带 system token 通过且仓库取到上下文归属；白名单免 token；CLI `migrate-rbac`/调度仍可跑（system_context）。
- 完成标准：默认 deny 为机制（中间件+路由扫描测试）、角色守卫闭合越权窗口、存量功能带对应角色 token 照常。

### 6.6 任务 T6：安全加固（限流/锁定/验证码/安全头）
- 状态：**已完成**（commit 待提交）。T4 已落地的（登录失败计数+锁定、图形/邮箱验证码 gen/verify、auth 端点 IP/账号限流、R16 默认值邮箱开/图形关、邮箱码 dev 投递）沿用；**T6 净新增**：`SecurityMiddleware`（纯 ASGI，置 CORS 内层/Auth 外层）——①**安全响应头**（x-content-type-options:nosniff、x-frame-options:SAMEORIGIN、referrer-policy；HSTS/CSP 留反代层）覆盖所有响应；②**全局 /api per-IP 限流 backstop**（`api_rate_per_min`=600，固定窗口，超限 429，Redis 故障 fail-open）。验证：test 安全头存在/全局限流 429/**图形验证码闭环（开关开启后失败达阈值需码，无码拒绝、正确码放行）**，全量 **266 passed**。
- 依赖：T3,T4
- 涉及文件/模块：`backend/auth/middleware.py`、`backend/services/auth_service.py`、[backend/main.py](../../../backend/main.py)
- 目标：限流中间件 + 安全响应头 + 登录失败锁定 + 图形验证码闭环 + 邮箱码（dev 投递）。
- 操作：限流中间件（Redis 令牌桶，IP+账号，命中 429，**Redis 失败 fail-open+告警**）；安全头中间件（X-Content-Type-Options/X-Frame-Options/Referrer-Policy 等）；图形验证码生成（轻量自包含，避免重依赖；优先纯 SVG/文本码，确需图像再评估 Pillow）+ 校验；邮箱码 gen/verify + **dev 日志投递（开发态降级）**；登录失败计数接 T3。**开关默认值对齐需求 R16：邮箱验证码默认开、图形验证码默认关**（图形码登录失败阈值后按其开关触发）。
- 产出：中间件 + 验证码闭环 + 开关默认值（邮箱开/图形关）。
- 影响范围：所有请求过限流/安全头中间件（白名单接口也过）。
- 边界与异常：限流误伤→阈值可配 + 内网/本机放宽；验证码大小写/过期处理；**邮箱码 dev 日志投递不满足公网验收，生产放量前须接 SMTP（§9 发布前检查项）**。
- 验证方式：超频 429；失败达阈值要求验证码并锁定；验证码错误拒绝；开关默认值与需求 R16 一致（邮箱开/图形关）。
- 完成标准：R15 基础项可观察生效；R16 开关默认值与需求一致。

### 6.7 任务 T7：前端 auth store + http 拦截 + 路由守卫
- 状态：**已完成**（commit 待提交）。落地：`api/authToken.ts`（localStorage 事实源，解耦 client↔store↔api 循环）；`stores/auth.ts`（token/user/tenant/role，login/register/fetchMe/logout/clearLocal，state 从 localStorage 自 hydrate=等价 loadFromStorage）；`api/auth.ts`（login/register/refresh/logout/me/captcha/send-email-code/public-config 封装）；`api/client.ts`（请求拦截注 `Authorization`；响应按 HTTP 分流：401 清态跳 `/login`?redirect、403 无权、429 限流、503 依赖不可用）；`router`（加 `/login` meta.public/fullscreen + 全局守卫：公开放行/未登录跳登录带 redirect/已登录进登录页回首页）；`App.vue`（`route.meta.fullscreen` 时脱离主框架单独渲染）；`views/LoginView.vue`（**最小可用骨架**打通登录闭环，科技风+黑白 UI 留 T8 按原型重做）。SideMenu 不改（静态 menuConfig，§4.7）。验证：`npm run build`（vue-tsc 类型检查 + 产物同步 frontend/dist）通过；浏览器可视/交互验证随 T8 登录页 UI 一并做（preview 5181）。
- 依赖：T4（接口契约）
- 涉及文件/模块：`frontend/src/stores/auth.ts`、`frontend/src/api/auth.ts`、[frontend/src/api/client.ts](../../../frontend/src/api/client.ts)、[frontend/src/router/index.ts](../../../frontend/src/router/index.ts)、[frontend/src/main.ts](../../../frontend/src/main.ts)
- 目标：登录态闭环骨架。
- 操作：`auth` store（token/refresh/user/tenant/**role**，持久化 localStorage，`login/logout/fetchMe/loadFromStorage`）；`api/auth.ts` 封装接口；`client.ts` 请求拦截注 `Authorization`，响应拦截：HTTP 401→清态跳 `/login`（带 redirect）、403→ElMessage 无权、429→限流提示；router 加 `/login`（`meta.public/fullscreen`）+ `beforeEach`（public 放行；无 token 跳 login；已登录访问 login 跳首页）；main 启动 `loadFromStorage`。**SideMenu 不改**（仍消费静态 menuConfig）；`/me` 的 `menus/permissions` 本阶段为空，store 存但暂不消费（§4.7 兼容策略）。
- 产出：store/api/拦截/守卫。
- 影响范围：全局请求与导航行为；**SideMenu/menuConfig 不动**。
- 边界与异常：token 失效统一跳登录；网络错误不误清态；刷新页保持登录；菜单仍为静态（阶段三再切后端菜单）。
- 验证方式：未登录访问受控路由跳 `/login`；登录后跳回原路由；登出清态；静态菜单照常渲染。
- 完成标准：R20 骨架闭环 + §4.7 菜单兼容口径落地。

### 6.8 任务 T8：登录/注册页（科技风 + 黑白主题）
- 状态：**已完成**（commit 待提交）。落地：`views/LoginView.vue` 按视觉原型 [../prototypes/login.html](../prototypes/login.html) 全量重做——分栏壳（左科技风品牌视觉 网格+脉冲+标语 / 右认证卡）、登录/注册 Tab、账密+密码显隐、确认密码（注册）、邮箱验证码+60s 倒计时（注册且 `require_email_code`）、图形验证码（`login_captcha_enabled` 且本地已失败后显隐，点图刷新）、第三方 4 入口置灰+title、右上主题切换复用 `useTheme`。**黑白双主题坑**：`:global(html.dark) .login-shell` 组合选择器在 scoped CSS 下不生效（`:global` 段落断作用域链）；改为自身类绑定 `:class="{'is-dark':isDark}"` + `.login-shell.is-dark{...深色 token}`，完全 scoped 可靠命中。公开配置挂载时 `getPublicConfig()` 拉取，失败保守默认（要邮箱码/不强制图形码）。App.vue（T7 已就绪）按 `route.meta.fullscreen` 只渲染 `<router-view>`。未新增 `usePublicAuthConfig.ts`（逻辑内联进 LoginView 足够，避免过度抽象）。验证：preview 5181 截图核验 light/dark 两套 + 登录/注册切换 + 第三方置灰 + 窄屏退化（品牌收顶条单列）均达标；控制台无告警；`npx vitest run src` 85 passed（含 `layout-contract.spec.ts` 绿，未踩 vh/布局类红线）；`npm run build`（vue-tsc + 产物同步）通过。
- 依赖：T7,T4
- 涉及文件/模块：`frontend/src/views/LoginView.vue`、[frontend/src/App.vue](../../../frontend/src/App.vue)（按 `route.meta.fullscreen` 决定是否套主框架，T7 已改）、登录页样式（CSS 变量 light/dark 双 token）
- 目标：按视觉原型 [../prototypes/login.html](../prototypes/login.html) 实现登录页与全部页面功能点（§4.3.1），并满足 §4.6 页面设计闭环。
- 操作：分栏壳（左视觉 / 右认证卡）；登录/注册 Tab；表单校验；图形验证码（开关/失败触发显隐）；邮箱码发送倒计时；第三方占位置灰 + tooltip；右上主题切换复用 `useTheme`；科技风视觉（CSS 变量 + 纯 CSS/SVG 网格脉冲，light/dark 各一套 token）；App.vue 改为 `route.meta.fullscreen` 时只渲染 `<router-view>`（不套 SideMenu/顶栏）。**契约硬约束（§4.6）：全屏用 `position:fixed;inset:0` 或 `height:100%` 继承链，禁 `vh/dvh` 高度、禁手写 `.v-page/.v-grow/.v-scroll`，类名用 `.login-*`，确保过 `layout-contract.spec.ts`。**
- 产出：LoginView + 公共配置 composable + App 壳条件渲染。
- 影响范围：新增页面；App 渲染分支；需 `npm run build` 同步产物。
- 边界与异常：登录 loading/锁定剩余时间/429；注册唯一性/强度/验证码错；空态/错误内联；窄屏左栏隐藏退化。
- 验证方式：preview 端口 **5181** 截图核验 light/dark 两套 + 登录/注册切换 + 第三方置灰 + 窄屏退化；正确账密登录进首页；错误提示符合 7.1 验收；`npm test` 含 `layout-contract.spec.ts` 绿。
- 完成标准：7.1 全部功能点验收通过；黑白双主题与科技风达标；满足 §4.6 页面设计闭环（含前端契约）。

### 6.9 任务 T9：顶栏用户区 + 退出
- 状态：**已完成**（commit 待提交）。落地：`App.vue` 顶栏/用户抽屉的硬编码身份（原 `hello，彭帅疯！`/`彭帅疯`/`本地单用户工作区`）全部接 auth store——`displayName`=account、头像取首字母、副行 `roleLabel(system→系统管理员/tenant_admin→租户管理员/normal→普通用户) · 租户 {tenantId}`；抽屉底部加红色描边「退出登录」按钮，`onLogout()`→`auth.logout()`（接口失败也强制 `clearLocal`）→跳 `/login`；挂载即 `fetchMe()` 刷新身份并校验会话（token 失效由拦截器统一 401→跳登录，失败静默）。验证：preview 5181 注入登录态截图——顶栏 `hello，admin！`+头像 `A`、抽屉「admin / 系统管理员 · 租户 default」、退出按钮均正确；点退出后 localStorage 清空且跳 `/login`（后端黑名单致旧 token 401 由 T4 单测覆盖）；`npm run build` 通过。
- 依赖：T7
- 涉及文件/模块：[frontend/src/App.vue](../../../frontend/src/App.vue)
- 目标：顶栏显示身份 + 退出。
- 操作：顶栏右侧「用户名 · 租户」下拉（个人信息占位 / 退出）；退出调 `auth.logout()`→清态跳登录；已登录可见。
- 产出：顶栏用户区。
- 影响范围：App 顶栏。
- 边界与异常：退出接口失败也强制前端清态。
- 验证方式：退出后旧 token 访问受控接口 401；preview 截图。
- 完成标准：7.2 验收通过。

### 6.10 任务 T10：测试 + 文档治理 + 页面闭环收尾
- 状态：**已完成**（commit 待提交）。落地：①测试——路由扫描（`test_all_controlled_get_routes_require_token`）、角色守卫（`test_system_route_forbidden_for_tenant_admin`/`_allows_system_role`）、fail-closed 503（`test_redis_failure_fails_closed_503`）、白名单/无 token 401/上下文隔离/layout 归属取上下文/安全头/全局限流 429 等在 T5/T6 已随功能建齐（`test_auth_middleware.py` 13 项），本任务确认全绿未新增缺口。②质量门槛——全量 `python -m pytest backend/tests/` **266 passed**（阶段一 215 + 阶段二新增）；前端 `npx vitest run src` **85 passed**（含 `layout-contract.spec.ts` 绿，登录页非 registry 不入 `pageRegistry.spec.ts`）；`npm run build`（vue-tsc）通过。③文档治理——[CLAUDE.md](../../../CLAUDE.md) 项目概述更新阶段二已落地 + 「开发契约」新增「认证与鉴权」九条铁律（默认 deny/纯 ASGI 中间件/白名单/归属不回落/角色守卫/Redis fail-closed vs 限流 fail-open/异常 HTTP 码/Redis 键前缀/环境变量/邮箱码 dev 降级/登录页全屏壳非 registry）；项目记忆 `multi-tenant-rbac-pivot` 更新为阶段二完成。④页面闭环——登录页 §4.6 七项满足（全屏壳、无整页滚动、light/dark 双主题、窄屏退化、未误入 registry/DESIGN §9、`router`+`App.vue` 已同步、契约测试绿）。
- 依赖：T1–T9
- 涉及文件/模块：`backend/tests/test_auth_*.py`、前端 `pageRegistry.spec.ts`/`layout-contract.spec.ts`、[CLAUDE.md](../../../CLAUDE.md)、本目录文档
- 目标：质量门槛 + 契约文档同步 + 页面维护闭环收尾（DESIGN §7.4）。
- 操作：补单测/接口测（见 §8，含**路由扫描测试**：除白名单外所有 `/api` 路由经鉴权；**角色守卫测试**：非 system 角色访问系统级接口 403；**fail-closed 测试**：Redis 不可用时鉴权链拒绝）；全量 `pytest` 绿 + `npm run build` 通过；**前端契约 `pageRegistry.spec.ts`/`layout-contract.spec.ts` 仍绿**（登录页非 registry 不入 pageRegistry/§9、且不踩 vh/`.v-page` 红线）；CLAUDE.md 补「认证与鉴权」约定（白名单/中间件默认 deny/角色守卫范围/JWT/上下文不回落/Redis fail-closed/异常码/Redis 键前缀/环境变量 `AI_STOCKS_JWT_SECRET`·`AI_STOCKS_ADMIN_PASSWORD`/邮箱码 dev 降级）；更新本目录与（如适用）architecture。**注：登录页不登记 DESIGN §9、不接 settings-drawer**（理由见 §4.6）。
- 产出：测试 + 文档 + 页面闭环验收（§4.6 七项）。
- 影响范围：文档与测试。
- 验证方式：CI/本地全绿（含前端契约测试）；§4.6 设计闭环验收项逐条满足；文档可被后续 AI 据以理解认证契约。
- 完成标准：阶段二里程碑（§ 末）全达成 + §4.6 页面闭环全满足。

---

## 7. 数据库与 SQL 计划

- **SQL 文件路径**：`agent-works/multi-tenant-rbac/stage2-auth-kernel/auth-schema.sql`（T1 产出）。
- **用途**：`sys_user` 扩展认证列（`role_code/perm_ver/last_login_at`）+ `email` 部分唯一索引；记录 admin seed 密码口径。
- **执行时机**：随 `init_pg_db()` 启动期幂等执行（`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` + `CREATE UNIQUE INDEX IF NOT EXISTS ... WHERE email IS NOT NULL`）；SQL 文件作为人读留痕与手工补执行兜底。
- **影响范围**：仅 `sys_user`/`sys_tenant` 平台表；不动资产表（阶段一已复合主键）与行情 DuckDB。
- **回滚方式**：新增列为 additive，回滚可 `ALTER TABLE sys_user DROP COLUMN`（无数据丢失风险，admin 密码可重 seed）；**不涉及不可逆迁移**。
- 说明：`sys_role/sys_user_role/sys_menu/sys_resource/audit_log/dict_*` 等表**本阶段不建**（阶段三/五）。

---

## 8. 测试与验证计划
- **单元测试**：密码哈希往返/错误拒绝/强度校验；JWT 签发-解码-过期-篡改；session_store 失败计数+锁定/黑名单/令牌桶/验证码过期。
- **接口测试**：登录成功/账密错/禁用/锁定/限流429；refresh 换新 + 旧 refresh 失效；登出后 access/refresh 进黑名单 401；注册建用户+建租户+绑租管+唯一冲突+验证码开关；`/me` 身份；白名单免 token、受控接口无 token 401、有 token 通过。
- **权限与数据范围测试**：登录后资产仓库从上下文取归属；**HTTP 请求缺上下文报错（不回落 admin）**；CLI/后台经 `system_context()` 用 default/admin 不破阶段一；**角色守卫**：非 system 角色访问 data_admin/data_tasks/调度/indicators 写/config 平台段/layout 管理 → 403；system 角色通过。
- **机制性默认 deny 测试（路由扫描）**：扫描所有注册的 `/api` 路由，断言白名单之外**无一漏挂鉴权**（新增路由若忘加保护，此测试直接红）。
- **回归测试**：全量 `pytest` 保持绿（阶段一 215 + 新增）；带对应角色 token 后存量功能照常；`npm run build` 通过（vue-tsc）。
- **异常与边界测试**：token 缺失/篡改/过期/吊销/perm_ver 失配；**Redis 不可用→鉴权链 fail-closed（拒绝/503）、限流 fail-open**；限流误伤阈值。
- **图示与原型一致性验证**：LoginView 实现匹配 [../prototypes/login.html](../prototypes/login.html) 的主要区域（左视觉/右认证卡）、操作入口（登录·注册 Tab/主题切换/第三方置灰）、关键状态（登录态/注册态字段差异/验证码显隐）与响应式退化（≤768px 左栏隐藏），并覆盖 light/dark 两套。
- **页面设计/维护闭环验证（DESIGN §5.2/§7.4）**：§4.6 设计闭环七项逐条满足；**无整页滚动**、关键视口（1440×900/1366×768/1100×620）可用；维护闭环——`router/index.ts`+`App.vue` 已同步、登录页**未误入** `pageRegistry`/DESIGN §9、`pageRegistry.spec.ts`/`layout-contract.spec.ts` 仍绿。
- **配置闭环验证**：JWT TTL/限流阈值/验证码开关改 settings 或开关后即时被登录链路读取（R16 链路读取口径，可视化开关页阶段五）。
- **需求映射验证**：§5 表每个本期 R 项均有任务+状态+可观察验证；超范围两项（T1 数据层、异常契约）已标注为必要技术依赖。
- **页面功能点验证**：7.1 各功能点（登录/验证码/注册/邮箱码/第三方/主题）均有实现+任务+状态+异常处理。
- **视觉验证**：preview 端口 **5181** 截图 light + dark 两套（禁占用 5173）。

## 9. 发布与回滚
- **发布前检查**：环境变量 `AI_STOCKS_JWT_SECRET`（必设）、`AI_STOCKS_ADMIN_PASSWORD`（建议设）已配置；PG/Redis 运行；`init_pg_db` 已补 admin 密码；`npm run build` 产物同步。**⚠️ 若开放公网自助注册（邮箱码默认开），必须先接真实 SMTP——dev 日志投递仅限内网/开发，不可公网放量**（否则注册防滥用失效）。
- **发布步骤**：部署后端（自动 `ALTER` 扩列 + seed）→ 重启 → 验证可登录 → 部署前端产物。
- **配置或环境变量**：`AI_STOCKS_JWT_SECRET`（必），`AI_STOCKS_ADMIN_PASSWORD`（首部署），`auth.access_ttl_min`/`refresh_ttl_days`/限流阈值（settings.yaml）。
- **回滚方案**：前端可回退到无登录构建；后端列为 additive 可保留（前端不调用即无影响）；如需彻底回滚 `DROP COLUMN` + 移除 auth 路由挂载。**无不可逆点**（区别于阶段一 R3）。

## 10. 风险、假设与待确认项

### 10.1 风险
- **【P0·已缓解】自助注册越权窗口**：开放公开注册 + 仅"登录即放行"会让任意注册的 tenant_admin 访问系统级存量接口（数据管理/任务调度/技术指标/系统设置/布局配置，需求仅 system 可见）。**缓解**：§3.1 R8 最小切片 `require_role("system")` 守卫系统级/全市场写接口（T5），关闭窗口。残留风险：守卫的接口清单需覆盖全，靠**路由扫描 + 角色守卫测试**兜底（§8）。
- **默认 deny 误伤存量**（中）：存量路由全量经中间件鉴权后，前端未带 token 页面将 401。应对：T7 前端登录态先就绪再开 T5 中间件全量拦截；本机/内网可配开发开关。
- **认证异常 HTTP 码改造影响既有前端**（中）：现拦截器只认业务 code。应对：业务异常仍 200，仅认证类用真实码，前端拦截器同步加 HTTP status 分支（T7）。
- **【已决策】Redis 故障影响登录链路**（中）：黑名单/perm_ver 依赖 Redis。决策：鉴权关键 **fail-closed**（拒绝/503，保吊销语义）、限流 fail-open + 告警（见 §10.2）；Redis 本为启动硬依赖。
- **邮箱码 dev 投递误用于公网**（中）：dev 日志投递不防滥用。应对：§9 发布前检查显式拦截——公网放量前必接 SMTP。
- **科技风视觉黑白对等遗漏 / 触碰前端契约**（低）：dark 对比度、`vh`/`.v-page` 红线。应对：CSS 变量两套 + preview 双主题截图核验；LoginView 按 §4.6 契约硬约束实现，`layout-contract.spec.ts` 兜底。

### 10.2 假设与已确认决策
- 【已确认】**阶段二范围全并入** R5（注册+建租户）/ R6（第三方入口占位）/ R16（图形验证码 + 开关消费基础）。
- 【已确认·评审 P0】**保留公开注册 + 加 R8 最小角色守卫**：系统级/全市场写接口限 `system` 角色，闭合注册越权窗口。
- 【已确认·评审 P1】**R16 开关默认值对齐需求**：邮箱验证码默认**开**、图形验证码默认**关**；邮箱码投递本阶段 **dev 日志（开发态降级）**，公网放量前必接真实 SMTP。
- 【已确认·评审 P1】**Redis 鉴权关键 fail-closed**（黑名单/perm_ver 不可用→拒绝/503，保"登出旧 token 失效"里程碑）；限流 fail-open + 告警。
- 【已确认·评审 P1】**默认 deny 用中间件机制 + 路由扫描测试**，非逐 router 约定挂依赖。
- 【已确认·评审 P1】**HTTP 请求链缺上下文直接报错，不回落 admin**；仅 CLI/后台/迁移经 `system_context()` 用 default/admin。
- 【已确认】角色本阶段单 `role_code`（system/tenant_admin/normal）：seed admin=system、注册=tenant_admin、normal 无创建入口、paid 不做；阶段三 1:1 迁 `sys_role`。
- 【已确认】存量受控接口本阶段**全量需登录**（公开仅 auth/health）。
- 第三方 OAuth 仅前端占位 + 后端路由占位（不实现）。

### 10.3 待确认项（非阻塞，已给默认，开发中可定）
1. **图形验证码触发时机**：始终显示 vs 仅登录失败 N 次后显示？**已定：失败达阈值后显示**（减少正常用户摩擦，对齐 R15）。落地（Codex 再审整改）：`public-config` 下发 `captcha_after_fails`，前端按 `loginFails >= captcha_after_fails` 显示，与后端 `login()` 强制阈值精确对齐（此前前端失败一次即显示，虽非安全缺口但与口径偏差，已修）。
2. **登录页前端契约**：已核实 `pageRegistry.spec.ts` 仅校验 registry 页（登录页非 registry 不纳入，无需排除）、`layout-contract.spec.ts` 扫 `src/views` 卡 vh/`.v-page`（LoginView 按 §4.6 契约实现即过）。倾向：**无需改测试/无需豁免**，T8/T10 跑通确认即可。

---

## 11. 里程碑与验收

**阶段二完成 = 同时满足**（对齐需求 12 章里程碑「可登录、受控接口需 token、未登录跳登录页」）：
1. 可登录/登出/刷新/`/me`，JWT 携带 user_id/tenant_id/role/perm_ver，登出旧 token 失效（**Redis fail-closed 保证**）（R4）。
2. 非白名单接口无有效 token 一律 401（**中间件机制性默认 deny + 路由扫描测试兜底**）；**系统级接口非 system 角色 403**（R8 最小切片，闭合注册越权）；上下文可被资产仓库读取，**请求链缺上下文报错不回落 admin**（R7）。
3. 密码哈希、登录失败锁定、接口限流 429、安全头、图形验证码生效；**R16 开关默认值=邮箱码开/图形码关**（R15/R16 基础）。
4. 自助注册自动建租户并成为租户管理员（role_code=tenant_admin）（R5）。
5. 前端：未登录跳 `/login`、登录回原路由、顶栏用户区/退出、401/403/429 统一处理；**/me 菜单/功能码空、SideMenu 仍静态**（R20 骨架 + §4.7 兼容）。
6. 登录/注册页：科技风 + 黑白双主题 + 第三方占位，符合原型 [../prototypes/login.html](../prototypes/login.html) 与 7.1 验收；满足 §4.6 页面设计闭环（无整页滚动、关键视口可用、登录页不误入 registry/§9）。
7. 全量 `pytest` 绿 + `npm run build` 通过 + 前端契约测试（`pageRegistry.spec.ts`/`layout-contract.spec.ts`）仍绿；CLAUDE.md 同步认证契约。

达成后进入**阶段三（RBAC 与租户管理）**：补 `sys_role/sys_menu/sys_resource/sys_user_role/...` 与管理页、接口级/按钮级校验、菜单数据化、`role_code`→关联表迁移、数据隔离上下文全量透传。
