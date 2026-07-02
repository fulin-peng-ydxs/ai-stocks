# 开发计划 · 多租户 RBAC 阶段三（RBAC 与租户管理）

## 1. 需求来源与目标

- **需求文档**：[../requirement.md](../requirement.md)（§12 阶段三；§5 详细需求 R8–R14；§7.4–7.7 页面条目 + 原型）。
- **页面原型**（需求阶段已敲定，本计划只承接、不重画）：
  - [../prototypes/user-management.html](../prototypes/user-management.html)（R10）
  - [../prototypes/role-management.html](../prototypes/role-management.html)（R11，master-detail 权限树）
  - [../prototypes/menu-resource-management.html](../prototypes/menu-resource-management.html)（R12+R13 合页，含 EP 图标选择器）
  - [../prototypes/tenant-management.html](../prototypes/tenant-management.html)（R14）
- **功能目标**：把阶段二"仅登录即放行 + system 粗守卫"升级为**数据化 RBAC**——用户/角色/菜单/功能/租户全套管理页 + **接口级 `require_perm(resource_code)` + 按钮级 `v-permission`** + 数据隔离全量透传；菜单从前端硬编码 `menuConfig` 迁后端数据化，SideMenu 消费后端菜单 + 权限过滤。
- **本次不做**（明确边界，防蔓延）：
  - **存量 13 路由全量接 resource code → 阶段四（R21）**；本阶段只建机制 + 用在新管理接口，存量维持现有 `require_system` 不动。
  - 审计（R17）/ 数据字典（R18）/ 配置管理拆父子菜单（R19）/ 注册防滥用开关页（R16）→ **阶段五**。
  - 租户管理员**自建角色**（R11 遗留项 5）→ 本期仅分配系统预设角色。
  - 付费角色**创建入口** → 仅预留 `paid` 角色类型。
- **计划输出目录**：`agent-works/multi-tenant-rbac/stage3-rbac-tenant/`（与 stage1/stage2 同级）。

## 2. 当前项目依据

阶段一（混合持久层）、阶段二（认证鉴权内核）已落地，本阶段在其上扩展。关键现状：

- **数据层**：`backend/storage/pg_ddl.py` 现有 `sys_tenant` + `sys_user`（`role_code` **单列**：system/tenant_admin/normal，`perm_ver`、`password_hash`）。**无** sys_role/sys_menu/sys_resource/sys_user_role。`init_pg_db()` 启动幂等建表 + `seed_default_tenant()` seed 默认租户/admin。
- **认证内核**（`backend/auth/`）：
  - `jwt_tokens.py`：claims = `sub/tenant_id/role(单)/perm_ver/typ/jti/iat/exp`。
  - `context.py`：`AuthContext`（含 `role`）+ `get_current_owner()`（请求链缺上下文抛错、不回落）+ `system_context()`。
  - `deps.py`：`require_system()` 判 `ctx.role==ROLE_SYSTEM`。
  - `middleware.py`：纯 ASGI `AuthMiddleware`（默认 deny，白名单 health+auth/*，注上下文）+ `SecurityMiddleware`。
  - `session_store.py`：Redis `auth:*`/`rl:*`，`cache_perm_ver/get_cached_perm_ver`、`_critical` fail-closed。
  - `services/auth_service.py`：`me()` 返回 `{user,tenant,role,menus:[],permissions:[]}`（menus/permissions 空占位，**本阶段填充**）。
- **归属守卫**（阶段二铁律，本阶段延续）：资产读写经 `get_current_owner()`；`main.py` 对 data_admin/data_tasks/config 写/layout 写/indicators 写挂 `require_system`。
- **前端**：`components/menuConfig.ts`（静态菜单树，icon=emoji）、`components/SideMenu.vue`（消费 menuConfig）、`stores/auth.ts`（menus/permissions 状态占位）、`api/auth.ts`（getMe）、`router/index.ts`（守卫仅判 token）。
- **UI 规范**：[../../../DESIGN.md](../../../DESIGN.md)（§4 弹窗/抽屉、表格；§5 LayoutHost/原型；§8 视口 1440 验收 + 宽表体内横滚）、[HelpTip.vue](../../../frontend/src/components/HelpTip.vue)、`layout-contract.spec.ts`/`pageRegistry.spec.ts` 契约测试。图标库 `@element-plus/icons-vue`（Element Plus 配套，已在依赖内）。
- **测试基线**：全量 `pytest` **273 passed**；前端 `vitest` 85 passed。

## 3. 实施范围

### 3.1 必须实现
- R8 接口级 + 按钮级 RBAC 校验（**机制 + 新管理接口**）。
- R9 数据归属与租户隔离**全量透传**（tenant_admin 数据域限本租户）。
- R10 用户管理（CRUD/启停锁定/重置密码/**多角色分配**/关联租户）。
- R11 角色管理（角色 CRUD + 勾选菜单&功能 + 内置角色 + 付费类型预留）。
- R12 菜单管理（菜单树后端数据化 CRUD + 排序 + EP 图标名）。
- R13 功能管理（菜单下功能点/资源登记：按钮 + 接口权限码）。
- R14 租户管理（租户 CRUD + 指定管理员 + 启停 + 查看用户）。
- R5 复用：注册建租户时绑定 tenant_admin 角色改走 sys_user_role（保持自动登录不变）。

