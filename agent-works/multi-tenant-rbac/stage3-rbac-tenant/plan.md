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
| P5 角色管理 | `role-manage` | list | 页头 + 新建角色 | 左角色列表 + 右权限树（`section` 内主从：右树内滚；窄屏体内横滚） | 新建/重命名 dialog + **settings-drawer** | loading/empty(无角色)/error/no-perm |
| P6 菜单与功能 | `menu-manage` | list | 页头 + 新增菜单节点 | 左菜单树 + 右属性/功能表（`section` 内主从：右侧内滚；功能表体内横滚） | 新增菜单节点 dialog + **settings-drawer** | loading/empty/error/no-perm |
| P7 租户管理 | `tenant-manage` | list | 工具栏(筛选/搜索/查询/新建) | `data-table`(growMain，体内滚/横滚) | 编辑 dialog + **settings-drawer** | loading/empty/error/no-perm |

> **实现口径修订（Codex 复审整改，2026-07-03）**——与计划初稿差异及原因，已同步实现/文档：
> - **archetype：P5/P6 由 `master-detail` 改记为 `list`（含内部 `section` 主从）。** 经核代码：布局系统虽有 `master-detail` 原型，但 `LayoutHost` 对多 `main` slot 在 `allowReflow=false` 时按**纵向 scroll** 渲染、并不产出左右并排；全库无任一页面使用该 archetype。主从视觉一律以 `list`（或 workbench）+ 页面内 `section` flex 分栏实现（与既有 `LayoutPagesView` 等一致）。故此处是**修订计划贴合实现与框架事实**，非让 DESIGN 迁就实现。
> - **pageKey：P6 由 `menu-resource` 改为 `menu-manage`**，与同组 `user-manage`/`role-manage`/`tenant-manage` 的 `*-manage` 命名一致（初稿 `menu-resource` 为孤例）。
> - **P6 #overlays 增「新增菜单节点」dialog（初稿写"无编辑 dialog"）**：菜单**属性编辑**与**功能点增删改**均已按原型**表内联**（无 dialog）；仅**新建菜单节点**保留轻量 dialog——新节点需先录入不可变自然键 `code`+类型才能入树，原型对"新增菜单节点"仅留 toast 桩、无内联设计，dialog 是创建（非编辑）场景的合理承载。属"创建用 dialog、编辑走内联"的明确取舍。
> - **P7 编辑弹窗状态段 → 行内启停**：原型编辑弹窗含"启用/停用"段；实现改为编辑弹窗只管名称/指定管理员，**启停走行内动作**（对齐后端 `update_tenant` 仅收 name+adminUserId、`set_status` 为独立端点且停用需"踢下线"二次确认）。属接口拆分驱动的取舍，已在此标注。

### 4.6.1 Codex 复审整改清单（2026-07-03，全部已改 + 复验）
- **P1 路由守卫 fail-open**（阻塞）：原 `beforeEach` 在 `/me` 失败、菜单空时会 `return true` 放行到未授权页壳。抽纯函数 `utils/permission.resolveMenuGuard` 改 **fail-closed**：未授权一律漏斗到首个授权菜单，无安全落点则回 `SAFE_HOME=/board`（已在落点才放行，防死循环），**绝不放行被请求的未授权页**。新增 6 例守卫单测（含"菜单空非 system 不 fail-open→重定向 SAFE_HOME"）。
- **P2 v-permission 落地**：4 个管理页按钮由本地 `can()` 改走全局 `v-permission` 指令（脚本内 disabled/分支逻辑走共用 `hasPermission`），删除各页重复 `can()`，口径归一。
- **P2 页面状态闭环**：4 页列表/主数据加载补 `error` 态 + 重试入口（`el-result`），不再只靠全局 toast；no-perm 由路由守卫（页级）+ v-permission（按钮级）覆盖。
- **P2 组件级自动化测试**：新增 `directives/__tests__/permission.spec.ts`（指令无码移除元素）、`components/__tests__/SideMenu.spec.ts`（ready 按 menus 渲染 / error 显错误+重试且不露菜单 / loading）；`vitest.config` 加 `@vitejs/plugin-vue` + 逐文件 `jsdom` 环境。前端测试 100→**114**。
- **P2 registry/DESIGN 一致性**：见 §4.6 修订块（archetype/pageKey/overlays 已同步计划与实现）；DESIGN §设置抽屉澄清"三段按内容条件渲染"。
- **P3 el-checkbox `:label`→`:value`**（`ComponentAutoSettings.vue`，EP3.0 弃用）。
- **P3 `tenant:delete` 功能码**：`pg_ddl._SEED_RESOURCES` 补齐（4 个租户动作全资源化），前端删除按钮改 `v-permission="'tenant:delete'"`；顺带修 `_seed_role_grants` 让 **system 角色幂等补齐全量授权**（原仅首次授权，存量库新增资源会致 system 授权缺口 / `test_system_role_full_grants` 失败）。
- **原型一致性 P2 · 角色页右侧**：由默认 `el-tree` **重建为定制三级权限树** `PermissionTree.vue`（分组卡片 + 菜单行 + 功能点 chip 面板 + 图例 + 三态级联），承接 `role-management.html`。勾选态以「原子叶子集合」派生分组/菜单三态，`sysLocked` 子树置灰不可授。UI 全选→保存 API 复验：只授登录可见菜单/资源、**零 system 锁定项泄漏**。
- **原型一致性 · 菜单页功能点**：由 dialog 改**表内联增删改**（承接原型 + 计划"表单内联"）。
- **交付卫生**：`.gitignore` 由 `/**/screenshots*/**` 放宽为 `**/*screenshot*/`，覆盖 `page-test-screenshots/`。
- **全量回归**：后端 `pytest` **398 passed**（先 `./start.sh stop` 释放 DuckDB 锁）；前端 `build` 绿 + `vitest` 114 passed；四页 preview 双主题 × 三档视口自验，无控制台错误。
- **数据订正**：修复此前 T15 编码诊断误置 `/board` `parent_id=NULL`（已复原到 `quotes`）。

