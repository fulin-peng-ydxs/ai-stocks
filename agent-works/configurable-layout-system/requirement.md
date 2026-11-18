# 需求文档

归档状态：已归档

## 1. 背景与目标

当前项目已经完成可配置布局系统产品化。本需求文档维护其稳定业务目标、边界和验收契约；页面开发的直接执行入口是 `DESIGN.md` 与同目录 `page-template.md`，运行时事实源是 `frontend/src/layout/`、`pageRegistry.ts` 和后端布局配置仓储。

系统不是自由拖拽大屏，也不是只切换主题色，而是以“组件目录 + 布局原型 + 响应式规则 + 代码默认/页面/用户配置覆盖 + 字段开放策略 + 校验器 + AI 开发流程”为核心，让新页面开发稳定按以下模式推进：

1. 选择页面原型。
2. 选择组件清单。
3. 选择全局风格预设。
4. 声明页面级补充配置。
5. 通过校验器和渲染器生成合规页面。
6. 用户在 Web 设置面板中做受控调整并持久化。

最终效果：

- 前端布局不再依赖 AI 临时手写 `.v-page`、`.v-grow`、`height: calc(100vh - Npx)` 等不稳定写法。
- 列表、搜索、表单、抽屉、弹窗、图表、主从、工作台等常见后台场景都有可登记、可配置、可校验的最小组件单元。
- 代码内置 `balanced`（澄空蓝）稳定预设；管理员自定义预设可存储、启停、切换和导入导出，并支持页面级和用户级受控覆盖。
- 新页面交给 AI 开发时，有明确的“选型-声明-填充-校验-登记”开发抓手，减少随机开发和页面规范漂移。

## 2. 当前项目现状

### 2.1 布局规范依据

页面设计与自适应硬约束统一维护在 [DESIGN.md](../../DESIGN.md)，新页面或页面改造流程统一维护在 [page-template.md](./page-template.md)。已经代码化退场的旧规范文件不再作为入口。

当前核心模型：

- 整页/视口永不滚动。
- 页面外壳分为固定操作区和主内容区。
- 主内容区按组件最低尺寸、理想尺寸和兜底阶梯处理。
- 兜底顺序为组件内部滚动、满足条件才重排多列、最后主内容区整体滚动。
- 列表、宽表格、筛选栏、表单、KPI、图表、主从、树、Tabs、抽屉、弹窗等都有最低尺寸和滚动归属要求。

这些约束同时由布局 schema、渲染器、契约测试和页面验证守卫，不得退回成只依赖人工阅读的规则。

### 2.2 已有代码底座

布局系统位于 [frontend/src/layout](../../frontend/src/layout)：

- [schema.ts](/Users/pengshuaifeng/ai-stocks/frontend/src/layout/schema.ts)：定义 `PageLayout`、`Archetype`、`SlotSpec`、`ComponentKind`、`EditableKnob` 等类型。
- [components.ts](../../frontend/src/layout/components.ts)：`COMPONENT_CATALOG` 是组件种类、尺寸、滚动、成长、重排、四态和能力摘要事实源。
- [archetypes.ts](/Users/pengshuaifeng/ai-stocks/frontend/src/layout/archetypes.ts)：已有 `list`、`master-detail`、`dashboard`、`form`、`detail`、`workbench`、`wizard` 原型预设。
- [validator.ts](/Users/pengshuaifeng/ai-stocks/frontend/src/layout/validator.ts)：已有 schema 层校验器，能校验组件下限、主表唯一、操作区一致性、响应式断点和可编辑白名单。
- [LayoutHost.vue](/Users/pengshuaifeng/ai-stocks/frontend/src/layout/components/LayoutHost.vue)：布局宿主消费 `PageLayout`，统一输出页面外壳、`VAdaptiveGrow`、`VMixedGrow`、整区滚动与响应式多列容器。
- [useLayoutConfig.ts](../../frontend/src/layout/useLayoutConfig.ts)：代码默认/页面/用户配置合并内核；页面运行时统一由 `useRemoteLayoutConfig` 包装，登录用户配置以 PG 为权威，localStorage 仅作为受控 fallback 和旧值迁移源。
- [componentConfig.ts](../../frontend/src/layout/componentConfig.ts)：`COMPONENT_FIELD_DEFS` 定义组件 Web 配置字段、开放层级、值域和适用性。
- [ComponentAutoSettings.vue](../../frontend/src/components/ComponentAutoSettings.vue)：页面设置抽屉和页面布局编辑器共用的组件字段安全渲染器。

已有单测：

- [validator.spec.ts](/Users/pengshuaifeng/ai-stocks/frontend/src/layout/__tests__/validator.spec.ts)：覆盖原型合规、尺寸下限、重排规则、滚动轴、editable path、取值域守门。
- [path.spec.ts](/Users/pengshuaifeng/ai-stocks/frontend/src/layout/__tests__/path.spec.ts)：覆盖点分路径读写。

### 2.3 页面接入情况

全部 `pageRegistry` 业务页面已经统一使用 `LayoutHost`、`getPageLayout` 和 `useRemoteLayoutConfig`。路由、registry、页面真实宿主消费与 `DESIGN.md` 页面登记由 `pageRegistry.spec.ts` 和布局契约测试双向守卫；新增页面不得依赖人工补记忆维持一致性。

### 2.4 已有配置存储能力

当前前端已有两类用户设置入口，登录态均以后端持久化为权威：

