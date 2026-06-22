# 需求文档

## 1. 背景与目标

当前项目已经开始建设可配置布局系统，但现有方向偏向“把自适应布局规范代码化”，覆盖范围仍偏窄：它能约束页面外壳、主内容区、密度和少量布局参数，但还没有形成用户期望的“组件化、自适应化、可配置化、AI 开发稳定化”的完整 Web 布局系统。

本需求目标是基于现有 `frontend/src/layout/` 底座，升级为一套面向后台系统页面开发的自定义 Web 布局系统。该系统不是自由拖拽大屏，也不是只切换主题色，而是以“组件目录 + 布局原型 + 响应式规则 + 配置覆盖层 + 校验器 + AI 开发流程”为核心，让新页面开发时能稳定地按以下模式推进：

1. 选择页面原型。
2. 选择组件清单。
3. 选择全局风格预设。
4. 声明页面级补充配置。
5. 通过校验器和渲染器生成合规页面。
6. 用户在 Web 设置面板中做受控调整并持久化。

最终效果：

- 前端布局不再依赖 AI 临时手写 `.v-page`、`.v-grow`、`height: calc(100vh - Npx)` 等不稳定写法。
- 列表、搜索、表单、抽屉、弹窗、图表、主从、工作台等常见后台场景都有可登记、可配置、可校验的最小组件单元。
- 政务风、科技风、专业金融后台风等预设风格可存储、可切换，并支持页面级和用户级覆盖。
- 新页面交给 AI 开发时，有明确的“选型-声明-填充-校验-登记”开发抓手，减少随机开发和页面规范漂移。

## 2. 当前项目现状

### 2.1 已有布局规范依据

项目已有硬性布局规范：[ai-agent/前端布局自适应规范.md](/Users/pengshuaifeng/ai-stocks/ai-agent/前端布局自适应规范.md)。

该规范已经明确了核心模型：

- 整页/视口永不滚动。
- 页面外壳分为固定操作区和主内容区。
- 主内容区按组件最低尺寸、理想尺寸和兜底阶梯处理。
- 兜底顺序为组件内部滚动、满足条件才重排多列、最后主内容区整体滚动。
- 列表、宽表格、筛选栏、表单、KPI、图表、主从、树、Tabs、抽屉、弹窗等都有最低尺寸和滚动归属要求。

这部分是本需求必须继续保留并代码化的核心，不应退回成纯文档约束。

### 2.2 已有代码底座

项目已经有初版布局系统，位于 [frontend/src/layout](/Users/pengshuaifeng/ai-stocks/frontend/src/layout)：

- [schema.ts](/Users/pengshuaifeng/ai-stocks/frontend/src/layout/schema.ts)：定义 `PageLayout`、`Archetype`、`SlotSpec`、`ComponentKind`、`EditableKnob` 等类型。
- [components.ts](/Users/pengshuaifeng/ai-stocks/frontend/src/layout/components.ts)：已有组件最低尺寸目录 `COMPONENT_CATALOG`。
- [archetypes.ts](/Users/pengshuaifeng/ai-stocks/frontend/src/layout/archetypes.ts)：已有 `list`、`master-detail`、`dashboard`、`form`、`detail`、`workbench`、`wizard` 原型预设。
- [validator.ts](/Users/pengshuaifeng/ai-stocks/frontend/src/layout/validator.ts)：已有 schema 层校验器，能校验组件下限、主表唯一、操作区一致性、响应式断点和可编辑白名单。
- [LayoutHost.vue](/Users/pengshuaifeng/ai-stocks/frontend/src/layout/components/LayoutHost.vue)：已有布局宿主，消费 `PageLayout` 并输出 `.v-page`、`.v-grow`、`.v-scroll`、`VMixedGrow`、`VColumns`。
- [useLayoutConfig.ts](/Users/pengshuaifeng/ai-stocks/frontend/src/layout/useLayoutConfig.ts)：已有 L2 覆盖层，使用 localStorage 存储用户布局覆盖。
- [LayoutSettingsSection.vue](/Users/pengshuaifeng/ai-stocks/frontend/src/layout/components/LayoutSettingsSection.vue)：已有基于 `editable` 自动渲染的布局设置表单。