**Codex 二轮复审整改（2026-07-03，error+retry 闭环补漏）**——一轮"页面状态闭环"仅覆盖首屏主数据，遗漏两处次级加载失败：
- **角色页 `loadAll()` 漏 role 列表失败态**：原实现只有菜单/资源 `Promise.all` 在 `try`，`await loadRoles()` 在 `catch` 之外——`listRoles()` 失败不进 `loadError`、不显错误态。已将 `loadRoles()` 移入同一 `try`，任一加载失败均进 `el-result` 错误态 + 重试。（`loadRoles` 本身 try/**finally** 无 catch，异常正常上抛被 `loadAll` 捕获。）
- **菜单页 `loadResources()` 无失败态**：菜单树有 `treeError`，但右栏功能点列表加载失败仅结束 `resLoading`、无恢复入口。补 `resError` 态 + `retryResources()`，表内以"功能点加载失败 + 重试"行呈现（与"暂无功能点"空态互斥）。preview 拦截 `/resources` 请求强制失败复验：错误行+重试出现；恢复后切节点回正常空/数据态。
- **两处失败路径已沉淀为正式回归测试**（防长期回退）：`views/system/__tests__/manage-error-states.spec.ts`（jsdom，4 例）——① 菜单/资源成功但 `listRoles` 失败→角色页进错误态（精确复现"loadRoles 曾在 catch 外"）；② `listResources` 失败→菜单页显"功能点加载失败+重试"；③④ 重试后接口恢复→错误态消失。mock `@/api/*` + 布局组合式（其 onMounted 发 `/layout` 请求，jsdom 无 server 会挂起），stub `LayoutHost` 渲染各插槽使 `#main` 错误态可见。前端测试 114→**118**。
- **口径复核（非缺陷，维持既有决策）**：①**设置抽屉三段**——`PageSettingsDrawer` 按内容条件渲染（布局恒在、组件设置有 `hasComponentConfig` 时、业务选项有 `$slots.business` 时），此为全站既有页统一范式；"每页强制显式三段"会与既有页不一致且产生空段，故维持"固定顺序、按内容渲染"（DESIGN §设置抽屉）。②**archetype/pageKey 修订**——`master-detail` 在 `LayoutHost` 多主槽下按纵向 scroll 渲染、不并排（全库无并排页），`list`+内部 `section` 才是既有主从范式；`menu-resource`→`menu-manage` 对齐 `*-manage` 命名。均为基于框架事实的有据修订（§4.6），非降级实现。

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
| R8 | 接口级+按钮级 RBAC | require_perm 精确码机制 + v-permission + 新管理接口接入 | T2,T3,T4,T15 | 进行中 | 部分覆盖 | **存量13路由=阶段四R21**；机制(T2/T3/T4)+用户管理接口接入(T5)+角色接口守卫(T6)+菜单接口守卫(T7)+功能接口守卫(T8)+租户接口守卫(T9·整 router require_system)已完成；**按钮级 v-permission 指令 + 路由守卫菜单校验(T15)已完成**——Codex 复审整改后 **v-permission 已真正落到 4 个管理页模板**（原用本地 can()，现模板走 `v-permission`、脚本逻辑走共用 `utils/permission.hasPermission`，口径统一）；守卫补 fail-closed 修复（`resolveMenuGuard`）+ 指令/SideMenu/守卫组件测。剩存量13业务路由精确 resource code 接入=阶段四 R21 |
| R9 | 私有资产 tenant_id+owner_user_id 读写自动过滤 | ①资产隔离(阶段一/二已完成)本阶段**回归复核**；②平台管理表(用户/租户)本阶段**新增**域过滤；③存量业务接口=阶段四 | T16(+T5,T9) | 已完成 | 一致 | 用户管理域过滤(T5,system 全局/tenant_admin 本租户/跨租户 404)+租户管理 require_system(T9) 已落地；**多账号交叉核查(T16)完成**：补 4 例锁死用户变更全动词跨租户 404 + 越权提角色 403，资产隔离回归 398 passed 绿。存量业务接口精确码=阶段四 R21 |
| R10 | 用户管理(CRUD/启停/重置/多角色/租户) | user API+repo + 用户管理页(去勾选列) + roles/assignable 供角色下拉 | T5,T6,T11 | 进行中 | 一致 | 后端(T5)完成:多角色落 sys_user_role；可分配角色走 `roles/assignable`(require_perm user:list)，闭合 tenant_admin 分配链路；system 调用得含自建 custom、tenant_admin 仅系统预设（承接 R11「新建角色可被用户分配」） |
| R11 | 角色管理(CRUD+授权+内置+全选/清空/还原) | role API+repo + 角色页(权限树+全选/清空/还原必做) | T6,T12 | 进行中 | 一致 | 后端(T6)完成：角色 CRUD/授权(全删重插+bump)/内置保护/超管锁定/system-only 码禁授/assignable 分流；`GET /api/roles/{id}/perms` 供前端权限树回显。角色页(T12·全选/清空/还原+三态树)已完成 |
| R12 | 菜单管理(树CRUD+排序+图标) | menu API+repo + 菜单页 + IconPicker + SideMenu 改造 | T7,T13,T15 | 已完成 | 一致 | 后端(T7)完成：菜单树 CRUD/排序/图标名/内置保护/防成环/删除·可见性变更 bump；`{menu_id:path}` 兼容含斜杠内置 id。**前端菜单页 + IconPicker(T13)已完成**（树 draggable+属性表单+图标选择器）；**SideMenu 消费后端菜单(T15)已完成**（后端数据化渲染 + EP 图标 + fail-closed，menuConfig 已删；normal 用户菜单仅业务页自验） |
| R13 | 功能管理(资源登记) | resource API+repo + 功能子表 | T8,T13 | 已完成 | 一致 | 后端(T8)完成：功能点 CRUD/唯一不可复用/内置保护(不可删·码不可改)/删除·改码 bump/role_count 引用统计。**前端功能子表(T13)已完成**（按 menu 拉取、类型 tag、内置禁改删、增删改弹窗，自验闭环） |
| R14 | 租户管理(CRUD+管理员+启停) | tenant API+repo + 租户页(去勾选列) | T9,T14 | 已完成 | 一致 | 后端(T9)完成：租户 CRUD/名称唯一/指定管理员归属校验/默认租户保护/停用即时踢下线(bump 该租户全部用户 + 登录·刷新 status 校验)。**前端租户页(T14)已完成**（列表/筛选/建·停·启·编辑·删全生命周期 + 查看用户带过滤跳转 + default 保护 + row-key 修 fixed 列标签错位，自验闭环） |
| R5 | 注册绑租管角色 | register 改写 sys_user_role(保留自动登录) | T5 | 已完成 | 一致 | register_tenant_and_admin 同事务绑 tenant_admin |
| —(技术依赖) | 权限数据模型+seed+迁移 | 6 表 + FK/索引 + seed + role_code 迁移 | T1 | 已完成 | 超范围(必要依赖) | R8-R14 底座；对开发 PG 实跑校验+10 单测 |
| —(技术依赖) | 瘦令牌+解析缓存+失效+上下文 | perm_resolver + Redis 缓存 + bump 全触发点 + JWT/context | T2,T3 | 已完成 | 超范围(必要依赖) | 多角色运行时前提；require_perm/require_system 守卫(T4)一并落地 |
| —(技术依赖) | /me 填充 + 前端权限底座 | /me menus+perms + v-permission + SideMenu(fail-closed) + 守卫 | T10,T15 | 进行中 | 超范围(必要依赖) | /me 菜单树细化(T10)完成：menus 为「授权∩可见性」双过滤的 MenuNode 树、permissions 功能码列表；v-permission/SideMenu/守卫(T15)待做 |

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
- 状态：已完成
- 依赖：T4
- 涉及文件/模块：`backend/api/roles.py`(新)、`backend/services/role_admin_service.py`(**新增**，编排/守卫/失效，沿用 user_admin_service 分层，api 保持薄层)、`backend/storage/role_repository.py`(T5 只读部分之上扩 CRUD/授权/内置·成员·system-only 检测)、`backend/main.py`(注册 roles_router)、`backend/tests/test_rbac_roles.py`(产出，15 用例)
- 目标：角色 CRUD + 授权（全选/清空/还原）+ 内置保护 + 授权 bump。
- 操作：`GET/POST/PUT/DELETE /api/roles`、`GET/PUT /api/roles/{id}/perms`（写 role_menu/role_resource 单事务全删重插 + `bump_users_of_roles([id])`）——均挂 **require_system**；内置不可删、超管 is_locked 不可改/不可授、system-only 码拒绝授予、code 撞内置/重复拒。**另加 `GET /api/roles/assignable`（挂 `require_perm("user:list")`，非 require_system）**（Codex P1 + 二轮复核）：**按调用者角色分流**——① `ctx.is_system`：返回**除 system 超管外的全部可分配角色**（系统预设 tenant_admin/normal/paid **＋系统管理员自建的 custom 角色**），承接 R11「新建角色可被用户分配」；② tenant_admin：**仅系统预设可分配角色**（is_builtin 且 kind∈{tenant_admin,normal,paid}），**不含 system 超管、不含任何 custom**（自建角色仅 system 可分配）。供用户管理页角色下拉，闭合 R10/R11 分配链路。
- 产出：角色接口(含 assignable 只读 + get/set perms) + 仓库 CRUD/授权 + service 编排 + bump 联动。
- 影响范围：新 router/service/repo；assignable 供 T5/T11 用户页消费；`GET /api/roles/{id}/perms` 供 T12 权限树回显。
- 边界与异常：名/code 唯一（撞内置码亦拒）；删被 sys_user_role 引用角色——应用层先查 member_count 给友好提示（避免 FK RESTRICT 直接抛库错 500）；超管锁定名称/描述与授权均拒；system-only 码（归属 visible='system' 菜单的功能，如 role:*/menu:*/tenant:*）不可授非 system 角色；set_grants 前校验 menu/resource id 存在性（非法 id 直接 ValidationError 而非 FK 抛错）。
- 验证方式：接口测试——CRUD、授权保存(全选/清空)、内置保护(删内置 403/改超管 403/超管授权 403)、授权后关联用户 perm_ver 自增(下次 401)、system-only 码不可授(403)、删有成员角色拒(4000)、撞内置/重复 code 拒(4000)；**assignable 两条分流用例：① system 调用可见系统管理员自建的 custom 角色；② tenant_admin 调用不含任何 custom、不含 system，仅系统预设**。
- 完成标准：R11 后端功能点全通过。**已达成**：15 个 T6 用例全通过；全量 **333 passed**（318→333）。前端角色管理页（T12）待做。

