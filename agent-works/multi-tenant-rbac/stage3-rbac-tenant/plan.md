# 开发计划 · 多租户 RBAC 阶段三（RBAC 与租户管理）

> 本版已按 Codex 计划评审整改（精确权限码 / 系统级接口硬守卫 / R9 边界拆分 / 菜单资源缓存失效 / 菜单兜底 fail-closed / DB 索引 FK 回滚细化 / 逐页页面设计闭环 + 维护矩阵 / 官方视口三档 / 原型操作不降级）。已确认决策：**授权变更 = perm_ver bump → 强制重登**；**用户表本期不做批量、去勾选列**。

## 1. 需求来源与目标

- **需求文档**：[../requirement.md](../requirement.md)（§12 阶段三；§5 详细需求 R8–R14；§7.3–7.7 页面条目 + 原型）。
- **页面原型**（需求阶段已敲定，本计划只承接、不重画）：
  - [../prototypes/user-management.html](../prototypes/user-management.html)（R10）
  - [../prototypes/role-management.html](../prototypes/role-management.html)（R11，master-detail 权限树）
  - [../prototypes/menu-resource-management.html](../prototypes/menu-resource-management.html)（R12+R13 合页，含 EP 图标选择器）
  - [../prototypes/tenant-management.html](../prototypes/tenant-management.html)（R14）
- **功能目标**：把阶段二"仅登录即放行 + system 粗守卫"升级为**数据化 RBAC**——用户/角色/菜单/功能/租户全套管理页 + **接口级 `require_perm(resource_code)` + 按钮级 `v-permission`** + 数据隔离全量透传；菜单从前端硬编码 `menuConfig` 迁后端数据化，SideMenu 消费后端菜单 + 权限过滤。
- **本次不做**（明确边界，防蔓延）：
  - **存量 13 业务路由全量接 resource code → 阶段四（R21）**；本阶段只建机制 + 用在新管理接口。
  - 审计（R17）/ 数据字典（R18）/ 配置拆父子菜单（R19）/ 注册防滥用开关页（R16）→ **阶段五**。
  - 租户管理员**自建角色**（R11 遗留 5）→ 仅分配系统预设角色；付费角色**创建入口** → 仅预留 `paid` 类型。
  - 用户/租户表**批量操作**（R10/R14 未提）→ 去勾选列、不做批量工具条。
- **计划输出目录**：`agent-works/multi-tenant-rbac/stage3-rbac-tenant/`。

## 2. 当前项目依据

阶段一（混合持久层）、阶段二（认证鉴权内核）已落地。关键现状：

- **数据层** `backend/storage/pg_ddl.py`：现有 `sys_tenant` + `sys_user`（`role_code` **单列**、`perm_ver`、`password_hash`）。**无** sys_role/menu/resource/user_role。`init_pg_db()` 幂等建表 + `seed_default_tenant()`。
- **认证内核** `backend/auth/`：`jwt_tokens`（claims=sub/tenant_id/**role(单)**/perm_ver/typ/jti）、`context`（`AuthContext.role` + `get_current_owner()` 缺上下文抛错、`system_context()`）、`deps.require_system()`（判 ctx.role==system）、`middleware.AuthMiddleware`（默认 deny、白名单 health+auth/*、注上下文）、`session_store`（Redis auth:*/rl:*、`cache_perm_ver`、`_critical` fail-closed）、`services/auth_service.me()`（menus/permissions **空占位**）。
- **归属守卫**（阶段二铁律延续）：资产经 `get_current_owner()`；`main.py` 对 data_admin/data_tasks/config 写/layout 写/indicators 写挂 `require_system`。
- **前端**：`components/menuConfig.ts`（静态菜单树 icon=emoji）、`SideMenu.vue`（消费 menuConfig）、`stores/auth.ts`（menus/permissions 占位）、`api/auth.ts`（getMe）、`router/index.ts`（守卫仅判 token）。
- **UI 规范**：[../../../DESIGN.md](../../../DESIGN.md)（§4 弹窗/抽屉/表格；§5 LayoutHost/原型/维护矩阵；§8 视口 + 宽表体内横滚；§9 页面登记）、[page-template.md](../../configurable-layout-system/page-template.md)（页面模板 + 验收视口 1100×620/1366×768/1440×900 + 维护矩阵）、[HelpTip.vue](../../../frontend/src/components/HelpTip.vue)、`layout-contract.spec.ts`/`pageRegistry.spec.ts`。图标库 `@element-plus/icons-vue`（Element Plus 配套，已在依赖）。
- **测试基线**：`pytest` **273 passed**；`vitest` 85 passed。

## 3. 实施范围

### 3.1 必须实现
- R8 接口级 + 按钮级 RBAC 校验（**机制 + 新管理接口**）。
- R9 数据隔离**全量透传**（平台管理表按角色域过滤 + 交叉验证；资产隔离已由阶段一/二完成，本阶段回归复核）。
- R10 用户管理（CRUD/启停锁定/重置密码/**多角色**/关联租户）。
- R11 角色管理（角色 CRUD + 勾选菜单&功能 + 内置角色 + 付费预留 + **全选/清空/还原/保存并刷新权限**）。← 全选/清空/还原为原型确认操作，**必做**（非可选）。
- R12 菜单管理（树数据化 CRUD + 排序 + EP 图标名）。
- R13 功能管理（菜单下功能点/资源登记）。
- R14 租户管理（CRUD + 指定管理员 + 启停 + 查看用户）。
- R5 复用：注册绑 tenant_admin 角色改走 sys_user_role（保持自动登录）。

### 3.2 可选增强（不改闭环，超工作量则移后续）
- 菜单/功能"被引用影响面"预检（删除前显示引用它的角色数）。
- 角色权限树"按分组批量勾选"快捷（原型已示意分组勾选，全选/清空已在必做）。

### 3.3 暂不实现
- 存量 13 路由全量 resource code（阶段四 R21）；审计/字典/配置拆页/开关页（阶段五）；租管自建角色、付费角色入口、字段级变更对比、用户/租户批量操作。

## 4. 技术方案

### 4.1 权限模型（数据化 RBAC）
新增 PG 平台表（自然键、不带 tenant/owner 归属，与阶段一"平台表用自然键"一致）：

| 表 | 主键 | 关键列 | 索引 / FK |
| --- | --- | --- | --- |
| `sys_role` | `id` | code(唯一)/name/kind/is_builtin/is_locked/description | UNIQUE(code) |
| `sys_menu` | `id` | parent_id/code(唯一)/title/type(group\|leaf)/route_path/icon/sort/visible(login\|system)/is_builtin | UNIQUE(code)；INDEX(parent_id,sort)；FK parent_id→sys_menu(id) ON DELETE RESTRICT（有子节点禁删，级联确认在应用层） |
| `sys_resource` | `id` | menu_id/code(全局唯一)/name/type(button\|api)/api_method/api_path | UNIQUE(code)；INDEX(menu_id)；FK menu_id→sys_menu(id) ON DELETE RESTRICT |
| `sys_user_role` | `(user_id, role_id)` | — | FK user_id→sys_user ON DELETE CASCADE；FK role_id→sys_role ON DELETE RESTRICT（角色被引用禁删）；INDEX(role_id) |
| `sys_role_menu` | `(role_id, menu_id)` | — | FK role_id→sys_role ON DELETE CASCADE；FK menu_id→sys_menu ON DELETE CASCADE（菜单删则清授权）；INDEX(menu_id) |
| `sys_role_resource` | `(role_id, resource_id)` | — | FK role_id→sys_role ON DELETE CASCADE；FK resource_id→sys_resource ON DELETE CASCADE；INDEX(resource_id) |