已有单测：

- [validator.spec.ts](/Users/pengshuaifeng/ai-stocks/frontend/src/layout/__tests__/validator.spec.ts)：覆盖原型合规、尺寸下限、重排规则、滚动轴、editable path、取值域守门。
- [path.spec.ts](/Users/pengshuaifeng/ai-stocks/frontend/src/layout/__tests__/path.spec.ts)：覆盖点分路径读写。

### 2.3 已有页面接入情况

已有页面开始使用 `LayoutHost`：

- [BoardView.vue](/Users/pengshuaifeng/ai-stocks/frontend/src/views/BoardView.vue)：每日榜单，使用 `list` 原型，开放 `density` 信息密度。
- [QualityView.vue](/Users/pengshuaifeng/ai-stocks/frontend/src/views/data/QualityView.vue)：数据质量页也已接入 `LayoutHost` 和 `useLayoutConfig`。

但 [DESIGN.md](/Users/pengshuaifeng/ai-stocks/DESIGN.md) 当前只登记了 `BoardView`，说明现有文档与实际改造进度已经有轻微不同步，后续需要把页面登记作为验收项。

### 2.4 已有配置存储能力

当前前端已有两类本地设置：

- [usePageSettings.ts](/Users/pengshuaifeng/ai-stocks/frontend/src/composables/usePageSettings.ts)：页面组件偏好，使用 `localStorage`，例如列显隐、排序、默认 Top N。
- [useLayoutConfig.ts](/Users/pengshuaifeng/ai-stocks/frontend/src/layout/useLayoutConfig.ts)：布局参数覆盖，使用 `localStorage`，例如 `density`。

后端已有系统配置覆盖层：

- [backend/storage/app_config.py](/Users/pengshuaifeng/ai-stocks/backend/storage/app_config.py)：`app_config` 表，点分路径存 JSON 值，具备白名单、类型、范围和跨字段校验。
- [backend/storage/ddl.py](/Users/pengshuaifeng/ai-stocks/backend/storage/ddl.py)：已定义 `app_config` 表。
- [backend/api/data_admin.py](/Users/pengshuaifeng/ai-stocks/backend/api/data_admin.py)：已有 `/settings` 读写系统设置的 API。

这些能力可以复用，但当前还没有面向布局系统的专用后端表和 API，也没有“预设-页面-用户”的布局配置优先级模型。

### 2.5 当前主要差距

1. 组件目录偏基础，只覆盖了布局类型和最低尺寸，没有完整定义每类组件的共同特性、专属特性、状态、数据绑定、操作区、权限、空态、错误态、加载态等配置。
2. 原型只有页面布局原型，缺少组件组合模板，例如“筛选 + 批量 + 主表 + 分页”、“主表 + 右抽屉详情”、“图表 + 明细表”等高频业务组合。
3. 风格预设没有一等模型。当前只有 CSS 变量和 `density`，没有政务风、科技风、专业后台风等可存储、可切换预设。
4. 覆盖优先级不满足目标。当前是代码默认 schema + 用户 localStorage 覆盖，缺少“预设配置 -> 页面配置 -> 用户配置”的明确合并链路。
5. Web 配置能力偏弱。当前设置面板只能渲染少量 `editable` 旋钮，不能管理全局预设、页面配置、组件目录、响应式规则、导入导出和重置范围。
6. AI 开发流程还停留在文档提醒和代码约束，缺少面向 AI 的页面开发清单、页面 schema 模板、选型确认表、自动校验报告和登记机制。

## 3. 用户角色与使用场景

### 3.1 系统管理员 / 产品负责人

负责选择系统默认风格、管理预设、决定某个页面是否允许用户自定义、查看页面配置是否合规。

典型场景：

- 在后台设置中切换系统为“政务风”或“科技风”。
- 为某个业务页面指定默认布局密度、表格分页大小、默认显示列。
- 禁止普通用户修改某些关键布局项，例如主内容区策略、组件顺序。

### 3.2 普通业务用户

只关注自己使用页面的便利性。可在页面设置中修改个人偏好，例如列显隐、默认分页、信息密度、搜索栏展开状态。