### 6.7 任务 T7：菜单管理 API + 仓库（R12，含变更 bump）
- 状态：已完成
- 依赖：T4,T2
- 涉及文件/模块：`backend/api/menus.py`(新)、`backend/services/menu_admin_service.py`(**新增**，编排/校验/失效，沿用 admin service 分层)、`backend/storage/menu_repository.py`(新)、`backend/main.py`(注册 menus_router，整 router 挂 require_system)、`backend/tests/test_rbac_menus.py`(产出，15 用例)
- 目标：菜单树 CRUD + 排序 + 图标名 + **变更缓存失效**（Codex P1）。
- 操作：`GET /api/menus`(树)、`POST/PUT/DELETE`、`/reorder`；均挂 **require_system**；icon 存 EP 图标名；**删除/可见性变更 → `bump_users_of_menu(menu_id)`**（查引用该菜单的角色→用户 ∪ 全部 system 用户）；删有子节点 RESTRICT + 应用层级联确认（先查 child_count 给提示，避免 FK 抛库错）。删除**先 bump 再删**（删后 role_menu CASCADE 清空则查不到引用用户）。
- 产出：菜单接口 + 仓库 + service 编排 + bump 联动。
- 影响范围：新 router/service/repo。
- 边界与异常：route_path 唯一（非空叶子间）；leaf 须有 route、group 强制 route=None；code 全局唯一且建后不可改；**内置菜单不可删**（对应已发布前端页面/路由，可改标题/图标/可见性）；移动节点防成环（目标父不得为自身或子孙）；**新建为加性变更不 bump**（新节点无引用，system 按缓存 TTL 自然刷新，避免每次加菜单强制管理员重登；纯展示编辑/排序同理不 bump——对齐 plan §6.7「仅删除/可见性变更失效」口径）。**关键：`{menu_id:path}` 路径转换器**——内置 seed id=code 含斜杠（`/screen`/`/system/users`），普通 str 段无法匹配（404/405），:path 可捕获且不与 `/menus/reorder`(POST) 冲突。
- 验证方式：接口测试——树 CRUD、排序、唯一(code/route)、级联保护、内置保护(删内置 403)、移动防成环、**删除/改可见性后引用用户 perm_ver 自增**、纯改名不 bump。
- 完成标准：R12 功能点全通过 + 缓存失效验证。**已达成**：15 个 T7 用例全通过；全量 **348 passed**（333→348）。前端菜单&功能页（T13）待做。