- **FK 删除策略取舍**：`sys_menu.parent_id` / `sys_resource.menu_id` / `sys_user_role.role_id` 用 **RESTRICT**（有子节点/被用户引用时 DB 兜底禁删，应用层先给"影响范围"提示）；`sys_role_menu`/`sys_role_resource` 对菜单/资源/角色删除用 **CASCADE**（授权关系随主体消亡自动清）。删除操作在**单事务**内：先查引用 → 提示或放行 → 删主体 + 级联 + bump 受影响用户（见 §4.2）。
- **role_code 去留【已确认】**：`sys_user.role_code` **保留**为兼容/兜底列（seed admin=system、注册=tenant_admin 仍写它，阶段二读它的代码不破）；权限解析**以 sys_user_role 为准**。
- **seed**（幂等 ON CONFLICT DO NOTHING）：内置 3 角色（system 全授权 + is_locked、tenant_admin、normal）+ paid（预留）；菜单树（按现 menuConfig + 新增「系统管理→权限管理」子组 4 叶子，emoji→EP 图标名映射）；各页功能点（精确码见 §4.3）；存量 sys_user 按 role_code 补 sys_user_role。

### 4.2 权限解析与令牌【已确认：瘦令牌 + 服务端解析 + Redis 缓存 + 强制重登】
- **JWT 瘦身**：claims 去 `role`，留 `sub/tenant_id/perm_ver/typ/jti`。
- **权限解析** `backend/auth/perm_resolver.py`(新)：`resolve(user_id)->{roles,is_system,menus:[code],resources:[code],perm_ver}`（user→sys_user_role→roles→role_menu/role_resource 并集；system 角色解析为全量）。
- **缓存**：Redis `auth:perms:{user_id}`（含 perm_ver + 结果，TTL=access_ttl），`_critical` fail-closed。中间件校验 token（含 stage2 perm_ver 比对）后从缓存加载注上下文，缺失则实时解析回写。
- **失效 = 强制重登【已确认】**：任何改变用户有效权限的操作 → `bump_and_invalidate(user_ids)`（perm_ver+1 + 删 `auth:perms:{user_id}`）。因 stage2「token.perm_ver ≠ 当前 → 401 重登」，受影响用户**下次请求 401、重登后拿新权限**（对齐 R11「perm_ver 自增、即时生效」口径）。**触发点全集**（Codex P1 整改，务必全覆盖）：
  - 用户角色变更（sys_user_role 增删）→ bump 该用户；
  - 角色授权变更（role_menu/role_resource 改）→ 查该角色关联的全部用户 → bump；
  - 角色删除 → 查关联用户 → bump；
  - **菜单删除 / 可见性变更 / 资源码删除或改**（影响 /me 菜单与权限集合）→ 查引用该菜单/资源的角色 → 再查这些角色的用户 → bump；
  - 用户禁用/锁定 → bump + token 黑名单。
  - **租户停用 → 该租户全部用户 bump**（Codex P2 整改）：停用后其用户下次请求因 perm_ver 失配 401 → 重登时被租户 status 校验拒绝，闭合"已登录 token 仍可访问"缺口。
  - 统一封装 `bump_users_of_roles(role_ids)` / `bump_users_of_menu(menu_id)` / `bump_users_of_resource(resource_id)` / `bump_users_of_tenant(tenant_id)` 供各仓库调用（**实现在 `perm_resolver.py`**，因需查 PG 找受影响用户；session_store 保持纯 Redis）。菜单/资源结构变更额外 bump 全部 system 用户（超管解析为全量视图，结构变更也影响其 /me）。
- **上下文改造**：`AuthContext` 由单 `role` → `roles:[]` + `is_system` + `perms`(menus/resources set)；`system_context()` 设 is_system + 全量 perms。`get_current_owner()` 不变。

### 4.3 鉴权守卫与权限码（精确码，Codex P0 整改）
**逐接口精确 resource code，不用通配符**：

| 域 | 接口 → 精确码 | 守卫 |
| --- | --- | --- |
| 用户 | `user:list` `user:create` `user:update` `user:disable`(启停锁定) `user:reset-password` `user:delete` | **`require_perm(code)`**（tenant_admin 可获授权，system 恒过） |
| 用户·可分配角色（只读） | `GET /api/roles/assignable`（供用户管理页角色下拉，**按调用者角色分流**：system 得全部可分配含自建 custom、tenant_admin 仅系统预设） | **`require_perm("user:list")`**（进用户管理即可读；Codex P1 整改，避免 tenant_admin 断链） |
| 角色 | `role:list` `role:create` `role:update` `role:delete` `role:assign-perm` | **`require_system`**（系统专属，见下） |
| 菜单 | `menu:list` `menu:create` `menu:update` `menu:delete` `menu:reorder` | **`require_system`** |
| 功能 | `resource:list` `resource:create` `resource:update` `resource:delete` | **`require_system`** |
| 租户 | `tenant:list` `tenant:create` `tenant:update` `tenant:disable` | **`require_system`** |

- **`require_perm(code)`**（`deps.py` 新增）：`ctx.is_system` 恒过；否则 `code ∉ ctx.perms.resources → ForbiddenError(403)`。
- **系统级接口硬守卫（Codex P1 整改）**：requirement 明确**菜单/功能/租户/角色管理仅系统管理员**（§7.6/7.7/R12 line 219 等）。故 role/menu/resource/tenant 管理接口挂 **`require_system`（而非 require_perm）**——**不可经 RBAC 配置误授权给 tenant_admin**；对应功能码在 seed 中**标记不可授予非 system**（角色管理页对这些码禁勾选/置灰）。仅 **user 管理接口**走 require_perm（tenant_admin 经授权管本租户用户）。
- `require_system` 改判 `ctx.is_system`；存量 13 路由的 require_system 挂载不动（阶段四细化）。
- **路由扫描测试延续**（stage2 `test_all_controlled_get_routes_require_token`）：新管理路由额外断言——system-only 接口非 system→403、user 接口无授权角色→403。

### 4.4 数据隔离全量透传（R9）
- **资产表隔离**：阶段一/二已完成 tenant_id+owner_user_id 端到端过滤，本阶段**仅回归复核**、不改。
- **平台管理表按角色域过滤（本阶段新增）**：用户/租户查询——system 全局、tenant_admin 限本租户（`WHERE tenant_id=ctx.tenant_id`）；写入校验 tenant_admin 不跨租户、不分配非预设/非 system 可授码。
- **前端传归属一律忽略**（阶段二铁律）：租户、角色归属取上下文校验。