典型场景：

- 在榜单页隐藏不关心的列。
- 把表格密度改为紧凑。
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

- 新增“政务稳重风”预设，调整主色、边框、卡片密度、按钮风格、表格行高。
- 为数据大屏类页面选择“科技风”，为管理台选择“专业后台风”。

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
   - 继承 `前端布局自适应规范.md` 的两层模型和兜底阶梯。
   - 支持根据浏览器窗口、容器宽度、分辨率、密度档位自动调整布局。
   - 支持容器查询或等效 ResizeObserver 策略。

4. 可配置能力：
   - 支持固定风格预设并持久化。
   - 支持页面级配置持久化。
   - 支持用户级配置持久化。
   - 合并优先级必须为：系统代码默认 < 预设配置 < 页面配置 < 用户配置。
   - 用户表述中的“预设-页面-用户”应理解为业务覆盖优先级从低到高，用户配置最高。

5. Web 配置界面：
   - 全局风格预设管理。
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

7. 现有页面渐进迁移：
   - 优先迁移高频列表页和已接近规范的页面。
   - 每个页面迁移后要做小屏验证、滚动验证、密度切换验证。

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
   - 未来条件：可开放 token 级变量，例如颜色、间距、圆角、密度档位，不能开放任意选择器。

3. 多租户权限体系。
   - 原因：当前项目 `training_session.user_id` 等字段仍是预留，多用户体系不是本需求前置。
   - 未来条件：系统引入真实登录用户和角色后，再扩展配置表的 `user_id`、`tenant_id`、`role_id`。

4. 跨项目通用 npm 包。
   - 原因：当前首要目标是在本项目稳定落地。
   - 未来条件：本项目页面迁移稳定后，再抽为共享包或 Codex 技能模板。

## 5. 详细功能需求

### 5.1 布局领域模型

功能描述：

布局系统必须从当前 `PageLayout` 扩展为完整领域模型，至少包含以下对象：

- `LayoutPreset`：风格预设，例如政务风、科技风、专业后台风。
- `PageLayoutDefinition`：页面布局定义，包含页面原型、区域、组件槽、响应式规则。
- `ComponentDefinition`：组件目录定义，描述组件共同特性和专属特性。
- `ComponentInstanceConfig`：页面中某个组件实例的配置。
- `ResponsiveRuleSet`：响应式规则集合。
- `LayoutOverride`：配置覆盖记录，区分预设、页面、用户。
- `EditablePolicy`：配置可编辑策略，说明哪些层级可改、哪些角色可改、取值范围是什么。

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
- 用户配置只能覆盖 `EditablePolicy` 允许的字段。
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

- 当前 `useLayoutConfig` 需要升级为从多层配置源读取，而不是只读 localStorage。
- 当前 `usePageSettings` 可保留，但需要纳入统一配置视图，避免 L2 和 L3 两套入口割裂。

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
- `styleTokens`：背景色、文字色、边框、圆角、阴影、间距、密度。
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

自适应规则必须承接 `前端布局自适应规范.md` 的核心精华，并扩展为可配置、可校验、可复用的代码模式。

必须实现的规则：

- 页面外壳永不滚动。
- 固定操作区按内容取高。
- 主内容区吃剩余高度。
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

系统必须提供几套固定风格预设，预设本身作为可存储配置存在，而不是只散落在 CSS 中。

必须内置的预设建议：

1. `professional`：专业后台风，默认风格。
   - 用于数据、股票、回测、配置管理等高密度业务页面。
   - 特点：低饱和、清晰边界、信息密度高、少装饰。

2. `government`：政务风。
   - 用于稳重、规范、低视觉噪音的管理系统。
   - 特点：蓝白基调、清晰分组、表单和列表可读性优先。

3. `technology`：科技风。
   - 用于分析、监控、概览、数据驾驶舱。
   - 特点：深浅两套可选、强调图表和状态色，但不能牺牲可读性。

4. `finance`：金融数据风。
   - 用于行情、回测、榜单、策略分析。
   - 特点：紧凑、数字对齐、涨跌色、表格扫描效率高。