### 6.8 任务 T8：功能管理 API + 仓库（R13，含变更 bump）
- 状态：已完成
- 依赖：T4,T7,T2
- 涉及文件/模块：`backend/api/resources.py`(新)、`backend/services/resource_admin_service.py`(**新增**，编排/校验/失效)、`backend/storage/resource_repository.py`(新)、`backend/main.py`(注册 resources_router，整 router 挂 require_system)、`backend/tests/test_rbac_resources.py`(产出，13 用例)
- 目标：功能点登记 + **变更缓存失效**（Codex P1）。
- 操作：`GET/POST/PUT/DELETE /api/resources?menu_id=`；挂 **require_system**；type button/api；**删除/改码 → `bump_users_of_resource(resource_id)`**（引用该功能角色的用户 ∪ 全部 system 用户）。删除**先 bump 再删**（删后 role_resource CASCADE 清空则查不到引用用户）。
- 产出：功能接口 + 仓库 + service 编排 + bump 联动。
- 影响范围：新 router/service/repo。
- 边界与异常：功能码全局唯一不可复用（撞现有拒）；**内置功能码与端点 require_perm 硬绑——不可删、code 不可改**（可改 name/type/接口元数据）；归属菜单须存在；改 code=角色授出的有效权限码变，必 bump；改 name/type/元数据/移动菜单不 bump；新建为加性变更不 bump（对齐 plan §6.8「仅删除/改码失效」口径）；list 附 `role_count`（引用该功能的角色数）供前端展示删除影响（CASCADE 清授权前提示）。功能码含冒号(user:list)不含斜杠，普通 str 路径段可匹配、无需 :path。
- 验证方式：接口测试——CRUD、按菜单过滤、唯一(不可复用)、坏菜单拒、内置保护(删 403·改码 403·改名允许)、**删除/改码后引用用户 perm_ver 自增**、改名不 bump、role_count 反映引用。
- 完成标准：R13 功能点全通过 + 缓存失效验证。**已达成**：13 个 T8 用例全通过；全量 **361 passed**（348→361）。前端菜单&功能页功能子表（T13）待做。