### 4.5 前端权限消费（菜单 fail-closed，Codex P2 整改）
- `/me` 填充 `menus`（后端菜单树、已按当前用户权限+可见性过滤）+ `permissions`（resource_code 列表）；`stores/auth.ts` 存之。
- **SideMenu 改造**：消费 `auth.menus`（后端下发、已过滤），按 EP 图标名渲染。
- **菜单兜底 fail-closed**：`menuConfig.ts` **仅**作路由存在性/开发期兜底，**不作生产菜单渲染源**；**已登录态下 `/me`/菜单拉取失败 → 显示错误/空态 + 重试，绝不回退展示全量静态菜单**（避免露出未授权入口，符合「无权菜单不出现」）。
- **`v-permission` 指令** `frontend/src/directives/permission.ts`(新)：功能码 ∉ `auth.permissions` → 移除/禁用元素。
- **路由守卫增强** `router/index.ts`：token 基础上增"目标路由对应菜单 ∈ auth.menus"校验（system 恒过；无权→回首页/403）。

### 4.6 页面设计闭环（逐页，DESIGN §5.2/§7.4 + page-template；Codex 页面组整改）
4 页均走 LayoutHost，登记 `pageRegistry.ts` + `router` + DESIGN §9，过 `layout-contract.spec.ts`（禁 vh/手写 .v-page）+ `pageRegistry.spec.ts`。**统一状态设计**：每页覆盖 loading（骨架/加载）/ empty（空态占位）/ error（错误+重试）/ no-perm（无权提示或按 v-permission 隐藏）。**视口验收（官方三档）**：**1100×620 不整页滚、主区内滚**；1366×768 核心列优先；1440×900 无溢出无重叠。master-detail 页在 1100×620 下右栏内滚 + 窄栏体内横滚。

| 页面 | pageKey | archetype | #action | #main（growMain / 滚动归属） | #overlays | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| P4 用户管理 | `user-manage` | list | 工具栏(筛选/搜索/查询/新建) | `data-table`(growMain，表体内滚，宽表体内横滚) | 编辑 dialog + 重置密码 dialog + **settings-drawer** | loading/empty/error/no-perm |
| P5 角色管理 | `role-manage` | master-detail | 页头 + 新建角色 | 左角色列表 + 右权限树（growMain=右树内滚；窄屏体内横滚） | 新建/重命名 dialog + **settings-drawer** | loading/empty(无角色)/error/no-perm |
| P6 菜单与功能 | `menu-resource` | master-detail | 页头 + 新增菜单节点 | 左菜单树 + 右属性/功能表（growMain=右侧内滚；功能表体内横滚） | **settings-drawer**（本页表单内联，无编辑 dialog） | loading/empty/error/no-perm |
| P7 租户管理 | `tenant-manage` | list | 工具栏(筛选/搜索/查询/新建) | `data-table`(growMain，体内滚/横滚) | 编辑 dialog + **settings-drawer** | loading/empty/error/no-perm |

- **弹窗/抽屉规范（DESIGN §4/§9）**：所有弹窗、settings-drawer 一律放 `#overlays` 插槽；dialog 短表单、自适应 `min(px,92vw)`、正文 max-height 内滚；**registry 页必须有 `settings-drawer` overlay**（`pageRegistry.spec.ts` 强制），三段"布局/组件设置/业务选项"，用 `PageSettingsDrawer`。
- **组件/布局维护矩阵（page-template 要求）**：本阶段**不新增布局 archetype**（复用既有 list/master-detail）。**新增组件**：`IconPicker.vue`（EP 图标选择器，P6 用）——须登记维护矩阵：组件种类=图标选择器、消费字段=菜单 icon(图标名)、可配置旋钮=无（纯选择器）、样板接入=菜单与功能页；**settings-drawer 可编辑旋钮**：各页表格列显隐/密度（走 `ComponentAutoSettings` 既有渲染器，page/user 层），不新写第二套设置表单。

### 4.7 页面 P4 技术实现：用户管理（承接 [user-management.html](../prototypes/user-management.html)）
> 原型已**去掉勾选列**（本阶段不做批量，避免假交互）；行操作按状态显隐。

| 页面功能点 | 需求 | 交互要点 | 技术实现 | 组件/模块 | 数据/API | 状态与异常 | 任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 列表查询/筛选/分页 | R10 | 租户(system)/角色/状态筛选 + 搜索 + 分页 | LayoutHost list；el-table 体内滚/横滚；服务端分页 | UserManageView、el-table、el-pagination | `GET /api/users`(域过滤) → `user:list` | loading/空/错误重试；租管仅本租户 | T5,T11 |
| 新建/编辑(多角色) | R10 | 账号/邮箱/多角色/租户/状态 | dialog 自适应；角色 el-select multiple | 编辑弹窗 | `POST/PUT /api/users`→`user:create/update`、**`GET /api/roles/assignable`**(非 require_system 的 `/api/roles`，防 tenant_admin 断链；system 得含自建 custom、tenant_admin 仅系统预设) | 账号/邮箱唯一；租管不跨租户/仅系统预设可分配角色，system 可分配自建 custom | T5,T11 |
| 启停/锁定/重置/删除 | R10 | 行操作随状态变 | 行操作调接口刷新；重置密码弹窗 | 行操作、重置弹窗 | `POST /api/users/{id}/status`→`user:disable`、`/reset-password`→`user:reset-password`、`DELETE`→`user:delete` | 禁用即时失效(bump+黑名单)；删自身/最后管理员阻止 | T5,T11 |

### 4.8 页面 P5 技术实现：角色管理（承接 [role-management.html](../prototypes/role-management.html)）
| 页面功能点 | 需求 | 交互要点 | 技术实现 | 组件/模块 | 数据/API | 状态与异常 | 任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 角色列表/CRUD | R11 | 左列表切换 + 新建/重命名 | master-detail 左栏 | RoleManageView | `GET/POST/PUT/DELETE /api/roles`(require_system) | 名/code 唯一；删被引用阻止；内置不可删 | T6,T12 |
| 菜单&功能授权树 + 全选/清空/还原 | R11 | 右栏 el-tree 三态勾选；**全选/清空/还原**(原型确认，必做)；保存刷新权限 | el-tree show-checkbox；`assign-perm` | 权限树 | `GET /api/menus`+`/api/resources`、`PUT /api/roles/{id}/perms`→`role:assign-perm` | 保存→bump 关联用户 perm_ver；超管树置灰；system-only 码禁勾选 | T6,T12 |

### 4.9 页面 P6 技术实现：菜单与功能管理（承接 [menu-resource-management.html](../prototypes/menu-resource-management.html)）
| 页面功能点 | 需求 | 交互要点 | 技术实现 | 组件/模块 | 数据/API | 状态与异常 | 任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 菜单树 CRUD/排序 | R12 | 左树增删/拖拽排序、选中切右栏 | el-tree draggable；属性表单 | MenuResourceView | `GET/POST/PUT/DELETE /api/menus`、`/reorder`(require_system) | route 唯一且匹前端路由；删有子节点级联确认→bump 受影响用户 | T7,T13 |
| 图标选择 | R12 | EP 图标库可搜索网格 | `IconPicker.vue`(新)消费 `@element-plus/icons-vue`；icon 存图标名 | IconPicker | icon 随菜单保存 | 无匹配提示；空图标允许 | T7,T13 |
| 功能点登记 | R13 | 右下功能表增删改 | 功能子表；button/api | 功能点子表 | `GET/POST/PUT/DELETE /api/resources?menu_id=`(require_system) | 功能码全局唯一不可复用；删/改→bump 引用角色的用户 | T8,T13 |