5. `high-contrast`：高对比可访问风。
   - 用于可访问性和复杂光照环境。
   - 特点：对比度高、交互状态明显、弱化装饰。

预设配置项：

- 色彩 token：主色、成功、警告、危险、信息、背景、卡片、边框、文本。
- 密度 token：页面 gap、卡片 padding、表格行高、表单项间距。
- 形态 token：圆角、阴影、边框强度。
- 组件默认策略：表格是否紧凑、筛选栏默认是否折叠、抽屉宽度档位。
- 响应式默认策略：默认断点、默认列数、默认主区策略。

校验规则：

- 预设只能配置 token 和默认策略，不能删除页面业务组件。
- 颜色必须满足基础可读性要求。
- 密度不能低于组件目录最低尺寸。
- 暗色预设必须覆盖 Element Plus 关键变量，避免局部亮色块。

### 5.6 配置覆盖与持久化

功能描述：

所有布局、组件、响应式、风格配置都必须可存储。最终生效配置按层合并。

配置优先级：

```text
系统代码默认 < 预设配置 < 页面配置 < 用户配置
```

层级说明：

- 系统代码默认：由开发者维护，作为兜底，不允许 Web 修改。
- 预设配置：管理员选择或维护，例如政务风、科技风。
- 页面配置：管理员针对某个页面的默认布局和组件设置。
- 用户配置：普通用户自己的显示偏好，优先级最高。

建议数据表：

```sql
layout_preset(
  id,
  name,
  style_key,
  schema_version,
  config_json,
  builtin,
  enabled,
  created_at,
  updated_at
)

layout_page_config(
  page_key,
  schema_version,
  preset_id,
  config_json,
  editable_policy_json,
  updated_at
)

layout_user_config(
  user_id,
  page_key,
  schema_version,
  config_json,
  updated_at
)
```

当前项目单用户阶段可先将 `user_id` 置空或使用固定值，但接口和表结构建议预留。

API 需求：

- `GET /api/layout/presets`：读取预设列表。
- `POST /api/layout/presets`：新增或更新预设。
- `GET /api/layout/pages/{pageKey}`：读取页面布局配置。
- `POST /api/layout/pages/{pageKey}`：保存页面级配置。
- `GET /api/layout/users/{pageKey}`：读取当前用户配置。
- `POST /api/layout/users/{pageKey}`：保存当前用户配置。
- `POST /api/layout/validate`：校验配置。
- `POST /api/layout/reset`：按范围重置预设、页面或用户配置。
- `GET /api/layout/effective/{pageKey}`：返回最终生效配置。

校验规则：

- 后端必须复用类似 `app_config._coerce` 的白名单、类型和范围校验。
- 前端也必须在 `coerceEditableValue` 层做即时校验。
- 前后端校验规则不能长期分叉，建议从同一份 schema 生成或共享规则定义。

迁移策略：

- 第一阶段可继续使用 localStorage 验证交互。
- 第二阶段将预设和页面配置落后端，形成管理员可维护的系统级和页面级默认值。
- 第三阶段用户配置也接入后端，localStorage 只做离线缓存或降级；在真实多用户和权限管理接入前，用户级配置可先继续使用 localStorage。

### 5.7 Web 配置界面

功能描述：

系统需要提供可视化配置入口，但必须是受控配置，不是自由画布。

配置入口：

- 新增独立“布局配置”页面：管理预设、默认风格、全局 token、页面默认配置和可编辑策略，不并入现有 `ConfigView`。
- 页面设置抽屉：当前页面的布局、组件和个人偏好。
- 管理员页面配置页：针对页面配置默认值和可编辑策略。

页面设置抽屉建议分组：

- 风格：当前预设、明暗模式、密度。
- 布局：主区策略、断点列数、组件顺序、最低高度。
- 组件：表格列、分页、筛选栏、图表、抽屉。
- 个人偏好：排序、默认筛选、列显隐。

操作要求：

- 所有可配置项由 schema 自动生成控件。
- enum 使用分段器或下拉。
- bool 使用开关。
- number 使用数字输入，并显示最小最大值。
- 复杂对象使用配置表或分组表单。
- 非法配置不能保存。
- 保存后即时生效。
- 支持恢复默认，且要区分恢复用户默认、页面默认、预设默认。