### 3.2 可选增强（不改业务闭环，超工作量则移后续）
- 角色权限树"全选/清空/按分组批量"操作（原型已示意）。
- 菜单/功能"被引用影响面"预检提示（删除前显示引用它的角色数）。

### 3.3 暂不实现
- 存量 13 路由全量 resource code 接入（阶段四 R21）；审计/字典/配置拆页/开关页（阶段五）；租管自建角色、付费角色入口、字段级变更对比（R24）。

## 4. 技术方案

### 4.1 权限模型（数据化 RBAC）
新增 PG 平台表（自然键、**不带 tenant/owner 归属**，与阶段一"平台表用自然键"一致）：

| 表 | 主键 | 关键列 | 说明 |
| --- | --- | --- | --- |
| `sys_role` | `id` | code(唯一)/name/kind(system\|tenant_admin\|normal\|paid\|custom)/is_builtin/is_locked/description | 内置 3 角色 + 付费预留 + 自定义；`is_locked` 超管权限锁定 |
| `sys_menu` | `id` | parent_id/code(唯一)/title/type(group\|leaf)/route_path/icon(EP图标名)/sort/visible(login\|system)/is_builtin | 菜单树；`route_path` 叶子唯一且需匹配前端注册路由 |
| `sys_resource` | `id` | menu_id(FK)/code(全局唯一)/name/type(button\|api)/api_method/api_path | 功能点/资源，挂在菜单下；`code` 稳定不可复用 |
| `sys_user_role` | `(user_id, role_id)` | — | 用户↔角色多对多（R10 多角色，本期核心新增） |
| `sys_role_menu` | `(role_id, menu_id)` | — | 角色↔菜单授权 |
| `sys_role_resource` | `(role_id, resource_id)` | — | 角色↔功能点授权 |

- **role_code 去留【已确认】**：`sys_user.role_code` **保留**为兼容/兜底列（seed admin=system、注册=tenant_admin 仍写它，阶段二读它的代码不破）；权限解析**以 sys_user_role 为准**，role_code 仅作主角色展示/兜底。
- **seed**：内置 3 角色（system 全量 + is_locked、tenant_admin、normal）+ 付费 paid（预留）；菜单树按现 `menuConfig` 结构 seed（含新增「系统管理→权限管理」子组 4 叶子）+ emoji→EP 图标名映射；功能点按各页关键动作 seed。迁移：为存量 sys_user 按 role_code 补写一条 sys_user_role。

### 4.2 权限解析与令牌【已确认：瘦令牌 + 服务端解析 + Redis 缓存】
- **JWT 瘦身**：claims 去掉 `role`，保留 `sub/tenant_id/perm_ver/typ/jti`。多角色不进令牌。
- **权限解析**（`backend/auth/perm_resolver.py` 新增）：`resolve(user_id) -> {roles:[code], is_system:bool, menus:[menu_code], resources:[resource_code], perm_ver}`——user→sys_user_role→roles→sys_role_menu/sys_role_resource 并集。
- **缓存**：Redis `auth:perms:{user_id}`（值含 perm_ver + 解析结果，TTL=access_ttl），`_critical` fail-closed。中间件在校验 token（含 stage2 的 perm_ver 比对）后，从缓存加载解析结果注入上下文；缓存缺失则实时解析并回写。
- **即时失效**：角色/授权/用户角色变更 → `bump_perm_ver` 相关用户 + 删 `auth:perms:{user_id}` 缓存。因 stage2 已有"token.perm_ver ≠ 当前 perm_ver → 401 重登"，故授权变更 = 受影响用户**强制重登**后拿到新权限（对齐 R11「保存后即时生效」口径）。
- **上下文改造**：`AuthContext` 由单 `role` 改为 `roles:[]` + `is_system` + `perms`(menus/resources set)；`system_context()` 设 is_system=True + 全量 perms。`get_current_owner()` 不变（仍取 tenant_id+user_id）。

### 4.3 鉴权守卫
- 新增依赖 `require_perm(resource_code)`（`deps.py`）：非 system 且 resource_code ∉ ctx.perms.resources → `ForbiddenError`(403)。
- `require_system()` **保留并兼容**：改判 `ctx.is_system`（system 角色恒真，绕过 resource 校验）。存量 13 路由的 `require_system` 挂载**不动**（阶段四再细化）。
- 新管理接口（用户/角色/菜单/功能/租户）挂 `require_perm("<code>")`（如 `user:list`/`role:save`/`menu:save`/`tenant:save`），system 恒通过、tenant_admin 按其角色授权。
- **路由扫描测试延续**（stage2 `test_all_controlled_get_routes_require_token`）：新管理路由默认受 AuthMiddleware 保护，额外断言其对无授权角色 403。

### 4.4 数据隔离全量透传（R9）
- 资产表隔离（阶段一/二已落地）不变。
- **平台管理表按角色域过滤**（本阶段新增）：用户/租户/审计类查询——**system 看全局，tenant_admin 限本租户**（`WHERE tenant_id = ctx.tenant_id`）。用户列表、租户"查看用户"均按此域过滤；写入校验 tenant_admin 不得跨租户、不得分配非预设角色。
- **前端传归属一律忽略**（阶段二铁律延续）：用户所属租户、角色归属取自上下文校验，不信任前端。