- [usePageSettings.ts](/Users/pengshuaifeng/ai-stocks/frontend/src/composables/usePageSettings.ts)：页面业务偏好，消费 `useUserPreference` 并写入 PG `user_preference`；localStorage 仅作为未登录/接口失败 fallback 和旧值迁移源。
- `useRemoteLayoutConfig`：一次读取 page/user 层和组件字段开放策略，结合代码 default 完成三层合并；登录态用户层写入 PG `layout_user_config`，组件路径保存必须带真实 `PageLayout` 校验归属。

后端已有系统配置覆盖层：

- [backend/storage/app_config.py](/Users/pengshuaifeng/ai-stocks/backend/storage/app_config.py)：`app_config` 表，点分路径存 JSON 值，具备白名单、类型、范围和跨字段校验。
- [backend/storage/ddl.py](/Users/pengshuaifeng/ai-stocks/backend/storage/ddl.py)：已定义 `app_config` 表。
- [backend/api/data_admin.py](/Users/pengshuaifeng/ai-stocks/backend/api/data_admin.py)：已有 `/settings` 读写系统设置的 API。

这些能力已经扩展为“预设-页面-用户”的布局配置优先级模型：平台布局配置写入 PG `layout_preset`、`layout_page_config`、`layout_field_policy`，真实页面用户层写入 PG `layout_user_config`，非布局用户偏好写入 PG `user_preference`。

### 2.5 持续治理重点

1. 新增真实组件时必须先复用同类实现，并判断它是内部实现、真实复用组件还是需要平台识别的系统组件 kind。
2. 页面登记 slot 后按 kind 自动继承适用字段；页面只声明结构能力、候选元数据和带原因的明确例外，不得恢复逐页字段白名单。
3. 新增组件字段必须同步前端字段定义与 schema、后端规则与实例归属、安全渲染、页面真实消费、系统组件覆盖状态和测试。
4. 普通页面必须消费 effective 接口返回的字段策略；策略关闭或实例不适用的历史值不得进入页面/用户合并。
5. 新页面继续由脚手架、维护矩阵、页面登记测试、布局契约、构建和关键交互验收共同守卫。
6. 视觉风格继续使用 `balanced` 稳定内置预设和管理员自定义预设，不重新增加散落 CSS 或历史内置 key。

## 3. 用户角色与使用场景

### 3.1 系统管理员 / 产品负责人

负责选择系统默认风格、管理预设、决定某个页面是否允许用户自定义、查看页面配置是否合规。

典型场景：

- 在视觉预设页启用 `balanced` 或管理员维护的自定义预设。
- 为某个业务页面指定默认页面密度、表格分页大小和默认显示列；这些都属于页面配置，不进入视觉预设。
- 禁止普通用户修改某些关键布局项，例如主内容区策略、组件顺序。

### 3.2 普通业务用户

只关注自己使用页面的便利性。可在页面设置中修改个人偏好，例如列显隐、默认分页、信息密度、搜索栏展开状态。

典型场景：

- 在榜单页隐藏不关心的列。
- 把当前页面密度改为紧凑，表格、按钮、表单、卡片和页面浮层统一跟随。
- 将默认分页从 20 改为 50。
- 将搜索栏默认设为展开更多条件。

### 3.3 前端开发者 / AI 开发代理

负责新建或改造页面。不能随意发明布局结构，必须基于布局原型、组件目录和校验器开发。

典型场景：

- 收到“新增某某列表页”需求后，从 `list` 原型开始，选择 `filter-bar`、`data-table`、`pagination`、`drawer` 等组件。
- 为页面声明 `PageLayout` 和组件配置。
- 运行校验器、构建和浏览器自适应检查。
- 在 `DESIGN.md` 或布局登记文件中记录页面选型。

### 3.4 设计 / 运营配置人员

不直接写代码，但可以配置预设风格和页面展示策略。

典型场景：

- 新增自定义预设，调整主色、边框、卡片密度、按钮风格和表格行高。
- 为不同页面选择已启用的自定义预设，同时保持业务结构和可读性红线不变。

## 4. 功能范围

### 4.1 必须实现

1. 布局系统核心数据模型升级：
   - 页面原型模型。
   - 组件目录模型。
   - 组件共同配置。
   - 组件专属配置。
   - 响应式规则模型。
   - 风格预设模型。
   - 配置覆盖模型。

2. 组件化能力：
   - 覆盖后台系统常用组件最小单元。
   - 每个组件有统一共同特性和专属特性。
   - 组件必须声明最低尺寸、理想尺寸、滚动归属、是否可 grow、是否可重排、状态占位策略。

3. 自适应能力：
   - 继承 `DESIGN.md` 的两层布局模型和兜底阶梯。
   - 支持根据浏览器窗口、容器宽度、分辨率、密度档位自动调整布局。
   - 支持容器查询或等效 ResizeObserver 策略。

4. 可配置能力：
   - 支持唯一稳定内置预设 `balanced` 与管理员自定义预设并持久化。
   - 支持页面级配置持久化。
   - 支持用户级配置持久化。
   - 合并优先级必须为：系统代码默认 < 预设配置 < 页面配置 < 用户配置。
   - 用户表述中的“预设-页面-用户”应理解为业务覆盖优先级从低到高，用户配置最高。

5. Web 配置界面：
   - 全局视觉预设管理。
   - 页面布局配置管理。
   - 页面组件配置管理。
   - 用户个人设置。
   - 配置校验、错误提示、重置、导入导出。