异常情况：

- 后端保存失败：保留当前页面状态，提示错误，不污染本地缓存。
- 配置版本不匹配：提示重置或迁移。
- 当前用户无权限：隐藏或禁用管理级配置项。

### 5.8 AI 开发稳定化流程

功能描述：

布局系统必须服务于后续 AI 开发。AI 不能每次重新理解页面布局规范，而应按固定流程产出页面。

新页面开发流程：

1. 读取 `DESIGN.md` 布局系统章和 `frontend/src/layout` 目录。
2. 根据需求判断页面类型。
3. 从原型注册表选择页面原型，并给出理由。
4. 列出组件清单，包括组件 kind、业务作用、区域、是否 grow、是否可配置。
5. 选择风格预设，默认继承系统预设。
6. 声明页面级配置和用户可编辑项。
7. 使用 `LayoutHost` 填业务 slot。
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

### 5.9 现有页面迁移

功能描述：

当前项目页面需要按风险分批迁移，不应一次性大改。

建议迁移顺序：

1. 已接入页面补登记和修正：
   - `BoardView`
   - `QualityView`

2. 高频列表页：
   - `StocksView`
   - `ScreenView`
   - 数据管理相关列表页。

3. 工作台和复杂页：
   - `BacktestView`
   - `OverviewView`
   - `TrainingView`

4. 配置和表单页：
   - `ConfigView`
   - 各 profile 配置页。

每页迁移要求：

- 明确页面原型。
- 明确组件清单。
- 明确 L2 和 L3 可配置项。
- 通过单测和构建。
- 小屏不出现整页滚动。
- 表格表头吸顶、分页固定。
- 页面登记更新。

## 6. 数据与接口需求

### 6.1 前端数据结构

建议扩展当前 `PageLayout`：

```ts
interface EffectiveLayoutConfig {
  pageKey: string
  schemaVersion: number
  presetKey: string
  layout: PageLayoutDefinition
  components: ComponentInstanceConfig[]
  styleTokens: StyleTokenConfig
  responsive: ResponsiveRuleSet
  editablePolicy: EditablePolicy
  sourceMeta: {
    preset?: string
    page?: string
    user?: string
  }
}
```

`sourceMeta` 用于 Web 配置界面展示某个值来自预设、页面还是用户，方便用户理解“为什么这个值生效”。

### 6.2 后端存储

推荐新增布局专用表，不建议把复杂布局配置塞入现有 `app_config`：

- `app_config` 更适合系统运行参数。
- 布局配置有预设、页面、用户、版本、导入导出、回滚等独立生命周期。
- 使用专用表更利于校验和迁移。

若短期为了快速落地，也可先复用 `app_config` 保存全局预设选择，但页面和用户配置仍建议独立表。

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
- 禁用预设后，引用页面应回落到默认预设。
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
- 切换预设只影响 token、密度和允许的默认表现。
- 用户个人覆盖项仍保留，除非用户明确重置。
- 如果用户覆盖与新预设冲突，提示冲突项并使用用户项优先。

### 7.4 AI 开发体验

- AI 能从组件目录和原型注册表直接选型。
- AI 能通过校验器得到明确错误，而不是靠肉眼看页面。
- AI 开发完成后能生成页面登记信息。

## 8. 边界条件与异常场景

- 浏览器高度很低，例如 1100×620：页面不得出现整页滚动，主内容区内部滚动。
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
   - 政务风、科技风、金融风不再是散落 CSS，而是可选择、可存储、可导出的配置资产。

4. 形成“规范可执行”。
   - 自适应规范不再只写在 Markdown，而是变成 schema、渲染器、校验器和测试。

5. 形成“AI 稳定交付闭环”。
   - AI 每次新建页面都按固定选型流程，减少随机 CSS、随机滚动、随机布局层级。

## 11. 落地可行性与实施路径

### 11.1 可行性判断

该需求可以落地，而且当前项目已经具备较好的起点：

- 已有布局规范，规则完整。
- 已有 `PageLayout` schema、组件目录、原型、校验器。
- 已有 `LayoutHost` 渲染器。
- 已有 `useLayoutConfig` 和设置抽屉。
- 已有后端 `app_config` 的白名单校验范式可参考。