### 4.5 前端权限消费
- `/me` 填充 `menus`（后端菜单树，已按当前用户权限过滤）+ `permissions`（resource_code 列表）；`stores/auth.ts` 存之。
- **SideMenu 改造**：由消费静态 `menuConfig` 改为消费 `auth.menus`（后端下发、已过滤）；`menuConfig.ts` 降级为**前端兜底默认**（后端菜单拉取失败时用）。图标由 emoji 改为按图标名渲染 EP 图标组件。
- **`v-permission` 指令**（`frontend/src/directives/permission.ts` 新增）：`v-permission="'user:save'"` → 功能码不在 `auth.permissions` 则移除/禁用元素（按钮级）。
- **路由守卫增强**：`router/index.ts` beforeEach 在 token 基础上增加"目标路由对应菜单是否在 auth.menus"校验（无权访问 → 回首页/403 页），system 恒通过。

### 4.6 页面设计/维护闭环（DESIGN §5.2/§7.4）
4 个新增页均走 **LayoutHost + list/master-detail 原型**，登记 `pageRegistry.ts` + `router` + DESIGN §9；过 `layout-contract.spec.ts`（禁 vh/手写 .v-page）+ `pageRegistry.spec.ts`。视口对齐 DESIGN §8（1440 验收、宽表体内横滚、master-detail 窄屏横滚、弹窗自适应）——原型已在 560/700/1440 三档核验，实现照此。

### 4.7 页面 P4 技术实现：用户管理（承接 [user-management.html](../prototypes/user-management.html)）
| 页面功能点 | 需求 | 交互要点 | 技术实现 | 组件/模块 | 数据/API | 状态与异常 | 任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 列表查询/筛选/分页 | R10 | 租户(系统管理员)/角色/状态筛选 + 搜索 + 分页 | LayoutHost list；el-table 表体内滚(min-width 横滚)；服务端分页 | UserManageView、el-table、el-pagination | `GET /api/users`(分页/筛选，按域过滤) | loading/空/错误重试；租管只见本租户 | T5,T11 |
| 新建/编辑用户 | R10 | 账号/邮箱/**多角色**/租户/状态 | el-dialog 自适应；角色 el-select multiple(标签) | 编辑弹窗、el-select multiple | `POST /api/users`、`PUT /api/users/{id}`、`GET /api/roles` | 账号/邮箱唯一冲突；租管不可跨租户/非预设角色 | T5,T11 |
| 启停/锁定/重置密码/删除 | R10 | 行内操作随状态变 | 行操作调接口→刷新；重置密码弹窗指定新密码 | 行操作、重置弹窗 | `POST /api/users/{id}/status`、`/reset-password` | 禁用/锁定即时失效(bump perm_ver+黑名单)；删除自身/最后管理员阻止 | T5,T11 |

### 4.8 页面 P5 技术实现：角色管理（承接 [role-management.html](../prototypes/role-management.html)）
| 页面功能点 | 需求 | 交互要点 | 技术实现 | 组件/模块 | 数据/API | 状态与异常 | 任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 角色列表/CRUD | R11 | 左列表切换 + 新建/重命名 | master-detail 左栏；内置角色不可删、超管锁定 | RoleManageView、角色列表 | `GET/POST/PUT/DELETE /api/roles` | 角色名/code 唯一；删被引用角色阻止 | T6,T12 |
| 菜单&功能授权树 | R11 | 右栏 el-tree show-checkbox 三态勾选 | 菜单为父、功能点为叶；勾选存 role_menu/role_resource | el-tree、权限树 | `GET /api/menus`+`/api/resources`、`PUT /api/roles/{id}/perms` | 保存→bump 相关用户 perm_ver；超管树置灰 | T6,T12 |

### 4.9 页面 P6 技术实现：菜单与功能管理（承接 [menu-resource-management.html](../prototypes/menu-resource-management.html)）
| 页面功能点 | 需求 | 交互要点 | 技术实现 | 组件/模块 | 数据/API | 状态与异常 | 任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 菜单树 CRUD/排序 | R12 | 左树增删/拖拽排序、选中切右栏 | master-detail；el-tree draggable；节点属性表单 | MenuResourceView、el-tree | `GET/POST/PUT/DELETE /api/menus`、`POST /api/menus/reorder` | route_path 唯一且匹配前端路由；删有子节点级联确认 | T7,T13 |
| 图标选择 | R12 | 图标选择器（EP 图标库、可搜索网格） | icon 存图标名；选择器渲染 `@element-plus/icons-vue` | 图标选择器组件 | icon 字段随菜单保存 | 无匹配提示；空图标允许 | T7,T13 |
| 功能点登记 | R13 | 右下功能点表增删改（code/名称/类型/接口） | 功能表；类型 button/api | 功能点子表 | `GET/POST/PUT/DELETE /api/resources?menu_id=` | 功能码全局唯一不可复用；删被引用提示影响 | T8,T13 |

### 4.10 页面 P7 技术实现：租户管理（承接 [tenant-management.html](../prototypes/tenant-management.html)）
| 页面功能点 | 需求 | 交互要点 | 技术实现 | 组件/模块 | 数据/API | 状态与异常 | 任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 租户列表/CRUD/启停 | R14 | 列表 + 新建/编辑弹窗 + 行内启停 | LayoutHost list；编辑弹窗(名称/管理员/状态) | TenantManageView、el-table、弹窗 | `GET/POST/PUT /api/tenants`、`/status` | 默认租户不可删；停用→其下用户不可登录；删有用户租户阻止 | T9,T14 |
| 指定/变更管理员 | R14 | 从该租户用户中选管理员 | 管理员下拉取该租户用户 | 管理员选择 | `GET /api/users?tenant=` | 管理员须属该租户 | T9,T14 |
| 查看租户内用户 | R14 | 跳用户管理带租户过滤 | 路由跳转带 query | 路由 | 跳 `/system/users?tenant=` | — | T9,T14 |