6. AI 开发稳定化：
   - 新页面必须选择布局原型。
   - 新页面必须选择组件清单。
   - 新页面必须声明页面配置和可编辑项。
   - 新页面必须通过布局校验器和构建。
   - 新页面必须登记布局选型。

7. 页面覆盖持续治理：
   - 全部 registry 业务页面统一消费布局宿主和远端页面/用户配置入口。
   - 新增或改造页面必须做小屏、滚动、密度、四态和关键交互验证。

### 4.2 建议实现

1. 配置导入导出：
   - 导出某个预设、某个页面配置、某个用户配置。
   - 导入时校验 schema 版本、组件是否存在、取值是否合法。

2. 页面开发脚手架：
   - 输入 `pageKey`、页面原型、组件清单，生成初始 `PageLayout` 和页面模板。
   - 自动生成待确认选型说明。

3. 配置版本与回滚：
   - 预设配置和页面配置记录版本号。
   - 管理员可回滚到历史版本。

4. 布局健康检查报告：
   - 输出页面是否存在整页滚动、双滚动、硬编码高度、未登记组件、未登记页面等问题。

5. 组件配置说明文档自动生成：
   - 从组件目录生成可配置项说明，减少文档和代码漂移。

### 4.3 暂不实现

1. 自由拖拽画布。
   - 原因：自由拖拽会破坏“布局规范可校验”的目标，容易回到随机布局。
   - 未来条件：若需要可视化搭建平台，可在当前 schema 基础上做受限拖拽，但仍必须过校验器。

2. 任意 CSS 自定义输入。
   - 原因：用户输入任意 CSS 会绕过规范，造成不可控溢出、双滚动和主题污染。
   - 可开放的预设 token 只包括语义颜色、边框、阴影和圆角，不能开放间距、密度或任意选择器。

3. 布局模块自建平行权限体系。
   - 原因：项目已有统一 RBAC、租户与用户归属模型；布局配置必须复用请求上下文、系统权限和现有资产隔离，不另建角色或身份来源。

4. 跨项目通用 npm 包。
   - 原因：当前首要目标是在本项目稳定落地。
   - 未来条件：本项目页面迁移稳定后，再抽为共享包或 Codex 技能模板。

## 5. 详细功能需求

### 5.1 布局领域模型

功能描述：

当前完整领域模型由以下事实对象组成：

- `LayoutPreset`：代码内置 `balanced`，并支持管理员维护的自定义风格预设。
- `PageLayout`：页面布局定义，包含页面原型、区域、组件 slot、响应式规则和布局旋钮。
- `ComponentMeta` / `COMPONENT_CATALOG`：组件目录定义，描述组件共同特性和能力摘要。
- `SlotSpec.config` / `ComponentInstanceConfig`：页面中某个组件实例的结构配置。
- `ResponsivePlan`：响应式断点与重排规则集合。
- `LayoutOverride`：配置覆盖记录，区分预设、页面、用户。
- `COMPONENT_FIELD_DEFS` / `layout_field_policy`：字段最大开放集、值域、实例适用性和管理员当前开放策略。

前置条件：

- 继续使用 Vue 3 + Element Plus。
- 继续复用 `frontend/src/layout/schema.ts` 的基本方向。

操作流程：

1. 开发者在组件目录登记组件类型。
2. 开发者选择页面原型，生成页面布局定义。
3. 系统加载代码默认配置。
4. 系统合并选中的预设配置。
5. 系统合并页面配置。
6. 系统合并当前用户配置。
7. 合并结果通过校验器后交给 `LayoutHost` 渲染。

输入输出：

- 输入：页面 key、预设 key、页面配置、用户配置。
- 输出：`EffectiveLayoutConfig`，即最终生效布局。

校验规则：

- 未登记组件不得出现在页面布局中。
- 组件实例配置不得低于组件目录声明的业务最低尺寸。
- 用户配置只能覆盖布局 `editable` 与组件字段最大层级、实例适用性、管理员当前策略共同允许的字段。
- 页面配置可以覆盖比用户更多的字段，但仍不能违反布局红线。
- 预设配置只能覆盖视觉 token、密度、组件默认表现，不得改变页面业务结构。

异常情况：

- 预设缺失：回落系统默认预设。
- 页面配置非法：回落该页面代码默认配置，并提示管理员。
- 用户配置非法：丢弃非法项，保留其他合法项。
- schema 版本不兼容：提示需要迁移或重置。

权限与数据范围：

- 普通用户只能修改用户级配置。
- 管理员可修改页面级配置和全局预设。
- 代码默认配置只能由开发流程变更。

对现有功能的影响：

- 页面必须通过 `useRemoteLayoutConfig` 消费远端 page/user、字段策略和本地 default；`useLayoutConfig` 只作为该入口内部的三层合并内核。
- `usePageSettings` 已纳入 PG 用户偏好骨架，后续页面业务偏好必须继续消费 `useUserPreference`，避免 L2 和 L3 两套入口割裂。

### 5.2 组件目录与组件共同特性

功能描述：

组件目录是布局系统的基础。凡是可作为页面最小布局单元的对象，都必须作为组件登记，包含共同特性和专属特性。

必须支持的组件类型：

