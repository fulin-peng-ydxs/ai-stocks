# 前端布局与外观配置实现

## 文档边界

本文面向开发者，维护前端布局与外观配置从加载、过滤、合并、组件消费到持久化、恢复和失败处理的实现机制，覆盖 `frontend/src/layout/`、配置 composable、设置抽屉及对应后端 API。依据为当前源码；文中的测试入口用于定位覆盖范围，不代表已经执行运行验证。

[DESIGN](../../DESIGN.md) 维护设计契约、字段归属及允许的表现；[环境配置](environment-configuration.md#3-生效配置与数据库覆盖层) 维护配置来源、权威表和作用域；[系统架构](system-architecture.md) 维护装配总览；[页面模板](../configurable-layout-system/page-template.md) 维护接入步骤与维护矩阵；[显示比例策略](../configurable-layout-system/display-scale-policy.md) 维护比例公式、尺寸匹配和该偏好的同步细则。本文不复制这些规则、算法或操作清单。

## 配置通道与调用关系

页面结构、组件特性、业务偏好和应用外观有不同的消费与保存入口，不能合成一份无差别的配置对象。

| 通道 | 输入与共享入口 | 消费结果 |
| --- | --- | --- |
| 页面布局 | `pageRegistry.ts` 的 `PageLayout`、远端 page/user 覆盖 → `useRemoteLayoutConfig` → `useLayoutConfig` / `mergeLayoutConfig` | `effective` 布局交给 `LayoutHost`，决定密度、slot 显隐、尺寸与滚动组织 |
| 组件特性 | `COMPONENT_FIELD_DEFS`、slot 的 `config` / `componentMeta`、page/user 覆盖和字段策略 → `resolveComponentConfig` | `componentValueOf` 等访问器供页面绑定真实组件属性 |
| 页面业务偏好 | 页面声明的 defaults → `usePageSettings` → `useUserPreference` | `settings` 提供业务默认值，主区通过独立会话值使用 |
| 主题明暗、导航、比例与抽屉偏好 | 各专用 composable → `createGlobalPreferenceSync` | 共享响应式状态供多个页面或应用外壳消费；各调用方补充自身的并发与恢复规则 |
| K 线范围偏好 | `useKlinePrefs` 模块级单例 → `useUserPreference(scope='global', prefKey='kline-prefs')` | 跨页面共享快捷范围与默认范围，直接使用用户偏好读写链路 |
| 视觉预设 | 内置 `presets.ts` + 后端启用目录/覆盖 → `useLayoutPreset` | 根节点 CSS 变量、组件库主题变量和 `themeRevision` |

页面布局与普通组件字段使用 `default < page < user`。视觉预设只处理外观 token，不作为页面布局的第四层；`LayoutConfigRepo.get_page_config()` 返回的 `presetKey` 为兼容字段，值为 `None`，写接口拒绝绑定页面预设。组件中声明 `userPersistence='global-preference'` 的字段走专用全局偏好，不进入页面用户层。

核心源码分别位于 [布局接线](../../frontend/src/composables/useRemoteLayoutConfig.ts)、[布局核心](../../frontend/src/layout/useLayoutConfig.ts)、[组件字段解析](../../frontend/src/layout/componentConfig.ts)、[页面偏好](../../frontend/src/composables/usePageSettings.ts) 和 [视觉预设](../../frontend/src/layout/useLayoutPreset.ts)。表与归属键以环境配置正文为准。

## 页面加载、过滤与合并

### 首屏与远端水合

“水合”指把服务端已保存值应用到当前前端实例。`useRemoteLayoutConfig(base)` 先从 registry 取得组件实例元数据，创建 `useLayoutConfig`；后者读取代码默认与本地 fallback，首屏无需等待配置请求。

挂载后只请求一次 `GET /api/layout/effective/{pageKey}`。后端 [LayoutConfigRepo.effective_config](../../backend/storage/layout_config.py) 分别读取页面和当前用户配置，过滤 page/user 覆盖，返回各层、来源摘要及组件字段策略；它没有前端完整的代码默认布局，因此返回值不能替代前端最终布局。

前端按以下顺序应用响应：

1. `applyComponentFieldPolicies()` 安装当前字段开放策略。
2. `applyPageConfig()` 将配置按布局路径和 `slots.<slotId>.config.<field>` 分流。
3. `applyUserConfig(..., { preserveDirty: true })` 注入用户层；水合前用户已经编辑或重置的路径优先保留，并在水合结束后补写远端。
4. `effective` 与组件配置的 computed 重新求值，已有模板绑定随 Vue 响应式更新。

水合前的改动由 `preHydrationDirtyPaths` 按路径记录，不是把整个本地缓存当作新草稿。没有本次编辑的本地旧值会被远端替换。加载失败时保留本地默认/缓存，设置 `remoteError` 并结束等待；`remoteHydrated=true` 表示加载流程已经结束，不能据此判断远端读取成功。

### 布局与组件采用不同的校验粒度

[merge.ts::mergeLayoutConfig](../../frontend/src/layout/merge.ts) 只处理布局旋钮：允许路径来自 `PageLayout.editable`，值通过旋钮校验。page 层以整层候选布局检查，合法路径的值非法或组合后布局不合法时，该层候选不应用；user 层逐项检查，单项失败不影响其他合法项。未开放路径被跳过，schema 不兼容的覆盖被丢弃。结果保留 `sourceMeta`、`perLayerValues` 和 `dropped` 供展示与诊断。

[componentConfig.ts::resolveComponentConfig](../../frontend/src/layout/componentConfig.ts) 先填组件字段默认，再叠加 slot 的代码配置，随后按 page/user 顺序覆盖。每项检查 slot、组件种类、字段定义、实例适用性、代码开放层级、管理员策略及值域；不合法项记录到 `componentDropped`。覆盖粒度是整个字段值，不能假定对象型字段会自动做任意深合并。

字段策略只能在代码允许的最大层级内调整。前端解析与设置控件共同消费 `componentAllowedLayers`；后端保存时仍执行值域、组件归属及策略校验。专用全局偏好字段还受 `_enforce_component_persistence_target()` 限制，禁止通过布局写接口混入 `layout_user_config`。设计与接入要求见 [DESIGN §7.3](../../DESIGN.md#73-组件特性配置治理)。

例如页面代码密度为 `standard`、page 层为 `comfortable`、user 层为 `compact` 时，最终布局为 `compact`，来源为 `user`。删除该用户覆盖后回到 `comfortable`；“恢复默认”不意味着无条件写入代码值。

### 当前受控字段目录

下表承接当前实现的字段与开放层级摘要；可用字段、页面 slot、候选及适用性以 `COMPONENT_FIELD_DEFS`、slot `config` 和 `componentMeta` 为事实源。字段变更同步此目录，`pageRegistry.spec.ts` 反查真实消费；目录不另外定义设计规则。

| 组件 | 字段 | 层级 | 归属事实源 |
|---|---|---|---|
| `filter-bar` | `commonFields` | page/user | 候选为 `componentMeta.searchFields`，默认组合在 slot.config；不足三个有效候选时运行时不提供编辑入口 |
| `data-table` | `border` | page | 全部 `data-table` slot 自动继承；页面需实际消费 `tableBorder(slotId)` |
| `data-table` | `pageSize` | page/user | slot `config.pagination=true` 时自动启用 |
| `data-table` | `defaultSort` | page/user | 候选排序字段以 `componentMeta.sortFields` 为准 |
| `data-table` | `hiddenColumns` | page/user | 候选列以 `componentMeta.columns` 为准 |
| `wide-table` | `border` | page | 全部 `wide-table` slot 自动继承；页面需实际消费 `tableBorder(slotId)` |
| `wide-table` | `pageSize` | page/user | slot `config.pagination=true` 时自动启用 |
| `wide-table` | `defaultSort` | page/user | 候选排序字段以 `componentMeta.sortFields` 为准 |
| `wide-table` | `hiddenColumns` | page/user | 候选列以 `componentMeta.columns` 为准 |
| `section` | `visibleIndicatorFields` | page/user | 仅由指标快照分区明确开放，候选字段由受控组件定义提供 |
| `chart` | `minHeight` | page/user | 图表 slot 以 `config.minHeight` 明确开放；自适应高度的工作台通过 `fieldApplicability.minHeight` 明确关闭并说明原因 |
| `chart` | `klineRangePreferences` | user（全局偏好持久化） | 含 `config.stockChart` 的 K 线工作区自动启用；组件设置统一编辑跨页面共享的 K 线快捷范围与默认范围 |
| `chart` | `stockAnalysis` | page/user | 联动股票走势工作台以 `config.stockAnalysis` 明确开放；默认模式、显示状态、对比周期、指数和指标统一由组件设置生成并单向投影到会话态 |
| `chart` | `sectorAnalysis` | page/user | 联动板块走势工作台以 `config.sectorAnalysis` 明确开放；使用独立板块指标模型，默认模式、显示状态、对比指数、指标和周期由组件设置生成并单向投影到会话态 |
| `tabs` | `defaultActive` | page/user | 仅在页面登记 tabs slot 且 `componentMeta.tabs` 提供候选时渲染 |
| `settings-drawer` | `size` | page/user（全局偏好持久化） | `supportsPageSettings !== false` 的 registry 页面共享 `settings` overlay slot；具体 slotId 不作为存储判定条件 |
| `settings-drawer` | `bodyScroll` | page | `supportsPageSettings !== false` 的 registry 页面共享 `settings` overlay slot |
| `config-panel` | `collapsibleSections` | page | `config-system.configPanel` |
| `config-panel` | `defaultCollapsed`、`showGroupDescription`、`showSectionDescription` | page/user | `config-system.configPanel`、`trade-discipline.stockConditions`（仅默认折叠适用）；分区候选以 `componentMeta.collapseSections` 为准 |

## 页面、设置控件与会话值如何生效

[LayoutHost](../../frontend/src/layout/components/LayoutHost.vue) 接收 `effective`，统一组织 slot、密度、成长区、滚动与页面浮层目标。组件配置由消费页通过 `componentValueOf`、`componentConfigOf` 等访问器传入组件；布局核心不会凭字段名自动修改任意 Vue 组件。

### 设置渲染与折叠偏好

[PageSettingsDrawer](../../frontend/src/components/PageSettingsDrawer.vue) 按 registry 和配置访问器组织设置。布局控件调用 `setKnob()`，组件控件复用 [ComponentAutoSettings](../../frontend/src/components/ComponentAutoSettings.vue)；管理员页面布局工作台也消费该渲染器。抽屉以 `layer='user'` 编辑个人默认，页面工作台以 `layer='page'` 编辑页面默认，配合 `slotIds`、`allowedLayersOf`、`collapsibleSlot`、`clearable` 适配可见 slot、字段权限、分组和清除入口。共享渲染器保证字段、候选与策略一致，两个入口的保存生命周期仍然不同。

折叠偏好由 `PageSettingsDrawer` 提供 `SETTINGS_FOLD_PREFERENCES` 上下文，`SettingsGroup` 统一读写，节点键按宿主组成：

| 节点 | 稳定标识来源 |
| --- | --- |
| 布局分组 | `EditableKnob.groupKey`，缺省回退该组首字段路径；`LayoutSettingsSection` 加 `layout:` 前缀 |
| 组件分组及字段子组 | `slotId`，子组再加字段 key，由 `ComponentAutoSettings` 生成 `component:` 节点键 |
| 业务分区 | `PageSettingSection.sectionKey`，生成 `business:` 节点键 |

`useDrawerPreferences` 将全局一级关闭清单与页面内节点关闭清单分别保存，恢复时由同一上下文还原。保存队列、身份守卫和待同步意图见[偏好同步](#页面业务偏好与专用全局偏好)，字段的存储结构由环境配置维护。

### 专用字段的持久化路由

抽屉通过 `activeConfig` 将 `settings-drawer.size` 转交 `useDrawerPreferences`，K 线快捷范围由 `useKlinePrefs` 承接；两者的字段元数据均声明 `userPersistence='global-preference'`。未声明专用目的地的普通 user 字段进入页面布局用户层。后端按 `(component kind, field)` 反向检查保存目标，不绑定特定 pageKey 或 slotId。

`settings-drawer.bodyScroll` 由 page 层控制。抽屉交互状态使用全局一级 `collapsedSections` 和页面节点 `collapsedGroups[pageKey]`；旧偏好 `defaultCollapsed` 仅作为兼容读取源，新写入不再生成。它们与 `config-panel` 的可配置默认折叠字段属于不同通道。页面级组件过滤仍保留抽屉自身 slot，结构与开放约束由 DESIGN 维护。

### 默认值到会话值的投影

主区可修改的默认值使用 [useDefaultedSessionValue](../../frontend/src/composables/useDefaultedSessionValue.ts) 单向投影为会话 ref。它监听默认值变化、更新会话值，不反向监听会话值来写默认；`shouldSync` 由消费方控制，URL 或返回现场恢复后的保护不能仅靠调用该函数自动获得。调用方等待页面偏好与远端布局水合，再恢复显式会话状态。分页场景通过 [useComponentPageSizeSession](../../frontend/src/composables/useComponentPageSizeSession.ts) 统一归到第一页并重新加载。

`PageSettingsDrawer` 发出的 `component-default-change` 用于通知消费页处理显式默认值变更；恢复默认通过 `reset` 交给页面组合清理。上述局部事件、Vue 响应式以及主题版本号各有用途，不存在一个保存后自动广播所有配置的统一通知机制。

### 会话生命周期与返回现场

`useDefaultedSessionValue` 的 ref 随当前 Vue 实例存活，KeepAlive 保留该实例内存；刷新或实例重建时从默认值初始化。URL 恢复和跨路由返回现场由消费页另外接续，持久配置层不自动保存查询现场。

[pageSessionStorage](../../frontend/src/utils/pageSessionStorage.ts) 使用页面 namespace、租户与用户组成当前 Tab 的键。`readPageSession()` 优先读取当前键，可将调用方声明的旧键迁入并移除旧值；`writePageSession()` 写入当前身份键；`removePageSession()` 删除该 namespace 的当前键与显式声明的旧键。浏览器拒绝存储或载荷损坏时回退为实例/Store 内存，不能保证刷新恢复。

业务 Store 持有状态结构和消费时机，共享工具负责键与存储；例如 `sectorsSession`、`limitLadderSession` 消费返回现场后将相应字段置空并重新持久化，重置 session 时删除对应键。退出或切换身份时，认证 Store 经 `stockSet.resetSession(true)` 调用 `clearAllPageSessions()` 清理应用会话；浏览器关闭 Tab 时结束 sessionStorage 生命周期。设计要求的初始化顺序与清理范围仍以 DESIGN 为准。

## 保存、回读与草稿保护

### 用户页面布局与组件字段

`setKnob()` / `setComponentKnob()` 先更新当前实例及本地 fallback；响应式消费立即变化。`useRemoteLayoutConfig` 监听 `userConfigValues`，在远端加载流程结束后以 300ms 防抖保存。`saveRemoteUserConfig()` 取消待执行计时，进入同一串行队列，并在轮到写入时读取最新快照。

保存调用 `POST /api/layout/users/{pageKey}`，携带真实页面布局用于组件归属校验；归属从后端请求上下文取得。关闭实例时会尝试提交尚在防抖窗口内的改动，身份已变化时拒绝写入。失败设置 `remoteSaveError`，保留当前值供重试，不回滚页面，也没有在所有失败后自动循环重试的保证。

成功后保持当前响应式配置，不再额外 GET 回读；下一次实例挂载重新从 effective 读取。`remoteSaving`、`remoteSaveError` 与 `remoteError` 分别表示写入中、写入失败和加载失败，不能互相替代。

批量密度同步由 [PageDensitySyncSettings](../../frontend/src/components/PageDensitySyncSettings.vue) → [pageDensitySync::unifyPageDensity](../../frontend/src/composables/pageDensitySync.ts) → `POST /api/layout/user-density` 承接。同步前排空已有页面保存，后续保存等待屏障；后端事务只补丁合并 `density`。成功后更新已挂载/缓存实例与本地 fallback，不建立全局密度覆盖层；同步期间用户新做的逐页密度选择仍保留，屏障释放后按原页面通道保存。

### 页面业务偏好与专用全局偏好

[useUserPreference](../../frontend/src/composables/useUserPreference.ts) 是 `usePageSettings` 的底层。它按页面 defaults 规范化远端字段，移除已下线的未知键；`deferUnknownFieldCleanup` 允许专用迁移器接管清理时机。无水合前编辑时应用远端，有编辑时保留当前值并尝试保存；后续编辑以 300ms 防抖提交到用户偏好 API，失败保留当前值与错误状态。

该入口不复用布局保存队列，也不承诺所有偏好都具有相同的串行或身份隔离机制。[createGlobalPreferenceSync](../../frontend/src/composables/useGlobalPreferenceSync.ts) 只提供全局偏好的身份检查、加载去重、PG 读写、防抖及回调；具体的待同步意图、revision 和队列由各偏好实现补充。

K 线范围偏好走另一条链路：[useKlinePrefs](../../frontend/src/composables/useKlinePrefs.ts) 在模块内惰性创建并复用一个 `useUserPreference` 实例，以 `scope='global'`、`prefKey='kline-prefs'` 读写。这里的 global 表示偏好作用域，单例用于跨页面共享状态；它没有接入 `createGlobalPreferenceSync` 的身份检查与加载去重机制，不能把后者的保障套用到 K 线偏好。

例如 [useDrawerPreferences](../../frontend/src/composables/useDrawerPreferences.ts) 按租户/用户选择本地键，记录未同步字段与页面节点，通过 revision、身份判断和串行保存避免旧响应反向覆盖。读到远端时只覆盖本地未编辑部分，保存成功且 revision 仍匹配后才清除待同步意图；失败保留意图供后续加载重试。节点接线与保存分类见[设置渲染与折叠偏好](#设置渲染与折叠偏好)。

### 管理员页面默认与视觉预设

| 入口 | 保存与回读机制 | 失败边界 |
| --- | --- | --- |
| [LayoutPagesView](../../frontend/src/views/layout/LayoutPagesView.vue) | 独立草稿和基线；冻结同一快照，先 `/layout/validate`，再保存 page 层；成功用返回值更新已保存配置和基线，不额外 GET | 保存失败保留草稿与原基线；加载/刷新通过 `loadPageConfig()` 重建草稿，不能声称任意刷新均保留草稿；切页和旧请求由请求序号/上下文守卫处理 |
| [LayoutPresetsView](../../frontend/src/views/layout/LayoutPresetsView.vue) | 弹窗编辑；保存成功后关闭弹窗，再 `reloadPresets()` 回读目录并注入运行时外观 | 写入和目录回读是两个阶段，回读失败显示加载错误；不能把它解释为写入已回滚或自动保留编辑弹窗 |

页面默认的保存不会自动刷新其他已经挂载的业务页面；这些页面通过自身挂载请求取默认值。视觉预设管理页回读后会更新当前浏览器的共享外观状态，也不表示其他浏览器已收到推送。

## 视觉预设、明暗模式与比例装配

[main.ts](../../frontend/src/main.ts) 初始化明暗、比例和预设；`initLayoutPreset()` 读取本地选择和最近外观目录，先应用可用的内置/缓存 token。登录页从公开认证配置取得经过筛选的 `appearance_presets`，经 `setRuntimePresetSources()` 更新目录；登录后 [App.vue::bootstrapAuthenticatedShell](../../frontend/src/App.vue) 依次确保身份、迁移旧偏好，再加载预设目录与公开配置。

`useLayoutPreset` 的处理顺序为：过滤禁用/重复预设并保留内置回退 → 根据可用目录解析当前 key → 在内置明暗 token 上叠加允许覆盖的颜色、阴影和圆角 → 写根节点及 Element Plus CSS 变量 → 递增 `themeRevision`。失效选择回到内置默认；非法覆盖不会直接写成无效颜色。基础表面与密度不由视觉预设任意覆盖。

边框与中性分段的派生分别集中在 `themeSurfaces.ts::themeBorderVariables(tokens, mode)` 与 `themeSelectionVariables(tokens, mode)`，`useLayoutPreset` 在同一次主题提交内应用。控件边框直接取预设原值，表面轻边框、分隔线向当前内容面混合；暗色使用独立比例。分组、分段、表格和普通面板按语义消费，首屏 CSS 兜底与默认预设一致；派生角色不进入后端预设字段或配置持久化。

普通 DOM 消费 CSS 变量；Canvas 需显式重新取色，[chartTheme.ts::useResponsiveEChartsTheme](../../frontend/src/components/chartTheme.ts) 监听整套 token 提交后的 `themeRevision`，股票图表再通过 `useStockChartTheme` 复用。明暗模式变化也会重新应用当前预设。

以下状态不能混称为一份已云端同步的“主题”：

- 明暗选择由 `useTheme` 以全局 `theme` 偏好同步；`system` 模式再根据系统媒体查询得到实际明暗。
- 预设目录与 token 覆盖由管理员维护。当前选中的预设 key 由 `setLayoutPreset()` 写本地 `ai-stocks:layout-preset`，当前实现没有把该选择写到 `user_preference`，不能保证跨设备恢复同一预设。
- 比例由 `useDisplayScale` 独立消费系统指数与用户比例偏好；切换视觉预设不切换比例算法。公式、屏幕与档案匹配的唯一正文见[显示比例策略](../configurable-layout-system/display-scale-policy.md)。

## 来源展示与恢复

布局核心的 `sourceOf` / `layerValuesOf` 和组件核心的 `componentSourceOf` / `componentLayerValuesOf` 分别提供当前来源与分层值。[SourceTag](../../frontend/src/components/SourceTag.vue) 显示默认、页面、个人来源；该标签表示当前有效值的来源，不表示本次远端写入成功。

单项恢复由 `resetKnob()` / `resetComponentKnob()` 删除用户覆盖；`resetAll()` 清除页面布局与组件用户层，使剩余 page/default 值重新生效。抽屉 footer 的恢复还会清理不完整搜索草稿、抽屉尺寸及当前页面折叠偏好，适用时重置全局 K 线偏好，再向页面发出 `reset`，由消费页接续重置业务偏好和布局。未接页面处理函数就不具备完整恢复语义。

管理员的 `POST /api/layout/reset` 按 scope 清理 page 或当前用户覆盖；它与用户抽屉本地状态重置后的自动保存是不同入口。恢复的设计范围、保留其他页面内部折叠记忆等要求仍由 DESIGN 定义。

## 权限、兼容与变更影响

权限由 [backend/api/layout.py](../../backend/api/layout.py) 和 [user_preferences.py](../../backend/api/user_preferences.py) 实施：effective/预设读取使用 `layout:view`；个人布局写入及密度同步使用 `layout:user-config`；页面默认、视觉预设与字段策略管理分别要求系统级 `layout:page-manage`、`layout:preset-manage`、`layout:field-policy`。reset 接口在函数内按 scope 守卫，page 要求 system，user 要求个人布局权限。用户偏好 API 使用 `user-preference:manage`。用户身份不从 payload 的 `userId` 取得，前端隐藏控件不能代替后端守卫；完整租户与授权模型见[权限架构](system-rbac-tenant.md)。

旧偏好通过 [usePreferenceMigration](../../frontend/src/composables/usePreferenceMigration.ts) 校验、分批写入 PG，完成后写 marker；失败保留迁移源供后续登录重试。旧组件字段迁移还可能由专用迁移器接管，不能先清源再写目标。

本地状态的实现范围应分别判断：抽屉偏好已按身份隔离；布局 fallback 的 `ai-stocks:layout:<pageKey>` / `ai-stocks:layout-cc:<pageKey>` 和业务偏好的 `ai-stocks:page-settings:<pageKey>` 仍是按页面的旧键。它们不是按租户/用户隔离的权威存储，远端失败时的本地回退不能据此证明身份隔离验收通过。登录用户配置的权威归属仍在 PG，本地策略约束见环境配置正文。

新增页面或字段按页面模板执行，不在本文另列操作清单。机制变更需追踪共享核心、前后端字段定义、自动设置渲染器、消费页与脚手架；设计规则变化更新 DESIGN，存储/作用域变化更新环境配置，比例算法变化更新比例策略，当前实现链路变化更新本文。

## 验证入口与限制

| 证据入口 | 覆盖目标 |
| --- | --- |
| `frontend/src/layout/__tests__/merge.spec.ts`、`useLayoutConfig.spec.ts`、`componentConfig.spec.ts` | 分层合并、来源、非法值与字段策略 |
| `frontend/src/composables/__tests__/useRemoteLayoutConfig.spec.ts`、`useUserPreference.spec.ts`、`useDrawerPreferences.spec.ts` | 水合前编辑、保存状态、偏好同步与抽屉恢复 |
| `frontend/src/composables/__tests__/useDefaultedSessionValue.spec.ts`、`useComponentPageSizeSession.spec.ts` | 单向默认投影与分页重载 |
| `frontend/src/layout/__tests__/useLayoutPreset.spec.ts`、`presets.spec.ts` | 预设目录、token、明暗及运行时外观入口 |
| `frontend/src/components/__tests__/PageSettingsDrawer.spec.ts`、`frontend/src/layout/__tests__/pageRegistry.spec.ts` | 设置接线、恢复与真实字段消费 |
| `backend/tests/test_layout_config.py`、`test_layout_density_sync.py`、`test_stage4_layout.py`、`test_user_preference.py` | 后端配置校验、归属、密度及权限边界 |

定向验证命令与服务保护以 [AGENTS](../../AGENTS.md) 为准。纯文档变动核对源码、职责、相对链接和结构；不要求启动服务或执行业务测试。静态走读不能证明 PG 实际内容、跨设备同步、浏览器视觉状态或全部并发时序，运行验收需另按真实变更范围执行。