## 5. 需求与开发内容映射和开发状态

| 需求编号 | 需求内容/来源 | 计划开发内容 | 对应任务 | 状态 | 偏差判断 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| R8 | 接口级+按钮级 RBAC 校验 | require_perm 机制 + v-permission 指令 + 新管理接口接入 | T2,T3,T4,T15 | 待开始 | 部分覆盖 | **存量13路由全量接入=阶段四R21**；本阶段=机制+新接口 |
| R9 | 数据归属与租户隔离全量透传 | tenant_admin 平台管理查询按本租户域过滤 + 写入归属校验 | T4,T5,T9,T16 | 待开始 | 一致 | 资产隔离阶段一/二已落地，本阶段补平台管理表域过滤 |
| R10 | 用户管理(CRUD/启停/重置/多角色/租户) | user API+repo + 用户管理页 | T5,T11 | 待开始 | 一致 | 多角色落 sys_user_role |
| R11 | 角色管理(CRUD+勾选菜单&功能+内置) | role API+repo + 角色管理页(权限树) | T6,T12 | 待开始 | 一致 | 租管仅分配不自建(遗留5) |
| R12 | 菜单管理(树数据化CRUD+排序+图标) | menu API+repo + 菜单页 + SideMenu 改造 | T7,T13,T15 | 待开始 | 一致 | icon 存 EP 图标名；menuConfig 降兜底 |
| R13 | 功能管理(资源登记) | resource API+repo + 功能点子表 | T8,T13 | 待开始 | 一致 | 与 R8 接口标注、R11 授权闭环 |
| R14 | 租户管理(CRUD+指定管理员+启停) | tenant API+repo + 租户管理页 | T9,T14 | 待开始 | 一致 | 默认租户保护 |
| R5 | 注册绑租管角色 | register 改写 sys_user_role(保留自动登录) | T5 | 待开始 | 一致 | 阶段二 register 已建租户，本阶段改角色绑定方式 |
| —(技术依赖) | 权限数据模型+seed+迁移 | sys_role/menu/resource/user_role/role_menu/role_resource | T1 | 待开始 | 超范围(必要技术依赖) | R8-R14 的数据底座，无独立 R 编号 |
| —(技术依赖) | 瘦令牌+权限解析缓存+上下文 | perm_resolver + Redis 缓存 + JWT/context 改造 | T2,T3 | 待开始 | 超范围(必要技术依赖) | 多角色权限运行时前提 |
| —(技术依赖) | /me 填充 + 前端权限消费底座 | /me menus+permissions + v-permission + SideMenu + 守卫 | T10,T15 | 待开始 | 超范围(必要技术依赖) | R8 按钮级/R12 菜单渲染前端前提 |

## 6. 详细实施步骤与进度追踪

> 顺序按依赖：**内核先行**（T1 数据模型 → T2 权限解析缓存 → T3 瘦令牌/上下文 → T4 守卫）→ **后端 API**（T5–T9）→ T10 /me 填充 → **前端页**（T11–T14 + T15 权限消费底座）→ T16 隔离核查 → T17 测试+文档。

### 6.1 任务 T1：权限数据模型 + seed + role_code 迁移
- 状态：待开始
- 依赖：无（阶段一/二数据层已就绪）
- 涉及文件/模块：`backend/storage/pg_ddl.py`、`stage3-rbac-tenant/rbac-schema.sql`（产出）
- 目标：建 6 张 RBAC 表 + seed 内置角色/菜单树/功能点 + 存量 sys_user 补 sys_user_role。
- 操作：`init_pg_db` 幂等建 sys_role/sys_menu/sys_resource/sys_user_role/sys_role_menu/sys_role_resource（复合主键见 §4.1）；扩 `seed_default_tenant`/新增 `seed_rbac`：内置 3 角色(+paid)、菜单树(按 menuConfig + 权限管理子组、emoji→EP 图标名)、各页功能点、system 角色全授权+is_locked、存量用户按 role_code 补 sys_user_role。
- 产出：6 表 + seed + SQL 留痕文件。
- 影响范围：仅新增平台表；不动资产表与行情 DuckDB；`sys_user.role_code` 保留。
- 边界与异常：幂等（IF NOT EXISTS + ON CONFLICT DO NOTHING）；seed 只在缺失时写、不覆盖既有授权。
- 验证方式：启动 `init_pg_db` 无错；`python -m backend.cli health` 通过；PG 查 6 表存在 + 内置角色/菜单/功能点行数符合预期。
- 完成标准：表 + seed 就绪，存量用户各有 sys_user_role，admin=system 全授权。