### 4.10 页面 P7 技术实现：租户管理（承接 [tenant-management.html](../prototypes/tenant-management.html)）
| 页面功能点 | 需求 | 交互要点 | 技术实现 | 组件/模块 | 数据/API | 状态与异常 | 任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 租户列表/CRUD/启停 | R14 | 列表 + 编辑弹窗 + 行内启停 | LayoutHost list；编辑弹窗 | TenantManageView | `GET/POST/PUT /api/tenants`、`/status`(require_system) | 默认租户不可删；停用→其下用户不可登录；删有用户阻止 | T9,T14 |
| 指定管理员 + 查看用户 | R14 | 管理员取该租户用户；查看跳用户管理 | 下拉 + 路由跳转带 query | 管理员选择 | `GET /api/users?tenant=` | 管理员须属该租户 | T9,T14 |

## 5. 需求与开发内容映射和开发状态

| 需求编号 | 需求内容/来源 | 计划开发内容 | 对应任务 | 状态 | 偏差判断 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| R8 | 接口级+按钮级 RBAC | require_perm 精确码机制 + v-permission + 新管理接口接入 | T2,T3,T4,T15 | 进行中 | 部分覆盖 | **存量13路由=阶段四R21**；机制(T2/T3/T4)+用户管理接口接入(T5)已完成；角色/菜单/功能/租户接口守卫(T6–T9)、按钮级 v-permission(T15)待做 |
| R9 | 私有资产 tenant_id+owner_user_id 读写自动过滤 | ①资产隔离(阶段一/二已完成)本阶段**回归复核**；②平台管理表(用户/租户)本阶段**新增**域过滤；③存量业务接口=阶段四 | T16(+T5,T9) | 进行中 | **部分覆盖** | 用户管理域过滤(T5,system 全局/tenant_admin 本租户/跨租户 404)已落地；租户管理域过滤(T9)+多账号交叉核查(T16)待做；R9 端到端资产隔离非本阶段新做 |
| R10 | 用户管理(CRUD/启停/重置/多角色/租户) | user API+repo + 用户管理页(去勾选列) + roles/assignable 供角色下拉 | T5,T6,T11 | 进行中 | 一致 | 后端(T5)完成:多角色落 sys_user_role；可分配角色走 `roles/assignable`(require_perm user:list)，闭合 tenant_admin 分配链路；system 调用得含自建 custom、tenant_admin 仅系统预设（承接 R11「新建角色可被用户分配」） |
| R11 | 角色管理(CRUD+授权+内置+全选/清空/还原) | role API+repo + 角色页(权限树+全选/清空/还原必做) | T6,T12 | 待开始 | 一致 | 租管仅分配不自建；system-only 码禁勾选 |
| R12 | 菜单管理(树CRUD+排序+图标) | menu API+repo + 菜单页 + IconPicker + SideMenu 改造 | T7,T13,T15 | 待开始 | 一致 | icon 存 EP 图标名；menuConfig 降兜底(fail-closed) |
| R13 | 功能管理(资源登记) | resource API+repo + 功能子表 | T8,T13 | 待开始 | 一致 | 与 R8/R11 闭环 |
| R14 | 租户管理(CRUD+管理员+启停) | tenant API+repo + 租户页(去勾选列) | T9,T14 | 待开始 | 一致 | 默认租户保护；停用即时踢下线(bump 该租户全部用户，非仅拦新登录) |
| R5 | 注册绑租管角色 | register 改写 sys_user_role(保留自动登录) | T5 | 已完成 | 一致 | register_tenant_and_admin 同事务绑 tenant_admin |
| —(技术依赖) | 权限数据模型+seed+迁移 | 6 表 + FK/索引 + seed + role_code 迁移 | T1 | 已完成 | 超范围(必要依赖) | R8-R14 底座；对开发 PG 实跑校验+10 单测 |
| —(技术依赖) | 瘦令牌+解析缓存+失效+上下文 | perm_resolver + Redis 缓存 + bump 全触发点 + JWT/context | T2,T3 | 已完成 | 超范围(必要依赖) | 多角色运行时前提；require_perm/require_system 守卫(T4)一并落地 |
| —(技术依赖) | /me 填充 + 前端权限底座 | /me menus+perms + v-permission + SideMenu(fail-closed) + 守卫 | T10,T15 | 进行中 | 超范围(必要依赖) | /me 已填 roles/menus/permissions(T3)；v-permission/SideMenu/守卫(T15)、/me 菜单树细化(T10)待做 |

## 6. 详细实施步骤与进度追踪

> 顺序：内核（T1→T2→T3→T4）→ 后端 API（T5–T9）→ T10 /me → 前端（T11–T15）→ T16 隔离核查 → T17 测试+文档。

### 6.1 任务 T1：权限数据模型 + seed + role_code 迁移
- 状态：已完成
- 依赖：无
- 涉及文件/模块：`backend/storage/pg_ddl.py`、`backend/auth/constants.py`(补 ROLE_PAID/ASSIGNABLE_PRESET_ROLES)、`stage3-rbac-tenant/rbac-schema.sql`(产出)、`backend/tests/test_rbac_schema.py`(产出)
- 目标：建 6 张 RBAC 表（含 FK/索引，§4.1）+ seed 内置角色/菜单树/功能点 + 存量补 sys_user_role。
- 操作：`init_pg_db` 幂等建 6 表（复合主键 + FK 删除策略 + 索引）；`seed_rbac`：4 内置角色(system/tenant_admin/normal/paid)、菜单树(menuConfig+权限管理子组、emoji→EP 图标名)、24 精确功能码、system 全授权+is_locked、tenant_admin=业务+用户管理+user:*、normal/paid=业务页、存量用户按 role_code 补 sys_user_role。
- 产出：6 表 DDL + seed 逻辑 + `rbac-schema.sql` 留痕 + 10 个 T1 单测。
- 影响范围：仅新增平台表；不动资产表/行情 DuckDB/`role_code`。
- 边界与异常：幂等（IF NOT EXISTS + ON CONFLICT DO NOTHING）；默认授权仅角色首次无授权时写、不覆盖后续手工调整；FK RESTRICT/CASCADE 按 §4.1。
- 验证方式：`init_pg_db` 无错（对开发 PG 实跑）；PG 查 6 表 + FK 删除策略(RESTRICT/CASCADE) + 5 索引存在、4 内置角色/22 菜单/24 功能点行数符合、各角色授权域符合、存量 admin=system；幂等复跑行数不变。
- 完成标准：表+FK+索引+seed 就绪，admin=system 全授权，存量平滑迁移。**（已达成：全量 pytest 283 passed = 273 基线 + 10 T1 用例）**