| 类别 | 组件类型 | 说明 |
|---|---|---|
| 页面结构 | `page-shell`、`section`、`split-pane`、`slot-group` | 页面容器、区域、分栏、组件组 |
| 查询操作 | `filter-bar`、`search-box`、`advanced-filter`、`toolbar`、`batch-bar` | 搜索、筛选、工具栏、批量操作 |
| 数据展示 | `data-table`、`wide-table`、`simple-list`、`description-list`、`tree-table` | 表格、宽表、列表、描述、树表 |
| 表格附属 | `pagination`、`column-settings`、`sort-control`、`export-button` | 分页、列设置、排序、导出 |
| 表单输入 | `form`、`form-section`、`field-grid`、`inline-editor` | 创建、编辑、分组表单 |
| 反馈状态 | `loading-state`、`empty-state`、`error-state`、`skeleton` | 加载、空态、错误、骨架屏 |
| 数据摘要 | `kpi-grid`、`metric-card`、`stat-strip` | 指标卡、统计条 |
| 图表分析 | `chart`、`mini-chart`、`chart-grid`、`trend-panel` | 图表、趋势、分析面板 |
| 详情结构 | `detail-panel`、`drawer`、`dialog`、`side-panel` | 详情、抽屉、弹窗、侧栏 |
| 复杂布局 | `master-detail`、`tabs`、`steps`、`collapse`、`kanban`、`timeline` | 主从、标签、向导、折叠、看板、时间线 |
| 导航辅助 | `tree-nav`、`anchor-nav`、`breadcrumb` | 树、锚点、面包屑 |

组件共同特性：

- `id`：组件实例唯一标识。
- `kind`：组件类型。
- `label`：组件显示名。
- `region`：所属区域，例如 action、main、overlay。
- `order`：排序。
- `visible`：是否显示，可支持表达式或权限控制。
- `permission`：权限标识。
- `styleTokens`：白天/夜间语义色、边框、圆角和阴影；间距与密度属于独立页面契约。
- `minW`、`minH`：业务最低尺寸。
- `idealW`、`idealH`：理想尺寸。
- `maxW`、`maxH`：最大尺寸，主要用于弹窗、抽屉、侧栏。
- `scroll`：滚动归属，沿用 `none`、`body-y`、`body-xy`、`region`。
- `growMain`：是否吃富余空间。
- `reflowable`：是否可参与多列重排。
- `responsive`：组件级响应式规则。
- `states`：loading、empty、error、disabled、readonly 的展示策略。
- `dataBinding`：数据源、接口、字段映射。
- `actions`：组件内动作，例如刷新、导出、保存、取消。
- `editable`：允许 Web 配置的字段白名单。

组件专属特性示例：

- `data-table`：
  - 是否分页。
  - 默认分页大小。
  - 分页大小选项。
  - 显示列。
  - 列顺序。
  - 列宽。
  - 冻结列。
  - 操作列位置。
  - 是否多选。
  - 是否跨页保留选择。
  - 是否服务端分页。
  - 是否服务端排序。
  - 行点击行为。
  - 空态文案。

- `filter-bar`：
  - 搜索字段。
  - 默认展开字段。
  - 高级筛选开关。
  - 自动查询策略。
  - 回车查询策略。
  - 清空策略。
  - 是否记忆筛选条件。

- `form`：
  - 字段分组。
  - label 宽度。
  - 每行列数。
  - 必填规则。
  - 只读规则。
  - 底部按钮吸底。
  - 长表单内部滚动。

- `drawer`：
  - 方向。
  - 宽度档位。
  - 最大高度。
  - header/footer 是否固定。
  - body 滚动策略。
  - 是否允许点击遮罩关闭。

- `dialog`：
  - 尺寸档位。
  - 最大高度。
  - body 滚动策略。
  - footer 按钮区。
  - 是否居中。

- `chart`：
  - 图表类型。
  - 最低高度。
  - 宽高比。
  - legend 位置。
  - tooltip 策略。
  - 数据为空时占位。

- `tabs`：
  - tab 条是否吸顶。
  - tab 内容是否独立布局。
  - 默认激活项。
  - 是否记忆激活项。

校验规则：

- 每个组件类型必须有目录元信息。
- 每个组件专属配置必须有 schema。
- 组件共同特性与专属特性不能混在任意对象中，避免 AI 随意扩字段。
- 组件状态切换不能改变外层尺寸，必须遵守“loading / empty / error / 正常态同尺寸”。

### 5.3 页面原型与布局模板

功能描述：

页面原型用于降低 AI 和开发者选型成本。现有 A~G 原型需要保留并扩展组合模板。

必须支持的页面原型：

- `list`：列表页。
- `master-detail`：主从页。
- `dashboard`：仪表盘/概览页。
- `form`：表单/编辑页。
- `detail`：详情页。
- `workbench`：分析工作台。
- `wizard`：向导页。
- `settings`：配置管理页，建议新增。
- `data-admin`：数据管理页，建议新增。
- `report`：报告/复盘页，建议新增。

必须支持的组合模板：

- `filter-table-page`：筛选栏 + 工具栏 + 主表 + 分页。
- `filter-table-drawer`：筛选栏 + 主表 + 右侧详情抽屉。
- `master-table-detail`：左列表 + 右详情。
- `kpi-chart-table`：KPI + 图表 + 明细表。
- `form-drawer`：页面列表 + 抽屉表单。
- `tabs-with-layout`：Tabs，每个 Tab 内容独立套用布局系统。
- `settings-sections`：左侧锚点或 Tabs + 右侧配置表单。

前置条件：

- 原型必须由 `createLayout` 或同等工厂创建。
- 新增原型必须有校验器测试。