### 6.9 任务 T9：租户管理 API + 仓库（R14）
- 状态：已完成
- 依赖：T4,T5
- 涉及文件/模块：`backend/api/tenants.py`(新)、`backend/services/tenant_admin_service.py`(**新增**，编排/校验/停用踢下线)、`backend/storage/tenant_repository.py`(新)、`backend/services/auth_service.py`(login/refresh 加 `_ensure_tenant_active` 租户 status 校验)、`backend/main.py`(注册 tenants_router，整 router 挂 require_system)、`backend/tests/test_rbac_tenants.py`(产出，12 用例)
- 目标：租户 CRUD + 指定管理员 + 启停（**停用即时踢下线**）。
- 操作：`GET/POST/PUT/DELETE /api/tenants`、`/status`；挂 **require_system**；指定管理员须属该租户；停用 → ①登录/刷新校验租户 status 拒绝（auth_service `_ensure_tenant_active`）+ ②**`bump_users_of_tenant(tenant_id)` 使该租户全部在线用户 token 失效**（Codex P2：不止拦新登录，已登录 token 下次请求 401→重登被 status 拒）。
- 产出：租户接口 + 仓库 + service 编排 + 停用踢下线联动 + 登录链路 status 校验。
- 影响范围：新 router/service/repo；auth_service login/refresh 加租户 status 校验；停用调 bump。
- 边界与异常：租户名全局唯一；指定管理员须属该租户（跨租户拒）；**默认租户(id=default)不可删、不可停用**（防平台管理员自锁）；删有用户租户阻止（先迁走/删用户）；停用后该租户用户**新登录被拒 + 已登录 token 失效**。
- 验证方式：接口测试——CRUD、名称唯一、指定管理员归属校验、默认保护(删/停 403)、删有用户租户拒、停用后该租户用户 perm_ver 自增、**已登录旧 token 下次请求 401**（在线踢下线）、**停用后新登录被 AuthService 拒**。
- 完成标准：R14 功能点全通过 + 停用即时失效验证。**已达成**：12 个 T9 用例全通过；全量 **373 passed**（361→373）。前端租户管理页（T14）待做。

### 6.10 任务 T10：/me 填充 + 权限消费
- 状态：已完成
- 依赖：T2,T7,T8
- 涉及文件/模块：`backend/services/auth_service.py`（`me()` + `_visible_menu_tree`/`_menu_node`）、`backend/tests/test_rbac_me.py`(产出，5 用例)、`backend/tests/test_auth_service.py`(既有 me 断言改树形)
- 目标：/me 返回按权限过滤的菜单树 + 功能码列表。
- 操作：`me()` 调 perm_resolver(load_perms) + menu_repository.tree() 返回 `menus`(按「角色授权 ∩ 可见性」双过滤的嵌套树) + `permissions`(功能码列表)；role→roles/主角色。菜单节点映射为前端 **MenuNode 形状** `{index,title,icon,children}`（叶子 index=route_path、分组 index=code，icon=EP 图标名），SideMenu 可直接渲染。
- 产出：/me 富返回（菜单树 + 功能码）。
- 影响范围：auth_service（新增 MenuRepository 依赖）。
- 边界与异常：**双过滤**——① 非 system，visible='system' 节点及整棵子树隐藏；② 叶子仅当 system 或 code∈授权集保留；③ 分组仅当有存活子节点保留（**剪空组**，故授权叶子自动带出祖先分组）；system 全量（含系统专属分支）。
- 验证方式：接口/服务测试——system 全菜单(含 data/角色/租户管理)、tenant_admin 过滤后菜单(业务 + 系统>权限>用户管理，无 data/config/角色/租户，权限组仅剩用户管理)、normal 仅业务(系统组整体剪除)、permissions 准确(system 含 role:*/tenant:*、tenant_admin 仅 user:*、normal 空)、MenuNode 形状(分组有 children/叶子无、icon 为 EP 名)。
- 完成标准：前端可据 /me 渲染菜单 + 控按钮。**已达成**：5 个 T10 用例 + 既有 me 断言改树形全通过；全量 **378 passed**（373→378）。前端 SideMenu/v-permission 消费(T15)待做。