### 6.2 任务 T2：权限解析 + Redis 缓存 + 失效全触发点
- 状态：已完成
- 依赖：T1
- 涉及文件/模块：`backend/auth/perm_resolver.py`(新)、`backend/auth/session_store.py`、`backend/tests/test_rbac_perm_resolver.py`(产出)
- 目标：多角色权限解析 + 按 perm_ver 缓存 + **全触发点失效**（Codex P1）。
- 操作：`resolve(user_id)`（§4.2）；session_store 加 `cache_perms/get_cached_perms/clear_perms`（`_critical` fail-closed，**纯 Redis**）；**bump 编排放 perm_resolver（非 session_store）**——`bump_and_invalidate(user_ids)`(PG perm_ver+1 + 清 perms/pv 缓存) + `bump_users_of_roles/of_menu/of_resource/of_tenant`（供 T6/T7/T9 调用）。**微调理由**：bump 需查 PG 找受影响用户，而 session_store docstring 明确「不耦合 PG」，故 PG 耦合的失效编排归 perm_resolver，session_store 只留纯缓存读写。
- 产出：解析器 + 失效编排(4 个 bump) + session_store 缓存三方法 + 11 个单测。
- 影响范围：新增模块 + session_store 加缓存方法（additive）。
- 边界与异常：Redis 故障 fail-closed(503)；缓存缺失实时解析回写（回填编排在 T3 中间件）；system 全量；菜单/资源结构变更额外 bump 全部 system 用户（超管看全量）。
- 验证方式：单测——多角色并集/system 全量/无角色空；菜单·资源·角色·租户变更后正确 bump 到关联用户(含 system)；bump 后 perm_ver+1 且缓存清；Redis 故障抛 ServiceUnavailableError。
- 完成标准：解析/缓存/全触发点失效可用且有单测。**（已达成：11 个 T2 用例全通过）**

### 6.3 任务 T3：JWT 瘦令牌 + 上下文/中间件改造
- 状态：已完成
- 依赖：T2
- 涉及文件/模块：`jwt_tokens.py`、`context.py`、`middleware.py`、`deps.py`、`services/auth_service.py`、多测试文件调用点
- 目标：令牌去 role；上下文携带 roles+is_system+perms；中间件按缓存注权限。
- 操作：`_issue`/`issue_access`/`issue_refresh` 去 role 参数与 claim；`AuthContext`→`roles/is_system/menus/resources`（frozenset）；`AuthMiddleware` 校验 token 后 `svc.load_perms(user_id)`（缓存优先/实时解析回填，503 纳入 fail-closed）注上下文；`system_context()` 设 `is_system=True`；`deps.require_system` 改判 `ctx.is_system`；`context.get_current_role`→`get_current_roles`+`is_current_system`；`auth_service.me()` 用 load_perms 填 roles/menus/permissions（`role` 兼容保留）。
- 产出：瘦令牌 + 富上下文 + 中间件注权限 + load_perms。
- 影响范围：**令牌契约变更（旧 token 失效需重登，发布注意点）**；`ctx.role`→`ctx.is_system/roles` 全量改引用点（deps/middleware/context/多测试 `issue_access` 去 role 参数）。
- 边界与异常：CLI/后台经 system_context 全权；请求链缺上下文抛错延续；load_perms 缓存故障 fail-closed 503。
- 验证方式：单测——令牌无 role claim；中间件注 perms（admin=system 恒过、tadmin 无 user_role→非 system 恒 403）；stage2 中间件回归绿。
- 完成标准：瘦令牌链路通，stage2 鉴权回归绿。**（已达成：全量 294 passed；修正 T2 测试 bump 波及真实 admin perm_ver 的隔离问题——sandbox teardown 还原 admin perm_ver）**

### 6.4 任务 T4：require_perm 守卫 + require_system 兼容 + 系统级硬守卫
- 状态：已完成
- 依赖：T3
- 涉及文件/模块：`backend/auth/deps.py`、`backend/tests/test_rbac_deps.py`(产出)
- 目标：resource-code 精确依赖 + system-only 硬守卫（Codex P0/P1）。
- 操作：`require_perm(code)` 工厂依赖（system 恒过；否则 code∉ctx.resources **精确匹配**→403，不用通配符）；`require_system` 已在 T3 改判 is_system；约定 role/menu/resource/tenant 接口用 require_system、user 接口用 require_perm。
- 产出：require_perm + 兼容 require_system + 8 单测。
- 影响范围：deps；新管理接口 T5+ 按 §4.3 挂守卫（本任务只建机制未接路由）。
- 边界与异常：无上下文→401；非 system 无码→403；精确匹配（`user:list` 不放行 `user:list-all`）；system-only 码不可授予非 system（seed 标记 + 角色页禁勾选，落 T6/前端）。
- 验证方式：单测——system 过、授权 user 码过、无授权 403、无 token 401、精确匹配不通配。
- 完成标准：两守卫可用且有单测。**（已达成：8 个 T4 用例全通过）**

### 6.5 任务 T5：用户管理 API + 仓库（R10）
- 状态：已完成
- 依赖：T4
- 涉及文件/模块：`backend/api/users.py`(新)、`backend/services/user_admin_service.py`(新)、`backend/storage/user_repository.py`(扩)、`backend/storage/role_repository.py`(**新，只读部分提前落地供可分配校验；T6 扩 CRUD**)、`main.py`、`services/auth_service`(register 经 repo 走 user_role)、`backend/tests/test_rbac_users.py`(产出)
- 目标：用户 CRUD/启停锁定/重置/多角色/租户，按域过滤，精确码守卫。
- 操作：按 §4.3 精确码挂 `require_perm`（list/create/update/disable/reset-password/delete）；`GET /api/users`(域过滤)、`POST/PUT`、`/status`、`/reset-password`、`DELETE`；编排在 UserAdminService（域范围/可分配校验/自身与最后管理员保护/bump 失效）；多角色写 sys_user_role（新建/编辑/改角色/停用/删除/重置 → `bump_and_invalidate` 即时失效）；`register_tenant_and_admin` 同事务写 sys_user_role(tenant_admin)；tenant_admin 恒本租户（跨租户目标 404）/仅 `RoleRepository.assignable(调用者)` 可分配。
- 产出：用户管理接口 + service 编排 + 仓库多角色/域过滤方法 + role_repository 只读 + 16 接口测试。
- 影响范围：新 router/service/role_repository；user_repository 扩展；register 绑角色（故 /me 对注册用户返回非空菜单，同步改 test_auth_service 断言）。
- 边界与异常：账号/邮箱唯一（业务软失败 200+4000）；跨租户目标 404；删/停自身阻止；最后 tenant_admin 不可停用/删除/降级；停用/删除/改角色 bump（下次请求 401，停用者重登被 status 拒）。
- 验证方式：接口测试——精确码 403、域隔离、多角色 CRUD、唯一冲突、启停 perm_ver bump、自身与最后管理员保护、tenant_admin 不可授 system。
- 完成标准：R10 功能点全通过 + 隔离回归。**（已达成：16 个 T5 用例全通过；全量 318 passed）**