操作流程：

1. AI 根据需求判断页面类型。
2. 给出推荐原型和理由。
3. 用户确认或接受默认推荐。
4. AI 生成页面 layout schema。
5. AI 将业务组件填入具名 slot。

校验规则：

- `list` 原型必须恰好有一个主表或主列表作为 `growMain`。
- `dashboard` 原型只允许无强阅读顺序的组件参与重排。
- `workbench` 原型必须使用混合成长区，不能用 `.v-scroll` 替代。
- `tabs` 内容区必须作为新的第二层布局，不允许 Tab 内随意滚动。

### 5.4 自适应规则

功能描述：

自适应规则必须承接 `DESIGN.md` 的布局、滚动和响应式红线，并保持为可配置、可校验、可复用的代码模式。

必须实现的规则：

- 页面外壳永不滚动。
- 固定操作区按内容取高。
- 主内容区吃剩余高度。
- 剩余高度达到主组件有效 `minH` 时，主内容区不滚动，由主组件内部滚动；低于 `minH` 时才允许主内容区整体滚动兜底。
- 主表、主图、主列表优先内部滚动。
- 宽表只允许表体横向滚动，不允许整页横向滚动。
- 多组件在满足最低尺寸时可重排。
- 不满足重排条件时走区域整体滚动兜底。
- `min-height: 0`、表头吸顶、分页固定底部由渲染器统一处理。

响应式配置维度：

- viewport 宽度断点。
- 容器宽度断点。
- 分辨率密度，例如 1100×620 小屏。
- 信息密度档位：compact、standard、comfortable。
- 设备类型：desktop、laptop、tablet。
- 组件可读最低尺寸。
- 区域最大宽度和边距。

建议默认断点：

- `< 1024px`：单列。
- `1024px - 1439px`：两列，限平级组件。
- `>= 1440px`：可三列，限卡片、图表、KPI。

校验规则：

- 开启重排时，所有参与重排的组件必须 `reflowable=true`。
- 拆列后的净宽必须大于所有组件最低宽。
- 单个大表格不得通过多列重排解决高度问题。
- 响应式配置必须有 `minWidth=0` 的基础断点。

### 5.5 风格预设与主题配置

功能描述：

系统以 `balanced`（对外名称“澄空蓝”）作为唯一稳定内置预设，同时允许管理员在视觉预设页新增、启用和维护自定义预设。预设必须作为可存储配置存在，而不是散落在 CSS 中；历史内置 key 不再作为页面或导入导出契约。

预设配置项：

- 色彩 token：主色、成功、警告、危险、金融涨跌色和边框。
- 形态 token：共享圆角和阴影。

校验规则：

- 预设只能配置上述视觉 token，不得携带密度、间距、组件默认或响应式策略。
- 颜色必须满足基础可读性要求。
- 暗色预设必须覆盖 Element Plus 关键变量，避免局部亮色块。

### 5.6 配置覆盖与持久化

功能描述：

代码 default 保留在版本控制中；允许 page/user 层覆盖的布局、组件和响应式字段必须按其开放层级持久化。视觉 preset 独立承载颜色、圆角、边框和阴影，不参与页面配置合并。

配置优先级：

```text
系统代码默认 < 预设配置 < 页面配置 < 用户配置
```

层级说明：

- 系统代码默认：由开发者维护，作为兜底，不允许 Web 修改。
- 预设配置：管理员选择 `balanced` 或维护自定义预设。
- 页面配置：管理员针对某个页面的默认布局和组件设置。
- 用户配置：普通用户自己的显示偏好，优先级最高。

当前存储模型：

- `layout_preset`：预设内容、启停和内置标记。
- `layout_page_config`：页面选择的预设与页面层覆盖。
- `layout_field_policy`：按 `(component_kind, field)` 维护当前开放层级。
- `layout_user_config`：用户布局/组件覆盖；归属必须来自请求上下文中的真实租户与用户，禁止由前端传入 owner，也不得用空值或固定用户代替登录用户。

API 需求：

- `GET /api/layout/presets`：读取预设列表。
- `POST /api/layout/presets`：新增或更新预设。
- `GET /api/layout/pages/{pageKey}`：读取页面布局配置。
- `POST /api/layout/pages/{pageKey}`：保存页面级配置。
- `GET /api/layout/users/{pageKey}`：读取当前用户配置。
- `POST /api/layout/users/{pageKey}`：保存当前用户配置。
- `POST /api/layout/validate`：校验配置。
- `POST /api/layout/reset`：按范围重置预设、页面或用户配置。
- `GET /api/layout/effective/{pageKey}`：返回 page/user 分层配置、最终值/来源与当前组件字段开放策略；页面运行时结合代码 default 完成三层合并。

校验规则：

- 后端必须复用类似 `app_config._coerce` 的白名单、类型和范围校验。
- 前端也必须在 `coerceEditableValue` 层做即时校验。
- 前后端校验规则不能长期分叉，建议从同一份 schema 生成或共享规则定义。

存储边界：

- 预设、页面默认和字段开放策略以 PostgreSQL 的布局配置表为权威。
- 真实页面布局/组件用户层以 PostgreSQL `layout_user_config` 为权威。
- 页面业务偏好、主题、导航、K 线、回测参数记忆和设置抽屉跨页面偏好以 PostgreSQL `user_preference` 为权威。
- localStorage 仅保留为未登录/接口失败 fallback、旧偏好迁移源、登录前主题读取和临时交互态，不得重新成为登录用户配置权威。