### 6.11 任务 T11：前端 用户管理页（P4）
- 状态：已完成（页面/api/登记落地；vue-tsc + build 绿；pageRegistry/layout-contract 契约绿；**preview 5181 双主题 + 三档视口(1440×900/1366×768/1100×620)交互闭环已验**：新建(多角色+指定租户)/编辑回填(账号禁用·租户锁定·角色回填)/改状态/行内启停解锁/锁定→删除/重置弹窗，无整页横纵溢出、无控制台错误）
- 验证中发现并修复 2 个 T5 后端缺陷（均补回归测试，见 test_rbac_users）：①`update_user` 的"最后管理员保护"漏 `target_is_admin` 前置——租户内无 active tenant_admin 时（如默认租户 admin 为 system 角色）编辑弹窗停用**普通用户**被误拦，与行内 `set_status` 口径统一后修复；②`_row_to_admin_view._iso` 在**混合结果集**里把 SQL NULL 的 `last_login_at` 序列化成字符串 `'NaT'` 泄漏前端（pandas 列 dtype 提升为 datetime64），`pd.isna` 兜住 → null。
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
- 状态：已完成（RoleManageView + api/role.ts + api/menu.ts(只读，T13 扩展) + 登记；vue-tsc/build 绿；pageRegistry/layout-contract 契约绿；**preview 5181 双主题 + 1440/1100 视口交互闭环已验**：master-detail 三级三态权限树、级联勾选、全选/清空/还原、脏检测、新建/重命名/删除角色、保存往返(API 核验 menu-only 授权 `/screen` 正确落库)、超管锁定整树只读+按钮禁用、system 可见子树(数据/配置/布局/角色/菜单/租户)对可编辑角色置灰而用户管理可授——与后端 `system_only_resource_ids`(按 `menu.visible='system'`)口径一致；无整页溢出、无控制台错误）
- 关键实现：权限树 node-key 用 `m:`/`r:` 前缀区分菜单/功能点；保存收集 menuIds=选中∪半选的菜单、resourceIds=选中功能点；回显走叶子(功能点 + 无子菜单)由 el-tree 级联回算三态；置灰口径复用后端 `menu.visible='system'`，与 set_grants 的 system-only 硬拒一致（无"前端可勾但后端拒"错位）。
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
- 状态：已完成（build 绿 + 前端 85 tests 全绿；preview 5181 双主题×窄视口自验闭环）
- 依赖：T7,T8,T10
- 涉及文件/模块：`frontend/src/views/system/MenuResourceView.vue`(新)、`components/IconPicker.vue`(新)、`api/menu.ts`(新)、路由/registry/DESIGN、维护矩阵登记
- 目标：承接 [menu-resource-management.html](../prototypes/menu-resource-management.html)（§4.9）。
- 操作：左 el-tree draggable + 右属性表单(含 IconPicker 消费 `@element-plus/icons-vue`) + 功能子表增删；#overlays 挂 settings-drawer；IconPicker 可搜索网格；功能表体内横滚。
- 产出：菜单页 + IconPicker 组件 + api + 登记 + **维护矩阵登记 IconPicker**。
- 影响范围：新页面 + 新组件 + 路由 `/system/menus`；build。
- 边界与异常：route_path 唯一校验；图标名渲染；loading/空/错误/无权。
- 验证方式：preview 双主题 + 图标选择/搜索 + 树增删排序 + 功能增删；**三档视口**；契约绿；build。
- 完成标准：7.6 功能点验收 + 页面闭环 + 维护矩阵登记。
- 落地留痕：
  - `api/menu.ts` 扩展 CRUD：`createMenu/updateMenu/deleteMenu/reorderMenus` + `createResource/updateResource/deleteResource`。
  - **坑修正（自验实测，与后端注释相反）**：含斜杠内置 id（`/board`、`/system/menus`）在 `updateMenu/deleteMenu` **必须 `encodeURIComponent(id)`**。后端注释称"前端 `/menus/${id}` 天然形成路径、勿编码"——但浏览器/fetch 会把 `/menus//board` 的双斜杠规范化、丢掉前导斜杠 → 后端收 `board` 报「菜单不存在」（实测 200+错误 msg）。编码为 `%2Fboard` 后 `{menu_id:path}` 解码回 `/board` 才命中（实测「已保存」）；对 uuid 自定义 id 编码恒等，两者皆安全。已改 `encodeURIComponent` 并重测内置 /board 改图标→保存→清除还原全通。
  - `components/IconPicker.vue`：`import * as` 消费 `@element-plus/icons-vue`（293 图标），可搜索网格 + 清除 + `<component :is>` 按名渲染；`v-model` 存图标名。DESIGN §9 已登记复用组件。
  - `MenuResourceView.vue`：LayoutHost list + master-detail——左 `el-tree` draggable（`allow-drop` 限 inner 仅落分组、`allow-drag` 门控 `menu:reorder`；`node-drop` 全量重算 sort/parentId 提交）+ 右 菜单属性表单（IconPicker + 分组隐藏路由 + 排序只读“拖拽树调整”）+ 功能点 `el-table`（类型 tag/绑定接口/内置禁改删）；#overlays 挂 新建菜单/功能点弹窗 + settings-drawer。按钮 gating 走 `can(menu:*/resource:*)`（system 恒真，页 require_system）。
  - 自验（preview 5181 admin/system）：分组 vs 叶子属性回填正确（分组隐路由/有“新增子节点”、内置不可删）；功能子表按 menu 拉取、类型 tag、内置禁改删；IconPicker 搜索“Trend”精确命中 TrendCharts + 选中回填 + 脏标 + 还原；**自建菜单全生命周期**（创建入树自动选中→加功能点→删功能点→删菜单，API 复核 200「已删除」清理干净）；reorder no-op 契约 22 节点 200「排序已保存」；22 树项 `draggable=true`；深/浅双主题一致（全 `--el-*` 变量）；1100×620 无整页横向溢出；无控制台错误。

### 6.14 任务 T14：前端 租户管理页（P7）
- 状态：已完成（build 绿 + 前端 85 tests 全绿；preview 5181 双主题×三档视口自验闭环）
- 依赖：T9,T10
- 涉及文件/模块：`frontend/src/views/system/TenantManageView.vue`(新)、`api/tenant.ts`(新)、路由/registry/DESIGN
- 目标：承接 [tenant-management.html](../prototypes/tenant-management.html)（§4.10），去勾选列。
- 操作：LayoutHost list + 编辑弹窗 + 行内启停 + 查看用户跳转；默认租户删除置灰；#overlays 挂 dialog + settings-drawer。
- 产出：租户管理页 + api + 登记。
- 影响范围：新页面 + 路由 `/system/tenants`；build。
- 边界与异常：loading/空/错误/无权；停用二次确认。
- 验证方式：preview 双主题 + 启停 + 跳转带过滤；**三档视口**；契约绿；build。
- 完成标准：7.7 功能点验收 + 页面闭环。
- 落地留痕：
  - `api/tenant.ts` 扩展写接口 `createTenant/updateTenant/setTenantStatus/deleteTenant`（租户 id 无斜杠，路径无需编码）。
  - `TenantManageView.vue`：LayoutHost list（filter-bar + data-table + 分页 + 编辑弹窗 + settings-drawer），与 user-manage 同构。列：租户名(default 带「内置」tag、fixed-left)/租户 ID/状态 tag/管理员/用户数/创建时间；组件段可显隐 id·admin·userCount·created 列。行操作：编辑、查看用户（跳 `/system/users?tenant=<id>`）、启用/停用（**停用二次确认**，default 不显停用）、删除（default 不显、有用户禁用）。状态经 `setTenantStatus` 独立端点走行操作（不塞进编辑弹窗，对齐后端 update 仅收 name+adminUserId）；编辑弹窗按 `listUsers({tenant_id})` 填「指定管理员」下拉。
  - **配套改 `UserManageView`**：`onMounted` 读 `route.query.tenant`，system 身份预置租户筛选（tenant_admin 忽略防越权）——支撑租户页「查看用户」带过滤跳转。
  - **坑修正**：`el-table` 加 `row-key="id"`。新增/重排数据时 **fixed-left 列内的按行 v-if（如「内置」tag）会 DOM 复用错位**（实测新建租户后「内置」错标到新行，重载才正常）；`row-key` 稳定行标识后修复，启停/改名/删除等 reload 操作后标签均不错位（已复验）。
  - 自验（preview 5181 admin/system）：**全生命周期**建→停(二次确认)→启→编辑改名→删（0 用户可删）全通、toast 正确；default 租户仅「编辑/查看用户」（无停用删除，受保护）；「查看用户」跳转 `?tenant=default` 且用户页租户筛选预置「默认租户」、列表按租户过滤；深/浅双主题；1440/1366/1100 三档无整页横向溢出；无控制台错误；DB 复核仅剩默认租户。

