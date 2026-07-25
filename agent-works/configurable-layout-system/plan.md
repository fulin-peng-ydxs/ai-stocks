# 可配置 Web 布局系统开发计划

> 对应需求文档：[requirement.md](./requirement.md)。
> 目标：在现有 `frontend/src/layout/` 底座上，建设“组件化、自适应化、可配置化、AI 开发稳定化”的后台 Web 布局系统。

## 1. 总体判断

可以落地。当前项目已经完成了布局系统的第一层底座：

- 已有 `PageLayout`、`SlotSpec`、`Archetype`、`ComponentKind`、`EditableKnob` 类型。
- 已有 `COMPONENT_CATALOG` 最低尺寸目录。
- 已有 `list`、`master-detail`、`dashboard`、`form`、`detail`、`workbench`、`wizard` 页面原型。
- 已有 `validateLayout`、`coerceEditableValue`、`assertLayout`。
- 已有 `LayoutHost`、`VMixedGrow`、`VColumns` 渲染器。
- 已有 `useLayoutConfig` 本地覆盖层和 `LayoutSettingsSection` 自动表单。
- `BoardView`、`QualityView` 已接入 `LayoutHost`。

但现有实现仍是“布局规范代码化”的底座，不是完整产品化布局系统。后续开发重点要从“页面外壳合规”升级为：

- 组件能力目录。
- 风格预设系统。
- `系统代码默认 < 预设 < 页面 < 用户` 覆盖链路。
- 独立“布局配置”页面。
- 后端持久化与导入导出。
- AI 页面开发流程固化。
- 存量页面分批迁移。

## 2. 已确认决策

| 事项 | 决策 |
|---|---|
| 自定义模式 | 受控配置，不做自由拖拽画布，不开放任意 CSS |
| 配置优先级 | 系统代码默认 < 预设配置 < 页面配置 < 用户配置 |
| 首批预设 | `professional`、`government`、`technology`、`finance`、`high-contrast` |
| 用户配置持久化 | 预设、页面配置和登录用户配置均已接入后端；localStorage 仅保留为未登录/接口失败 fallback、旧偏好迁移源和临时交互态 |
| 权限体系 | 后续会接入多用户和权限管理，表和 API 设计先预留 |
| 配置中心入口 | 新增独立“布局配置”页面，不并入 `ConfigView` |
| 自定义预设 | 允许管理员新增，只开放 token 和受控策略 |
| 组件顺序 | 页面级可调，但仅管理员可调；普通用户不能改页面结构 |
| 导入导出 | 作为 M5 范围实现，用于跨环境迁移和复盘 |

## 3. 实施原则

1. 先扩模型，再扩界面。
   - 先把 schema、目录、校验和合并链路定稳，再做配置页面，避免界面驱动出临时字段。

2. 前后端校验双层守门。
   - 前端即时反馈，后端最终拒绝非法配置。
   - 白名单、类型、范围、跨字段约束必须明确。

3. 预设不改变页面业务结构。
   - 预设只影响 token、密度、组件默认策略和响应式默认值。
   - 页面业务组件增删、组件顺序等结构调整归页面配置，且仅管理员可操作。

4. 用户配置不突破布局红线。
   - 用户可以调整展示偏好，但不能绕过组件最低尺寸、滚动归属、重排条件和页面结构。

5. 每个阶段都要有可验证产物。
   - 类型、单测、页面、API、浏览器验证和文档登记缺一不可。

## 4. 里程碑总览

| 阶段 | 名称 | 目标 | 状态 |
|---|---|---|---|
| M0 | 基线收口 | 同步需求、计划、登记当前已接入页面 | 待做 |
| M1 | 组件能力目录 | 将 `COMPONENT_CATALOG` 升级为完整组件能力目录 | 待做 |
| M2 | 风格预设系统 | 建立预设模型、token 映射和预设切换 | 待做 |
| M3 | 配置覆盖链路 | 实现 `default < preset < page < user` 合并和校验 | 待做 |
| M4 | 后端持久化 API | 新增布局配置表、仓储、API、后端校验 | 待做 |
| M5 | 独立布局配置页面 | 新增配置中心、预设管理、页面配置、导入导出 | 待做 |
| M6 | AI 开发稳定化 | 固化页面开发模板、校验报告、登记机制 | 待做 |
| M7 | 存量页面迁移 | 分批迁移页面到新布局系统并验证 | 待做 |

## 5. M0：基线收口

### 5.1 目标

