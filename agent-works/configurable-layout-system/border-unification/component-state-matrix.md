# 全组件边框与状态核查矩阵

## 用途与边界

本矩阵是 2026-10-22 对 `ab036779` 前端快照的审查附录，逐项记录边框所有者、适用状态、继承入口和差异；不作为新的设计规范。规范权威入口为 [DESIGN.md](../../../DESIGN.md)，差异定级、实测证据和建议见 [核查与统一方案](audit.md)。

覆盖 156 个 Vue 单元（含 App 壳、通用/业务/布局和页面私有组件）及 `AppHoverInfo.ts`，合计 **157 个组件单元**；另覆盖 25 个路由 View 的私有边界。`BrandMark`、布局容器、图形标记等也逐项登记，不因没有外框而漏项。图表 tooltip 的运行时样式另见主报告。

**证据标记**：以下单元格均为源码与共享入口追踪（S），不能解释成157个组件的全部状态均已浏览器通过。已实测的状态只以主报告 B01–B08 为准。`—` 表示该组件自身没有该状态，slot/子控件有状态时归对应子项；“子项”不表示父容器也应 hover/selected。组件组合状态不能用简单文本搜索判“通过”。

**继承角色**：B=命令按钮；I=输入/选择；T=布尔；K=结构排版；P=面板；A=异步反馈；D=分组展开；N=导航/列表；H=说明触发；L=领域标签；C=图表；F=表单组合；R=排序/尺寸调整；V=预览原型。通用规则只在本表的角色含义中引用，不要求所有组件外形相同。

“异常”包含错误/空态；“加载”只检查已有异步状态的边框归属，不通过触发真实采集、交易、权限或配置写入制造状态。只读资产的禁用由实际权限属性与子组件透传决定，不能凭外观猜测。

## 2026-10-23 实施补核