### 6.15 任务 T15：前端权限消费底座（v-permission + SideMenu fail-closed + 守卫）
- 状态：已完成（build 绿 + 前端 100 tests 全绿含 15 新增 permission 单测；preview 5181 system+normal 双身份自验闭环）
- 依赖：T10
- 涉及文件/模块：`frontend/src/directives/permission.ts`(新)、`components/SideMenu.vue`、`components/menuConfig.ts`、`stores/auth.ts`、`router/index.ts`、`main.ts`
- 目标：按钮级指令 + 菜单后端化(fail-closed) + 路由守卫增强（Codex P2）。
- 操作：`v-permission` 消费 `auth.permissions`；SideMenu 消费 `auth.menus`(EP 图标名)；**menuConfig 仅路由/开发兜底，登录态拉取失败显错误/空态不回退全量菜单**；`fetchMe` 填充；beforeEach 增菜单权限校验(system 恒过)。
- 产出：指令 + SideMenu 改造 + 守卫增强。
- 影响范围：跨页面横切；SideMenu 渲染源切换。
- 边界与异常：/me 失败→错误/空态 + 重试（**不 fail-open**）；无权路由→回首页。
- 验证方式：组件测——指令无码移除元素；SideMenu 按 menus 渲染；拉取失败不露全量菜单；无权路由拦截。preview 验证。
- 完成标准：按钮/菜单按权限显隐，system 全见，拉取失败 fail-closed。
- 落地留痕：
  - `utils/permission.ts`(新)：无 DOM 纯逻辑 `collectMenuPaths/firstMenuPath/isRouteAllowed/hasPermission`，供指令/守卫/store/SideMenu 共用，node 环境可单测（`utils/__tests__/permission.spec.ts` 15 例：叶子收集、system 恒过、前缀匹配、`/stocksXYZ` 不误命中 `/stocks`、allowed 空 fail-closed、多码取并）。
  - `directives/permission.ts`(新) + `main.ts` 注册 `app.directive('permission')`：`v-permission="'code'|['a','b']"`，无权 mounted 时移除元素（system 恒过）。会话内权限稳定（变更走 perm_ver→401→重登整页重载），故 mounted 判定即可。
  - `stores/auth.ts`：`menus` 强类型 `MenuTreeNode[]`、新增 `menusStatus(idle|loading|ready|error)` + `ensureLoaded()`（模块级 `inflightMe` 去重，守卫每次导航 + App 挂载并发只发一次 /me）+ `retryMe()`；getter `isSystem/menuRoutePaths/firstMenuPath`。`fetchMe` 失败置 error 并抛出（fail-closed）。
  - `SideMenu.vue`：改由 `auth.menus` 渲染（`status==='ready'&&menus.length` 才出 el-menu；loading 显「加载中」；error 显「加载失败+重试」）；`activeMenu`/展开链据授权叶子动态算（不再硬编码前缀）。`SideMenuItem.vue`：icon 按 EP 图标名取组件渲染（非图标名回退文本）。
  - **`components/menuConfig.ts` 已删除**：fail-closed 不回退静态全量菜单，该文件无消费者即死代码（原是 SideMenu 唯一引用）；删后结构上杜绝 fail-open。
  - `router/index.ts`：`beforeEach` 改 async——已登录先 `await auth.ensureLoaded()`（fail-closed；401 由拦截器清态、守卫复查 token 跳登录），再 `isRouteAllowed(to.path, menuRoutePaths, isSystem)`；无权重定向到 `firstMenuPath`（无安全落点则放行、交后端接口守卫兜底，避免重定向死循环）。
  - `App.vue`：`onMounted` 改调 `ensureLoaded()`（与守卫共用去重）。
  - 自验（preview 5181）：**system**——SideMenu 全量 22 项含旧 menuConfig 没有的「权限管理」子组（用户/角色/菜单与功能/租户），分组渲染 EP 图标（无 emoji），board 数据正常、导航不阻断。**normal**（临时建 testnormal 验后删）——菜单仅业务页（最新行情/策略筛选/策略回测/盘感训练，无数据管理·系统管理系统子树）；守卫拦截 `/system/users`→`/stocks`、`/data/quality`→`/stocks`，放行 `/screen` 与子路由 `/stocks/600000.SH`。无控制台错误；DB 清理无残留。