### 6.2 任务 T2：权限解析与 Redis 缓存
- 状态：待开始
- 依赖：T1
- 涉及文件/模块：`backend/auth/perm_resolver.py`(新)、`backend/auth/session_store.py`
- 目标：user → 多角色 → 菜单/功能并集解析 + 按 perm_ver 缓存 + 失效。
- 操作：`resolve(user_id)` 返回 `{roles,is_system,menus,resources,perm_ver}`；`session_store` 加 `cache_perms/get_cached_perms/clear_perms`（`auth:perms:{user_id}`，`_critical` fail-closed）；`bump_and_invalidate(user_ids)`（perm_ver+1 + 清缓存），供角色/授权/用户角色变更调用。
- 产出：解析器 + 缓存读写/失效。
- 影响范围：新增模块 + session_store 扩展。
- 边界与异常：Redis 故障 fail-closed(503)；缓存缺失实时解析回写；system 角色解析为全量 perms。
- 验证方式：单测——多角色并集正确；bump 后缓存清空 + 重解析；Redis 故障抛 ServiceUnavailableError。
- 完成标准：解析/缓存/失效可用且有单测。

### 6.3 任务 T3：JWT 瘦令牌 + 上下文/中间件改造
- 状态：待开始
- 依赖：T2
- 涉及文件/模块：`backend/auth/jwt_tokens.py`、`context.py`、`middleware.py`、`services/auth_service.py`
- 目标：令牌去 role；上下文携带 roles+is_system+perms；中间件按缓存注权限。
- 操作：`_issue` 去 `role` claim（保留 sub/tenant_id/perm_ver/typ/jti）；`AuthContext` 改为 roles/is_system/perms；`AuthMiddleware` 校验 token(含 perm_ver 比对) 后从 `get_cached_perms` 或实时解析注上下文；`auth_service` 签发处不再传 role。`system_context()` 设 is_system+全量 perms。
- 产出：瘦令牌 + 富上下文 + 中间件注权限。
- 影响范围：令牌契约变更（旧 token 失效需重登，属发布注意点）；上下文 API 变更（`ctx.role`→`ctx.roles`/`is_system`）。
- 边界与异常：CLI/后台经 system_context 仍全权；请求链缺上下文抛错(不回落)延续。
- 验证方式：单测——令牌无 role claim；中间件注入 perms；system 恒 is_system。回归 stage2 中间件用例（改 role→is_system 断言）。
- 完成标准：瘦令牌链路通，stage2 鉴权回归绿。

### 6.4 任务 T4：require_perm 守卫 + require_system 兼容
- 状态：待开始
- 依赖：T3
- 涉及文件/模块：`backend/auth/deps.py`
- 目标：resource-code 级依赖 + 兼容 require_system。
- 操作：`require_perm(code)` 依赖工厂（system 恒过；否则 code ∉ ctx.perms.resources → 403）；`require_system` 改判 `ctx.is_system`。存量路由 require_system 挂载不动。
- 产出：require_perm + 兼容 require_system。
- 影响范围：deps；新管理接口用 require_perm。
- 边界与异常：无上下文→401；非 system 无码→403。
- 验证方式：单测——system 通过、授权角色通过、无授权 403、无 token 401。
- 完成标准：两守卫可用且有单测。

### 6.5 任务 T5：用户管理 API + 仓库（R10）
- 状态：待开始
- 依赖：T4
- 涉及文件/模块：`backend/api/users.py`(新)、`backend/storage/user_repository.py`(扩)、`main.py`(挂 router)
- 目标：用户 CRUD/启停锁定/重置密码/多角色/租户，按域过滤。
- 操作：`GET /api/users`(分页/筛选，system 全局、tenant_admin 限本租户)、`POST/PUT /api/users`、`POST /api/users/{id}/status`(启停锁定→bump perm_ver+黑名单)、`POST /api/users/{id}/reset-password`、多角色写 sys_user_role；均挂 `require_perm("user:*")`；写入校验 tenant_admin 不跨租户/仅预设角色；register 改走 sys_user_role。
- 产出：用户管理接口 + 仓库方法。
- 影响范围：新 router；user_repository 扩多角色/域过滤。
- 边界与异常：账号/邮箱唯一；删自身/最后管理员阻止；禁用即时失效。
- 验证方式：接口测试——CRUD、多角色、域隔离(租管看不到他租户用户)、启停即时失效、唯一冲突。
- 完成标准：R10 功能点全通过 + 隔离回归。

### 6.6 任务 T6：角色管理 API + 仓库（R11）
- 状态：待开始
- 依赖：T4
- 涉及文件/模块：`backend/api/roles.py`(新)、`backend/storage/role_repository.py`(新)
- 目标：角色 CRUD + 菜单&功能授权 + 内置保护 + 授权即时生效。
- 操作：`GET/POST/PUT/DELETE /api/roles`、`PUT /api/roles/{id}/perms`(写 role_menu/role_resource + bump 相关用户 perm_ver)；内置角色不可删、超管 is_locked 不可改权；挂 `require_perm("role:*")`。
- 产出：角色接口 + 仓库。
- 边界与异常：角色名/code 唯一；删被 sys_user_role 引用角色阻止；超管锁定。
- 验证方式：接口测试——角色 CRUD、授权保存、内置保护、授权后相关用户 perm_ver 自增(下次请求 401 重登)。
- 完成标准：R11 功能点全通过。