### 6.6 任务 T6：角色管理 API + 仓库（R11）
- 状态：待开始
- 依赖：T4
- 涉及文件/模块：`backend/api/roles.py`(新)、`backend/storage/role_repository.py`(新)
- 目标：角色 CRUD + 授权（全选/清空/还原）+ 内置保护 + 授权 bump。
- 操作：`GET/POST/PUT/DELETE /api/roles`、`PUT /api/roles/{id}/perms`（写 role_menu/role_resource + `bump_users_of_roles([id])`）——均挂 **require_system**；内置不可删、超管 is_locked 不可改、system-only 码拒绝授予。**另加 `GET /api/roles/assignable`（挂 `require_perm("user:list")`，非 require_system）**（Codex P1 + 二轮复核）：**按调用者角色分流**——① `ctx.is_system`：返回**除 system 超管外的全部可分配角色**（系统预设 tenant_admin/normal/paid **＋系统管理员自建的 custom 角色**），承接 R11「新建角色可被用户分配」；② tenant_admin：**仅系统预设可分配角色**（is_builtin 且 kind∈{tenant_admin,normal,paid}），**不含 system 超管、不含任何 custom**（自建角色仅 system 可分配）。供用户管理页角色下拉，闭合 R10/R11 分配链路。
- 产出：角色接口(含 assignable 只读) + 仓库 + bump 联动。
- 影响范围：新 router/repo；assignable 供 T5/T11 用户页消费。
- 边界与异常：名/code 唯一；删被 sys_user_role 引用角色 RESTRICT 阻止 + 应用层提示；超管锁定；assignable 分流——system 得含自建 custom、tenant_admin 严格过滤到系统预设（不含 system/custom）。
- 验证方式：接口测试——CRUD、授权保存(全选/清空)、内置保护、授权后关联用户 perm_ver 自增(下次 401)、system-only 码不可授；**assignable 两条分流用例：① system 调用可见系统管理员自建的 custom 角色；② tenant_admin 调用不含任何 custom、不含 system，仅系统预设**。
- 完成标准：R11 功能点全通过。

### 6.7 任务 T7：菜单管理 API + 仓库（R12，含变更 bump）
- 状态：待开始
- 依赖：T4,T2
- 涉及文件/模块：`backend/api/menus.py`(新)、`backend/storage/menu_repository.py`(新)
- 目标：菜单树 CRUD + 排序 + 图标名 + **变更缓存失效**（Codex P1）。
- 操作：`GET /api/menus`(树)、`POST/PUT/DELETE`、`/reorder`；均挂 **require_system**；icon 存 EP 图标名；**删除/可见性变更 → `bump_users_of_menu(menu_id)`**（查引用该菜单的角色→用户）；删有子节点 RESTRICT + 应用层级联确认。
- 产出：菜单接口 + 仓库 + bump 联动。
- 影响范围：新 router/repo。
- 边界与异常：route_path 唯一且匹前端路由(非法告警)；删有子节点/被引用提示影响。
- 验证方式：接口测试——树 CRUD、排序、唯一、级联保护、**删除/改可见性后引用用户 perm_ver 自增**。
- 完成标准：R12 功能点全通过 + 缓存失效验证。

### 6.8 任务 T8：功能管理 API + 仓库（R13，含变更 bump）
- 状态：待开始
- 依赖：T4,T7,T2
- 涉及文件/模块：`backend/api/resources.py`(新)、`backend/storage/resource_repository.py`(新)
- 目标：功能点登记 + **变更缓存失效**（Codex P1）。
- 操作：`GET/POST/PUT/DELETE /api/resources?menu_id=`；挂 **require_system**；type button/api；**删除/改码 → `bump_users_of_resource(resource_id)`**。
- 产出：功能接口 + 仓库 + bump 联动。
- 影响范围：新 router/repo。
- 边界与异常：功能码全局唯一不可复用；删被角色引用提示影响（CASCADE 清授权前先提示）。
- 验证方式：接口测试——CRUD、唯一、引用提示、**改/删后引用用户 perm_ver 自增**、可被角色勾选。
- 完成标准：R13 功能点全通过 + 缓存失效验证。

### 6.9 任务 T9：租户管理 API + 仓库（R14）
- 状态：待开始
- 依赖：T4,T5
- 涉及文件/模块：`backend/api/tenants.py`(新)、`backend/storage/tenant_repository.py`(新)
- 目标：租户 CRUD + 指定管理员 + 启停（**停用即时踢下线**）。
- 操作：`GET/POST/PUT /api/tenants`、`/status`；挂 **require_system**；指定管理员须属该租户；停用 → ①登录校验租户 status 拒绝 + ②**`bump_users_of_tenant(tenant_id)` 使该租户全部在线用户 token 失效**（Codex P2：不止拦新登录，已登录 token 下次请求 401→重登被 status 拒）。
- 产出：租户接口 + 仓库 + 停用踢下线联动。
- 影响范围：新 router/repo；登录链路加租户 status 校验；停用调 bump。
- 边界与异常：默认/平台租户不可删；删有用户租户阻止；停用后该租户用户**新登录被拒 + 已登录 token 失效**。
- 验证方式：接口测试——CRUD、启停、默认保护、停用后该租户用户**新登录被拒**、**已登录旧 token 下次请求 401/403**。
- 完成标准：R14 功能点全通过 + 停用即时失效验证。

### 6.10 任务 T10：/me 填充 + 权限消费
- 状态：待开始
- 依赖：T2,T7,T8
- 涉及文件/模块：`backend/services/auth_service.py`
- 目标：/me 返回按权限过滤的菜单树 + 功能码列表。
- 操作：`me()` 调 perm_resolver + menu_repository 返回 `menus`(按 ctx.perms + 可见性双过滤的树) + `permissions`(码列表)；role→roles/主角色。
- 产出：/me 富返回。
- 影响范围：auth_service。
- 边界与异常：菜单可见性(login/system)+角色授权双过滤；system 全量。
- 验证方式：接口测试——system 全菜单、tenant_admin 过滤后菜单、permissions 准确。
- 完成标准：前端可据 /me 渲染菜单 + 控按钮。

### 6.11 任务 T11：前端 用户管理页（P4）
- 状态：待开始
- 依赖：T5,T10
- 涉及文件/模块：`frontend/src/views/system/UserManageView.vue`(新)、`api/user.ts`(新)、`router`、`pageRegistry.ts`、`DESIGN.md §9`
- 目标：承接 [user-management.html](../prototypes/user-management.html)（§4.7），**去勾选列**，含 settings-drawer。
- 操作：LayoutHost list（§4.6）；筛选/搜索/分页；多角色 el-select multiple；编辑/重置 dialog 自适应；行操作随状态；`v-permission` 控按钮；#overlays 挂 dialog + PageSettingsDrawer 三段；表格列显隐走 ComponentAutoSettings。
- 产出：用户管理页 + api + registry/DESIGN 登记。
- 影响范围：新页面 + 路由 `/system/users`；`npm run build`。
- 边界与异常：loading/空/错误重试/无权状态；窄视口表格体内横滚。
- 验证方式：preview 5181 双主题 + 交互；**视口 1100×620/1366×768/1440×900** 验证无整页滚/溢出；`layout-contract`/`pageRegistry` 绿；`npm run build`。
- 完成标准：7.4 功能点验收 + §4.6 页面闭环（含 settings-drawer + 状态 + 三档视口）。

### 6.12 任务 T12：前端 角色管理页（P5）
- 状态：待开始
- 依赖：T6,T7,T8,T10
- 涉及文件/模块：`frontend/src/views/system/RoleManageView.vue`(新)、`api/role.ts`(新)、路由/registry/DESIGN
- 目标：承接 [role-management.html](../prototypes/role-management.html)（master-detail + el-tree 三态 + **全选/清空/还原必做**，§4.8）。
- 操作：左角色列表 + 右 el-tree show-checkbox；全选/清空/还原/保存刷新权限；内置保护/超管置灰/system-only 码禁勾选；#overlays 挂新建/重命名 dialog + settings-drawer；master-detail 窄屏体内横滚。
- 产出：角色管理页 + api + 登记。
- 影响范围：新页面 + 路由 `/system/roles`；build。
- 边界与异常：loading/空(无角色)/错误/无权；保存 dirty 提示。
- 验证方式：preview 双主题 + 勾选/全选/清空/还原/保存 + 内置保护；**三档视口**；契约绿；build。
- 完成标准：7.5 功能点验收（含全选/清空/还原）+ 页面闭环。