把现有实现、需求文档和设计登记对齐，避免后续计划建立在不一致状态上。

### 5.2 任务

1. 更新 `DESIGN.md` 的已迁移页面登记。
   - 加入 `QualityView`。
   - 记录 `BoardView` 和 `QualityView` 的原型、组件清单、可编辑项。

2. 标注现有实现边界。
   - `useLayoutConfig` 已从单一 localStorage 用户覆盖升级为多层配置源；旧 localStorage 仅作为迁移源和 fallback。
   - `COMPONENT_CATALOG` 当前只是最低尺寸目录，不是完整组件能力目录。
   - `LayoutSettingsSection` 当前只支持简单 knob，不支持复杂对象配置。

3. 明确旧计划和新计划关系。
   - 旧底座视为已完成基础能力。
   - 后续按本计划执行，不再按旧 “M5 可选后端持久化” 的弱优先级处理。

### 5.3 产物

- 更新后的 `DESIGN.md`。
- 本 `plan.md`。
- 需求文档 `requirement.md` 已确认决策章节。

### 5.4 验收

- `DESIGN.md` 中 `BoardView`、`QualityView` 登记与代码一致。
- `agent-works/configurable-layout-system/` 下同时存在 `requirement.md` 和新版 `plan.md`。

## 6. M1：组件能力目录

### 6.1 目标

将当前 `components.ts` 从“组件最低尺寸目录”升级为“组件能力目录”，支撑组件化、配置化和校验。

### 6.2 任务

1. 扩展组件类型。
   - 页面结构：`page-shell`、`section`、`split-pane`、`slot-group`。
   - 查询操作：`filter-bar`、`search-box`、`advanced-filter`、`toolbar`、`batch-bar`。
   - 数据展示：`data-table`、`wide-table`、`simple-list`、`description-list`、`tree-table`。
   - 表格附属：`pagination`、`column-settings`、`sort-control`、`export-button`。
   - 表单输入：`form`、`form-section`、`field-grid`、`inline-editor`。
   - 状态反馈：`loading-state`、`empty-state`、`error-state`、`skeleton`。
   - 摘要分析：`kpi-grid`、`metric-card`、`stat-strip`、`chart`、`mini-chart`、`chart-grid`、`trend-panel`。
   - 覆盖层：`detail-panel`、`drawer`、`dialog`、`side-panel`。
   - 复杂结构：`master-detail`、`tabs`、`steps`、`collapse`、`kanban`、`timeline`。
   - 导航辅助：`tree-nav`、`anchor-nav`、`breadcrumb`。

2. 定义组件共同特性。
   - `id`、`kind`、`label`、`region`、`order`。
   - `visible`、`permission`。
   - `styleTokens`。
   - `minW`、`minH`、`idealW`、`idealH`、`maxW`、`maxH`。
   - `scroll`、`growMain`、`reflowable`。
   - `responsive`、`states`、`dataBinding`、`actions`、`editable`。

3. 定义组件专属配置 schema。
   - 表格：分页、分页大小、列显隐、列顺序、列宽、冻结列、多选、跨页选择、服务端分页排序、行点击。
   - 筛选栏：字段、默认展开、高级筛选、自动查询、清空策略、记忆策略。
   - 表单：字段分组、label 宽度、列数、校验、只读、按钮吸底、字段区滚动。
   - 抽屉和弹窗：尺寸档位、最大高度、header/footer 固定、body 滚动、关闭策略。
   - 图表：类型、最低高度、宽高比、legend、tooltip、空态。
   - Tabs：tab 条吸顶、内容独立布局、默认激活、是否记忆。

4. 升级校验器。
   - 未登记组件拒绝。
   - 专属配置类型错误拒绝。
   - 组件最低尺寸下限继续强制。
   - 状态盒子必须声明稳定占位策略。

5. 增加单测。
   - 每类组件有元信息。
   - 每类组件专属配置 schema 可校验。
   - 非法组件、非法配置、低于尺寸下限均被拒绝。

### 6.3 主要文件

- `frontend/src/layout/schema.ts`
- `frontend/src/layout/components.ts`
- `frontend/src/layout/validator.ts`
- `frontend/src/layout/__tests__/validator.spec.ts`
- 可新增：`frontend/src/layout/componentSchemas.ts`

### 6.4 验收

- 组件目录覆盖需求文档列出的组件类别。
- 新增组件类型均有 label、尺寸、滚动、grow、reflow、editable 策略。
- `npm test` 通过。
- `npm run build` 通过。