### 5.7 Web 配置界面

功能描述：

系统需要提供可视化配置入口，但必须是受控配置，不是自由画布。

配置入口：

- 独立“布局配置”工作台：管理预设、默认风格、全局 token、页面默认配置和字段开放策略，不并入现有 `ConfigView`。
- 页面设置抽屉：当前页面的布局、自动继承的组件设置和显式业务选项。
- 管理员页面配置页：针对页面配置默认值和可编辑策略。
- 视觉预设、页面布局和系统组件三个平台布局管理页只管理系统配置，不开放个人页面设置；`pageRegistry` 必须以 `supportsPageSettings=false` 明确排除，不得登记页面未消费的 `settings-drawer` 或配置字段。

页面设置抽屉固定分组：

- 布局：当前页面开放的布局旋钮。
- 组件设置：页面已登记 slot 自动继承且当前实例、用户层策略均适用的组件字段。
- 业务选项：页面通过 `#business` 显式提供业务偏好，不展示存储实现类徽标。

没有内容的分组不得渲染；视觉预设、页面布局和系统组件三个平台管理页不开放个人页面设置。

操作要求：

- 布局旋钮由布局 schema 生成；组件字段由 `COMPONENT_FIELD_DEFS` 经 `ComponentAutoSettings` 自动生成，动态候选使用页面 `componentMeta`；业务选项由页面显式声明。
- enum 使用分段器或下拉。
- bool 使用开关。
- number 使用数字输入，并显示最小最大值。
- 复杂对象使用配置表或分组表单。
- 非法配置不能保存。
- 普通页面必须通过 `/layout/effective/{pageKey}` 一次获取 page/user 层及组件字段开放策略，结合代码 default 完成三层合并。
- 页面登记组件 slot 后不得再维护逐页字段白名单；结构能力、候选元数据和明确例外共同决定实例适用性。
- 历史已存但被管理员策略关闭或对当前实例不适用的值必须在运行时丢弃，写接口也必须拒绝。
- 系统组件页必须展示每个字段在各消费页面 slot 的自动继承、策略关闭或不适用状态与原因。
- 保存后即时生效。
- 支持恢复默认，且要区分恢复用户默认、页面默认、预设默认。
- 页面业务抽屉宽度只允许 `PageDrawer` 的 `sm/md/lg/xl/xxl/wide` 语义档位；`wide=clamp(560px, 46%, 760px)` 仅用于日志、字段差异和长 JSON 等横向内容，`xl=560px` 用于固定宽度复杂详情和组件预览，`xxl=clamp(640px, 60%, 820px)` 用于资产搜索等需要更宽横向空间的复杂详情。页面设置抽屉只开放 `sm/md/lg`，页面不得传 px 或百分比宽度。

异常情况：

- 后端保存失败：保留当前页面状态，提示错误，不污染本地缓存。
- 配置版本不匹配：提示重置或迁移。
- 当前用户无权限：隐藏或禁用管理级配置项。

### 5.8 AI 开发稳定化流程

功能描述：

布局系统必须服务于后续 AI 开发。AI 不能每次重新理解页面布局规范，而应按固定流程产出页面。

新页面开发流程：

1. 读取 `DESIGN.md`、同目录 `page-template.md` 和 `frontend/src/layout` 事实源。
2. 根据需求判断页面类型。
3. 从原型注册表选择页面原型，并给出理由。
4. 先查真实复用组件，再列出组件清单，包括真实组件、系统 kind、业务作用、区域、是否 grow、是否可配置。
5. 选择风格预设，默认继承系统预设。
6. 在 `pageRegistry` 登记独立系统组件 slot；已有 kind 自动继承字段，结构、候选和明确例外分别写入 slot `config`、`componentMeta` 和 `fieldApplicability`。
7. 使用 `LayoutHost` 填业务 slot，并通过 `useRemoteLayoutConfig` 将 `componentAllowedLayers` 接入 `PageSettingsDrawer`。
8. 运行布局校验器和前端构建。
9. 做浏览器验证：至少覆盖 1100×620 和常规桌面宽度。
10. 登记页面布局选型、组件清单和可编辑项。

AI 输出物要求：

- 页面布局选型说明。
- `PageLayout` 或新 schema。
- 组件配置清单。
- 可编辑项清单。
- 校验结果。
- 页面登记更新。

验收红线：

- 不得新增视口硬编码高度。
- 不得绕过 `LayoutHost` 手写页面布局外壳。
- 不得新增未登记组件类型。
- 不得将页面业务结构放入用户级配置。
- 不得把不可重排的大表格放进多列重排。

### 5.9 页面覆盖持续治理

功能描述：

全部 registry 业务页面已经完成统一迁移。新增页面或改造已有页面时继续满足：

- 明确页面原型。
- 明确组件清单。
- 明确布局旋钮、组件字段、页面业务记忆及各自持久化边界。
- 页面 slot 自动继承适用组件字段，并真实消费字段生效值和管理员字段策略。
- 通过单测和构建。
- 小屏不出现整页滚动。
- 表格表头吸顶、分页固定。
- 路由、registry、页面宿主消费与 DESIGN 登记保持机器可校验的一致。

## 6. 数据与接口需求

### 6.1 前端数据结构

当前 `/layout/effective/{pageKey}` 响应契约由 `frontend/src/api/layout.ts` 的 `EffectiveLayoutConfig` 维护：