### 6.7 任务 T7：菜单管理 API + 仓库（R12）
- 状态：待开始
- 依赖：T4
- 涉及文件/模块：`backend/api/menus.py`(新)、`backend/storage/menu_repository.py`(新)
- 目标：菜单树 CRUD + 排序 + 图标名。
- 操作：`GET /api/menus`(树)、`POST/PUT/DELETE /api/menus`、`POST /api/menus/reorder`；icon 存 EP 图标名；挂 `require_perm("menu:*")`。
- 边界与异常：route_path 唯一且匹配前端注册路由(非法告警)；删有子节点级联确认；删被角色引用菜单提示影响。
- 验证方式：接口测试——树 CRUD、排序、唯一校验、级联保护。
- 完成标准：R12 功能点全通过。

### 6.8 任务 T8：功能管理 API + 仓库（R13）
- 状态：待开始
- 依赖：T4,T7
- 涉及文件/模块：`backend/api/resources.py`(新)、`backend/storage/resource_repository.py`(新)
- 目标：菜单下功能点/资源登记。
- 操作：`GET/POST/PUT/DELETE /api/resources?menu_id=`；type button/api，api 类带 method+path；挂 `require_perm("resource:*")`。
- 边界与异常：功能码全局唯一不可复用；删被角色引用功能点提示影响。
- 验证方式：接口测试——CRUD、唯一、引用保护、可被角色勾选。
- 完成标准：R13 功能点全通过。

### 6.9 任务 T9：租户管理 API + 仓库（R14）
- 状态：待开始
- 依赖：T4,T5
- 涉及文件/模块：`backend/api/tenants.py`(新)、`backend/storage/tenant_repository.py`(新)
- 目标：租户 CRUD + 指定管理员 + 启停。
- 操作：`GET/POST/PUT /api/tenants`、`POST /api/tenants/{id}/status`；挂 `require_perm("tenant:*")`（仅 system）；指定管理员须属该租户。
- 边界与异常：默认/平台租户不可删；停用→其下用户不可登录(登录校验租户 status)；删有用户租户阻止。
- 验证方式：接口测试——CRUD、启停、默认租户保护、停用后该租户用户登录被拒。
- 完成标准：R14 功能点全通过。

### 6.10 任务 T10：/me 填充 + 权限公开消费
- 状态：待开始
- 依赖：T2,T7,T8
- 涉及文件/模块：`backend/services/auth_service.py`
- 目标：/me 返回按权限过滤的菜单树 + 功能码列表。
- 操作：`me()` 调 perm_resolver + menu_repository 返回 `menus`(按 ctx.perms 过滤的树) + `permissions`(resource_code 列表)；role 字段改 roles/主角色。
- 产出：/me 富返回。
- 边界与异常：菜单按可见性(login/system)+角色授权双过滤；system 全量。
- 验证方式：接口测试——system 全菜单、tenant_admin 过滤后菜单、permissions 准确。
- 完成标准：前端可据 /me 渲染菜单 + 控按钮。

### 6.11 任务 T11：前端 用户管理页（P4）
- 状态：待开始
- 依赖：T5,T10
- 涉及文件/模块：`frontend/src/views/system/UserManageView.vue`(新)、`api/user.ts`(新)、`router`、`pageRegistry.ts`、`DESIGN.md §9`
- 目标：承接 [user-management.html](../prototypes/user-management.html) 实现（§4.7 功能点表）。
- 操作：LayoutHost list；筛选/搜索/分页；多角色 el-select multiple；编辑/重置弹窗自适应；行操作随状态；`v-permission` 控按钮。
- 影响范围：新页面 + 路由 `/system/users` + registry/DESIGN 登记；`npm run build`。
- 边界与异常：空/加载/错误/无权状态；窄视口表格体内横滚（对齐原型）。
- 验证方式：preview 5181 截图 light/dark + 交互；`layout-contract`/`pageRegistry` 绿；`npm run build`。
- 完成标准：7.4 功能点验收 + §4.6 页面闭环。

### 6.12 任务 T12：前端 角色管理页（P5）
- 状态：待开始
- 依赖：T6,T7,T8,T10
- 涉及文件/模块：`frontend/src/views/system/RoleManageView.vue`(新)、`api/role.ts`(新)、路由/registry/DESIGN
- 目标：承接 [role-management.html](../prototypes/role-management.html)（master-detail + el-tree 三态权限树，§4.8）。
- 操作：左角色列表 + 右 el-tree show-checkbox；勾选保存→PUT perms；内置保护/超管置灰；master-detail 窄屏横滚。
- 验证方式：preview 双主题 + 勾选保存 + 内置保护；契约绿；build。
- 完成标准：7.5 功能点验收 + 页面闭环。

### 6.13 任务 T13：前端 菜单与功能页（P6，含 EP 图标选择器）
- 状态：待开始
- 依赖：T7,T8,T10
- 涉及文件/模块：`frontend/src/views/system/MenuResourceView.vue`(新)、`components/IconPicker.vue`(新)、`api/menu.ts`(新)、路由/registry/DESIGN
- 目标：承接 [menu-resource-management.html](../prototypes/menu-resource-management.html)（§4.9）。
- 操作：左 el-tree draggable 菜单树 + 右属性表单(含 IconPicker 消费 `@element-plus/icons-vue`) + 功能点子表增删；IconPicker 可搜索网格。
- 边界与异常：route_path 唯一校验；图标名渲染；功能表窄屏体内横滚。
- 验证方式：preview 双主题 + 图标选择/搜索 + 树增删排序 + 功能点增删；契约绿；build。
- 完成标准：7.6 功能点验收 + 页面闭环。