但必须明确：现有实现还不是完整目标系统，只是底座。要达到用户期望，需要新增配置模型、预设模型、组件目录扩展、后端持久化和 AI 开发流程闭环。

### 11.2 推荐里程碑

#### M1：需求定型与现状修正

- 补齐本需求文档。
- 同步 `DESIGN.md` 页面登记，加入 `QualityView` 当前状态。
- 明确配置优先级为“系统代码默认 < 预设 < 页面 < 用户”。
- 明确不做自由拖拽画布。

#### M2：组件目录升级

- 扩展 `ComponentKind`。
- 为每类组件定义共同特性和专属配置 schema。
- 将 `COMPONENT_CATALOG` 从“最低尺寸目录”升级为“组件能力目录”。
- 增加组件目录单测。

#### M3：风格预设模型

- 新增 `LayoutPreset` 类型。
- 内置 `professional`、`government`、`technology`、`finance`、`high-contrast`。
- 将 CSS token 与预设配置关联。
- 实现预设切换并持久化。

#### M4：配置覆盖链路

- 前端实现 `default -> preset -> page -> user` 合并。
- 后端新增布局配置表和 API。
- 前端设置面板显示配置来源。
- 用户配置非法时按项丢弃，不影响页面。

#### M5：Web 配置中心

- 新增独立“布局配置”页面。
- 增加预设管理。
- 增加页面配置管理。
- 增加导入导出和重置。

#### M6：AI 开发流程固化

- 增加页面开发模板。
- 增加页面选型确认清单。
- 增加布局校验报告。
- 更新 `DESIGN.md` 和 `CLAUDE.md`。

#### M7：存量页面迁移

- 按页面分批迁移。
- 每页迁移后执行构建、单测和浏览器验证。
- 页面登记和可配置项同步更新。

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
   - 系统支持至少 3 套固定风格预设。
   - 配置合并优先级满足：系统代码默认 < 预设 < 页面 < 用户。
   - 页面配置和用户配置都能持久化。
   - 非法配置被拒绝或丢弃，页面不崩溃。

4. Web 配置验收：
   - 用户可以在页面设置中修改个人偏好。
   - 管理员可以管理预设和页面默认配置。
   - 每项配置能看到当前值、默认值或来源层级。
   - 支持重置。

5. AI 开发稳定化验收：
   - 新页面开发必须产出页面原型、组件清单、配置清单。
   - 新页面必须使用 `LayoutHost` 或后续统一布局宿主。
   - 新页面必须通过布局校验器和前端构建。
   - 新页面必须登记到设计文档或布局注册表。

6. 存量页面验收：
   - `BoardView` 和 `QualityView` 登记状态与代码一致。
   - 后续迁移页面逐页记录原型和可编辑项。

## 13. 已确认决策

以下事项已由用户确认，后续实施计划按此执行，不再作为遗留问题处理：

1. 首批风格预设固定为 `professional`、`government`、`technology`、`finance`、`high-contrast`。
   - 影响：预设 key、默认 token、配置界面文案和导入导出 schema 均按这 5 套起步。

2. 用户配置持久化采用推荐节奏。
   - 决策：预设配置和页面配置优先后端化；用户配置短期可继续 localStorage，后续随多用户体系接入后端。

3. 后续会接入多用户和权限管理。
   - 决策：布局配置表、API 和权限策略从设计阶段预留 `user_id`、角色权限和管理级操作校验。

4. Web 配置中心新开独立“布局配置”页面。
   - 决策：不并入现有 `ConfigView`，避免系统运行参数和布局配置混杂。

5. 允许管理员新增自定义风格预设。
   - 决策：只开放 token 和受控策略，不开放任意 CSS。

6. 页面级配置允许调整组件顺序，但仅限管理员。
   - 决策：普通用户不允许调整页面业务结构，只能修改个人展示偏好。

7. 需要配置导出能力，用于跨环境迁移和复盘。
   - 决策：作为 M5 范围实现，导入时必须校验 schema version、组件存在性、取值域和权限。