## 7. M2：风格预设系统

### 7.1 目标

将风格预设从散落 CSS 变量升级为可存储、可切换、可校验的布局预设模型。

### 7.2 任务

1. 新增预设类型。
   - `LayoutPreset`
   - `StyleTokenConfig`
   - `PresetComponentDefaults`
   - `PresetResponsiveDefaults`

2. 内置首批 5 套预设。
   - `professional`：专业后台风，默认。
   - `government`：政务风。
   - `technology`：科技风。
   - `finance`：金融数据风。
   - `high-contrast`：高对比可访问风。

3. 建立 token 映射。
   - 色彩：主色、状态色、背景、卡片、边框、文字。
   - 密度：页面 gap、卡片 padding、表格行高、表单间距。
   - 形态：圆角、阴影、边框强度。
   - 组件默认策略：表格密度、筛选栏折叠、抽屉宽度。

4. 前端应用预设。
   - 在布局根或应用根挂预设 class 或 CSS 变量。
   - 保留 Element Plus 变量覆盖能力。
   - 保证暗色或高对比预设覆盖关键变量。

5. 预设校验。
   - 预设不能删除页面业务组件。
   - token 类型必须合法。
   - 密度不能突破组件最低尺寸。
   - 颜色至少满足基础对比度要求。

### 7.3 主要文件

- `frontend/src/layout/schema.ts`
- `frontend/src/layout/presets.ts`
- `frontend/src/styles/global.css`
- `frontend/src/layout/validator.ts`
- 可新增：`frontend/src/layout/useLayoutPreset.ts`

### 7.4 验收

- 可在前端切换 5 套预设。
- 切换预设不改变页面业务组件结构。
- `BoardView` 和 `QualityView` 在所有预设下可正常显示。
- 小屏 1100×620 无整页滚动。
- `npm test` 和 `npm run build` 通过。

## 8. M3：配置覆盖链路

### 8.1 目标

实现最终生效配置的统一合并链路：

```text
系统代码默认 < 预设配置 < 页面配置 < 用户配置
```

### 8.2 任务

1. 定义配置层。
   - `BaseLayoutDefinition`
   - `PresetLayoutOverride`
   - `PageLayoutOverride`
   - `UserLayoutOverride`
   - `EffectiveLayoutConfig`
   - `EditablePolicy`

2. 升级 `useLayoutConfig`。
   - 从单一 localStorage 覆盖升级为多源输入。
   - 支持显示配置来源 `sourceMeta`。
   - 支持按层重置。
   - 对旧 localStorage 值做兼容读取和非法项丢弃。

3. 前端合并与校验。
   - 合并前按白名单过滤。
   - 合并后运行 `validateLayout`。
   - 用户覆盖非法时按项丢弃。
   - 页面覆盖非法时回落页面代码默认并提示。

4. 权限策略预留。
   - 普通用户只允许写用户级字段。
   - 管理员允许写页面级配置和预设。
   - 页面结构字段仅管理员可调。

5. 单测。
   - 四层合并优先级。
   - 用户配置覆盖页面配置。
   - 页面配置覆盖预设配置。
   - 非法用户配置丢弃但页面不崩。
   - schema 版本不匹配时回落。

### 8.3 主要文件

- `frontend/src/layout/useLayoutConfig.ts`
- `frontend/src/layout/path.ts`
- `frontend/src/layout/validator.ts`
- `frontend/src/layout/__tests__/path.spec.ts`
- 可新增：`frontend/src/layout/merge.ts`
- 可新增：`frontend/src/layout/__tests__/merge.spec.ts`

### 8.4 验收

- 合并优先级可通过单测证明。
- 页面设置面板能区分当前值来源。
- 旧 localStorage 值不导致页面白屏。
- `npm test` 和 `npm run build` 通过。

## 9. M4：后端持久化 API

### 9.1 目标

新增布局配置专用后端存储和 API，承接预设配置、页面配置和后续用户配置。

### 9.2 任务

1. 新增 DDL。
   - `layout_preset`
   - `layout_page_config`
   - `layout_user_config`

2. 新增仓储。
   - `LayoutConfigRepo`
   - 预设 CRUD。
   - 页面配置读写。
   - 用户配置读写。
   - effective 配置读取辅助。

3. 新增后端校验。
   - 白名单字段。
   - 类型和范围。
   - schema version。
   - 组件存在性。
   - 权限预留。
   - 删除预设前检查引用。