### 6.14 任务 T14：前端 租户管理页（P7）
- 状态：待开始
- 依赖：T9,T10
- 涉及文件/模块：`frontend/src/views/system/TenantManageView.vue`(新)、`api/tenant.ts`(新)、路由/registry/DESIGN
- 目标：承接 [tenant-management.html](../prototypes/tenant-management.html)（§4.10）。
- 操作：LayoutHost list + 编辑弹窗 + 行内启停 + 查看用户跳转；默认租户删除置灰。
- 验证方式：preview 双主题 + 启停 + 跳转带过滤；契约绿；build。
- 完成标准：7.7 功能点验收 + 页面闭环。

### 6.15 任务 T15：前端权限消费底座（v-permission + SideMenu + 守卫）
- 状态：待开始
- 依赖：T10
- 涉及文件/模块：`frontend/src/directives/permission.ts`(新)、`components/SideMenu.vue`、`components/menuConfig.ts`、`stores/auth.ts`、`router/index.ts`、`main.ts`(注册指令)
- 目标：按钮级指令 + 菜单后端化 + 路由守卫增强。
- 操作：`v-permission` 指令消费 `auth.permissions`；SideMenu 消费 `auth.menus`(EP 图标名渲染)、menuConfig 降兜底；`fetchMe` 后填充；beforeEach 增菜单权限校验(system 恒过)。
- 影响范围：跨页面横切（所有页可用指令）；SideMenu 渲染源切换。
- 边界与异常：/me 失败→用 menuConfig 兜底 + 告警；无权路由→回首页。
- 验证方式：单测/组件测——指令无码时移除元素；SideMenu 按 menus 渲染；无权路由拦截。preview 验证。
- 完成标准：按钮/菜单按权限显隐，system 全见。

### 6.16 任务 T16：数据隔离全量透传核查
- 状态：待开始
- 依赖：T5,T6,T9
- 涉及文件/模块：新管理仓库 + 测试
- 目标：确认平台管理查询/写入按角色域正确隔离，无跨租户泄漏。
- 操作：脚本/测试核查用户/租户/角色管理每条 SQL 的域过滤（system 全局、tenant_admin 本租户）；多账号交叉验证。
- 产出：隔离核查结论 + 回归用例。
- 验证方式：多账号交叉测试——tenant_admin A 看不到/改不到 tenant B 的用户；跨租户分配被拒。
- 完成标准：R9 里程碑"多账号交叉验证隔离"达成。

### 6.17 任务 T17：测试 + 文档治理 + 页面闭环收尾
- 状态：待开始
- 依赖：T1–T16
- 涉及文件/模块：`backend/tests/test_rbac_*.py`、前端契约测试、`CLAUDE.md`、本目录文档、`../requirement.md`、`DESIGN.md §9`
- 目标：质量门槛 + 契约文档同步 + 闭环收尾。
- 操作：补单测/接口测/权限测/隔离测/回归；全量 `pytest` 绿 + `npm run build` + 前端契约绿；CLAUDE.md「认证与鉴权」补 RBAC 数据化/require_perm/瘦令牌/多角色/菜单后端化约定；requirement §12 阶段三标完成 + 本目录 plan 状态回填；4 页登记 DESIGN §9。
- 验证方式：CI/本地全绿；§4.6 闭环项逐条满足。
- 完成标准：阶段三里程碑（§11）达成。

## 7. 数据库与 SQL 计划

- **SQL 文件路径**：`agent-works/multi-tenant-rbac/stage3-rbac-tenant/rbac-schema.sql`（T1 产出，人读留痕 + 手工补执行兜底）。
- **用途**：建 sys_role/sys_menu/sys_resource/sys_user_role/sys_role_menu/sys_role_resource 六表（复合主键见 §4.1）+ seed 内置角色/菜单树/功能点 + 存量 sys_user 补 sys_user_role。
- **执行时机**：随 `init_pg_db()` 启动幂等执行（`CREATE TABLE IF NOT EXISTS` + seed `ON CONFLICT DO NOTHING`）。
- **影响范围**：仅新增平台表；不动资产表、行情 DuckDB、`sys_user.role_code`（保留）。
- **回滚方式**：新增表为 additive，回滚 `DROP TABLE` 六表即可（`role_code` 仍在，权限退回阶段二 system 粗守卫）；**无不可逆点**。

## 8. 测试与验证计划

- **单元测试**：perm_resolver 多角色并集/system 全量；瘦令牌无 role claim；require_perm(system过/授权过/无权403/无token401)；bump 后缓存失效重解析；Redis 故障 fail-closed。
- **接口测试**：用户 CRUD/多角色/启停即时失效/唯一冲突；角色 CRUD/授权/内置保护/授权后 perm_ver 自增；菜单树 CRUD/排序/唯一/级联；功能点 CRUD/唯一/引用保护；租户 CRUD/启停/默认保护/停用后登录被拒；/me 按角色过滤菜单+功能码。
- **页面/交互测试**：4 页 preview 5181 双主题截图 + 交互；承接原型主要区域/操作/状态/窄视口退化（对齐已核验的 560/700/1440）。
- **权限与数据范围测试**：**多账号交叉**——tenant_admin A 看不到/改不到 tenant B 数据；跨租户分配被拒；按钮/菜单按角色显隐；system 全见。
- **回归测试**：全量 `pytest`（273 基线 + 新增）；stage2 鉴权用例改 role→is_system 后绿；`npm run build`；前端 `layout-contract`/`pageRegistry` 绿。
- **图示与原型一致性验证**：4 页实现匹配对应 `prototypes/*.html` 的区域/入口/状态/响应式。
- **需求映射验证**：§5 每个本期 R 项有任务+状态+可观察验证；超范围三项（数据模型/瘦令牌/前端底座）标注为必要技术依赖。
- **页面功能点验证**：7.4–7.7 各功能点均有技术实现+任务+异常处理。
- **视觉验证**：preview 端口 5181 双主题（禁占用 5173）。