```ts
interface EffectiveLayoutConfig {
  pageKey: string
  userId: string
  schemaVersion: number
  presetKey: string | null
  values: LayoutOverlayValues
  source: Record<string, 'page' | 'user'>
  layers: Array<{ layer: 'page' | 'user'; config: LayoutOverride }>
  componentFieldPolicies: FieldPolicyRecord[]
}
```

`presetKey` 仅为旧客户端保留且恒为 `null`。前端再与代码 default 合并并生成完整来源链；`componentFieldPolicies` 同时约束普通页面渲染和写入，不能只在管理员配置中心展示。

### 6.2 后端存储

布局配置使用 PostgreSQL 专用表：`layout_preset`、`layout_page_config`、`layout_field_policy`、`layout_user_config`；`app_config` 只承载 `ui.display.auto_scale_exponent` 等系统运行参数，不作为页面布局覆盖的临时或并行存储入口。用户归属统一来自请求上下文中的 `tenant_id + owner_user_id`。

### 6.3 API 响应结构

所有接口遵循现有 `ApiResponse` 包装风格。

校验接口返回示例：

```json
{
  "valid": false,
  "issues": [
    {
      "level": "error",
      "code": "slot.minH.below",
      "message": "table 最低高低于数据表格下限",
      "path": "components.table.minH"
    }
  ]
}
```

### 6.4 数据一致性

- 保存页面配置时，必须先校验合并后的 effective 配置。
- 删除预设前，必须检查是否被页面引用。
- 视觉预设可独立启停，不得与页面布局形成引用关系。
- schema 升级时必须提供迁移函数或重置策略。

## 7. 交互体验要求

### 7.1 页面运行体验

- 页面必须保持整页不滚动。
- 操作区固定，不被主内容挤压。
- 主内容区自动吃剩余空间。
- 表格分页固定，表体滚动。
- loading、empty、error、normal 状态尺寸一致。
- 抽屉和弹窗不顶穿视口。

### 7.2 配置体验

- 配置项要按用户理解分组，不直接暴露底层字段名。
- 每项配置需要有当前值、默认值、来源层级。
- 修改后即时预览。
- 保存失败时提示具体原因。
- 支持单项重置和整体重置。
- 管理员配置与个人配置要视觉区分。

### 7.3 风格切换体验

- 切换预设后不应导致页面结构丢失。
- 切换预设只影响语义色、边框、阴影和共享圆角。
- 页面密度、分页、抽屉宽度、筛选状态、响应式结构和用户个人覆盖项均保持不变。

### 7.4 AI 开发体验

- AI 能从组件目录和原型注册表直接选型。
- AI 能通过校验器得到明确错误，而不是靠肉眼看页面。
- AI 开发完成后能生成页面登记信息。

## 8. 边界条件与异常场景

- 浏览器高度很低，例如 1100×620：应用外壳不得滚动；达到主组件 `minH` 时由组件内部滚动，低于 `minH` 时由主内容区滚动兜底。
- 表格分页大小改为 100：表体内部滚动，分页不被挤出。
- 搜索条件很多：筛选栏默认一行，支持展开更多，展开后挤压主内容区。
- 宽表列很多：表体横向滚动，冻结关键列，不让整页横滚。
- 抽屉内容很长：header/footer 固定，body 内滚。
- 弹窗 teleport 到 body：样式必须使用非 scoped 全局唯一类处理 Element Plus 内部结构。
- 用户保存了旧版本配置：系统丢弃非法项或执行迁移，不让页面崩溃。
- 预设被删除：页面回落系统默认预设。
- 组件目录变更：引用已删除组件的页面配置必须校验失败并回落。
- 页面配置和用户配置冲突：用户配置优先，但不能突破校验器。

## 9. 性能、安全与兼容性要求

### 9.1 性能

- effective 配置合并必须轻量，页面切换时不应明显卡顿。
- 配置修改应局部生效，避免重建整页复杂数据。
- ResizeObserver 使用需节流，避免频繁重排。
- 大表仍依赖 Element Plus 表格滚动；如后续数据量极大，再评估虚拟表格。

### 9.2 安全

- 用户不得输入任意 CSS。
- 用户不得覆盖未开放字段。
- 后端保存必须做白名单校验。
- 配置 JSON 不得直接作为 HTML 渲染。
- 权限字段不能只靠前端隐藏，管理级 API 必须后端校验。

### 9.3 兼容性

- 支持当前项目主流桌面浏览器。
- 至少验证小屏笔记本 1100×620。
- Element Plus 的抽屉、弹窗、表格样式必须兼容 teleport 和 scoped 样式限制。
- 现有 localStorage 配置变更时要兼容旧值，不可导致页面白屏。

## 10. 业务亮点与优化建议

1. 形成“页面开发资产库”。
   - 每个页面的原型、组件、配置项都有登记，后续 AI 开发不再从空白开始。

2. 形成“可管控的个性化”。
   - 用户可以配置自己的体验，但不能破坏业务结构和布局红线。

3. 形成“风格产品化”。
   - `balanced` 与管理员自定义预设都是可选择、可存储、可导出的配置资产，不把风格重新写成页面私有 CSS 或代码内置 key。

4. 形成“规范可执行”。
   - 自适应规范不再只写在 Markdown，而是变成 schema、渲染器、校验器和测试。

5. 形成“AI 稳定交付闭环”。
   - AI 每次新建页面都按固定选型流程，减少随机 CSS、随机滚动、随机布局层级。