4. 新增 API。
   - `GET /api/layout/presets`
   - `POST /api/layout/presets`
   - `GET /api/layout/pages/{pageKey}`
   - `POST /api/layout/pages/{pageKey}`
   - `GET /api/layout/users/{pageKey}`
   - `POST /api/layout/users/{pageKey}`
   - `POST /api/layout/validate`
   - `POST /api/layout/reset`
   - `GET /api/layout/effective/{pageKey}`

5. 前端 API 封装。
   - `frontend/src/api/layout.ts`
   - 错误响应对齐现有 `ApiResponse`。

6. 后端测试。
   - DDL 初始化。
   - 预设保存和读取。
   - 页面配置保存和读取。
   - 非法配置拒绝。
   - 被引用预设不可删除或不可禁用。

### 9.3 主要文件

- `backend/storage/ddl.py`
- `backend/storage/layout_config.py`
- `backend/api/layout.py`
- `backend/main.py`
- `backend/tests/test_layout_config.py`
- `frontend/src/api/layout.ts`

### 9.4 验收

- 后端测试通过。
- API 能返回预设、页面配置和 effective 配置。
- 非法配置后端拒绝。
- 不影响现有 `app_config` 和 `/api/data/settings`。

## 10. M5：独立布局配置页面

### 10.1 目标

新增独立“布局配置”页面，作为管理员管理预设、页面默认配置、导入导出的入口。

### 10.2 任务

1. 新增路由和菜单。
   - 建议路径：`/layout-config` 或 `/config/layout`。
   - 不并入现有 `ConfigView`。

2. 页面结构。
   - 左侧或顶部 Tabs：预设管理、页面配置、导入导出、校验报告。
   - 使用布局系统自身构建，避免配置页成为规范例外。

3. 预设管理。
   - 查看内置预设。
   - 新增自定义预设。
   - 编辑 token 和受控策略。
   - 禁用或启用预设。
   - 查看被哪些页面引用。

4. 页面配置管理。
   - 选择页面。
   - 选择默认预设。
   - 配置页面级覆盖。
   - 配置 `EditablePolicy`。
   - 管理员调整组件顺序。

5. 导入导出。
   - 导出预设。
   - 导出页面配置。
   - 导出用户配置。
   - 导入时校验 schema version、组件存在性、取值域和权限。

6. 校验报告。
   - 显示非法配置项。
   - 显示字段来源。
   - 支持一键重置非法用户覆盖。

### 10.3 主要文件

- `frontend/src/views/LayoutConfigView.vue`
- `frontend/src/router/index.ts`
- `frontend/src/api/layout.ts`
- `frontend/src/layout/components/LayoutSettingsSection.vue`
- 可新增：`frontend/src/layout/components/PresetEditor.vue`
- 可新增：`frontend/src/layout/components/PageLayoutEditor.vue`
- 可新增：`frontend/src/layout/components/LayoutImportExport.vue`

### 10.4 验收

- 管理员可在独立页面管理预设。
- 管理员可配置页面默认预设和页面级覆盖。
- 导入非法配置时明确提示并拒绝。
- 导出文件可再次导入。
- 1100×620 下配置页本身不整页滚动。
- `npm run build` 通过。

## 11. M6：AI 开发稳定化

### 11.1 目标

把“新页面交给 AI 开发”的流程固化成模板、校验和登记，减少随机布局。

### 11.2 任务

1. 新增页面开发模板。
   - 页面原型选择。
   - 组件清单。
   - 预设选择。
   - 页面级配置。
   - 用户可编辑项。
   - 验证清单。

2. 新增布局登记格式。
   - 页面 key。
   - 页面路径。
   - 原型。
   - 组件清单。
   - 可编辑项。
   - 已验证视口。

3. 更新 `DESIGN.md`。
   - 新增“AI 新页面开发流程”。
   - 新增“组件目录索引”。
   - 新增“页面登记表”。
   - 新增“配置优先级说明”。

4. 更新 `CLAUDE.md`。
   - 新页面必须使用布局系统。
   - 必须声明原型、组件清单和配置项。
   - 必须运行校验和构建。

5. 增加校验脚本或测试。
   - 检查页面是否登记。
   - 检查 `frontend/src/views` 是否新增硬编码 `height: calc(100vh`。
   - 检查新页面是否直接手写 `.v-page/.v-grow`，按过渡期策略可先 warn 后 error。

### 11.3 主要文件