### 6.16 任务 T16：数据隔离全量透传核查（R9）
- 状态：已完成（+4 跨租户回归用例；全量后端 398 passed 绿）
- 依赖：T5,T6,T9
- 涉及文件/模块：新管理仓库 + 测试
- 目标：确认平台管理查询/写入按角色域隔离；资产隔离回归；无跨租户泄漏。
- 操作：脚本/测试核查用户/租户管理每条 SQL 域过滤（system 全局、tenant_admin 本租户）；资产隔离回归（复用阶段一/二用例）；多账号交叉验证。
- 产出：隔离核查结论 + 回归用例。
- 影响范围：测试为主。
- 边界与异常：跨租户读/写/分配均被拒。
- 验证方式：多账号交叉——tenant_admin A 看不到/改不到 tenant B 用户；跨租户分配被拒；资产隔离回归绿。
- 完成标准：R9 里程碑"多账号交叉验证隔离"达成（平台管理表新增 + 资产回归）。
- 核查结论 + 留痕：
  - **平台管理域隔离（既有已覆盖 + 本次补全动词）**：用户管理所有变更动词经同一 `_load_in_scope`（非 system 且 target.tenant_id≠ctx.tenant_id → 404），角色分配经 `_validate_roles`（仅 `assignable(is_system)` 集合内，tenant_admin 不含 system/custom）。原仅 `status` 有跨租户用例——**本次补 `test_rbac_users.py` 4 例**锁死其余动词：`cannot_update_other_tenant_user`(PUT→4004 且未改)、`cannot_reset_other_tenant_user`(reset→4004)、`cannot_delete_other_tenant_user`(DELETE→4004 且未删)、`cannot_escalate_role_via_update`(本租户用户 PUT roleIds=['system']→403)。防未来重构漏挂域闸门。
  - **租户管理**：整 router `require_system`，`test_rbac_tenants.py::test_list_forbidden_for_tenant_admin` 已证 tenant_admin 完全够不到 → 无跨租户面。
  - **可分配角色分流**：`test_rbac_roles.py` 已覆盖 system 含 custom / tenant_admin 仅预设 / 授权 system-only 码被拒。
  - **资产隔离回归**：全量后端 **398 passed**（含阶段一/二资产复合主键 + layout owner-from-context 归属用例），无回归。
  - **数据订正**：修复 T15 编码诊断误把 `/board` `parent_id` 置 NULL（一次 `%2Fboard` 探针带 `parentId:null` 落库）——已 `UPDATE sys_menu SET parent_id='quotes',sort=20 WHERE id='/board'` 复原，`test_tree_for_system` 恢复绿。
  - **环境注意**：后端测试须先 `./start.sh stop` 释放 DuckDB 写锁（layout save 触发 DuckDB DDL init 会与运行中 dev 后端争锁 → 5003），跑完再 `./start.sh` 重启（已复位，PID 79624 health=200）。

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
2. ✅ **已达成**（T2/T3/T4）：瘦令牌 + 服务端权限解析 + **PG 权威 perm_ver/status 闸门** + Redis perms 缓存 + **全触发点** perm_ver 失效（强制重登）。五轮 Codex P1 整改收敛为**原子化**：① **业务写入 + `bump_perm_ver` 在同一 PG 事务原子提交**（`affected` 写前算定防级联缩水；`clear_perms_cache` 提交后 best-effort），要么都提交要么都回滚，无"业务已变/版本未进"或"版本已进/业务未变"窗口，**且不被 Redis 可用性左右**；② **鉴权闸门 `claims_from_bearer` 每请求以 PG 的 perm_ver + 用户 status + 租户 status 为权威**、不信任 Redis `auth:pv`——`load_perms` 再按权威 perm_ver 校验 perms 缓存新鲜度拒采信陈旧内容，黑名单仍走 Redis fail-closed。故 **Redis 清理失败不阻断权威失效、也不造成 fail-open**（旧实现"先清 Redis 清失败即不 bump"的脱钩已消除）。`require_perm(精确码)` 用于 user 接口、`require_system` 硬守 role/menu/resource/tenant 接口——**接口本体 T6–T9 已挂载**。
3. ◻ **部分**（**后端 4 套接口 T5–T9 全落地**；4 前端页 T11–T14 待做）：用户/角色/菜单+功能/租户 4 套接口已完成（含内置保护、级联/引用校验、租户存在校验 P2-b、最后 active 管理员保护 P1-b、菜单删除 resource 引用前置校验 P2-a）；4 前端页（承接原型、过契约、双主题、**三档视口达标**、settings-drawer、去勾选列、全选/清空/还原）待做。
4. ◻ **部分**（**/me 菜单树 T10 已落**；`v-permission`/SideMenu/路由守卫 T15 待做）：/me 返回「授权∩可见性」双过滤菜单树 + 功能码列表（含菜单移动跨可见域即时失效 P2-c，**按「当前节点+子树」递归 CTE 汇总失效**——修 Codex 二轮 P2-c：父分组变更须连带只授到子孙叶子的用户）；前端 `v-permission` 按钮级 + SideMenu 消费后端菜单(**fail-closed**、EP 图标) + 路由守卫按菜单待做。
5. ◻ **部分**（T5 用户管理隔离已达；完整交叉验证待 T16）：**多账号交叉验证**——tenant_admin 限本租户、跨租户不可见/不可改、system-only 接口非 system 403；授权变更后相关用户重登即生效。
6. ◻ **待做**（T17）：全量 `pytest` 绿（当前 **394 passed**；392 基线 + T11 验证补 2 条回归）+ `npm run build` + 前端契约绿；CLAUDE.md 同步 RBAC 契约；requirement §12 阶段三标完成。

达成后进入**阶段四（存量 13 路由全量接 resource code + 隔离，R21）**，再阶段五（审计/字典/配置拆页/开关页 R16–R19）。