## 9. 发布与回滚

- **发布前检查**：环境变量（`AI_STOCKS_JWT_SECRET` 等）就绪；PG/Redis 运行；`init_pg_db` 已建 6 表 + seed；`npm run build` 产物同步。**⚠️ 令牌契约变更（去 role）**：发布后**存量 token 全部失效**，所有在线用户需重登（属预期，非缺陷）。
- **发布步骤**：部署后端（自动建表 + seed）→ 重启 → 验证可登录 + 权限生效 → 部署前端产物。
- **配置或环境变量**：无新增必填环境变量。
- **回滚方案**：前端回退到 stage2 构建（静态 menuConfig + 无 v-permission）；后端 6 表 additive 可保留或 DROP，`role_code` 仍在 → 权限退回阶段二 system 粗守卫。**无不可逆点**（区别于阶段一 R3）。

## 10. 风险、假设与待确认项

### 10.1 风险
- **令牌契约变更影响面**（中）：去 role claim → 存量 token 失效需重登；上下文 `ctx.role`→`ctx.roles/is_system` 需改所有引用点。应对：T3 全量替换 + stage2 回归用例同步；发布公告重登。
- **权限即时生效 = 强制重登**（低-中）：授权变更经 perm_ver bump → 受影响用户当前 token 401 重登才拿到新权限（非无感刷新）。已对齐 R11「即时生效」口径，但需产品认可"重登"体验。已列待确认项 1。
- **菜单数据化后 route_path 与前端路由错配**（中）：后端菜单 route 若与前端注册路由不一致 → 菜单点击空白。应对：T7 保存时校验 route_path ∈ 前端已注册路由集（前端可提供路由清单校验接口或前端侧校验）+ menuConfig 兜底。
- **隔离回归（平台管理表新面）**（中·阶段一血泪）：用户/租户/角色查询新增，易漏 tenant 域过滤致跨租户泄漏。应对：T16 多账号交叉测试 + 每条管理 SQL 域过滤自审（延续阶段一铁律）。
- **seed 菜单/功能点与实际页面漂移**（低）：seed 的菜单树/功能码需与前端路由/按钮对齐。应对：T1 seed 以 menuConfig + 4 原型功能点为准，T17 对账。

### 10.2 假设
- 沿用阶段二 perm_ver 即时失效语义（授权变更 = bump + 强制重登），不引入无感权限热更新。
- 菜单可见性两档（login 可见 / system-only）够用；更细可见性留后续。
- `@element-plus/icons-vue` 已在前端依赖内（Element Plus 配套），无需新增依赖。
- tenant_admin 数据域 = 本租户（R10/R17 已确认口径），system = 全局。

### 10.3 待确认项（非阻塞，已给默认，开发中可定）
1. **授权变更的生效体验**：强制重登（默认，对齐 perm_ver 语义）vs 无感刷新（需前端轮询/推送 + 复杂化）。倾向：**强制重登**，公告告知。
2. **route_path 校验来源**：前端暴露已注册路由清单给后端校验 vs 仅前端保存时校验。倾向：**前端侧校验 + 后端存字符串**（轻量），非法给告警不强阻。
3. **菜单删除/停用对在线用户**：删除被引用菜单是否级联清 role_menu。倾向：**阻止删除并提示先解绑**（安全优先）。

## 11. 里程碑与验收

**阶段三完成 = 同时满足**（对齐需求 §12 阶段三里程碑「多账号交叉验证隔离与授权即时生效」）：
1. 6 张 RBAC 表 + seed 就绪；存量用户平滑迁 sys_user_role；role_code 兼容保留（R8 底座）。
2. 瘦令牌 + 服务端权限解析 + Redis 缓存 + perm_ver 即时失效；`require_perm(resource_code)` 接口级守卫用在新管理接口（R8 机制）。
3. 用户/角色/菜单+功能/租户 4 套管理接口 + 4 个前端页（承接原型、过契约、双主题、视口达标）（R10–R14）。
4. `v-permission` 按钮级 + SideMenu 消费后端菜单（EP 图标）+ /me 填充 menus/permissions + 路由守卫按菜单（R8/R12 前端）。
5. **多账号交叉验证**：tenant_admin 限本租户、跨租户不可见/不可改；授权变更后相关用户重登即生效（R9/R11 里程碑）。
6. 全量 `pytest` 绿 + `npm run build` + 前端契约（`layout-contract`/`pageRegistry`）绿；CLAUDE.md 同步 RBAC 契约；requirement §12 阶段三标完成。

达成后进入**阶段四（存量功能全量接入 R21）**：现有 13 路由逐一接 resource code + 隔离；再阶段五（审计/字典/配置拆页/开关页 R16–R19）。