- `DESIGN.md`
- `CLAUDE.md`
- 可新增：`agent-works/configurable-layout-system/page-template.md`
- 可新增：`frontend/src/layout/__tests__/layout-contract.spec.ts`
- 可新增：`scripts/check-layout-contract.*`

### 11.4 验收

- 新页面开发有可复用模板。
- `DESIGN.md` 能指导 AI 从原型选型到页面登记。
- 新增硬编码高度能被测试或脚本发现。
- `npm test` 和 `npm run build` 通过。

## 12. M7：存量页面迁移

### 12.1 目标

把存量页面逐步迁移到统一布局系统，迁移过程保持业务行为稳定。

### 12.2 迁移顺序

1. 已接入页面补登记和修正。
   - `BoardView`
   - `QualityView`

2. 高频列表页。
   - `StocksView`
   - `ScreenView`
   - 数据管理相关列表页。

3. 工作台和复杂页。
   - `BacktestView`
   - `OverviewView`
   - `TrainingView`

4. 配置和表单页。
   - `ConfigView`
   - 各 profile 配置页。

### 12.3 每页迁移流程

1. 阅读页面现有结构和业务状态。
2. 判定页面原型。
3. 列出组件清单。
4. 声明页面 layout schema。
5. 接入 `LayoutHost`。
6. 接入布局设置项。
7. 保留原有业务行为。
8. 运行单测和构建。
9. 浏览器验证 1100×620 和常规桌面宽度。
10. 更新页面登记。

### 12.4 特殊技术债

1. `OverviewView` 双列双成长表。
   - 当前 `VColumns` 是等宽重排，`VMixedGrow` 是单主表，无法完整覆盖“双列各自 grow + 内滚”。
   - 迁移前需要新增 `columns-of-grow` 或等价策略。

2. 复杂工作台页面。
   - 需要确认哪些块是固定分析块，哪一个是主 grow 表或主图。

3. 弹窗和抽屉。
   - 必须处理 Element Plus teleport + scoped 样式问题。

### 12.5 验收

- 每个迁移页面无整页滚动。
- 主表表体内滚，分页固定。
- loading、empty、error 状态不抖动。
- 页面业务行为与迁移前一致。
- 页面登记完整。

## 13. 测试策略

### 13.1 前端单测

- 组件目录完整性。
- 组件专属配置校验。
- 预设 token 校验。
- 四层配置合并。
- editable 权限和取值域。
- schema version 兼容。

### 13.2 后端测试

- DDL 初始化。
- 布局配置仓储 CRUD。
- API 返回结构。
- 非法配置拒绝。
- 预设引用保护。
- 导入导出校验。

### 13.3 构建验证

- `npm test`
- `npm run build`
- 后端 `pytest`

### 13.4 浏览器验证

至少覆盖：

- 1100×620 小屏。
- 1366×768 常规笔记本。
- 1440×900 常规桌面。
- 预设切换。
- 密度切换。
- 表格分页 20/50/100。
- 抽屉和弹窗打开状态。

## 14. 风险与应对

| 风险 | 表现 | 应对 |
|---|---|---|
| 过度抽象 | schema 复杂但页面难写 | 每个阶段必须用真实页面验证，禁止只做抽象 |
| 前后端校验漂移 | 前端能保存，后端拒绝或反之 | 规则集中定义，后端最终守门，前端只做即时反馈 |
| 预设污染业务结构 | 切换风格导致组件丢失或顺序变化 | 预设只允许 token 和默认策略，不允许改业务结构 |
| 用户配置破坏页面 | 用户调出不可用布局 | 用户配置只能覆盖白名单字段，合并后必须全量校验 |
| 存量页面迁移回归 | 页面样式好了但业务坏了 | 逐页迁移、逐页构建、逐页浏览器验证 |
| 多用户接入返工 | 表结构没预留用户和权限 | 从 M4 起预留 `user_id`、角色和管理级操作 |

## 15. 开发顺序建议

推荐先做 M0 到 M3，再决定是否立即推进 M4 到 M5。

第一批开发：

1. M0 基线收口。
2. M1 组件能力目录。
3. M2 风格预设系统。
4. M3 配置覆盖链路。

第一批完成后应能达到：

- 页面仍可只用前端本地配置运行。
- 组件目录和预设模型已经稳定。
- 配置优先级在前端可验证。
- `BoardView`、`QualityView` 可切换预设和密度。

第二批开发：

1. M4 后端持久化 API。
2. M5 独立布局配置页面。
3. M6 AI 开发稳定化。