### 6.13 任务 T13：前端 菜单与功能页（P6，含 IconPicker）
- 状态：待开始
- 依赖：T7,T8,T10
- 涉及文件/模块：`frontend/src/views/system/MenuResourceView.vue`(新)、`components/IconPicker.vue`(新)、`api/menu.ts`(新)、路由/registry/DESIGN、维护矩阵登记
- 目标：承接 [menu-resource-management.html](../prototypes/menu-resource-management.html)（§4.9）。
- 操作：左 el-tree draggable + 右属性表单(含 IconPicker 消费 `@element-plus/icons-vue`) + 功能子表增删；#overlays 挂 settings-drawer；IconPicker 可搜索网格；功能表体内横滚。
- 产出：菜单页 + IconPicker 组件 + api + 登记 + **维护矩阵登记 IconPicker**。
- 影响范围：新页面 + 新组件 + 路由 `/system/menus`；build。
- 边界与异常：route_path 唯一校验；图标名渲染；loading/空/错误/无权。
- 验证方式：preview 双主题 + 图标选择/搜索 + 树增删排序 + 功能增删；**三档视口**；契约绿；build。
- 完成标准：7.6 功能点验收 + 页面闭环 + 维护矩阵登记。

### 6.14 任务 T14：前端 租户管理页（P7）
- 状态：待开始
- 依赖：T9,T10
- 涉及文件/模块：`frontend/src/views/system/TenantManageView.vue`(新)、`api/tenant.ts`(新)、路由/registry/DESIGN
- 目标：承接 [tenant-management.html](../prototypes/tenant-management.html)（§4.10），去勾选列。
- 操作：LayoutHost list + 编辑弹窗 + 行内启停 + 查看用户跳转；默认租户删除置灰；#overlays 挂 dialog + settings-drawer。
- 产出：租户管理页 + api + 登记。
- 影响范围：新页面 + 路由 `/system/tenants`；build。
- 边界与异常：loading/空/错误/无权；停用二次确认。
- 验证方式：preview 双主题 + 启停 + 跳转带过滤；**三档视口**；契约绿；build。
- 完成标准：7.7 功能点验收 + 页面闭环。

### 6.15 任务 T15：前端权限消费底座（v-permission + SideMenu fail-closed + 守卫）
- 状态：待开始
- 依赖：T10
- 涉及文件/模块：`frontend/src/directives/permission.ts`(新)、`components/SideMenu.vue`、`components/menuConfig.ts`、`stores/auth.ts`、`router/index.ts`、`main.ts`
- 目标：按钮级指令 + 菜单后端化(fail-closed) + 路由守卫增强（Codex P2）。
- 操作：`v-permission` 消费 `auth.permissions`；SideMenu 消费 `auth.menus`(EP 图标名)；**menuConfig 仅路由/开发兜底，登录态拉取失败显错误/空态不回退全量菜单**；`fetchMe` 填充；beforeEach 增菜单权限校验(system 恒过)。
- 产出：指令 + SideMenu 改造 + 守卫增强。
- 影响范围：跨页面横切；SideMenu 渲染源切换。
- 边界与异常：/me 失败→错误/空态 + 重试（**不 fail-open**）；无权路由→回首页。
- 验证方式：组件测——指令无码移除元素；SideMenu 按 menus 渲染；拉取失败不露全量菜单；无权路由拦截。preview 验证。
- 完成标准：按钮/菜单按权限显隐，system 全见，拉取失败 fail-closed。

### 6.16 任务 T16：数据隔离全量透传核查（R9）
- 状态：待开始
- 依赖：T5,T6,T9
- 涉及文件/模块：新管理仓库 + 测试
- 目标：确认平台管理查询/写入按角色域隔离；资产隔离回归；无跨租户泄漏。
- 操作：脚本/测试核查用户/租户管理每条 SQL 域过滤（system 全局、tenant_admin 本租户）；资产隔离回归（复用阶段一/二用例）；多账号交叉验证。
- 产出：隔离核查结论 + 回归用例。
- 影响范围：测试为主。
- 边界与异常：跨租户读/写/分配均被拒。
- 验证方式：多账号交叉——tenant_admin A 看不到/改不到 tenant B 用户；跨租户分配被拒；资产隔离回归绿。
- 完成标准：R9 里程碑"多账号交叉验证隔离"达成（平台管理表新增 + 资产回归）。

### 6.17 任务 T17：测试 + 文档治理 + 页面闭环收尾
- 状态：待开始
- 依赖：T1–T16
- 涉及文件/模块：`backend/tests/test_rbac_*.py`、前端契约测试、`CLAUDE.md`、本目录文档、`../requirement.md`、`DESIGN.md §9`
- 目标：质量门槛 + 契约文档同步 + 闭环收尾。
- 操作：补单测/接口测/权限测/隔离测/回归；全量 `pytest` 绿 + `npm run build` + 前端契约绿；CLAUDE.md「认证与鉴权」补 RBAC 数据化/require_perm 精确码/系统级硬守卫/瘦令牌/多角色/菜单 fail-closed/缓存失效触发点约定；requirement §12 阶段三标完成 + 本目录 plan 回填；4 页登记 DESIGN §9 + IconPicker 维护矩阵。
- 产出：测试 + 文档 + 闭环验收。
- 影响范围：文档与测试。
- 边界与异常：CI/本地全绿含前端契约。
- 验证方式：全绿；§4.6 闭环项逐条满足；三档视口验证。
- 完成标准：阶段三里程碑（§11）达成。

## 7. 数据库与 SQL 计划

- **SQL 文件路径**：`agent-works/multi-tenant-rbac/stage3-rbac-tenant/rbac-schema.sql`（T1 产出，人读留痕 + 手工补执行兜底）。
- **用途**：建 sys_role/menu/resource/user_role/role_menu/role_resource 六表（复合主键 + **FK 删除策略 + 索引**，§4.1）+ seed 内置角色/菜单树/功能点 + 存量补 sys_user_role。
- **执行时机**：随 `init_pg_db()` 启动幂等（`CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS` + seed `ON CONFLICT DO NOTHING`）。删除类操作在**单事务**内（查引用→删主体+级联+bump）。
- **影响范围**：仅新增平台表；不动资产表、行情 DuckDB、`sys_user.role_code`。
- **迁移失败处理**：建表/seed 幂等可重跑；`role_code→sys_user_role` 迁移为 additive 追加（`ON CONFLICT DO NOTHING`），中断可重跑不重复。
- **回滚方式（细化，Codex P2）**：新表 additive；**回滚前须备份**（`pg_dump` 六表）——因回滚 `DROP TABLE` 会**丢失已配置的角色/菜单/授权/用户-角色数据**（非零成本）；`role_code` 仍在，DROP 后权限退回阶段二 system 粗守卫。前端回退到 stage2 构建。**无 schema 不可逆点，但有数据丢失成本**（区别于阶段一 R3 的结构不可逆）。

## 8. 测试与验证计划