## 11. 落地可行性与实施路径

### 11.1 当前落地结论

该需求已经完整落地：组件能力目录、七类页面原型、`LayoutHost`、代码默认/页面/用户三层合并、PG 持久化、字段开放策略、统一设置抽屉、三页布局配置工作台、页面脚手架和机器契约均已投入使用。后续工作属于持续治理，不得重新启用逐页字段白名单、页面私有 localStorage、平行配置表单或旧内置预设 key。

### 11.2 已完成里程碑

#### M1：需求定型与现状修正（已完成）

- 补齐本需求文档。
- 建立 `DESIGN.md` 页面登记，并由机器契约保持全部 registry 页面一致。
- 明确配置优先级为“系统代码默认 < 预设 < 页面 < 用户”。
- 明确不做自由拖拽画布。

#### M2：组件目录升级（已完成）

- 扩展 `ComponentKind`。
- 为每类组件定义共同特性和专属配置 schema。
- 将 `COMPONENT_CATALOG` 从“最低尺寸目录”升级为“组件能力目录”。
- 增加组件目录单测。

#### M3：风格预设模型（已完成）

- 新增 `LayoutPreset` 类型。
- 内置唯一稳定预设 `balanced`（澄空蓝），并允许管理员维护自定义预设。
- 将 CSS token 与预设配置关联。
- 实现预设切换并持久化。

#### M4：配置覆盖链路（已完成）

- 前端实现 `default -> preset -> page -> user` 合并。
- 后端新增布局配置表和 API。
- 前端设置面板显示配置来源。
- 用户配置非法时按项丢弃，不影响页面。

#### M5：Web 配置中心（已完成）

- 新增独立“布局配置”页面。
- 增加视觉预设。
- 增加页面配置管理。
- 增加导入导出和重置。

#### M6：AI 开发流程固化（已完成）

- 增加页面开发模板。
- 增加页面选型确认清单。
- 增加布局校验报告。
- 更新 `DESIGN.md` 和 `CLAUDE.md`。

#### M7：存量页面迁移（已完成）

- 全部 registry 业务页面统一迁移。
- 新增或改造页面继续执行构建、单测和必要的浏览器验证。
- 页面登记、组件 slot、可配置项和真实消费由机器契约持续同步。

## 12. 验收标准

1. 组件目录验收：
   - 至少覆盖本需求列出的后台常用组件类型。
   - 每类组件都有共同特性、专属特性、最低尺寸、滚动归属、可重排标记。
   - 未登记组件不能通过校验。

2. 自适应验收：
   - 1100×620 下页面无整页滚动。
   - 主表表体内滚，表头吸顶，分页固定。
   - 多组件页面按规则重排或区域滚动。
   - 不存在新增 `height: calc(100vh - Npx)`。

3. 配置验收：
   - 系统内置 `balanced`（澄空蓝），并支持管理员自定义预设的持久化、启停、切换和导入导出。
   - 配置合并优先级满足：系统代码默认 < 预设 < 页面 < 用户。
   - 页面配置和用户配置都能持久化。
   - 非法配置被拒绝或丢弃，页面不崩溃。

4. Web 配置验收：
   - 用户可以在页面设置中修改当前页面开放的布局、自动继承组件字段和显式业务选项。
   - 不消费个人设置的平台布局管理页不展示设置入口，也不登记 `settings-drawer` 假能力。
   - 管理员可以管理预设和页面默认配置。
   - 每项配置能看到当前值、默认值或来源层级。
   - 支持重置。

5. AI 开发稳定化验收：
   - 新页面开发必须产出页面原型、组件清单、配置清单。
   - 新页面必须使用 `LayoutHost`。
   - 新页面必须通过布局校验器和前端构建。
   - 新页面必须登记到设计文档或布局注册表。

6. 存量页面验收：
   - 全部 registry 业务页面的登记状态、原型、组件 slot、可编辑项与代码消费一致。
   - 新增页面必须由脚手架、页面登记测试和布局契约阻止旧实现回流。

## 13. 已确认决策

以下事项已由用户确认，后续实施计划按此执行，不再作为遗留问题处理：

1. 内置风格预设固定为 `balanced`（澄空蓝）。
   - 影响：代码默认、token 回退和测试以该稳定 key 为准；其他风格通过视觉预设作为自定义配置维护，不扩张代码内置 key。

2. 用户配置持久化采用推荐节奏。
   - 决策：配置存储 PG 迁移已经完成；登录用户布局/组件用户层和非布局用户偏好均以 PostgreSQL 为权威，localStorage 不再作为登录用户配置权威。

3. 布局配置复用现有多租户 RBAC。
   - 决策：平台预设、页面配置和字段策略使用系统级权限；用户配置按请求上下文写入真实 `tenant_id + owner_user_id`，前端不决定归属。

4. Web 配置中心新开独立“布局配置”页面。
   - 决策：不并入现有 `ConfigView`，避免系统运行参数和布局配置混杂。

5. 允许管理员新增自定义风格预设。
   - 决策：只开放 token 和受控策略，不开放任意 CSS。

6. 页面级配置允许调整组件顺序，但仅限管理员。
   - 决策：普通用户不允许调整页面业务结构，只能修改个人展示偏好。

7. 需要配置导出能力，用于跨环境迁移和复盘。
   - 决策：作为 M5 范围实现，导入时必须校验 schema version、组件存在性、取值域和权限。