下方157项矩阵保留整改前快照及当时行号，不能作为当前源码行号引用。对应F01–F04/G04–G07已按[实施结果](audit.md#2026-10-23-实施结果)处理，当前角色权威入口为DESIGN §6。原有组件通过共享输入/弹层适配或既有角色消费继承变化，领域身份、圆/胶囊、图例与排版无框结构保留；实际浏览器结论仅以C01–C07及后续明确追加记录为准。

补入快照之后新增的3项，当前合计**160个组件单元、25个路由View**（184个Vue加AppHoverInfo.ts）：

| 组件 | 外沿/内部边界 | 适用状态与承接 | 本次处理/证据 |
|---|---|---|---|
| [ScheduleDownstreamDrawer](../../../frontend/src/components/data/ScheduleDownstreamDrawer.vue) | AppDetailDrawer拥有外沿，条目委托AppDetailSection，排序轮廓归AppReorderList | loading/error/empty由抽屉state；saving/loading锁排序与动作；saveError用AppStatusNotice；只读由权限决定 | S：无私有边框，继承新弹层与软提示角色；没有为验收保存排序 |
| [LayoutConfigTransferPanel](../../../frontend/src/layout/components/LayoutConfigTransferPanel.vue) | 自身card外沿，操作区只有上分隔；编辑器是内部输入 | busy禁用文件选择/textarea；导入解析和保存由父工作区负责；自身不虚构区域error/loading | S：已有边框角色合规，textarea继承新适配；保持原实现 |
| [BorderStatePreview](../../../frontend/src/layout/components/BorderStatePreview.vue) | 展开结构无多余卡；真实控件拥有各自边界；网格和结果各有唯一宿主外框 | 本地错误/禁用、选中禁用、结果loading/empty/error、详情1/2/3列与跨列；Tab核对真实焦点 | C01–C04/C07；增加深底Popover；定向测试；不调用业务API、不保存；非ready原型仍不代表业务入口 |

## 整改前逐组件状态矩阵

| 组件 / 源码 | 角色与默认边界 | 悬停 / 按下 | 焦点 | 选中 / 展开 / 拖动 | 禁用 / 只读 | 加载 | 错误 / 空态 | 差异或例外 |
|---|---|---|---|---|---|---|---|---|
| [App](../../../frontend/src/App.vue) | 导航/选择列表；导航/选择角色；L858 `border-right: 1px solid var(--chrome-border)`；L884 `border-top: 1px solid var(--chrome-border)` | 导航/列表共享 | 共享焦点 | route/active/checked | 支持禁用的条目 | 所属区域 | 所属区域 | 声明状态接口：无；状态可能来自内部/attrs/子项；普通导航边框同源；外观卡片12/13px属于浮层角色，待纳入 G04 角色表；装饰缩略图不按业务控件半径迁移。 |
| [AppActionHint](../../../frontend/src/components/AppActionHint.vue) | 说明/浮层触发；帮助/说明角色；L31 `border-radius: var(--layout-control-radius)` | help/link 共享 | 共享/库锚点 | — | 声明 disabled 时 | 所属内容 | 空说明不造框 | 声明状态接口：disabled；继承入口：AppHoverInfo |
| [AppAdvancedSearch](../../../frontend/src/components/AppAdvancedSearch.vue) | 表单/设置组合；表单/设置组合；L92 `border-top: 1px solid var(--el-border-color-lighter)` | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：states；继承入口：AppScrollArea, el-button, el-tag |
| [AppAsyncRegion](../../../frontend/src/components/AppAsyncRegion.vue) | 异步/反馈宿主；自身/宿主见备注；无私有 border/radius | 仅动作子项 | 仅动作子项 | 子项 | 子项 | 骨架/遮罩 | empty/error 分支 | 声明状态接口：loading, error, loadingTitle, loadingDescription, errorTitle, stateSize；继承入口：AppStateBlock |
| [AppCloseButton](../../../frontend/src/components/AppCloseButton.vue) | 命令/操作；按钮角色外框；无私有 border/radius | 角色 hover/pressed | 共享 ring | 业务选择另计 | 中性保形 | loading保留角色框 | 反馈组件承接 | 声明状态接口：disabled, loading；关闭入口专用几何/状态适配，不使用危险色；继承 AppIconButton。 |
| [AppControlItem](../../../frontend/src/components/AppControlItem.vue) | 结构/排版；自身无业务框；无私有 border/radius | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；自身只负责内容/几何；不新增状态边框 |
| [AppControlRow](../../../frontend/src/components/AppControlRow.vue) | 结构/排版；自身无业务框；无私有 border/radius | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；自身只负责内容/几何；不新增状态边框 |
| [AppDataTable](../../../frontend/src/components/AppDataTable.vue) | 异步/反馈宿主；自身/宿主见备注；L228 `border-right: none` | 仅动作子项 | 仅动作子项 | 子项 | 子项 | 骨架/遮罩 | empty/error 分支 | 声明状态接口：loading, loadingText；已分离列线/外框；自身无完整外框，宿主 AppTableCard 或工作区负责；border=true 保留库固定列计算。 |
| [AppDatePicker](../../../frontend/src/components/AppDatePicker.vue) | 输入/选择；输入内描边；无私有 border/radius | input/select 统一；其它库默认 | 单值主色；范围 F01 | 值/候选由库 | 透传禁用/只读 | —（无独立 loading） | 表单校验/上层 | 声明状态接口：无；状态可能来自内部/attrs/子项；F01：range 使用 is-active，当前未进入全局 is-focus 规则。单值与范围需分支验收。 |
| [AppDetailDrawer](../../../frontend/src/components/AppDetailDrawer.vue) | 异步/反馈宿主；自身/宿主见备注；无私有 border/radius | 仅动作子项 | 仅动作子项 | 子项 | 子项 | 骨架/遮罩 | empty/error 分支 | 声明状态接口：state, stateTitle, stateDescription；继承入口：PageDrawer, AppStateBlock |
| [AppDetailField](../../../frontend/src/components/AppDetailField.vue) | 内容面板；面板/宿主边界；无私有 border/radius | 仅交互子项 | 仅交互子项 | 业务标记另计 | 子项 | 宿主框保留 | 宿主框保留/子项 | 声明状态接口：无；状态可能来自内部/attrs/子项；G06：每个 field inset -1px -1px；只作结构分隔，不能在每个字段再加外框。 |
| [AppDetailFields](../../../frontend/src/components/AppDetailFields.vue) | 内容面板；面板/宿主边界；L18 `border: 1px solid var(--el-border-color-lighter)`；L19 `border-radius: var(--layout-card-radius)` | 仅交互子项 | 仅交互子项 | 业务标记另计 | 子项 | 宿主框保留 | 宿主框保留/子项 | 声明状态接口：无；状态可能来自内部/attrs/子项；G06：dl 外框与 field 右/下 inset 分隔共同绘制，需核查末行/末列边线的唯一所有者。 |
| [AppDetailSection](../../../frontend/src/components/AppDetailSection.vue) | 内容面板；面板/宿主边界；L34 `border-top: 1px solid var(--el-border-color-lighter)` | 仅交互子项 | 仅交互子项 | 业务标记另计 | 子项 | 宿主框保留 | 宿主框保留/子项 | 声明状态接口：无；状态可能来自内部/attrs/子项；自身只负责内容/几何；不新增状态边框 |
| [AppDialog](../../../frontend/src/components/AppDialog.vue) | 内容面板；面板/宿主边界；无私有 border/radius | 仅交互子项 | 仅交互子项 | 业务标记另计 | 子项 | 宿主框保留 | 宿主框保留/子项 | 声明状态接口：无；状态可能来自内部/attrs/子项；G04：实测无实体 border、4px 圆角；需决定短对话框是否与抽屉同属 overlay 角色。 |
| [AppDragHandle](../../../frontend/src/components/AppDragHandle.vue) | 命令/操作；按钮角色外框；无私有 border/radius | 角色 hover/pressed | 共享 ring | 业务选择另计 | 中性保形 | —/由组合宿主锁定 | 反馈组件承接 | 声明状态接口：active, disabled；继承入口：AppIconButton |
| [AppFilterSelect](../../../frontend/src/components/AppFilterSelect.vue) | 输入/选择；输入内描边；无私有 border/radius | input/select 统一；其它库默认 | 单值主色；范围 F01 | 值/候选由库 | 透传禁用/只读 | —（无独立 loading） | 表单校验/上层 | 声明状态接口：collapseTags, allSelectedLabel, disabled；继承入口：AppSelect, el-option |
| [AppFilterSwitch](../../../frontend/src/components/AppFilterSwitch.vue) | 布尔控件；库布尔控件；无私有 border/radius | 库状态/暗色适配 | 库焦点/暗色适配 | checked/半选 | 库禁用 | 仅支持 loading 的开关 | 表单/宿主 | 声明状态接口：disabled；继承入口：el-switch |
| [AppFormHelp](../../../frontend/src/components/AppFormHelp.vue) | 结构/排版；自身无业务框；无私有 border/radius | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；自身只负责内容/几何；不新增状态边框 |
| [AppHoverInfo](../../../frontend/src/components/AppHoverInfo.ts) | 说明/浮层触发；帮助/说明角色；无私有 border/radius | help/link 共享 | 共享/库锚点 | — | 声明 disabled 时 | 所属内容 | 空说明不造框 | 声明状态接口：disabled；TS 运行时组件；ElTooltip/ElPopover 的浮层边界仍依库角色，见 G04。 |
| [AppIconButton](../../../frontend/src/components/AppIconButton.vue) | 命令/操作；按钮角色外框；L59 `border: 1px solid transparent`；L60 `border-radius: var(--layout-control-radius, 6px)` | 角色 hover/pressed | 共享 ring | 业务选择另计 | 中性保形 | loading保留角色框 | 反馈组件承接 | 声明状态接口：disabled, loading；loading disabled 保持原语义色；普通 disabled 才走中性弱化，不能将两者合并。 |
| [AppJsonViewer](../../../frontend/src/components/AppJsonViewer.vue) | 结构/排版；自身无业务框；无私有 border/radius | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppScrollArea |
| [AppOverflowTooltipHost](../../../frontend/src/components/AppOverflowTooltipHost.vue) | 说明/浮层触发；帮助/说明角色；无私有 border/radius | help/link 共享 | 共享/库锚点 | — | 声明 disabled 时 | 所属内容 | 空说明不造框 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-tooltip |
| [AppPagination](../../../frontend/src/components/AppPagination.vue) | 导航/选择列表；导航/选择角色；无私有 border/radius | 分页按钮/页码 | 库按钮焦点 | currentPage | 按页码计算前后页禁用 | —（无独立 loading） | total=0；无 error接口 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-pagination |
| [AppReorderList](../../../frontend/src/components/AppReorderList.vue) | 排序/尺寸交互；结构/把手；L93 `border-radius: var(--layout-card-radius)`；L95 `border-radius: 2px` | 命中区反馈 | 键盘把手/分隔条 | 拖动/drop/预览 | 停止调整 | 提交归宿主 | 取消/拒绝恢复 | 声明状态接口：disabled；拖动 dashed outline 是合法操作反馈，不应改成普通容器边框。 |
| [AppReorderTree](../../../frontend/src/components/AppReorderTree.vue) | 排序/尺寸交互；结构/把手；L177 `border-radius: var(--layout-control-radius)`；L181 `border-top: 1px solid var(--app-border-default)` | 命中区反馈 | 键盘把手/分隔条 | 拖动/drop/预览 | 停止调整 | 提交归宿主 | 取消/拒绝恢复 | 声明状态接口：disabled, busy；drop-inside outline 与 drop-hint 结构线是操作反馈，不等于选择态。 |
| [AppRowActions](../../../frontend/src/components/AppRowActions.vue) | 命令/操作；按钮角色外框；L426 `border-radius: 4px` | 角色 hover/pressed | 共享 ring | 业务选择另计 | 中性保形 | action.loading | 反馈组件承接 | 声明状态接口：无；状态可能来自内部/attrs/子项；G04：更多菜单项固定4px是菜单子项形态，需映射角色；按钮本体已有B矩阵，不把菜单项误判普通按钮。 |
| [AppScrollArea](../../../frontend/src/components/AppScrollArea.vue) | 结构/排版；自身无业务框；无私有 border/radius | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；自身只负责内容/几何；不新增状态边框 |
| [AppSearchInput](../../../frontend/src/components/AppSearchInput.vue) | 输入/选择；输入内描边；无私有 border/radius | input/select 统一；其它库默认 | 单值主色；范围 F01 | 值/候选由库 | 透传禁用/只读 | —（无独立 loading） | 表单校验/上层 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-input |
| [AppSelect](../../../frontend/src/components/AppSelect.vue) | 输入/选择；输入内描边；无私有 border/radius | input/select 统一；其它库默认 | 单值主色；范围 F01 | 值/候选由库 | 透传禁用/只读 | 仅声明支持时 | 表单校验/上层 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-select |
| [AppSortControl](../../../frontend/src/components/AppSortControl.vue) | 命令/操作；按钮角色外框；无私有 border/radius | 角色 hover/pressed | 共享 ring | 业务选择另计 | 中性保形 | —/由组合宿主锁定 | 反馈组件承接 | 声明状态接口：disabled；继承入口：el-dropdown, el-button, el-icon, el-dropdown-menu, el-dropdown-item, AppIconButton |
| [AppSplitWorkspace](../../../frontend/src/components/AppSplitWorkspace.vue) | 排序/尺寸交互；结构/把手；L498 `border-radius: 2px` | 命中区反馈 | 键盘把手/分隔条 | 拖动/drop/预览 | 停止调整 | 提交归宿主 | 取消/拒绝恢复 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppScrollArea, PageDrawer |
| [AppStateBlock](../../../frontend/src/components/AppStateBlock.vue) | 异步/反馈宿主；自身/宿主见备注；无私有 border/radius | 仅动作子项 | 仅动作子项 | 子项 | 子项 | 骨架/遮罩 | empty/error 分支 | 声明状态接口：state；继承入口：el-skeleton, el-empty, el-button, el-result, el-icon |
| [AppStatusDot](../../../frontend/src/components/AppStatusDot.vue) | 说明/浮层触发；帮助/说明角色；L42 `border-radius: 50%`；L53 `border: 2px solid var(--status-dot-ring, var(--el-bg-color))` | help/link 共享 | 共享/库锚点 | — | 声明 disabled 时 | 所属内容 | 空说明不造框 | 声明状态接口：disabled；圆点描边用于与背景分离；不是需要统一成矩形的卡片外框。 |
| [AppStatusNotice](../../../frontend/src/components/AppStatusNotice.vue) | 内容面板；面板/宿主边界；L83 `border: 1px solid var(--app-status-notice-border)`；L84 `border-radius: var(--layout-control-radius)` | 仅交互子项 | 仅交互子项 | 业务标记另计 | 子项 | 宿主框保留 | 宿主框保留/子项 | 声明状态接口：actionLoading, loading；G05：success/warning/danger 走 el-color-*-light-7；inline 主动无框；与 app-border-* 配方不同，需明确软提示角色。 |
| [AppSummaryDisclosureCard](../../../frontend/src/components/AppSummaryDisclosureCard.vue) | 展开/分组；分组层级边界；L97 `border: 1px solid var(--app-border-default)`；L98 `border-radius: var(--layout-card-radius)` | disclosure 共享 | 标题共享 ring | 展开专用分支 | 静态头/子项 | 内容区 | 内容区 | 声明状态接口：expanded, collapsible；普通 card 使用 card token，compact 仅底部分隔线；展开主色边框+左侧线是显式契约，不能认作重复框。index 6px 为局部编号。 |
| [AppTabToolbar](../../../frontend/src/components/AppTabToolbar.vue) | 结构/排版；自身无业务框；无私有 border/radius | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppControlRow |
| [AppTableCard](../../../frontend/src/components/AppTableCard.vue) | 内容面板；面板/宿主边界；无私有 border/radius | 仅交互子项 | 仅交互子项 | 业务标记另计 | 子项 | 宿主框保留 | 宿主框保留/子项 | 声明状态接口：无；状态可能来自内部/attrs/子项；已统一独立列表外框；四态与分页由同一卡片承接；混合工作区不重复包裹。 |
| [AppTableColumn](../../../frontend/src/components/AppTableColumn.vue) | 结构/排版；自身无业务框；无私有 border/radius | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-table-column |
| [AppWorkspacePane](../../../frontend/src/components/AppWorkspacePane.vue) | 内容面板；面板/宿主边界；L50 `border: 1px solid var(--el-border-color)`；L51 `border-radius: var(--layout-card-radius)` | 仅交互子项 | 仅交互子项 | 业务标记另计 | 子项 | 宿主框保留 | 宿主框保留/子项 | 声明状态接口：无；状态可能来自内部/attrs/子项；自身 card token；直接 app-stock-chart-frame 子项明确 border:0/radius:0，已处理嵌套边界。 |
| [AssetProfileLabel](../../../frontend/src/components/AssetProfileLabel.vue) | 结构/排版；自身无业务框；无私有 border/radius | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：readonly；自身只负责内容/几何；不新增状态边框 |
| [AssetVisibilityActions](../../../frontend/src/components/AssetVisibilityActions.vue) | 命令/操作；按钮角色外框；无私有 border/radius | 角色 hover/pressed | 共享 ring | 业务选择另计 | 中性保形 | saving→子按钮 | 反馈组件承接 | 声明状态接口：readonly, saving, showReadonly, copyDisabled, reuseDisabled；继承入口：el-dropdown, el-icon, el-dropdown-menu, el-dropdown-item, el-button |
| [AssetVisibilityTag](../../../frontend/src/components/AssetVisibilityTag.vue) | 标签/静态标记；领域/标签外框；无私有 border/radius | 仅链接/说明子项 | 仅可交互子项 | — | 权限/领域 helper | — | 领域缺值/状态色 | 声明状态接口：readonly；继承入口：el-tag, AppHoverInfo |
| [BrandMark](../../../frontend/src/components/BrandMark.vue) | 结构/排版；自身无业务框；无私有 border/radius | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；自身只负责内容/几何；不新增状态边框 |
| [BuiltinOptionRow](../../../frontend/src/components/BuiltinOptionRow.vue) | 结构/排版；自身无业务框；无私有 border/radius | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；自身只负责内容/几何；不新增状态边框 |
| [ChartOperationGroup](../../../frontend/src/components/ChartOperationGroup.vue) | 展开/分组；分组层级边界；无私有 border/radius | disclosure 共享 | 标题共享 ring | 展开专用分支 | 静态头/子项 | 内容区 | 内容区 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承 SettingsGroup；保留图表操作分组职责。 |
| [ComparePinButton](../../../frontend/src/components/ComparePinButton.vue) | 命令/操作；按钮角色外框；无私有 border/radius | 角色 hover/pressed | 共享 ring | 业务选择另计 | 中性保形 | —/由组合宿主锁定 | 反馈组件承接 | 声明状态接口：active, disabled；继承入口：AppIconButton, el-icon |
| [CompareQueueRail](../../../frontend/src/components/CompareQueueRail.vue) | 内容面板；面板/宿主边界；L84 `border-bottom: 1px solid var(--el-border-color-lighter)`；L98 `border: 1px solid var(--el-border-color)` | 仅交互子项 | 仅交互子项 | 业务标记另计 | 子项 | 宿主框保留 | 宿主框保留/子项 | 声明状态接口：无；状态可能来自内部/attrs/子项；错误 chip 用 warning 原色；正常1px、error改变边色。应纳入 G05 语义子角色。 |
| [ComponentAutoSettings](../../../frontend/src/components/ComponentAutoSettings.vue) | 表单/设置组合；表单/设置组合；L1186 `border-radius: 12px` | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：collapsibleSlot；继承入口：SettingsGroup, PageSettingItem, el-checkbox-group, el-checkbox, AppRowActions, el-button, StockAnaly |
| [EquityChart](../../../frontend/src/components/EquityChart.vue) | 图表/行情；图表框/宿主；L184 `border-radius: 6px` | tooltip/序列高亮 | 仅工具/分隔条 | 序列/十字线另计 | 子项 | 内容/宿主 | 内容/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；G04：外层固定6px、无实体边框；先认定是宿主内画布还是独立面板，再决定边界。 |
| [GrowthChart](../../../frontend/src/components/GrowthChart.vue) | 图表/行情；图表框/宿主；无私有 border/radius | tooltip/序列高亮 | 仅工具/分隔条 | 序列/十字线另计 | 子项 | 内容/宿主 | 内容/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；自身只负责内容/几何；不新增状态边框 |
| [HelpHint](../../../frontend/src/components/HelpHint.vue) | 说明/浮层触发；帮助/说明角色；L30 `border-radius: 50%`；L32 `border: 1px solid var(--el-border-color)` | help/link 共享 | 共享/库锚点 | — | 声明 disabled 时 | 所属内容 | 空说明不造框 | 声明状态接口：无；状态可能来自内部/attrs/子项；50%圆形是帮助图形；边色来自共享 token，hover/focus 由 help 入口统一。 |
| [HelpTip](../../../frontend/src/components/HelpTip.vue) | 说明/浮层触发；帮助/说明角色；L39 `border-radius: 50%`；L40 `border: 1px solid var(--el-border-color)` | help/link 共享 | 共享/库锚点 | — | 声明 disabled 时 | 所属内容 | 空说明不造框 | 声明状态接口：无；状态可能来自内部/attrs/子项；同 HelpHint；不将帮助圆形改为普通控件圆角。 |
| [HelpTipItem](../../../frontend/src/components/HelpTipItem.vue) | 结构/排版；自身无业务框；无私有 border/radius | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；自身只负责内容/几何；不新增状态边框 |
| [IconPicker](../../../frontend/src/components/IconPicker.vue) | 输入/选择；输入内描边；L101 `border: 1px solid var(--el-border-color)`；L101 `border-radius: 4px` | 触发主色/候选列表 | 共享 app-focus-ring | on 候选主色边框 | disabled阻断弹层 | —（无独立 loading） | 空候选；无字段 error接口 | 声明状态接口：disabled；F03：触发器4px、候选6px；hover 触发器主色、on 候选主色，焦点继承 app-focus-ring；应统一输入/候选角色。 |
| [KlineRangeSelect](../../../frontend/src/components/KlineRangeSelect.vue) | 输入/选择；输入内描边；无私有 border/radius | input/select 统一；其它库默认 | 单值主色；范围 F01 | 值/候选由库 | 透传禁用/只读 | 仅声明支持时 | 表单校验/上层 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppSelect, el-option |
| [KlineSettingSection](../../../frontend/src/components/KlineSettingSection.vue) | 表单/设置组合；表单/设置组合；无私有 border/radius | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：PageSettingItem, el-input, el-switch, AppSelect, el-option |
| [MarketAnalysisHeader](../../../frontend/src/components/MarketAnalysisHeader.vue) | 内容面板；面板/宿主边界；L70 `border-bottom: 1px solid var(--el-border-color-lighter)` | 仅交互子项 | 仅交互子项 | 业务标记另计 | 子项 | 宿主框保留 | 宿主框保留/子项 | 声明状态接口：detailDisabled；继承入口：el-button, el-icon |
| [MarketBenchmarkSelect](../../../frontend/src/components/MarketBenchmarkSelect.vue) | 输入/选择；输入内描边；无私有 border/radius | input/select 统一；其它库默认 | 单值主色；范围 F01 | 值/候选由库 | 透传禁用/只读 | 仅声明支持时 | 表单校验/上层 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppSelect, el-option |
| [MarketBoardTag](../../../frontend/src/components/MarketBoardTag.vue) | 标签/静态标记；领域/标签外框；L71 `border-radius: var(--el-border-radius-small)` | 仅链接/说明子项 | 仅可交互子项 | — | 权限/领域 helper | — | 领域缺值/状态色 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-tag |
| [MarketCompareMetricStrip](../../../frontend/src/components/MarketCompareMetricStrip.vue) | 导航/选择列表；导航/选择角色；L80 `border-bottom: 1px solid var(--el-border-color-lighter)`；L97 `border: 0` | 导航/列表共享 | 共享焦点 | route/active/checked | 支持禁用的条目 | 所属区域 | 所属区域 | 声明状态接口：activeKey；继承入口：AppScrollArea, el-button |
| [MarketDetailHero](../../../frontend/src/components/MarketDetailHero.vue) | 内容面板；面板/宿主边界；L51 `border: 1px solid var(--el-border-color)`；L52 `border-radius: var(--layout-card-radius)` | 仅交互子项 | 仅交互子项 | 业务标记另计 | 子项 | 宿主框保留 | 宿主框保留/子项 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppScrollArea |
| [MarketMasterDetailWorkspace](../../../frontend/src/components/MarketMasterDetailWorkspace.vue) | 导航/选择列表；导航/选择角色；无私有 border/radius | 导航/列表共享 | 共享焦点 | route/active/checked | 支持禁用的条目 | 所属区域 | 所属区域 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppSplitWorkspace, AppWorkspacePane, AppIconButton, el-icon |
| [MasterDetailRatioProfileSettings](../../../frontend/src/components/MasterDetailRatioProfileSettings.vue) | 表单/设置组合；表单/设置组合；无私有 border/radius | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：disabled, saving；继承入口：PageSettingsApplyButton |
| [MenuIcon](../../../frontend/src/components/MenuIcon.vue) | 结构/排版；自身无业务框；无私有 border/radius | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-icon |
| [PageDrawer](../../../frontend/src/components/PageDrawer.vue) | 内容面板；面板/宿主边界；无私有 border/radius | 仅交互子项 | 仅交互子项 | 业务标记另计 | 子项 | 宿主框保留 | 宿主框保留/子项 | 声明状态接口：无；状态可能来自内部/attrs/子项；边界唯一转交 PageDrawerSurface；el-drawer 宿主不重复画边。 |
| [PageDrawerSurface](../../../frontend/src/components/PageDrawerSurface.vue) | 内容面板；面板/宿主边界；L76 `border: 1px solid var(--page-settings-border)`；L77 `border-radius: 16px` | 仅交互子项 | 仅交互子项 | 业务标记另计 | 子项 | 宿主框保留 | 宿主框保留/子项 | 声明状态接口：无；状态可能来自内部/attrs/子项；16px 有抽屉规范依据，属于允许例外，不应机械改为10px。 |
| [PageSegmented](../../../frontend/src/components/PageSegmented.vue) | 导航/选择列表；导航/选择角色；L76 `border: 1px solid var(--page-settings-section-border)`；L77 `border-radius: 12px` | 导航/列表共享 | 共享焦点 | route/active/checked | 支持禁用的条目 | 所属区域 | 所属区域 | 声明状态接口：disabled；F03：普通12/8px，small 才跟随 control token；tabs 无框是合法变体；selected 与 disabled 需按变体保留语义。 |
| [PageSettingItem](../../../frontend/src/components/PageSettingItem.vue) | 结构/排版；自身无业务框；无私有 border/radius | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；自身只负责内容/几何；不新增状态边框 |
| [PageSettingSection](../../../frontend/src/components/PageSettingSection.vue) | 展开/分组；分组层级边界；无私有 border/radius | disclosure 共享 | 标题共享 ring | 展开专用分支 | 静态头/子项 | 内容区 | 内容区 | 声明状态接口：collapsible；继承 SettingsGroup；不增加第二套分组边框。 |
| [PageSettingsApplyButton](../../../frontend/src/components/PageSettingsApplyButton.vue) | 命令/操作；按钮角色外框；无私有 border/radius | 角色 hover/pressed | 共享 ring | 业务选择另计 | 中性保形 | loading保留角色框 | 反馈组件承接 | 声明状态接口：disabled, loading；继承入口：el-button |
| [PageSettingsDrawer](../../../frontend/src/components/PageSettingsDrawer.vue) | 表单/设置组合；表单/设置组合；L362 `border-radius: 50%` | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：PageDrawer, AppIconButton, el-icon, AppStatusNotice, SettingsGroup, el-button |
| [PageSettingsTrigger](../../../frontend/src/components/PageSettingsTrigger.vue) | 命令/操作；按钮角色外框；L29 `border-radius: 50%` | 角色 hover/pressed | 共享 ring | 业务选择另计 | 中性保形 | —/由组合宿主锁定 | 反馈组件承接 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppIconButton, el-icon |
| [PageToggleRow](../../../frontend/src/components/PageToggleRow.vue) | 布尔控件；库布尔控件；无私有 border/radius | 库状态/暗色适配 | 库焦点/暗色适配 | checked/半选 | 库禁用 | 仅支持 loading 的开关 | 表单/宿主 | 声明状态接口：disabled；继承入口：el-switch |
| [RelatedBoardCell](../../../frontend/src/components/RelatedBoardCell.vue) | 标签/静态标记；领域/标签外框；L143 `border-radius: var(--el-border-radius-small)` | 仅链接/说明子项 | 仅可交互子项 | — | 权限/领域 helper | — | 领域缺值/状态色 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppHoverInfo, el-tag |
| [RelatedBoardEmptyValue](../../../frontend/src/components/RelatedBoardEmptyValue.vue) | 说明/浮层触发；帮助/说明角色；L54 `border-radius: var(--el-border-radius-small)` | help/link 共享 | 共享/库锚点 | — | 声明 disabled 时 | 所属内容 | 空说明不造框 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppHoverInfo |
| [RelatedBoardHistoryHint](../../../frontend/src/components/RelatedBoardHistoryHint.vue) | 说明/浮层触发；帮助/说明角色；无私有 border/radius | help/link 共享 | 共享/库锚点 | — | 声明 disabled 时 | 所属内容 | 空说明不造框 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppStatusDot |
| [ScoreGradeTag](../../../frontend/src/components/ScoreGradeTag.vue) | 标签/静态标记；领域/标签外框；无私有 border/radius | 仅链接/说明子项 | 仅可交互子项 | — | 权限/领域 helper | — | 领域缺值/状态色 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-tag |
| [SectorAnalysisDefaultFields](../../../frontend/src/components/SectorAnalysisDefaultFields.vue) | 表单/设置组合；表单/设置组合；无私有 border/radius | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：PageSettingItem, PageSegmented, PageToggleRow, el-checkbox-group, el-checkbox, AppSelect, el-option |
| [SectorCompareChart](../../../frontend/src/components/SectorCompareChart.vue) | 图表/行情；图表框/宿主；L346 `border-radius: 6px` | tooltip/序列高亮 | 仅工具/分隔条 | 序列/十字线另计 | 子项 | 内容/宿主 | 内容/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；G04：外层固定6px，空/错误通过 AppStateBlock；图表内容状态不等同外框状态。 |
| [SettingsGroup](../../../frontend/src/components/SettingsGroup.vue) | 展开/分组；分组层级边界；L127 `border: 1px solid var(--page-settings-section-border)`；L128 `border-radius: 12px` | disclosure 共享 | 标题共享 ring | 展开专用分支 | 静态头/子项 | 内容区 | 内容区 | 声明状态接口：collapsible；一级12px为设置浮层例外；二级及更深用结构线，无需每层套框。 |
| [SideMenu](../../../frontend/src/components/SideMenu.vue) | 导航/选择列表；导航/选择角色；L125 `border-right: none`；L135 `border-top: 1px solid var(--chrome-border)` | 导航/列表共享 | 共享焦点 | route/active/checked | 支持禁用的条目 | 所属区域 | 所属区域 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-menu, el-menu-item-group, el-icon, el-button |
| [SideMenuItem](../../../frontend/src/components/SideMenuItem.vue) | 导航/选择列表；导航/选择角色；无私有 border/radius | 导航/列表共享 | 共享焦点 | route/active/checked | 支持禁用的条目 | 所属区域 | 所属区域 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-sub-menu, el-menu-item |
| [SourceTag](../../../frontend/src/components/SourceTag.vue) | 标签/静态标记；领域/标签外框；L50 `border-radius: 999px`；L51 `border: 1px solid var(--page-settings-border)` | 仅链接/说明子项 | 仅可交互子项 | — | 权限/领域 helper | — | 领域缺值/状态色 | 声明状态接口：无；状态可能来自内部/attrs/子项；来源身份标签主动用胶囊；page/user 主色是来源语义，并非 generic selected。 |
| [StockAnalysisDefaultFields](../../../frontend/src/components/StockAnalysisDefaultFields.vue) | 表单/设置组合；表单/设置组合；无私有 border/radius | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：PageSettingItem, PageSegmented, AppSelect, el-option, el-checkbox-group, el-checkbox, PageToggleRow |
| [StockAnalysisNameCell](../../../frontend/src/components/StockAnalysisNameCell.vue) | 标签/静态标记；领域/标签外框；无私有 border/radius | 仅链接/说明子项 | 仅可交互子项 | — | 权限/领域 helper | — | 领域缺值/状态色 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-button, StockStatusTag |
| [StockAnalysisPanel](../../../frontend/src/components/StockAnalysisPanel.vue) | 图表/行情；图表框/宿主；L617 `border: 1px solid var(--el-border-color)`；L618 `border-radius: var(--layout-card-radius)` | tooltip/序列高亮 | 仅工具/分隔条 | 序列/十字线另计 | 子项 | 内容/宿主 | 内容/宿主 | 声明状态接口：active；继承入口：AppSelect, el-option, PageSegmented, AppAsyncRegion, AppStateBlock, el-button, StockCompareChart, St |
| [StockBoardMembershipPanel](../../../frontend/src/components/StockBoardMembershipPanel.vue) | 内容面板；面板/宿主边界；无私有 border/radius | 仅交互子项 | 仅交互子项 | 业务标记另计 | 子项 | 宿主框保留 | 宿主框保留/子项 | 声明状态接口：loading, error；继承入口：el-card, AppAsyncRegion |
| [StockChartSettingSection](../../../frontend/src/components/StockChartSettingSection.vue) | 表单/设置组合；表单/设置组合；L203 `border: 1px solid var(--page-settings-seg-active-border)`；L204 `border-radius: 10px` | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：savingCurrentRatios；G04：fixed-chart-value 是设置区只读值展示，不是可点击选择器；固定10px/strong border需要角色登记，暂不按普通输入框判错。 |
| [StockCompareChart](../../../frontend/src/components/StockCompareChart.vue) | 图表/行情；图表框/宿主；L242 `border-radius: 6px` | tooltip/序列高亮 | 仅工具/分隔条 | 序列/十字线另计 | 子项 | 内容/宿主 | 内容/宿主 | 声明状态接口：activeCode；G04：外层固定6px，空/错误通过 AppStateBlock；不应与既有工作区框重复。 |
| [StockGroupBatchActions](../../../frontend/src/components/StockGroupBatchActions.vue) | 表单/设置组合；表单/设置组合；L207 `border: 1px solid var(--el-color-primary-light-7)` | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：activeGroupId；继承入口：el-card, AppScrollArea, el-tag, el-button, AppDialog, el-form, el-form-item, el-input, TradeDatePick |
| [StockGroupFavoriteButton](../../../frontend/src/components/StockGroupFavoriteButton.vue) | 命令/操作；按钮角色外框；无私有 border/radius | 角色 hover/pressed | 共享 ring | 业务选择另计 | 中性保形 | 内部请求loading | 反馈组件承接 | 声明状态接口：active；继承入口：AppIconButton, el-icon |
| [StockStatusTag](../../../frontend/src/components/StockStatusTag.vue) | 标签/静态标记；领域/标签外框；无私有 border/radius | 仅链接/说明子项 | 仅可交互子项 | — | 权限/领域 helper | — | 领域缺值/状态色 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppHoverInfo, el-tag |
| [SubScoreBars](../../../frontend/src/components/SubScoreBars.vue) | 标签/静态标记；领域/标签外框；L55 `border-radius: 4px`；L73 `border-radius: 2px` | 仅链接/说明子项 | 仅可交互子项 | — | 权限/领域 helper | — | 领域缺值/状态色 | 声明状态接口：无；状态可能来自内部/attrs/子项；4px 单元与2px图形点属于微型评分图；按图形角色登记。 |
| [SubScoreChips](../../../frontend/src/components/SubScoreChips.vue) | 标签/静态标记；领域/标签外框；L47 `border-radius: 11px` | 仅链接/说明子项 | 仅可交互子项 | — | 权限/领域 helper | — | 领域缺值/状态色 | 声明状态接口：无；状态可能来自内部/attrs/子项；11px 为评分胶囊固定形态；需作为身份形态登记，不能机械套10/6px。 |
| [SystemBuiltinTag](../../../frontend/src/components/SystemBuiltinTag.vue) | 标签/静态标记；领域/标签外框；无私有 border/radius | 仅链接/说明子项 | 仅可交互子项 | — | 权限/领域 helper | — | 领域缺值/状态色 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-tag |
| [TopNavigation](../../../frontend/src/components/TopNavigation.vue) | 导航/选择列表；导航/选择角色；L183 `border: 0`；L184 `border-radius: var(--app-nav-item-radius)` | 导航/列表共享 | 共享焦点 | route/active/checked | 支持禁用的条目 | 所属区域 | 所属区域 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppScrollArea, el-dropdown, el-icon, el-dropdown-menu, el-dropdown-item |
| [TradeDatePicker](../../../frontend/src/components/TradeDatePicker.vue) | 输入/选择；输入内描边；无私有 border/radius | input/select 统一；其它库默认 | 单值主色；范围 F01 | 值/候选由库 | 透传禁用/只读 | —（无独立 loading） | 表单校验/上层 | 声明状态接口：无；状态可能来自内部/attrs/子项；沿 AppDatePicker；不能以单日期通过推断范围通过。 |
| [WorkspaceRouteView](../../../frontend/src/components/WorkspaceRouteView.vue) | 异步/反馈宿主；自身/宿主见备注；无私有 border/radius | 仅动作子项 | 仅动作子项 | 子项 | 子项 | 骨架/遮罩 | empty/error 分支 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppStateBlock |
| [WorkspaceTabs](../../../frontend/src/components/WorkspaceTabs.vue) | 导航/选择列表；导航/选择角色；L176 `border-bottom: 1px solid var(--chrome-border)`；L214 `border-radius: var(--app-control-height-xs)` | 导航/列表共享 | 共享焦点 | route/active/checked | 支持禁用的条目 | 所属区域 | 所属区域 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppIconButton, AppScrollArea, AppCloseButton |
| [AssetProfileSelect](../../../frontend/src/components/asset-search/AssetProfileSelect.vue) | 异步/反馈宿主；自身/宿主见备注；L499 `border-radius: var(--layout-control-radius, 6px)` | 仅动作子项 | 仅动作子项 | 子项 | 子项 | 骨架/遮罩 | empty/error 分支 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppStateBlock, AppSelect, el-option, el-button, el-icon, AppStatusNotice, AppScrollArea, AppCloseBut |
| [AssetSearchDrawer](../../../frontend/src/components/asset-search/AssetSearchDrawer.vue) | 异步/反馈宿主；自身/宿主见备注；L503 `border-top: 1px solid var(--el-border-color-lighter)` | 仅动作子项 | 仅动作子项 | 子项 | 子项 | 骨架/遮罩 | empty/error 分支 | 声明状态接口：canBrowse；继承入口：PageDrawer, PageSegmented, el-input, el-icon, AppScrollArea, AppStateBlock, AppDataTable, AppTableCo |
| [ConfigGroupForm](../../../frontend/src/components/config/ConfigGroupForm.vue) | 表单/设置组合；表单/设置组合；L242 `border-radius: 8px`；L296 `border-radius: 50%` | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：disabled；F03：根 config-group-panel 固定8px，覆盖同角色 ConfigPanelSection；is-invalid 只定义 number/select 输入红框。 |
| [ConfigPanelSection](../../../frontend/src/components/config/ConfigPanelSection.vue) | 展开/分组；分组层级边界；L96 `border: 1px solid var(--app-border-default)`；L97 `border-radius: 6px` | disclosure 共享 | 标题共享 ring | 展开专用分支 | 静态头/子项 | 内容区 | 内容区 | 声明状态接口：collapsible；F03：一级固定6px，未跟随 card token；原生标题 disclosure 的焦点已有共享入口。 |
| [BoardTaskScopeFields](../../../frontend/src/components/data/BoardTaskScopeFields.vue) | 表单/设置组合；表单/设置组合；无私有 border/radius | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-form-item, PageSegmented, AppFormHelp, el-checkbox-group, el-checkbox, TradeDatePicker |
| [CurrentDayFallbackField](../../../frontend/src/components/data/CurrentDayFallbackField.vue) | 表单/设置组合；表单/设置组合；无私有 border/radius | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-form-item, el-checkbox, AppFormHelp |
| [DataMetricCard](../../../frontend/src/components/data/DataMetricCard.vue) | 内容面板；面板/宿主边界；无私有 border/radius | 仅交互子项 | 仅交互子项 | 业务标记另计 | 子项 | 宿主框保留 | 宿主框保留/子项 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-card, el-button, el-icon |
| [DataMetricDetails](../../../frontend/src/components/data/DataMetricDetails.vue) | 说明/浮层触发；帮助/说明角色；L40 `border: 1px solid var(--el-border-color)`；L41 `border-radius: 50%` | help/link 共享 | 共享/库锚点 | — | 声明 disabled 时 | 所属内容 | 空说明不造框 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppHoverInfo, AppScrollArea, AppDetailFields, AppDetailField |
| [IntradayTaskScopeFields](../../../frontend/src/components/data/IntradayTaskScopeFields.vue) | 表单/设置组合；表单/设置组合；无私有 border/radius | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-form-item, PageSegmented, AppFormHelp, StockCodeMultiSelect, TradeDatePicker, el-alert |
| [ResultMaintenanceTaskFields](../../../frontend/src/components/data/ResultMaintenanceTaskFields.vue) | 表单/设置组合；表单/设置组合；无私有 border/radius | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-form-item, PageSegmented, TradeDatePicker, AppFormHelp, StockCodeMultiSelect, el-alert |
| [StockCodeMultiSelect](../../../frontend/src/components/data/StockCodeMultiSelect.vue) | 输入/选择；输入内描边；无私有 border/radius | input/select 统一；其它库默认 | 单值主色；范围 F01 | 值/候选由库 | 透传禁用/只读 | 仅声明支持时 | 表单校验/上层 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppSelect, el-option |
| [StockIngestScopeFields](../../../frontend/src/components/data/StockIngestScopeFields.vue) | 表单/设置组合；表单/设置组合；无私有 border/radius | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-form-item, AppSelect, el-option, PageSegmented, StockCodeMultiSelect, TradeDatePicker, el-input-n |
| [IndicatorParamFields](../../../frontend/src/components/indicator/IndicatorParamFields.vue) | 输入/选择；输入内描边；无私有 border/radius | input/select 统一；其它库默认 | 单值主色；范围 F01 | 值/候选由库 | 透传禁用/只读 | —（无独立 loading） | 表单校验/上层 | 声明状态接口：disabled；继承入口：el-input-number |
| [IndicatorParamSchemaEditor](../../../frontend/src/components/indicator/IndicatorParamSchemaEditor.vue) | 内容面板；面板/宿主边界；L65 `border: 1px solid var(--el-border-color-lighter)`；L66 `border-radius: var(--layout-card-radius)` | 仅交互子项 | 仅交互子项 | 业务标记另计 | 子项 | 宿主框保留 | 宿主框保留/子项 | 声明状态接口：disabled；继承入口：AppIconButton, el-icon, el-input, AppSelect, el-option, el-input-number, el-button |
| [IndicatorSelect](../../../frontend/src/components/indicator/IndicatorSelect.vue) | 输入/选择；输入内描边；无私有 border/radius | input/select 统一；其它库默认 | 单值主色；范围 F01 | 值/候选由库 | 透传禁用/只读 | 仅声明支持时 | 表单校验/上层 | 声明状态接口：disabled；继承入口：AppSelect, el-option-group, el-option |
| [ProfileVersionContent](../../../frontend/src/components/indicator/ProfileVersionContent.vue) | 表单/设置组合；表单/设置组合；无私有 border/radius | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppDetailFields, AppDetailField, AppDetailSection, AppDataTable, AppTableColumn, AppSummaryDisclosur |
| [RankedStockResultTable](../../../frontend/src/components/ranked-stock/RankedStockResultTable.vue) | 表单/设置组合；表单/设置组合；无私有 border/radius | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：loading, activeCode；继承入口：AppDataTable, AppTableColumn, AppRowActions, StockStatusTag, StockAnalysisNameCell, el-button |
| [RankedStockWorkbench](../../../frontend/src/components/ranked-stock/RankedStockWorkbench.vue) | 表单/设置组合；表单/设置组合；无私有 border/radius | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：loading；继承入口：StockAnalysisPanel |
| [StockChartLegend](../../../frontend/src/components/stock-chart/StockChartLegend.vue) | 结构/排版；自身无业务框；L56 `border-radius: 1px` | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；1px marker 圆角是图形语义，不按普通控件 token 判违规。 |
| [StockChartOperationsDrawer](../../../frontend/src/components/stock-chart/StockChartOperationsDrawer.vue) | 内容面板；面板/宿主边界；无私有 border/radius | 仅交互子项 | 仅交互子项 | 业务标记另计 | 子项 | 宿主框保留 | 宿主框保留/子项 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：PageDrawer |
| [StockChartPanelDivider](../../../frontend/src/components/stock-chart/StockChartPanelDivider.vue) | 排序/尺寸交互；结构/把手；L23 `border-top: 1px solid var(--el-border-color-lighter)`；L24 `border-bottom: 1px solid var(--el-border-color-lighter)` | 命中区反馈 | 键盘把手/分隔条 | 拖动/drop/预览 | 停止调整 | 提交归宿主 | 取消/拒绝恢复 | 声明状态接口：interactive；双分隔线、键盘内焦点和拖动条是专用图表契约；保持为独立角色。 |
| [StockChartPanelHeader](../../../frontend/src/components/stock-chart/StockChartPanelHeader.vue) | 结构/排版；自身无业务框；L32 `border-bottom: 1px solid var(--el-border-color-lighter)` | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：StockChartLegend |
| [StockChartRegion](../../../frontend/src/components/stock-chart/StockChartRegion.vue) | 结构/排版；自身无业务框；无私有 border/radius | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；自身只负责内容/几何；不新增状态边框 |
| [StockChartWorkspace](../../../frontend/src/components/stock-chart/StockChartWorkspace.vue) | 图表/行情；图表框/宿主；L1466 `border-bottom: 1px solid var(--el-border-color-lighter)`；L1479 `border: 1px solid var(--el-border-color-lighter)` | tooltip/序列高亮 | 仅工具/分隔条 | 序列/十字线另计 | 子项 | 内容/宿主 | 内容/宿主 | 声明状态接口：macdState, macdError, preserveActiveBar；继承入口：StockChartPanelHeader, PageSegmented, AppIconButton, StockChartLegend, AppStateBlock, StockChartPane |
| [StockIntradayChart](../../../frontend/src/components/stock-chart/StockIntradayChart.vue) | 图表/行情；图表框/宿主；无私有 border/radius | tooltip/序列高亮 | 仅工具/分隔条 | 序列/十字线另计 | 子项 | 内容/宿主 | 内容/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：StockChartPanelHeader, StockChartPanelDivider |
| [StockIntradayDialog](../../../frontend/src/components/stock-chart/StockIntradayDialog.vue) | 异步/反馈宿主；自身/宿主见备注；无私有 border/radius | 仅动作子项 | 仅动作子项 | 子项 | 子项 | 骨架/遮罩 | empty/error 分支 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppDialog, StockQuoteSummary, AppStateBlock, AppStatusNotice, StockIntradayChart |
| [StockQuoteSummary](../../../frontend/src/components/stock-chart/StockQuoteSummary.vue) | 结构/排版；自身无业务框；L63 `border-right: 1px solid var(--el-border-color)`；L74 `border-left: 1px solid var(--el-border-color)` | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppScrollArea |
| [StrategyItemEnabledSwitch](../../../frontend/src/components/strategy/StrategyItemEnabledSwitch.vue) | 布尔控件；库布尔控件；无私有 border/radius | 库状态/暗色适配 | 库焦点/暗色适配 | checked/半选 | 库禁用 | 仅支持 loading 的开关 | 表单/宿主 | 声明状态接口：disabled；继承入口：el-switch |
| [RuleSummaryCard](../../../frontend/src/components/trade-discipline/RuleSummaryCard.vue) | 展开/分组；分组层级边界；无私有 border/radius | disclosure 共享 | 标题共享 ring | 展开专用分支 | 静态头/子项 | 内容区 | 内容区 | 声明状态接口：expanded；继承入口：AppSummaryDisclosureCard, el-switch |
| [StockRuleChecklistEditor](../../../frontend/src/components/trade-discipline/StockRuleChecklistEditor.vue) | 表单/设置组合；表单/设置组合；无私有 border/radius | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：disabled；继承入口：el-button, ConfigPanelSection, AppReorderList, el-input, AppSelect, el-option, AppIconButton |
| [StockRuleConditionChecklist](../../../frontend/src/components/trade-discipline/StockRuleConditionChecklist.vue) | 表单/设置组合；表单/设置组合；无私有 border/radius | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：checking, disabled；继承入口：ConfigPanelSection, el-segmented |
| [TradeDirectionGroupGrid](../../../frontend/src/components/trade-discipline/TradeDirectionGroupGrid.vue) | 结构/排版；自身无业务框；L45 `border-top: 1px solid var(--el-border-color)` | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；自身只负责内容/几何；不新增状态边框 |
| [TradeDisciplineQuickCard](../../../frontend/src/components/trade-discipline/TradeDisciplineQuickCard.vue) | 表单/设置组合；表单/设置组合；L223 `border: 1px solid var(--page-settings-section-border)`；L224 `border-radius: 12px` | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：canSubmit；例外/G05：当前只由用户中心抽屉消费，12px符合浮层卡片允许范围；进度框8px与状态配方需登记，不能误判普通页面卡片。 |
| [TradeDisciplineSectionPanel](../../../frontend/src/components/trade-discipline/TradeDisciplineSectionPanel.vue) | 内容面板；面板/宿主边界；L42 `border: 1px solid var(--el-border-color-lighter)`；L43 `border-radius: var(--layout-card-radius)` | 仅交互子项 | 仅交互子项 | 业务标记另计 | 子项 | 宿主框保留 | 宿主框保留/子项 | 声明状态接口：无；状态可能来自内部/attrs/子项；自身只负责内容/几何；不新增状态边框 |
| [LayoutComponentPreview](../../../frontend/src/layout/components/LayoutComponentPreview.vue) | 设计预览；模型原型；L118 `border: 1px solid var(--el-border-color)`；L119 `border-radius: 6px` | slot 分支 | 交互预览/子项 | 预览选中 | 仅有真实属性者 | 状态原型 | AppStateBlock | 声明状态接口：state；G07：ready 允许代表性原型，固定4/6px不代表实际控件；禁止将预览状态视为真实组件验收。 |
| [LayoutHost](../../../frontend/src/layout/components/LayoutHost.vue) | 结构/排版；自身无业务框；无私有 border/radius | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppScrollArea |
| [LayoutPagePreview](../../../frontend/src/layout/components/LayoutPagePreview.vue) | 设计预览；模型原型；L238 `border: 1px solid var(--el-border-color)`；L239 `border-radius: 6px` | slot 分支 | 交互预览/子项 | 预览选中 | 仅有真实属性者 | 状态原型 | AppStateBlock | 声明状态接口：无；状态可能来自内部/attrs/子项；G07：设备框/slot 是模型图；选择轮廓与原始内容组件分开验收。 |
| [LayoutSettingsSection](../../../frontend/src/layout/components/LayoutSettingsSection.vue) | 表单/设置组合；表单/设置组合；无私有 border/radius | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：SettingsGroup, PageToggleRow, PageSettingItem, PageSegmented, el-input-number |
| [VAdaptiveGrow](../../../frontend/src/layout/components/VAdaptiveGrow.vue) | 结构/排版；自身无业务框；无私有 border/radius | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppScrollArea |
| [VColumns](../../../frontend/src/layout/components/VColumns.vue) | 结构/排版；自身无业务框；无私有 border/radius | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppScrollArea |
| [VMixedGrow](../../../frontend/src/layout/components/VMixedGrow.vue) | 结构/排版；自身无业务框；无私有 border/radius | — | —；slot另计 | — | — | 子项 | 子项/宿主 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppScrollArea |
| [CheckupReportContent](../../../frontend/src/views/data/components/CheckupReportContent.vue) | 异步/反馈宿主；自身/宿主见备注；无私有 border/radius | 仅动作子项 | 仅动作子项 | 子项 | 子项 | 骨架/遮罩 | empty/error 分支 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppStateBlock, AppDetailSection, AppSummaryDisclosureCard, AppDataTable, AppTableColumn |
| [QualityDiagnosticContent](../../../frontend/src/views/data/components/QualityDiagnosticContent.vue) | 异步/反馈宿主；自身/宿主见备注；无私有 border/radius | 仅动作子项 | 仅动作子项 | 子项 | 子项 | 骨架/遮罩 | empty/error 分支 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：AppDetailSection, AppDetailFields, AppDetailField, AppDataTable, AppTableColumn, AppSummaryDisclosur |
| [LadderHotspots](../../../frontend/src/views/limit-ladder/LadderHotspots.vue) | 导航/选择列表；导航/选择角色；L72 `border-bottom: 1px solid var(--el-border-color-lighter)`；L76 `border: 1px solid var(--el-border-color)` | 导航/列表共享 | 共享焦点 | route/active/checked | 支持禁用的条目 | 所属区域 | 所属区域 | 声明状态接口：activeType, activeKey；继承入口：AppHoverInfo, AppStatusDot |
| [LimitLadder](../../../frontend/src/views/limit-ladder/LimitLadder.vue) | 异步/反馈宿主；自身/宿主见备注；L306 `border-bottom: 1px solid var(--el-border-color-lighter)`；L311 `border-radius: 0` | 仅动作子项 | 仅动作子项 | 子项 | 子项 | 骨架/遮罩 | empty/error 分支 | 声明状态接口：loading, error, forbidden, canManageData, selectedCode；继承入口：AppStatusNotice, el-tag, el-button, AppScrollArea, AppStateBlock |
| [LimitLadderCard](../../../frontend/src/views/limit-ladder/LimitLadderCard.vue) | 导航/选择列表；导航/选择角色；L126 `border: 1px solid var(--el-border-color-lighter)`；L127 `border-radius: var(--layout-card-radius)` | 导航/列表共享 | 共享焦点 | route/active/checked | 支持禁用的条目 | 所属区域 | 所属区域 | 声明状态接口：selected；普通边界和选择标记由共享 app-interaction-card 唯一表面绘制；宿主透明框用于占位。 |
| [LimitLadderFilters](../../../frontend/src/views/limit-ladder/LimitLadderFilters.vue) | 表单/设置组合；表单/设置组合；无私有 border/radius | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-card, AppAdvancedSearch, TradeDatePicker, PageSegmented, AppFilterSelect, AppFilterSwitch, AppSea |
| [PermissionResourceList](../../../frontend/src/views/system/PermissionResourceList.vue) | 导航/选择列表；导航/选择角色；L41 `border-top: 1px solid var(--el-border-color-lighter)`；L53 `border: 1px solid var(--el-border-color-lighter)` | 导航/列表共享 | 共享焦点 | route/active/checked | 支持禁用的条目 | 所属区域 | 所属区域 | 声明状态接口：stateOf, readonly；G04：选中主要改变 checkbox 内框，外层 pt-func 保持中性；与整卡候选的选中边界职责需区分。 |
| [PermissionTree](../../../frontend/src/views/system/PermissionTree.vue) | 导航/选择列表；导航/选择角色；L137 `border: 1px solid var(--el-border-color)`；L138 `border-radius: 8px` | 导航/列表共享 | 共享焦点 | route/active/checked | 支持禁用的条目 | 所属区域 | 所属区域 | 声明状态接口：stateOf, readonly；G04：权限内部组面板固定8px；是否属于普通卡片需按嵌套职责确认；标题焦点已共享，不因圆角差异否定焦点。 |
| [FixedDecimalInput](../../../frontend/src/views/trade-discipline/components/FixedDecimalInput.vue) | 输入/选择；输入内描边；无私有 border/radius | input/select 统一；其它库默认 | 单值主色；范围 F01 | 值/候选由库 | 透传禁用/只读 | —（无独立 loading） | 表单校验/上层 | 声明状态接口：disabled；继承入口：el-input |
| [RuleMasterList](../../../frontend/src/views/trade-discipline/components/RuleMasterList.vue) | 导航/选择列表；导航/选择角色；L161 `border: 1px solid var(--el-border-color)`；L162 `border-radius: var(--layout-card-radius)` | 导航/列表共享 | 共享焦点 | route/active/checked | 支持禁用的条目 | 所属区域 | 所属区域 | 声明状态接口：selectedId, loading, error, canManage, checkinStates；普通外框card token；条目使用共享 app-interaction-list-item，选中和焦点分开。 |
| [StockOptionSelect](../../../frontend/src/views/trade-discipline/components/StockOptionSelect.vue) | 输入/选择；输入内描边；无私有 border/radius | input/select 统一；其它库默认 | 单值主色；范围 F01 | 值/候选由库 | 透传禁用/只读 | 仅声明支持时 | 表单校验/上层 | 声明状态接口：disabled；继承入口：AppSelect, el-option, StockStatusTag |
| [TradeCheckinForm](../../../frontend/src/views/trade-discipline/components/TradeCheckinForm.vue) | 表单/设置组合；表单/设置组合；L467 `border-bottom: 1px solid var(--el-border-color-lighter)`；L475 `border-left: 3px solid var(--el-color-primary)` | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：canSubmit；继承入口：AppScrollArea, AppStateBlock, TradeDatePicker, el-button, el-form, TradeDisciplineSectionPanel, el-f |
| [TradeCheckinRevisionDrawer](../../../frontend/src/views/trade-discipline/components/TradeCheckinRevisionDrawer.vue) | 异步/反馈宿主；自身/宿主见备注；L266 `border-bottom: 1px solid var(--el-border-color-lighter)`；L270 `border: 1px solid var(--el-border-color-lighter)` | 仅动作子项 | 仅动作子项 | 子项 | 子项 | 骨架/遮罩 | empty/error 分支 | 声明状态接口：canSubmit；继承入口：AppDetailDrawer, el-tag, AppFilterSelect, AppDataTable, AppTableColumn, StockStatusTag, StockRuleCon |
| [TradeDisciplineHistory](../../../frontend/src/views/trade-discipline/components/TradeDisciplineHistory.vue) | 异步/反馈宿主；自身/宿主见备注；无私有 border/radius | 仅动作子项 | 仅动作子项 | 子项 | 子项 | 骨架/遮罩 | empty/error 分支 | 声明状态接口：无；状态可能来自内部/attrs/子项；继承入口：el-card, AppAdvancedSearch, AppControlItem, TradeDatePicker, AppFilterSelect, StockOptionSelect, App |
| [TradeOperationEditor](../../../frontend/src/views/trade-discipline/components/TradeOperationEditor.vue) | 表单/设置组合；表单/设置组合；L496 `border-top: 1px solid var(--el-border-color-lighter)` | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：disabled；继承入口：TradeDisciplineSectionPanel, TradeDirectionGroupGrid, el-button, AppStateBlock, AppSummaryDisclosure |
| [TradeRuleEditor](../../../frontend/src/views/trade-discipline/components/TradeRuleEditor.vue) | 表单/设置组合；表单/设置组合；L804 `border: 1px solid var(--el-border-color)`；L804 `border-radius: var(--layout-card-radius)` | 子项 B/I/T | 子项 B/I/T | 子项选择 | 实际透传处 | saving/子项 | 校验/错误分支 | 声明状态接口：canManage；继承入口：AppScrollArea, AppStateBlock, AppStatusNotice, el-button, el-form, el-form-item, el-input, el-input- |
| [ViolationReasonCombobox](../../../frontend/src/views/trade-discipline/components/ViolationReasonCombobox.vue) | 输入/选择；输入内描边；无私有 border/radius | input/select 统一；其它库默认 | 单值主色；范围 F01 | 值/候选由库 | 透传禁用/只读 | 仅声明支持时 | 表单校验/上层 | 声明状态接口：disabled；继承入口：AppSelect, el-option, AppIconButton |

## 25 个路由 View 的边界补查

以下只核查边框消费与覆盖，不扩展到业务正确性。

| 页面 / 源码 | 私有边界与圆角证据 | 状态范围与统一方向 |
|---|---|---|
| [BacktestView](../../../frontend/src/views/BacktestView.vue) | L2546 `border-radius: 8px` (.dlg-summary)；L2563 `border-radius: 3px` (.bd-hit-legend)；L2606 `border-radius: 6px` (.prof-desc)；L2644 `border-radius: 8px` (.metric)；L2700 `border-radius: var(--layout-control-radius, 6px)` (.temp-readonly-chip) | 自绘普通面板/控件纳入 F04；图形/胶囊/登录独立形态按角色登记。 |
| [BoardView](../../../frontend/src/views/BoardView.vue) | 没有新增普通圆角/状态边框私有声明 | 继承共享组件边界；异步内容与配置状态由所属组件核查，不新增页面外框配方。 |
| [ConfigView](../../../frontend/src/views/ConfigView.vue) | L2901 `border-radius: 10px` (.ver-badge)；L2912 `border-radius: 6px` (.ver-item)；L2984 `border-radius: 4px` (.subchip)；L3014 `border-radius: 4px` (.expr)；L3052 `border-radius: 50%` (:global(.indicator-editor-section__head > span))；L3080 `border-radius: var(--layout-card-radius)` (:global(.indicator-create-mode .el-radio-button__inner))；L3087 `border-color: var(--el-color-primary)` (:global(.indicator-create-mode .el-radio-button.is-active .el-radio-button__inner))；L3148 `border-radius: var(--layout-card-radius)` (:global(.indicator-editor-section--preview))；L3164 `border-radius: var(--layout-card-radius)` (:global(.indicator-preview-result))；L3185 `border-radius: 8px` (.cond-block) | 技术指标列表已收敛；配置分组 F03 和自定义编辑/版本片段 F04 仍需分类迁移。 |
| [LimitLadderView](../../../frontend/src/views/LimitLadderView.vue) | 没有新增普通圆角/状态边框私有声明 | 继承共享组件边界；异步内容与配置状态由所属组件核查，不新增页面外框配方。 |
| [LoginView](../../../frontend/src/views/LoginView.vue) | L613 `border-radius: 50%` (.market-orbit)；L689 `border-radius: 50%` (.market-readout::before)；L820 `border-radius: 50%` (.login-brand-points li::before)；L848 `border-radius: 50%` (.login-theme)；L853 `border-radius: 999px` (.login-preset)；L865 `border-radius: 50%` (.login-preset i)；L878 `border-radius: 20px` (.login-card)；L908 `border-radius: 10px` (.login-tabs)；L915 `border-radius: 7px` (.login-tab)；L940 `border-radius: 10px` (.login-field)；L952 `border-color: var(--login-border-focus)` (.login-field:focus-within)；L959 `border-color: var(--login-danger)` (.login-field.is-error)；L962 `border-color: var(--login-danger)` (.login-field.is-error:focus-within)；L982 `border: 1px solid var(--app-border-danger)` (.login-form-error)；L983 `border-radius: 9px` (.login-form-error)；L1050 `border-radius: 10px` (.login-captcha-img)；L1069 `border-radius: 10px` (.login-primary)；L1082 `border-color: var(--login-accent)` (.login-primary:hover:not(:disabled))；L1111 `border-radius: 50%` (.login-security i)；L1161 `border-radius: 16px` (.login-card) | 登录为品牌页例外候选；已有错误+焦点保持错误色分支；不要求与工作台每个圆角数值相同，需登记身份形态。 |
| [ScreenView](../../../frontend/src/views/ScreenView.vue) | L1188 `border-radius: 10px` (.ver-badge)；L1203 `border-radius: 8px` (.cond-block)；L1243 `border-radius: 6px` (.ast)；L1251 `border-radius: 6px` (.ver-item) | 自绘普通面板/控件纳入 F04；图形/胶囊/登录独立形态按角色登记。 |
| [SectorDetailView](../../../frontend/src/views/SectorDetailView.vue) | L742 `border-radius: var(--layout-card-radius)` (.metric-strip)；L747 `border-radius: 999px` (.sector-type)；L804 `border-radius: 0` (.sector-chart-workspace) | 继承共享组件边界；异步内容与配置状态由所属组件核查，不新增页面外框配方。 |
| [SectorsView](../../../frontend/src/views/SectorsView.vue) | L1537 `border-radius: var(--layout-card-radius)` (.chart-panel) | 继承共享组件边界；异步内容与配置状态由所属组件核查，不新增页面外框配方。 |
| [StockDetailView](../../../frontend/src/views/StockDetailView.vue) | L1614 `border-radius: 999px` (.stock-type)；L1623 `border-radius: 4px` (.group-select-tag)；L1635 `border-radius: 50%` (.color-dot) | 自绘普通面板/控件纳入 F04；图形/胶囊/登录独立形态按角色登记。 |
| [StocksView](../../../frontend/src/views/StocksView.vue) | L1509 `border-radius: 50%` (.color-dot)；L1538 `border-radius: 4px` (.box-tag) | 自绘普通面板/控件纳入 F04；图形/胶囊/登录独立形态按角色登记。 |
| [TradeDisciplineView](../../../frontend/src/views/TradeDisciplineView.vue) | L802 `border-radius: var(--layout-card-radius)` (.panel-detail) | 继承共享组件边界；异步内容与配置状态由所属组件核查，不新增页面外框配方。 |
| [TrainingView](../../../frontend/src/views/TrainingView.vue) | L1028 `border-radius: 10px` (.grade-chip)；L1034 `border-radius: 8px` (.action-panel)；L1041 `border-radius: 6px` (.pending)；L1047 `border-radius: 4px` (.hl)；L1058 `border-radius: 8px` (.kpi) | 自绘普通面板/控件纳入 F04；图形/胶囊/登录独立形态按角色登记。 |
| [IngestView](../../../frontend/src/views/data/IngestView.vue) | L1335 `border-radius: 8px` (.act)；L1344 `border-radius: 6px` (.log-body) | 自绘普通面板/控件纳入 F04；图形/胶囊/登录独立形态按角色登记。 |
| [OverviewView](../../../frontend/src/views/data/OverviewView.vue) | L1326 `border-radius: 6px` (.layer-card)；L1361 `border-radius: 4px` (.board-hero-main, .board-hero-status, .board-side-block, .cov-card, .fresh-cell)；L1583 `border-radius: 4px` (.issue-card)；L1606 `border-radius: 4px` (.issue-ok-card)；L1613 `border-radius: 50%` (.issue-ok-dot) | 自绘普通面板/控件纳入 F04；图形/胶囊/登录独立形态按角色登记。 |
| [QualityView](../../../frontend/src/views/data/QualityView.vue) | 没有新增普通圆角/状态边框私有声明 | 继承共享组件边界；异步内容与配置状态由所属组件核查，不新增页面外框配方。 |
| [ScheduleView](../../../frontend/src/views/data/ScheduleView.vue) | 没有新增普通圆角/状态边框私有声明 | 继承共享组件边界；异步内容与配置状态由所属组件核查，不新增页面外框配方。 |
| [LayoutComponentsView](../../../frontend/src/views/layout/LayoutComponentsView.vue) | L587 `border-radius: 6px` (.plain-panel) | 自绘普通面板/控件纳入 F04；图形/胶囊/登录独立形态按角色登记。 |
| [LayoutPagesView](../../../frontend/src/views/layout/LayoutPagesView.vue) | L919 `border-radius: 6px` (.plain-panel)；L997 `border-radius: var(--layout-control-radius)` (.inspector-section--muted)；L1024 `border-radius: var(--layout-control-radius)` (.inspector-empty)；L1050 `border: 1px solid var(--el-border-color-lighter)` (.focused-slot-card)；L1051 `border-radius: var(--layout-control-radius)` (.focused-slot-card) | 自绘普通面板/控件纳入 F04；图形/胶囊/登录独立形态按角色登记。 |
| [LayoutPresetsView](../../../frontend/src/views/layout/LayoutPresetsView.vue) | 没有新增普通圆角/状态边框私有声明 | 继承共享组件边界；异步内容与配置状态由所属组件核查，不新增页面外框配方。 |
| [AuditLogView](../../../frontend/src/views/system/AuditLogView.vue) | L849 `border-radius: 8px` (.metric)；L910 `border-radius: 8px` (.detail-hero)；L950 `border-radius: 6px` (.change-table) | 自绘普通面板/控件纳入 F04；图形/胶囊/登录独立形态按角色登记。 |
| [DataDictionaryView](../../../frontend/src/views/system/DataDictionaryView.vue) | L756 `border-radius: var(--layout-card-radius)` (.dict-panel)；L780 `border-radius: 0` (.dict-type-card)；L805 `border-radius: 6px` (.dict-type-row)；L879 `border-radius: 3px` (.dict-color-swatch) | 自绘普通面板/控件纳入 F04；图形/胶囊/登录独立形态按角色登记。 |
| [MenuResourceView](../../../frontend/src/views/system/MenuResourceView.vue) | L863 `border-radius: 8px` (.mr-col)；L910 `border-radius: 6px` (.resource-table) | 自绘普通面板/控件纳入 F04；图形/胶囊/登录独立形态按角色登记。 |
| [RoleManageView](../../../frontend/src/views/system/RoleManageView.vue) | L484 `border-radius: 8px` (.rm-col)；L493 `border-radius: 7px` (.role) | 自绘普通面板/控件纳入 F04；图形/胶囊/登录独立形态按角色登记。 |
| [TenantManageView](../../../frontend/src/views/system/TenantManageView.vue) | 没有新增普通圆角/状态边框私有声明 | 继承共享组件边界；异步内容与配置状态由所属组件核查，不新增页面外框配方。 |
| [UserManageView](../../../frontend/src/views/system/UserManageView.vue) | 没有新增普通圆角/状态边框私有声明 | 继承共享组件边界；异步内容与配置状态由所属组件核查，不新增页面外框配方。 |

## 56 种组件库类型与运行时服务补查

以下包含布局标签，非交互标签的 H/F/S/D/L/E 均为不适用或子项状态。复合组件按真实着色入口判断，不能只看标签名。

| 标签 | 角色/边框入口 | 逐状态结论与适用边界 |
|---|---|---|
| el-alert | A | 库软反馈默认与 AppStatusNotice 实体边框不同；G05应分别定义软提示/边框提示。 |
| el-aside | K | 布局、图标或分组标签；本身无独立业务状态边框，实际状态由子项承接。 |
| el-button | B | buttonStates 完整角色矩阵；focus/disabled/loading 已区分；普通命令无 selected。 |
| el-button-group | B | 子按钮继承 B；相邻接缝与首尾圆角需随 control token。 |
| el-card | P | 主题 cardRadius、chrome border；纯列表通过 AppTableCard，普通 mixed卡不清零内距。 |
| el-checkbox | T | checked/半选/disabled 走库；暗色 hover/focus/checked/disabled 有全局覆盖。 |
| el-checkbox-button | T | 组边界与普通 checkbox 圆形/小方框不同，需按 control 角色映射。 |
| el-checkbox-group | K | 布局、图标或分组标签；本身无独立业务状态边框，实际状态由子项承接。 |
| el-collapse | D | 结构分隔由库边框角色继承；展开焦点在header，内容四态由子项。 |
| el-collapse-item | D | 同collapse；不要给每层再套独立card。 |
| el-collapse-transition | K | ElCollapseTransition大写入口：分组展开动画，无独立边框或业务状态；边界归SettingsGroup/摘要宿主。 |
| el-color-picker | I | 库 trigger 方框/圆角未被 input/select 规则覆盖；F02，未实测所有状态。 |
| el-container | K | 布局、图标或分组标签；本身无独立业务状态边框，实际状态由子项承接。 |
| el-date-picker | I | 单日期 input 继承；range is-active 聚焦缺失 F01；error继承表单，disabled保形。 |
| el-dialog | P | AppDialog 唯一消费；实测实体border=0/radius=4，与drawer不同；G04待决策。 |
| el-divider | K | 布局、图标或分组标签；本身无独立业务状态边框，实际状态由子项承接。 |
| el-drawer | P | PageDrawer 宿主；可见边界由 PageDrawerSurface 提供，避免双框。 |
| el-dropdown | B/H | 触发按钮归B，菜单浮层归G04；loading/disabled须在实际动作处传递。 |
| el-dropdown-item | N | 候选 hover/focus/disabled走库；选中不是命令按钮pressed。 |
| el-dropdown-menu | P | 所属浮层绘制外框，菜单项不再重复画整框。 |
| el-empty | A | 空态内容，不自造结果外框；所属宿主负责。 |
| el-form | F | 本身无业务外框；字段 validation归 el-form-item，不以表单整体红框替代。 |
| el-form-item | F | is-error 用库高specificity红内框；默认/hover/focus冲突应做组合态验收。 |
| el-header | K | 布局、图标或分组标签；本身无独立业务状态边框，实际状态由子项承接。 |
| el-icon | K | 布局、图标或分组标签；本身无独立业务状态边框，实际状态由子项承接。 |
| el-input | I | 单行全局适配；textarea 变体 F02；表单 error specificity 高于普通 wrapper。 |
| el-input-number | I | 内层 input 已适配；增减按钮角形仍来自库基础半径，需补子部件映射。 |
| el-link | H/L | ElLink大写入口：检查报告定位链接；真实链接hover/focus，不产生业务区域外框。 |
| el-main | K | 布局、图标或分组标签；本身无独立业务状态边框，实际状态由子项承接。 |
| el-menu | N | SideMenu/TopNavigation 专用入口；当前位置和键盘焦点分开。 |
| el-menu-item | N | route selected、hover、focus已由共享导航规则承接。 |
| el-menu-item-group | K | 布局、图标或分组标签；本身无独立业务状态边框，实际状态由子项承接。 |
| el-option | K | 布局、图标或分组标签；本身无独立业务状态边框，实际状态由子项承接。 |
| el-option-group | K | 布局、图标或分组标签；本身无独立业务状态边框，实际状态由子项承接。 |
| el-pagination | N | 当前页、禁用前后页属于分页子项；整体外框归结果宿主。 |
| el-popover | P | 浮层边框继承主题，圆角仍由库默认；与tooltip/菜单需明确角色 G04。 |
| el-progress | C/A | 进度图形/状态色，不按普通卡片或控件圆角迁移。 |
| el-radio | T | 圆形单选不套矩形圆角；暗色状态有适配。 |
| el-radio-button | T | 方形组边界仍取库基础半径；与 PageSegmented 是不同实现入口，F02。 |
| el-radio-group | K | 布局、图标或分组标签；本身无独立业务状态边框，实际状态由子项承接。 |
| el-result | A | 错误/无权限内容；重试按钮归B，外框归宿主。 |
| el-scrollbar | K | ElScrollbar大写入口：AppScrollArea统一管理；轨道/拇指是滚动图形，圆角不按普通卡片处理。 |
| el-segmented | N | 业务中仍有原生消费者；与 PageSegmented 的边界/圆角/disabled 入口分散，F02。 |
| el-select | I | 全局 default/hover/is-focused；候选 selected/disabled 由库；loading仅替换内容。 |
| el-skeleton | A | 首次加载内容；边界不由骨架决定。 |
| el-slider | T | 轨道/圆形 thumb 保留图形角色；focus/disabled 单独验收，不套卡片外框。 |
| el-sub-menu | N | 标题及浮层子菜单分别按导航/浮层角色；不能复用按钮选中态。 |
| el-switch | T | 胶囊轨道与圆形 knob 保留；checked/disabled/loading由库处理。 |
| el-tab-pane | K | 自身不新增 hover/focus/selected框；活动内容由tabs及业务子项负责。 |
| el-table | A | AppDataTable 唯一入口；border仅列线；外框已交AppTableCard/工作区。 |
| el-table-column | K | AppTableColumn 唯一入口；列线由表格统一，列内状态归子项。 |
| el-tabs | N | 页签活动下划线/工作区边界不是卡片选择框；已有全局工作区样式。 |
| el-tag | L | 静态/导航/筛选三类行为已在规范区分；领域字典与金融色保留专用helper。 |
| el-time-picker | I | 单值输入继承；时间浮层/范围分支需与日期适配一并核查，未实测。 |
| el-tooltip | H | 薄提示浮层；不能把普通业务焦点框套到 tooltip 容器；角色映射待齐。 |
| el-tree | N/K | ElTree大写入口：AppReorderTree交互树/AppJsonViewer只读树；selected、drop、focus归树/把手，默认不画独立整区框。 |
| ElMessage（服务） | A | 运行时成功/警告/错误软反馈；关闭入口有统一适配，外框配方归G05，不当作字段错误框。 |
| ElMessageBox（服务） | P/B | 运行时确认/提示弹层；关闭与动作已共享，弹层形态需纳入G04；本轮未确认任何破坏性业务操作。 |

`v-loading`另作为遮罩指令核查：不自行拥有业务外框；应保留宿主和已有内容边界，不能用遮罩圆角替代结果区外框。ElNotification在共享样式有兼容规则，但本次源码未发现业务调用，不虚报为真实消费者。