- **单元测试**：perm_resolver 多角色并集/system 全量；瘦令牌无 role claim；require_perm/require_system(system过/授权过/无权403/无token401/system-only非system403)；**bump 全触发点**（角色授权/菜单删改/资源删改/用户角色变更/**租户停用**→关联用户 perm_ver 自增 + 缓存清）；Redis 故障 fail-closed。
- **接口测试**：用户 CRUD/多角色/启停即时失效/唯一/精确码；**`roles/assignable` 分流：system 调用含系统管理员自建 custom 角色、tenant_admin 调用不含 custom 与 system(仅系统预设)**；角色 CRUD/授权(全选清空)/内置保护/system-only 码不可授；菜单树 CRUD/排序/唯一/级联/删改后 bump；功能 CRUD/唯一/引用提示/改删后 bump；租户 CRUD/启停/默认保护/**停用后该租户用户新登录被拒 + 已登录旧 token 下次请求 401/403**；/me 按角色过滤。
- **页面/交互测试**：4 页 preview 5181 双主题 + 交互；承接原型区域/入口/状态/退化。**视口验收 1100×620 / 1366×768 / 1440×900**（page-template 官方三档）——master-detail 在 1100×620 右栏内滚 + 窄栏体内横滚，无整页滚/无溢出。
- **权限与数据范围测试**：多账号交叉——tenant_admin A 看不到/改不到 tenant B；跨租户分配被拒；system-only 接口非 system→403；按钮/菜单按角色显隐；**菜单拉取失败不 fail-open**。
- **回归测试**：全量 `pytest`（273 基线 + 新增）；stage2 鉴权用例 role→is_system 后绿；`npm run build`；前端 `layout-contract`/`pageRegistry` 绿。
- **图示与原型一致性验证**：4 页匹配对应 `prototypes/*.html`（区域/入口/状态/响应式/去勾选列/全选清空还原）。
- **配置闭环验证**：各页 settings-drawer 三段可展示/保存/生效/重置（走 ComponentAutoSettings，page/user 层）。
- **需求映射验证**：§5 每 R 项有任务+状态+验证；R8/R9 标"部分覆盖"并说明缺口；超范围三项标必要依赖。
- **页面功能点验证**：7.4–7.7 各功能点均有技术实现+任务+异常处理。
- **视觉验证**：preview 5181 双主题（禁占用 5173）。

## 9. 发布与回滚

- **发布前检查**：环境变量就绪；PG/Redis 运行；`init_pg_db` 建 6 表+FK+索引+seed；`npm run build` 同步。**⚠️ 令牌契约变更（去 role）→ 存量 token 全失效、在线用户须重登（预期，非缺陷）**；发布公告告知。
- **发布步骤**：**备份 PG（尤其后续产生的 RBAC 数据）** → 部署后端（自动建表+seed）→ 重启 → 验证可登录+权限生效 → 部署前端产物。
- **配置或环境变量**：无新增必填。
- **回滚方案**：前端回退 stage2 构建；后端 6 表 additive 可保留；如需彻底回滚 `DROP TABLE` 六表（**先备份，会丢已配置 RBAC 数据**）+ `role_code` 兜底退回阶段二 system 粗守卫。**无 schema 不可逆点，有数据丢失成本**。

## 10. 风险、假设与待确认项

### 10.1 风险
- **令牌契约变更影响面**（中）：去 role → 存量 token 失效重登；`ctx.role`→`ctx.roles/is_system` 需改所有引用点。应对：T3 全量替换 + stage2 回归 + 发布公告。
- **缓存失效触发点遗漏致权限脏读**（中·Codex P1）：菜单/资源/角色变更未 bump 关联用户则旧权限残留。应对：T2 封装三个 bump + T7/T8 强制调用 + 单测覆盖每条触发路径。
- **系统级接口被 RBAC 误放开**（中·Codex P1）：应对：菜单/功能/租户/角色接口挂 require_system（非 require_perm）、system-only 码 seed 标记 + 角色页禁勾选，双重防线。
- **菜单数据化 route_path 与前端路由错配**（中）：应对：保存校验 route_path ∈ 前端注册路由集 + menuConfig 路由兜底（非菜单渲染兜底）。
- **隔离回归（平台管理表新面）**（中·阶段一血泪）：应对：T16 多账号交叉 + 每条管理 SQL 域过滤自审。
- **菜单兜底 fail-open 回潮**（低·Codex P2）：应对：T15 明确登录态拉取失败 fail-closed（错误/空态），组件测断言不露全量菜单。

### 10.2 假设
- 沿用 perm_ver 即时失效语义（授权变更 = bump + **强制重登**，已确认）。
- 菜单可见性两档（login/system）够用。
- `@element-plus/icons-vue` 已在依赖（EP 配套）。
- tenant_admin 数据域 = 本租户，system = 全局。

### 10.3 待确认项（非阻塞，已给默认，开发中可定）
1. **route_path 校验来源**：前端暴露注册路由清单给后端校验 vs 仅前端保存时校验。倾向：**前端侧校验 + 后端存字符串**，非法给告警不强阻。
2. **删除被引用菜单/资源**：级联清授权 vs 阻止先解绑。倾向：**RESTRICT 阻止 + 应用层提示影响范围**（安全优先；授权关系表本身 CASCADE 随主体消亡）。

> 注：原「授权生效体验」「用户表勾选列」两项已确认（强制重登 / 去勾选列），移出待确认、写入 §4.2 与 §4.7。

## 11. 里程碑与验收

**阶段三完成 = 同时满足**（对齐 §12 阶段三里程碑「多账号交叉验证隔离与授权即时生效」；前缀标当前达成度）：
1. ✅ **已达成**（T1）：6 张 RBAC 表（FK/索引）+ seed 就绪；存量平滑迁 sys_user_role；role_code 兼容保留。
2. ✅ **已达成**（T2/T3/T4）：瘦令牌 + 服务端权限解析 + Redis 缓存 + **全触发点** perm_ver 失效（强制重登）；`require_perm(精确码)` 用于 user 接口、`require_system` 硬守 role/menu/resource/tenant 接口（守卫机制就绪，role/menu/resource/tenant 接口本体待 T6–T9 挂载）。
3. ◻ **部分**（T5 用户接口+register 已落；角色/菜单+功能/租户接口 T6–T9、4 前端页 T11–T14 待做）：用户/角色/菜单+功能/租户 4 套接口 + 4 前端页（承接原型、过契约、双主题、**三档视口达标**、settings-drawer、去勾选列、全选/清空/还原）。
4. ◻ **待做**（T10/T15）：`v-permission` 按钮级 + SideMenu 消费后端菜单(**fail-closed**、EP 图标) + /me 填充（/me 数据已就绪 T3，菜单树细化待 T10）+ 路由守卫按菜单。
5. ◻ **部分**（T5 用户管理隔离已达；完整交叉验证待 T16）：**多账号交叉验证**——tenant_admin 限本租户、跨租户不可见/不可改、system-only 接口非 system 403；授权变更后相关用户重登即生效。
6. ◻ **待做**（T17）：全量 `pytest` 绿（当前 318 passed）+ `npm run build` + 前端契约绿；CLAUDE.md 同步 RBAC 契约；requirement §12 阶段三标完成。

达成后进入**阶段四（存量 13 路由全量接 resource code + 隔离，R21）**，再阶段五（审计/字典/配置拆页/开关页 R16–R19）。