第二批完成后应能达到：

- 管理员可维护预设和页面默认配置。
- 可导入导出。
- AI 新页面开发有固定模板和校验闭环。

第三批开发：

1. M7 存量页面迁移。
2. 针对复杂页面补齐布局策略。
3. 逐步退场旧 Markdown 规范中的重复内容。

## 16. 完成定义

本项目可配置 Web 布局系统完成时，必须同时满足：

1. 至少 5 套预设可存储、可切换、可导入导出。
2. 至少覆盖需求文档中的后台常用组件类别。
3. 配置合并优先级为 `系统代码默认 < 预设 < 页面 < 用户`。
4. 预设和页面配置后端持久化。
5. 登录用户配置以后端持久化为权威，localStorage 不作为登录用户配置权威。
6. 独立“布局配置”页面可用。
7. AI 新页面开发流程写入 `DESIGN.md` 和 `CLAUDE.md`。
8. 新页面必须使用布局系统、通过校验和构建。
9. `BoardView`、`QualityView` 和至少一批高频列表页完成迁移验证。

## 17. DESIGN 合规复审整改

- 任务编号：D1。
- 状态：已完成（2026-07-25）。
- 目标：收口全项目 DESIGN 审查发现的页面设置假登记、抽屉私有宽度、HelpTip 私有色板、真实复用组件清单缺口和非股票 Canvas 主题边界。
- 开发内容：
  - `pageRegistry` 新增 `supportsPageSettings` 机器字段；预设管理、页面布局和系统组件三个平台管理页显式为 false，不再自动补 `settings-drawer`、组件字段或个人设置能力。
  - `PageDrawer` 统一消费类型化 `sm/md/lg/xl` 宽度事实源；组件预览、审计详情和实时日志迁移到 `xl=560px`，布局契约测试禁止页面传 px/%。
  - `HelpTip` 清除私有 hex，统一消费 Element Plus 预设语义 token，并补键盘聚焦和真实页面 token 对账。
  - 新增 `useEChartsTheme()` 与共享 `useResponsiveEChartsTheme()`；`EquityChart`、`GrowthChart` 响应明暗、预设 key 和同 key 后端覆盖，股票画布继续通过 `useStockChartTheme()` 保持专属序列契约。
  - DESIGN 核心组件清单补齐 `PageSettingsTrigger`、`PageSettingSection`、`TradeDatePicker`、K线设置组件和普通曲线组件；机器测试扫描两个以上页面的组件消费，防止清单再次漂移。
- 产出：
  - `frontend/src/components/pageDrawerSize.ts`
  - `frontend/src/components/chartTheme.ts`
  - registry、抽屉、帮助提示、普通/股票图表及相关契约测试。
  - 同步后的 `DESIGN.md`、`requirement.md`、`page-template.md` 和本计划。
- 影响范围：前端布局元数据、页面业务抽屉、帮助提示、训练/回测曲线和 DESIGN 机器契约；不涉及路由、菜单、权限、接口、数据库、seed、配置字段或用户偏好结构。
- 复用判断：
  - 已查找：`PageSettingsDrawer`、三个布局管理页、全部 `PageDrawer` 消费点、`HelpHint`、股票主题入口、`EquityChart`、`GrowthChart` 和真实组件清单。
  - 已复用：`LayoutHost`/`PageDrawer` 边界、Element Plus token、`themeRevision`、页面 registry 和既有 E2E 控制台 helper。
  - 新增复用单元：类型化抽屉尺寸事实源、普通 ECharts 响应式主题入口。
  - 未合并：股票画布与净值/成长曲线的数据、option 和生命周期职责不同，只共享主题修订触发与基础语义色，不合并为万能图表组件。
- 验证：
  - 定向 Vitest：`9 files / 62 tests passed`。
  - 前端全量 Vitest：`66 files / 443 tests passed`。
  - 正式构建：通过；仅有既有依赖注释位置和大 chunk 告警。
  - Playwright：1100×620、1366×768、1440×900 三项目共 `6 passed`；确认系统组件页无个人设置入口、组件预览抽屉为 560px、HelpTip 实际样式等于当前预设 token，控制台无 error/warning。
  - MACD/T18 关键视口回归：1100×620、1366×768、1440×900 共 `3 passed`；三图纵向布局、语义主题和 reduced-motion 契约未受普通图表主题入口收敛影响。
  - 服务：后端 `/api/health=200`，前端 `5173=200`。
