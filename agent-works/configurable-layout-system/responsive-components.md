# 响应式组件触发清单

范围：`frontend/src/**/*.vue` 全部 166 个文件（含页面私有片段、布局宿主及应用外壳），每个文件一行。页面消费与实测结论见 [页面检查](responsive-pages.md)。响应式规则以 [DESIGN.md](../../DESIGN.md) §8 为准；全站字体角色及例外统一引用该文档 §3、§3.5；应用导航尺寸引用 §3.4，本清单只登记消费与适配行为，不另行定义字阶。

字体实现维护：所有行均消费 `global.css` 的 token/语义类；MarketCompareMetricStrip、行情和数据概览等普通数据强调使用完整 data 角色，交易纪律分区复用 app-section-title；ECharts 消费 chartTheme 的 typography 快照并经 echartsRenderer 统一基础字体，HTML 行情浮层消费共享 stockQuoteSummaryHtml。源码守卫、构建门禁及例外登记入口见 DESIGN §3.5。

尺寸均为缩放后 CSS 像素。`app-viewport` 是应用画布，匿名/命名容器查询看自身容器，ResizeObserver 看被观察元素；不得把浏览器原始视口直接当作触发尺寸。无自身断点不代表无需响应式：该行列出自然布局或委托对象。

已登记的菜单与交互卡片统一消费 [DESIGN.md](../../DESIGN.md)「动效与状态过渡」及 `global.css` 共享交互样式；消费组件不另写点击位移或动画状态锁。

尺寸恢复自动撤销 CSS 降级；折叠和选择等业务态不因尺寸重置。表中“委托”须同时查看被委托组件；不将静态检查写成所有业务状态已实测。新增/删除 Vue 文件、改变查询必须同步此表，`responsive-inventory.spec.ts` 检查文件及查询双向一致。JS 策略、语义行为和状态恢复仍需人工审查与定向测试。

| 文件 | 查询原文（去重） | 行为 / 恢复入口 | 直接消费方 |
|---|---|---|---|
| `frontend/src/App.vue` | `@container app-viewport (max-width: 720px)` | 两种导航模式共用工作页签且切换不重建实例；侧栏模式品牌/说明与底部固定，菜单独立内滚；右侧顶栏面包屑长标题省略。顶栏模式依次展示一级菜单、二级菜单、工作页签；内容区通过 flex 承接剩余高度，布局选项缩略图同步真实结构。窄宽收起交易日辅助文字，保留状态图标与用户/视觉环境入口；画布统一缩放。 | 应用入口 |
| `frontend/src/components/AppActionHint.vue` | 无自身 CSS 查询 | 命令说明与禁用原因共用显式提示契约；外壳维持原按钮几何，禁用且有原因时可键盘阅读，无权入口连同外壳隐藏。 | AppRowActions、BacktestView、QualityView |
| `frontend/src/components/AppAdvancedSearch.vue` | `@container app-viewport (max-width: 720px)` | 条件≥3时分常用/高级；高级折叠保留生效摘要与展开入口；窄宽逐行；错误自动展开，草稿不重置。 | ConfigView、StocksView、OverviewView、QualityView、LimitLadderFilters、AuditLogView、UserManageView、TradeDisciplineHistory |
| `frontend/src/components/AppAsyncRegion.vue` | 无自身 CSS 查询 | 委托 AppStateBlock。 | StockAnalysisPanel、StockBoardMembershipPanel、BacktestView、ConfigView、SectorDetailView、SectorsView、StockDetailView、TrainingView、LayoutPagesView、AuditLogView、DataDictionaryView、MenuResourceView、RoleManageView、RuleMasterList |
| `frontend/src/components/AppControlItem.vue` | 无自身 CSS 查询 | 控件min-width:0/max100%，标签不压缩，父行负责换行。 | BacktestView、AuditLogView、TradeDisciplineHistory |
| `frontend/src/components/AppControlRow.vue` | 无自身 CSS 查询 | flex-wrap、min-width:0、子项max100%；核心控件换行而不隐藏。 | AppAdvancedSearch、AppTabToolbar、BacktestView、BoardView、SectorDetailView、SectorsView、DataDictionaryView、TenantManageView |
| `frontend/src/components/AppDataTable.vue` | 无自身 CSS 查询 | 语义列最低宽不压缩；embedded 默认统一限高，显式 height/max-height 优先，max-height=null 可完整展开；表格内部横向/纵向滚动，分页交给AppPagination；用户列偏好不因尺寸改写。 | AssetSearchDrawer、RankedStockResultTable、BacktestView、ConfigView、SectorDetailView、SectorsView、StocksView、TrainingView、IngestView、OverviewView、QualityView、ScheduleView、LayoutComponentsView、LayoutPagesView、LayoutPresetsView、AuditLogView、DataDictionaryView、MenuResourceView、TenantManageView、UserManageView、TradeCheckinRevisionDrawer、TradeDisciplineHistory |
| `frontend/src/components/AppDatePicker.vue` | 无自身 CSS 查询 | 日期输入消费统一语义宽度与安全浮层位置；max100%，父行换行，不按尺寸清除日期。 | TradeDatePicker、QualityView、AuditLogView、TradeOperationEditor |
| `frontend/src/components/AppDetailDrawer.vue` | 无自身 CSS 查询 | 自然换行；正文单列网格与插槽根节点允许收缩，宽内容由子组件内部滚动；委托 AppStateBlock、PageDrawer。 | ConfigView、ScreenView、QualityView、ScheduleView、LayoutComponentsView、LayoutPresetsView、AuditLogView、TradeCheckinRevisionDrawer |
| `frontend/src/components/AppDetailField.vue` | 无自身 CSS 查询 | 标签/值网格且值min-width:0；长值换行，不依赖隐藏。 | StockDetailView、IngestView、OverviewView、LayoutComponentsView、AuditLogView |
| `frontend/src/components/AppDetailFields.vue` | `@container app-viewport (max-width: 760px)` | 窄宽从多列降为单列，字段值完整保留。 | StockDetailView、IngestView、OverviewView、LayoutComponentsView、AuditLogView |
| `frontend/src/components/AppDetailSection.vue` | 无自身 CSS 查询 | 分区头部换行，正文长内容在详情外壳滚动。 | LayoutComponentsView、AuditLogView |
| `frontend/src/components/AppCloseButton.vue` | 无自身 CSS 查询 | 关闭档位与状态统一消费 DESIGN §4 及 global.css；不浮起，点击和激活键不传播，Escape 保留；宿主管理显隐和业务关闭条件。 | WorkspaceTabs、PageDrawerSurface、CompareQueueRail、AssetProfileSelect、BacktestView、StockDetailView |
| `frontend/src/components/AppDialog.vue` | 无自身 CSS 查询 | 语义宽度，最大100cqw减安全间距；正文内部滚动，标题与关闭保持可达。 | StockGroupBatchActions、StockIntradayDialog、BacktestView、StocksView、TradeDisciplineView、IngestView、QualityView、ScheduleView、DataDictionaryView、MenuResourceView、RoleManageView、TenantManageView、UserManageView |
| `frontend/src/components/AppFilterSelect.vue` | 无自身 CSS 查询 | 统一语义宽度与max100%；标签摘要按数量折叠，完整选项在下拉；不按尺寸修改筛选。 | MarketBenchmarkSelect、BacktestView、BoardView、ConfigView、LimitLadderView、SectorsView、StocksView、TrainingView、OverviewView、QualityView、LimitLadderFilters、AuditLogView、TradeCheckinRevisionDrawer、TradeDisciplineHistory |
| `frontend/src/components/AppFilterSwitch.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | LimitLadderFilters |
| `frontend/src/components/AppIconButton.vue` | 无自身 CSS 查询 | 保持真实 button 根节点；名称不生成提示，显式 tooltip 复用 AppHoverInfo 虚拟锚点。 | App、AppCloseButton、AppSortControl、ComparePinButton、ConfigView、IndicatorParamSchemaEditor、MarketMasterDetailWorkspace、MenuResourceView、PageSettingsDrawer、PageSettingsTrigger、SectorDetailView、SectorsView、SettingsGroup、StockChartWorkspace、StockDetailView、StockGroupFavoriteButton、StocksView、TradeOperationEditor、TradeRuleEditor、ViolationReasonCombobox |
| `frontend/src/components/AppOverflowTooltipHost.vue` | 无自身 CSS 查询 | 只承接真实截断的原文，不读取或修改 title；完整内容不显示，提示尺寸服从统一浮层安全边界；与显式说明共享窗口失焦/后台清理，恢复窗口焦点不自动重弹，页面不复制监听。 | App |
| `frontend/src/components/AppPagination.vue` | 无自身 CSS 查询 | 自身宽≥640完整、420–639摘要、<420导航；实测溢出继续降档；始终保留翻页并自动恢复。 | AppDataTable、AssetSearchDrawer、OverviewView |
| `frontend/src/components/AppRowActions.vue` | 无自身 CSS 查询 | ResizeObserver 实测父容器与按钮宽，默认最多3个常显；放不下进入具名“更多”菜单，操作不丢失。 | ComponentAutoSettings、AssetSearchDrawer、ConfigView、ScreenView、TrainingView、IngestView、QualityView、ScheduleView、LayoutComponentsView、LayoutPresetsView、AuditLogView、DataDictionaryView、MenuResourceView、TenantManageView、UserManageView |
| `frontend/src/components/AppSearchInput.vue` | 无自身 CSS 查询 | 语义控件宽度compact/short/medium/long/wide=96/140/180/220/300，由global.css统一max100%、min0；父行自然换行。 | BoardView、ConfigView、SectorDetailView、SectorsView、StocksView、OverviewView、QualityView、LimitLadderFilters、AuditLogView、DataDictionaryView、TenantManageView、UserManageView、RuleMasterList、TradeDisciplineHistory |
| `frontend/src/components/AppSortControl.vue` | 无自身 CSS 查询 | 语义short宽140，排序方向动作不收缩；父级控件行换行，选择不重置。 | LimitLadderFilters |
| `frontend/src/components/AppSplitWorkspace.vue` | `@media (prefers-reduced-motion: reduce)` | 自身宽≤720或compact转单区+分析抽屉；双侧最小宽360/240，比例默认45%、范围30–70%；高度不足外层滚动。 | MarketMasterDetailWorkspace、SectorDetailView、StockDetailView |
| `frontend/src/components/AppStatusDot.vue` | 无自身 CSS 查询 | 辅助圆点不收缩；可访问名称和悬浮/键盘说明承接含义；文本为 inline，圆形入口为 top-right，角标依附宿主定位容器且不占横排空间。 | App、RelatedBoardHistoryHint、LadderHotspots |
| `frontend/src/components/AppStateBlock.vue` | 无自身 CSS 查询 | 默认/compact/tiny最低高度180/120/72；动作换行；密度由调用方选择，无自动隐藏恢复入口。 | AppAsyncRegion、AppDataTable、AppDetailDrawer、SectorCompareChart、StockAnalysisPanel、StockCompareChart、AssetProfileSelect、AssetSearchDrawer、StockChartWorkspace、StockIntradayDialog、TradeDisciplineQuickCard、LayoutComponentPreview、BacktestView、BoardView、ConfigView、LimitLadderView、ScreenView、SectorDetailView、SectorsView、StockDetailView、StocksView、TradeDisciplineView、TrainingView、IngestView、OverviewView、QualityView、ScheduleView、LayoutComponentsView、LayoutPagesView、LayoutPresetsView、LimitLadder、AuditLogView、DataDictionaryView、MenuResourceView、RoleManageView、TenantManageView、UserManageView、RuleMasterList、TradeCheckinForm、TradeDisciplineHistory、TradeOperationEditor、TradeRuleEditor |
| `frontend/src/components/AppStatusNotice.vue` | `@container app-viewport (max-width: 720px)`<br>`@media (prefers-reduced-motion: reduce)` | 窄宽正文/操作换行，恢复操作保留；减少动画偏好停用动画。 | PageSettingsDrawer、AssetProfileSelect、StockIntradayDialog、BacktestView、ConfigView、LimitLadderView、ScreenView、StocksView、OverviewView、LimitLadder、UserManageView、TradeRuleEditor |
| `frontend/src/components/AppSummaryDisclosureCard.vue` | `@media (prefers-reduced-motion: reduce)`<br>`@container app-viewport (max-width: 760px)` | 默认卡片窄宽摘要与工具上下排列；紧凑模式状态前缀与标题/说明自然换行，无明细时静态显示；用户展开独立于尺寸，保留摘要和显式开关。 | RuleSummaryCard、TradeOperationEditor、CheckupReportContent |
| `frontend/src/components/AppTabToolbar.vue` | 无自身 CSS 查询 | 工具条换行，结果说明宽度不超容器，业务动作保留。 | IngestView、OverviewView |
| `frontend/src/components/AppTableColumn.vue` | 无自身 CSS 查询 | 长文省略，完整内容由提示/详情承接；宽度不超过父容器。 | AssetSearchDrawer、RankedStockResultTable、BacktestView、BoardView、ConfigView、ScreenView、SectorDetailView、SectorsView、StocksView、TrainingView、IngestView、OverviewView、QualityView、ScheduleView、LayoutComponentsView、LayoutPagesView、LayoutPresetsView、AuditLogView、DataDictionaryView、MenuResourceView、TenantManageView、UserManageView、TradeCheckinRevisionDrawer、TradeDisciplineHistory |
| `frontend/src/components/AppWorkspacePane.vue` | 无自身 CSS 查询 | 头部不收缩、标题可省略；正文grow并由消费内容拥有滚动。 | MarketMasterDetailWorkspace、SectorDetailView、StockDetailView |
| `frontend/src/components/AssetProfileLabel.vue` | 无自身 CSS 查询 | 名称省略、版本保持；完整身份由提示/资产详情承接。 | AssetProfileSelect、AssetSearchDrawer、BacktestView |
| `frontend/src/components/AssetVisibilityActions.vue` | 无自身 CSS 查询 | 权限允许的动作自然换行，不按视口取消操作。 | BacktestView、ConfigView、ScreenView |
| `frontend/src/components/AssetVisibilityTag.vue` | 无自身 CSS 查询 | 标签max112、名称省略82；提示承接完整名称。 | AssetProfileLabel、AssetVisibilityActions、AssetSearchDrawer、BacktestView |
| `frontend/src/components/BrandMark.vue` | 无自身 CSS 查询 | 宽min(184,100%)保持比例；统一品牌身份不按页面变形。 | App、LoginView |
| `frontend/src/components/BuiltinOptionRow.vue` | 无自身 CSS 查询 | 名称省略，内置标识/操作固定，完整名称提示。 | TradeRuleEditor、ViolationReasonCombobox |
| `frontend/src/components/ChartOperationGroup.vue` | 无自身 CSS 查询 | 委托 SettingsGroup。 | StockChartWorkspace |
| `frontend/src/components/ComparePinButton.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | StockAnalysisNameCell、SectorsView |
| `frontend/src/components/CompareQueueRail.vue` | 无自身 CSS 查询 | 对比队列始终单行内部横向滚动，选中对象与移除动作不隐藏。 | StockAnalysisPanel、SectorsView |
| `frontend/src/components/ComponentAutoSettings.vue` | 无自身 CSS 查询 | 委托 AppRowActions、SettingsGroup、PageSegmented、PageSettingItem、PageToggleRow、StockChartSettingSection、StockAnalysisDefaultFields、SectorAnalysisDefaultFields、KlineSettingSection、MasterDetailRatioProfileSettings、SourceTag。 | PageSettingsDrawer、LayoutPagesView |
| `frontend/src/components/EquityChart.vue` | 无自身 CSS 查询 | 默认高420或fill满区，自身resize；图表容器min0。 | BacktestView、TrainingView |
| `frontend/src/components/GrowthChart.vue` | 无自身 CSS 查询 | 固定200高微图，自身resize；没有信息隐藏。 | TrainingView |
| `frontend/src/components/HelpHint.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | PageSettingItem、PageToggleRow、SettingsGroup、ConfigGroupForm、BacktestView、ConfigView、OverviewView、LayoutComponentsView |
| `frontend/src/components/HelpTip.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | BacktestView、BoardView、ConfigView、LimitLadderView、ScreenView、SectorsView、StocksView、TradeDisciplineView、TrainingView、IngestView、OverviewView、QualityView、ScheduleView、LayoutComponentsView、AuditLogView、DataDictionaryView、MenuResourceView、RoleManageView、TenantManageView、UserManageView、TradeRuleEditor |
| `frontend/src/components/HelpTipItem.vue` | 无自身 CSS 查询 | 标记+正文min0网格，长说明换行。 | BacktestView、BoardView、ConfigView、LimitLadderView、ScreenView、SectorsView、StocksView、TradeDisciplineView、TrainingView、IngestView、OverviewView、QualityView、ScheduleView、LayoutComponentsView、AuditLogView、DataDictionaryView、MenuResourceView、RoleManageView、TenantManageView、UserManageView、TradeRuleEditor |
| `frontend/src/components/IconPicker.vue` | 无自身 CSS 查询 | 弹层最大100cqw减32，4列网格min0，max-height320内部滚动。 | MenuResourceView |
| `frontend/src/components/KlineRangeSelect.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | StockAnalysisPanel、SectorDetailView、SectorsView、StockDetailView、TrainingView |
| `frontend/src/components/KlineSettingSection.vue` | 无自身 CSS 查询 | 委托 PageSettingItem；快捷范围说明通过 hint 帮助入口恢复，不占用标签宽度。 | ComponentAutoSettings |
| `frontend/src/components/MarketAnalysisHeader.vue` | `@container (max-width: 820px)`<br>`@container app-viewport (max-height: 700px)` | 自身容器≤820身份与控制区上下排列，隐藏辅助描述/重复标签；低高压缩头部；身份和全部操作保留。 | StockAnalysisPanel、SectorsView |
| `frontend/src/components/MarketBenchmarkSelect.vue` | 无自身 CSS 查询 | 委托 AppFilterSelect。 | SectorAnalysisDefaultFields、StockAnalysisDefaultFields、StockAnalysisPanel、BacktestView、SectorsView |
| `frontend/src/components/MarketBoardTag.vue` | 无自身 CSS 查询 | 板块名称省略，涨跌/相关性保留；完整信息由提示承接。 | StockBoardMembershipPanel |
| `frontend/src/components/MarketCompareMetricStrip.vue` | `@container app-viewport (max-width: 1180px)`<br>`@container app-viewport (max-height: 700px)`<br>`@media (hover: hover) and (pointer: fine)` | 窄宽3列；低高紧凑单行按内容确定列宽并内部横向滚动，仅隐藏辅助数值，完整值由紧凑态可见的独立HelpHint恢复，按钮保留完整无障碍名称；常规态不重复提示；保留全部指标切换。 连续指标共用内容微移，选中仅显示铺满单元格宽度的底线和共享6%浅背景，悬停不再加深；不套卡片外框、左侧线或外投影，不给数据更新添加动画。 | StockAnalysisPanel、SectorsView |
| `frontend/src/components/MarketDetailHero.vue` | `@container app-viewport (max-width: 980px)` | 窄宽主身份与侧摘要上下排列；侧摘要横向滚动，核心身份保留。 | SectorDetailView、StockDetailView |
| `frontend/src/components/MarketMasterDetailWorkspace.vue` | `@container app-viewport (max-width: 1180px)` | 消费AppSplitWorkspace的≤720紧凑抽屉策略；标准最低高480、紧凑400，剩余高度不足由外层滚动；窄宽隐藏列表操作辅助文字，操作入口保留。 | RankedStockWorkbench、BoardView、LimitLadderView、SectorsView、StocksView |
| `frontend/src/components/MasterDetailRatioProfileSettings.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | ComponentAutoSettings |
| `frontend/src/components/MenuIcon.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | SideMenuItem、TopNavigation、MenuResourceView |
| `frontend/src/components/PageDrawer.vue` | 无自身 CSS 查询 | 语义宽度且最大100%；工作台窄屏full；正文滚动，头部/关闭/footer保持可达。 | App、AppDetailDrawer、AppSplitWorkspace、PageSettingsDrawer、AssetSearchDrawer、StockChartOperationsDrawer、IngestView |
| `frontend/src/components/PageDrawerSurface.vue` | 无自身 CSS 查询 | 头部与footer不收缩；正文grow或scroll由语义参数选择，标题可省略。 | PageDrawer |
| `frontend/src/components/PageSegmented.vue` | 无自身 CSS 查询 | 长文省略，完整内容由提示/详情承接；宽度不超过父容器。 | App、ComponentAutoSettings、SectorAnalysisDefaultFields、StockAnalysisDefaultFields、StockAnalysisPanel、StockChartSettingSection、AssetSearchDrawer、BoardTaskScopeFields、ResultMaintenanceTaskFields、StockIngestScopeFields、StockChartWorkspace、LayoutPagePreview、LayoutSettingsSection、BacktestView、BoardView、ConfigView、LimitLadderView、ScreenView、SectorsView、StockDetailView、StocksView、TradeDisciplineView、TrainingView、IngestView、OverviewView、QualityView、ScheduleView、LimitLadderFilters、TenantManageView、UserManageView |
| `frontend/src/components/PageSettingItem.vue` | 无自身 CSS 查询 | 字段堆叠或语义inline，控件满宽且min0；提示收进HelpHint。 | ComponentAutoSettings、KlineSettingSection、SectorAnalysisDefaultFields、StockAnalysisDefaultFields、StockChartSettingSection、LayoutSettingsSection、BacktestView、BoardView、ConfigView、LimitLadderView、ScreenView、SectorsView、StockDetailView、StocksView、TrainingView、IngestView、OverviewView、QualityView、ScheduleView、AuditLogView、UserManageView |
| `frontend/src/components/PageSettingSection.vue` | 无自身 CSS 查询 | 委托 SettingsGroup。 | BacktestView、BoardView、ConfigView、LimitLadderView、ScreenView、SectorsView、StockDetailView、StocksView、TrainingView、IngestView、OverviewView、QualityView、ScheduleView、AuditLogView、TenantManageView、UserManageView |
| `frontend/src/components/PageSettingsApplyButton.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | ComponentAutoSettings、MasterDetailRatioProfileSettings、StockChartSettingSection |
| `frontend/src/components/PageSettingsDrawer.vue` | 无自身 CSS 查询 | 委托 SettingsGroup、ComponentAutoSettings、PageDrawer、LayoutSettingsSection、AppStatusNotice。 | BacktestView、BoardView、ConfigView、LimitLadderView、ScreenView、SectorDetailView、SectorsView、StockDetailView、StocksView、TradeDisciplineView、TrainingView、IngestView、OverviewView、QualityView、ScheduleView、AuditLogView、DataDictionaryView、MenuResourceView、RoleManageView、TenantManageView、UserManageView |
| `frontend/src/components/PageSettingsTrigger.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | BacktestView、BoardView、ConfigView、LimitLadderView、ScreenView、SectorDetailView、SectorsView、StockDetailView、StocksView、TradeDisciplineView、TrainingView、IngestView、OverviewView、QualityView、ScheduleView、AuditLogView、DataDictionaryView、MenuResourceView、RoleManageView、TenantManageView、UserManageView |
| `frontend/src/components/PageToggleRow.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | ComponentAutoSettings、SectorAnalysisDefaultFields、StockAnalysisDefaultFields、LayoutSettingsSection、BacktestView、LimitLadderView、ScreenView、QualityView |
| `frontend/src/components/RelatedBoardCell.vue` | 无自身 CSS 查询 | 关联名称可省略，历史标记不收缩；来源日期与原基准由浮层承接，详情入口不隐藏。 | RankedStockResultTable、StocksView |
| `frontend/src/components/RelatedBoardEmptyValue.vue` | 无自身 CSS 查询 | 长文省略，完整内容由提示/详情承接；宽度不超过父容器。 | RelatedBoardCell、LimitLadderCard |
| `frontend/src/components/RelatedBoardHistoryHint.vue` | 无自身 CSS 查询 | 黄色状态点不收缩，含义通过可访问名称和说明承接；来源日期通过悬浮与键盘聚焦提示，表格已有整体说明时不重复弹出。 | RelatedBoardCell、LimitLadderCard |
| `frontend/src/components/ScoreGradeTag.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | RankedStockResultTable、BacktestView |
| `frontend/src/components/SectorAnalysisDefaultFields.vue` | 无自身 CSS 查询 | 委托 MarketBenchmarkSelect、PageSettingItem、PageSegmented、PageToggleRow。 | ComponentAutoSettings |
| `frontend/src/components/SectorCompareChart.vue` | 无自身 CSS 查询 | 委托 AppStateBlock。 | SectorsView |
| `frontend/src/components/SettingsGroup.vue` | 无自身 CSS 查询 | 手动递归折叠，父级收起只隐藏子树，不重置下级展开状态；操作右侧下级按钮时展开当前组，并只切换直接子组。 | App、ChartOperationGroup、ComponentAutoSettings、PageSettingSection、PageSettingsDrawer、LayoutSettingsSection |
| `frontend/src/components/SideMenu.vue` | 无自身 CSS 查询 | 一级为常驻分区标题，与二级文字左边界一致；当前分区标题和父菜单随路由同步使用中性高对比文字高亮，当前标题右侧圆点使用导航强调色且不显示下划线、图标使用导航激活色，选中叶子保留主色，详情继承所属分区；主入口44px/三级起36px，尺寸、图标和圆角消费共享导航token，高度不足由App侧栏内滚承接。页面路径或授权树变化收起非当前下级组、展开当前链并最小滚动露出叶子，同页仍可手动浏览多个分组；同页查询变化不干预收展或滚动。加载/空授权/失败分别呈现。 可点击菜单接入共享内容微移和纯投影层，普通悬停/焦点共用中性悬停底，当前叶子通过角色变量保留浅主色背景与定位线；常驻标题保持静态，点击区及层级缩进不移动。 | App |
| `frontend/src/components/SideMenuItem.vue` | 无自身 CSS 查询 | 分区内部展示深度从0开始，三级起每层缩进12px；图标统一18px占位、下级图形16px，末尾箭头固定，长名称省略并交给全局溢出提示；收展及选中不重置页面。 | SideMenu |
| `frontend/src/components/SourceTag.vue` | 无自身 CSS 查询 | 来源浮层min180/max280、字段网格44+0；受统一浮层边界约束。 | ComponentAutoSettings、LayoutSettingsSection |
| `frontend/src/components/StockAnalysisDefaultFields.vue` | 无自身 CSS 查询 | 委托 MarketBenchmarkSelect、PageSettingItem、PageSegmented、PageToggleRow。 | ComponentAutoSettings |
| `frontend/src/components/StockAnalysisNameCell.vue` | 无自身 CSS 查询 | 委托 ComparePinButton、StockStatusTag。 | RankedStockResultTable、StocksView |
| `frontend/src/components/StockAnalysisPanel.vue` | `@container app-viewport (max-height: 700px)` | 低高压缩footer；分析头部、指标、图表分别委托共享组件，不整区隐藏切换入口。 | RankedStockWorkbench、BoardView、LimitLadderView、StocksView |
| `frontend/src/components/StockBoardMembershipPanel.vue` | 无自身 CSS 查询 | 自然换行；委托 AppAsyncRegion、MarketBoardTag。 | StockDetailView |
| `frontend/src/components/StockChartSettingSection.vue` | 无自身 CSS 查询 | 比例网格min52+116+14；长设置由共享抽屉滚动承接。 | ComponentAutoSettings |
| `frontend/src/components/StockCompareChart.vue` | 无自身 CSS 查询 | 委托 AppStateBlock。 | StockAnalysisPanel |
| `frontend/src/components/StockGroupBatchActions.vue` | 无自身 CSS 查询 | 批量动作自然换行；分组条max-height64内部滚动。 | BoardView、StocksView |
| `frontend/src/components/StockGroupFavoriteButton.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | BoardView、StockDetailView、StocksView |
| `frontend/src/components/StockStatusTag.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | StockAnalysisNameCell、RankedStockResultTable、BacktestView、SectorDetailView、StockDetailView、StocksView、LimitLadderCard、StockOptionSelect、TradeCheckinRevisionDrawer |
| `frontend/src/components/SubScoreBars.vue` | 无自身 CSS 查询 | 语义微图min132，消费表格内部横滚承担最低宽。 | 按路由/动态渲染或内部消费；无直接Vue import匹配 |
| `frontend/src/components/SubScoreChips.vue` | 无自身 CSS 查询 | 评分项自然换行，单项长文本省略并保留提示。 | RankedStockResultTable |
| `frontend/src/components/SystemBuiltinTag.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | AssetVisibilityTag、ConfigView、LayoutPresetsView、MenuResourceView、RoleManageView、TenantManageView |
| `frontend/src/components/TopNavigation.vue` | `@container app-viewport (max-width: 960px)`<br>`@media (prefers-reduced-motion: reduce)` | 窄宽压缩导航间距/隐藏辅助上下文；一级菜单不收缩，空间不足由导航条自身横向滚动，避免图文相互重叠；一级、二级与下拉入口的字体及尺寸按 DESIGN §3.4 消费共享导航 token；二级栏共用中性底色、不混入预设强调色；二级入口与工作标签复用`.app-nav-context-entry`的尺寸、圆角及选中边框/底线，下拉消费共享导航字阶、几何和叶子背景，导航动作保留。 两级及下拉入口共用悬停视觉层与180ms颜色过渡，下拉不回落组件库默认蓝底，指针移出后不保留焦点蓝色；命中区和下划线保持稳定。 一级保留图标框与整栏底部下划线，仅收紧悬停和键盘焦点面，不套二级选中框。 | App |
| `frontend/src/components/TradeDatePicker.vue` | 无自身 CSS 查询 | 委托 AppDatePicker。 | StockGroupBatchActions、BoardTaskScopeFields、ResultMaintenanceTaskFields、StockIngestScopeFields、BacktestView、BoardView、ConfigView、ScreenView、SectorDetailView、SectorsView、StocksView、TrainingView、LimitLadderFilters、TradeCheckinForm、TradeDisciplineHistory |
| `frontend/src/components/WorkspaceRouteView.vue` | 无自身 CSS 查询 | 页面按页签独立缓存；关闭最后一页后释放页面实例并显示居中紧凑空态，从导航菜单访问同一路由也可重开；菜单元数据刷新不得自行恢复已关闭页面。 | App |
| `frontend/src/components/WorkspaceTabs.vue` | `@container app-viewport (max-width: 720px)`、`@media (hover: none), (pointer: coarse)` | 默认收起为28px摘要行，展开为45px页签栏；折叠状态走账号级用户偏好自动记忆，折叠使用 v-show 保留页签；零标签时隐藏整栏。栏首固定折叠入口、工作区标题、实时数量徽标和清空页签按钮，折叠时仍可清空；未保存确认全部通过才统一关闭，取消保留全部，等待期间与单页关闭互斥，清空后整栏隐藏并聚焦空工作区；展开显示分隔符；标签由连续中性底托承接，图标复用授权菜单和 MenuIcon，无图标时回退 Document；保持共享32px高度与圆角，4px间距、12px水平内距、180px最大宽度。当前项显示中性选中面、强边框、主色上沿与图标；关闭入口预留空间，普通态弱显，当前、悬停或粗指针时清晰显示。窄宽由轨道内滚承接，路由切换和缩窄按布局坐标最小滚动露出当前项，销毁释放尺寸监听；关闭确认防重复，成功移除焦点标签后恢复当前项焦点。 | App |
| `frontend/src/components/asset-search/AssetProfileSelect.vue` | 无自身 CSS 查询 | 选择器0+auto网格，搜索交给AssetSearchDrawer。 | BacktestView、BoardView、ConfigView、ScreenView、StockDetailView |
| `frontend/src/components/asset-search/AssetSearchDrawer.vue` | 无自身 CSS 查询 | 共享抽屉满高、搜索换行、列表内部滚动、统一分页，查询值保留。 | AssetProfileSelect、BacktestView |
| `frontend/src/components/config/ConfigGroupForm.vue` | `@container app-viewport (max-width: 720px)` | 窄宽配置网格单列，控件占行宽；不清除输入。 | ConfigView |
| `frontend/src/components/config/ConfigPanelSection.vue` | `@container app-viewport (max-width: 720px)` | 窄宽缩短装饰线/限制说明宽度；分组手动折叠，标题入口保留。 | ConfigGroupForm |
| `frontend/src/components/data/BoardTaskScopeFields.vue` | 无自身 CSS 查询 | 委托 PageSegmented、TradeDatePicker、CurrentDayFallbackField。 | IngestView、ScheduleView |
| `frontend/src/components/data/CurrentDayFallbackField.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | BoardTaskScopeFields、StockIngestScopeFields |
| `frontend/src/components/data/ResultMaintenanceTaskFields.vue` | 无自身 CSS 查询 | 委托 TradeDatePicker、PageSegmented、StockCodeMultiSelect。 | IngestView、ScheduleView |
| `frontend/src/components/data/StockCodeMultiSelect.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | ResultMaintenanceTaskFields、StockIngestScopeFields、OverviewView |
| `frontend/src/components/data/StockIngestScopeFields.vue` | 无自身 CSS 查询 | 委托 PageSegmented、TradeDatePicker、StockCodeMultiSelect、CurrentDayFallbackField。 | IngestView、ScheduleView |
| `frontend/src/components/indicator/IndicatorParamFields.vue` | 无自身 CSS 查询 | 参数输入语义宽76、单项不换行；父级表单/编辑器负责换行或滚动。 | ConfigView、ScreenView |
| `frontend/src/components/indicator/IndicatorParamSchemaEditor.vue` | `@container app-viewport (max-width: 760px)` | 窄宽参数编辑网格改为2列，字段仍可访问。 | ConfigView |
| `frontend/src/components/indicator/IndicatorSelect.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | ConfigView、ScreenView |
| `frontend/src/components/ranked-stock/RankedStockResultTable.vue` | 无自身 CSS 查询 | 委托 AppDataTable、AppTableColumn、RelatedBoardCell、ScoreGradeTag、StockAnalysisNameCell、StockStatusTag、SubScoreChips。 | RankedStockWorkbench、BacktestView、BoardView |
| `frontend/src/components/ranked-stock/RankedStockWorkbench.vue` | 无自身 CSS 查询 | 委托 MarketMasterDetailWorkspace、StockAnalysisPanel、RankedStockResultTable。 | ConfigView、ScreenView |
| `frontend/src/components/stock-chart/StockChartLegend.vue` | `@container app-viewport (max-width: 1180px)` | 窄宽压缩图例间距；额外图例由StockChartWorkspace的指标栏承接。 | StockChartPanelHeader、StockChartWorkspace、StockIntradayChart |
| `frontend/src/components/stock-chart/StockChartOperationsDrawer.vue` | 无自身 CSS 查询 | 委托 PageDrawer。 | StockChartWorkspace |
| `frontend/src/components/stock-chart/StockChartPanelDivider.vue` | `@media (prefers-reduced-motion: reduce)` | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | StockChartWorkspace、StockIntradayChart |
| `frontend/src/components/stock-chart/StockChartPanelHeader.vue` | `@container app-viewport (max-width: 1180px)` | 窄宽压缩头部间距；标题/操作保持。 | StockChartWorkspace、StockIntradayChart |
| `frontend/src/components/stock-chart/StockChartRegion.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | TrainingView |
| `frontend/src/components/stock-chart/StockChartWorkspace.vue` | `@container app-viewport (max-width: 1180px)`<br>`@container app-viewport (max-width: 400px)` | 窄宽面板图例第4项起移入指标栏；极窄≤400指标栏也减少常显项，完整配置在图表操作抽屉。ResizeObserver按面板最小高度分配，滑块canvas高度<84隐藏；不重新取行情。 | StockAnalysisPanel、BacktestView、SectorDetailView、SectorsView、StockDetailView、TrainingView |
| `frontend/src/components/stock-chart/StockIntradayChart.vue` | `@container app-viewport (max-width: 960px)` | 窄宽图表58cqh、min340；图表自身resize，溢出由对话框正文滚动承接。 | StockIntradayDialog |
| `frontend/src/components/stock-chart/StockIntradayDialog.vue` | `@container app-viewport (max-width: 960px)` | 窄宽头部上下排列，图表置于AppDialog工作区。 | StockAnalysisPanel、StockDetailView |
| `frontend/src/components/stock-chart/StockQuoteSummary.vue` | `@container app-viewport (max-width: 720px)` | 窄宽补充信息换行，报价关键值保留；K 线联动摘要使用最新与可视窗口字符容量，空间不足由摘要内部横向滚动承接；可选字段说明复用 HelpHint 图标，字段名不加后缀；标签区容纳图标且数值列保持固定，支持悬浮与键盘聚焦。 | StockIntradayDialog、StockDetailView |
| `frontend/src/components/strategy/StrategyItemEnabledSwitch.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | ConfigView、ScreenView |
| `frontend/src/components/trade-discipline/RuleSummaryCard.vue` | 无自身 CSS 查询 | 委托 AppSummaryDisclosureCard。 | TradeRuleEditor |
| `frontend/src/components/trade-discipline/TradeDirectionGroupGrid.vue` | 无自身 CSS 查询 | 所有宽度按买入、卖出顺序单列，规则与操作逐条独占一行。 | TradeOperationEditor、TradeRuleEditor |
| `frontend/src/components/trade-discipline/TradeDisciplineQuickCard.vue` | `@container app-viewport (max-width: 520px)` | 窄容器操作换行，规则与动作保留。 | App |
| `frontend/src/components/trade-discipline/TradeDisciplineSectionPanel.vue` | `@container app-viewport (max-width: 760px)` | 窄宽头部上下排列，不隐藏操作。 | TradeCheckinForm、TradeOperationEditor、TradeRuleEditor |
| `frontend/src/layout/components/LayoutComponentPreview.vue` | 无自身 CSS 查询 | 固定256高规范样板；状态复用AppStateBlock，消费页可用性需独立验证。 | LayoutComponentsView |
| `frontend/src/layout/components/LayoutHost.vue` | 无自身 CSS 查询 | 按registry原型装配grow/mixed/columns/scroll；操作/footer不收缩，主区滚动，overlay始终挂载页面边界。 | BacktestView、BoardView、ConfigView、LimitLadderView、ScreenView、SectorDetailView、SectorsView、StockDetailView、StocksView、TradeDisciplineView、TrainingView、IngestView、OverviewView、QualityView、ScheduleView、LayoutComponentsView、LayoutPagesView、LayoutPresetsView、AuditLogView、DataDictionaryView、MenuResourceView、RoleManageView、TenantManageView、UserManageView |
| `frontend/src/layout/components/LayoutPagePreview.vue` | `@container app-viewport (max-width: 980px)` | 窄宽预览网格单列，两类原型均保留内容。 | LayoutPagesView |
| `frontend/src/layout/components/LayoutSettingsSection.vue` | 无自身 CSS 查询 | 委托 PageSegmented、PageSettingItem、PageToggleRow、SettingsGroup、SourceTag。 | PageSettingsDrawer |
| `frontend/src/layout/components/VAdaptiveGrow.vue` | 无自身 CSS 查询 | 依据slot minH及实际可用高度分配成长区；不足保持最低尺寸，宿主外层滚动。 | LayoutHost |
| `frontend/src/layout/components/VColumns.vue` | 无自身 CSS 查询 | ResizeObserver自身宽度匹配layout.responsive.breakpoints；基础断点0、列最小宽满足才重排，否则单列/滚动。 | LayoutHost |
| `frontend/src/layout/components/VMixedGrow.vue` | 无自身 CSS 查询 | 固定区idealH收敛至minH，主区grow；仍不足时主区域滚动，不裁掉固定操作。 | LayoutHost |
| `frontend/src/views/BacktestView.vue` | `@container app-viewport (max-width: 720px)`<br>`@container app-viewport (max-width: 480px)` | 窄宽头部/历史区上下排列、选择器满宽；更窄压缩表单间距；参数与运行/历史入口保留。 | 路由 |
| `frontend/src/views/BoardView.vue` | 无自身 CSS 查询 | 头部/筛选自然换行；排名/分析/分页委托共享工作台。 | 路由 |
| `frontend/src/views/ConfigView.vue` | `@container app-viewport (max-width: 760px)`<br>`@container app-viewport (max-width: 980px)` | 窄宽技术参数表单单列；系统工具条/网格单列；四个路由共用外壳，配置分组可折叠。 | 路由 |
| `frontend/src/views/LimitLadderView.vue` | 无自身 CSS 查询 | useLayoutViewport宽≤768/高≤700驱动热点数量策略；分析区显隐进入同一策略，未更改筛选口径。 | 路由 |
| `frontend/src/views/LoginView.vue` | `@container app-viewport (max-width: 980px)`<br>`@container app-viewport (max-width: 520px)`<br>`@container app-viewport (max-height: 720px) and (min-width: 981px)`<br>`@media (prefers-reduced-motion: reduce)`<br>`@media (forced-colors: active)`<br>`@container app-viewport (max-width: 360px)`<br>`@container app-viewport (max-height: 620px) and (max-width: 980px)`<br>`@media print`<br>`@media (hover: none)`<br>`@media (prefers-contrast: more)` | 窄宽隐藏品牌补充说明/行情装饰，登录卡片单列；低高顶对齐，极窄缩小验证码占位；无障碍媒体偏好另有规则。 | 路由 |
| `frontend/src/views/ScreenView.vue` | 无自身 CSS 查询 | 条件区限制高度并内部滚动，结果委托RankedStockWorkbench；运行条件始终可达。 | 路由 |
| `frontend/src/views/SectorDetailView.vue` | `@container app-viewport (max-width: 1120px)` | 窄宽摘要4列，每项min132；详情主体滚动，行情/成员表格委托共享组件。 | 路由 |
| `frontend/src/views/SectorsView.vue` | `@container app-viewport (max-width: 1180px)`<br>`@container app-viewport (max-height: 700px)` | 窄宽隐藏辅助副标题；低高压缩footer；列表/分析/指标分别消费共享工作台，选择保留。 | 路由 |
| `frontend/src/views/StockDetailView.vue` | `@container app-viewport (max-width: 980px)` | 窄宽分组选择器左对齐且最大100%/320；图表/归属表格委托共享组件。 | 路由 |
| `frontend/src/views/StocksView.vue` | 无自身 CSS 查询 | 头部/筛选换行，分组长名省略；主从/表格/分页委托共享组件。 | 路由 |
| `frontend/src/views/TradeDisciplineView.vue` | `@container app-viewport (max-width: 1100px)`<br>`@container app-viewport (max-width: 900px)` | 窄宽主从转单列并外层滚动；更窄头部上下排列，规则/履约入口保留。 | 路由 |
| `frontend/src/views/TrainingView.vue` | `@container app-viewport (max-width: 1100px)` | 窄宽训练网格单列；图表尺寸交给共享图表resize，输入不重置。 | 路由 |
| `frontend/src/views/data/IngestView.vue` | 无自身 CSS 查询 | auto-fill min220采集卡片；tab/table内部滚动，范围字段委托共享组件。 | 路由 |
| `frontend/src/views/data/OverviewView.vue` | `@container app-viewport (max-height: 700px)`<br>`@container app-viewport (max-width: 1100px)` | 低高压缩统计/层级间距，隐藏补充脚注；窄宽主概览/覆盖率/鲜活度单列，主体滚动。 | 路由 |
| `frontend/src/views/data/QualityView.vue` | 无自身 CSS 查询 | 头部/筛选自然换行；质检结果内部滚动，详情委托共享抽屉。 | 路由 |
| `frontend/src/views/data/components/CheckupReportContent.vue` | 无自身 CSS 查询 | 抽屉内复用 AppDetailSection、AppSummaryDisclosureCard 紧凑行和 AppDataTable/AppTableColumn；提醒与未通过统一可展开，板块和 SQL 样例统一明细表并标明总数，数量/基准日在前、处理说明在后；摘要自然换行，宽表在自身横向滚动并限高，展开状态不随尺寸变化重置；正文由共享抽屉滚动。 | QualityView 私有报告片段 |
| `frontend/src/views/data/ScheduleView.vue` | 无自身 CSS 查询 | 任务表格/日志独立滚动，操作区自然换行；实时日志消费共享抽屉。 | 路由 |
| `frontend/src/views/layout/LayoutComponentsView.vue` | 无自身 CSS 查询 | 头部/工具条换行；能力表格内部滚动、详情共享抽屉；覆盖范围与个人层覆盖表复用长文档限高，表头固定、表体双向内滚。 | 路由 |
| `frontend/src/views/layout/LayoutPagesView.vue` | `@container app-viewport (max-width: 980px)` | 窄宽标签头部上下排列、配置网格单列并滚动；动作换行，编辑值保留。 | 路由 |
| `frontend/src/views/layout/LayoutPresetsView.vue` | `@container app-viewport (max-width: 980px)` | 窄宽导入/导出区单列；正文滚动，应用/保存动作保留。 | 路由 |
| `frontend/src/views/limit-ladder/LadderHotspots.vue` | `@container app-viewport (max-width:720px)` | 常规每类12项；低高≤700、宽>768且分析开启时4项；选中项纳入常显，具名展开其余项，用户展开保留。 | LimitLadder |
| `frontend/src/views/limit-ladder/LimitLadder.vue` | `@container limit-ladder (max-width: 700px)`<br>`@container app-viewport (max-width: 720px)`<br>`@container app-viewport (max-height: 620px)` | 自身limit-ladder容器≤700摘要重排；app宽≤720或高≤620热点整区默认收起，显式展开恢复，展开区限高内部滚动。 | LimitLadderView |
| `frontend/src/views/limit-ladder/LimitLadderCard.vue` | 无自身 CSS 查询 | 自然换行；长文省略，真实截断由全局宿主提示，完整名称不附加重复title；关联名称可收缩，历史标记保留；委托 RelatedBoardEmptyValue、RelatedBoardHistoryHint、StockStatusTag。 仅主选择区触发共享浮起层，卡片宿主及底部链接固定；受控选中使用单套边框、内侧线及浅背景；悬停时完整表面与内容同步浮起，宿主透明占位，不复制轮廓。 | LimitLadder |
| `frontend/src/views/limit-ladder/LimitLadderFilters.vue` | 无自身 CSS 查询 | 委托 AppAdvancedSearch、AppFilterSelect、AppFilterSwitch、AppSearchInput、AppSortControl、PageSegmented、TradeDatePicker。 | LimitLadderView |
| `frontend/src/views/system/AuditLogView.vue` | `@container app-viewport (max-width: 980px)` | 窄宽摘要2列、头部上下排列、操作左对齐；审计表格内部滚动。 | 路由 |
| `frontend/src/views/system/DataDictionaryView.vue` | `@container app-viewport (max-width: 980px)` | 窄宽头部上下排列、操作左对齐；树与详情由主体内部滚动承接。 | 路由 |
| `frontend/src/views/system/MenuResourceView.vue` | 无自身 CSS 查询 | 语义窄栏固定300，详情min480，mr-split内部横向滚动；两侧内部纵向滚动。 | 路由 |
| `frontend/src/views/system/PermissionResourceList.vue` | 无自身 CSS 查询 | auto-fit最小260列；长名称省略、资源列表滚动。 | PermissionTree、页面私有片段 |
| `frontend/src/views/system/PermissionTree.vue` | `@media (prefers-reduced-motion: reduce)` | 权限树内部滚动、节点省略；不按尺寸修改权限选择。 | RoleManageView、页面私有片段 |
| `frontend/src/views/system/RoleManageView.vue` | 无自身 CSS 查询 | 语义窄栏固定288，详情min460，rm-split内部横向滚动；两侧内部纵向滚动，整页不横滚。 | 路由 |
| `frontend/src/views/system/TenantManageView.vue` | 无自身 CSS 查询 | 委托 AppTableColumn、AppControlRow、AppSearchInput、AppDataTable、AppDialog、AppRowActions、AppStateBlock、PageSettingsDrawer、PageSegmented、PageSettingSection、SystemBuiltinTag、LayoutHost。 | 路由 |
| `frontend/src/views/system/UserManageView.vue` | 无自身 CSS 查询 | 委托 AppAdvancedSearch、AppTableColumn、AppSearchInput、AppDataTable、AppDialog、AppRowActions、AppStateBlock、AppStatusNotice、PageSegmented、PageSettingSection、PageSettingItem、PageSettingsDrawer、LayoutHost。 | 路由 |
| `frontend/src/views/trade-discipline/components/FixedDecimalInput.vue` | 无自身 CSS 查询 | 语义控件/展示单元随父容器布局；无几何触发的信息隐藏。 | TradeOperationEditor、TradeRuleEditor |
| `frontend/src/views/trade-discipline/components/RuleMasterList.vue` | `@container app-viewport (max-width: 1100px)` | 窄宽列表满宽且max-height210内部滚动，规则选择保留。 规则选项接入共享浮起视觉层与静态选中标记，列表借用外壳内距露出首尾浮层，条目占位、内滚和选择保持。 | TradeDisciplineView |
| `frontend/src/views/trade-discipline/components/StockOptionSelect.vue` | 无自身 CSS 查询 | 自然换行；长文省略，完整内容由提示/详情承接；委托 StockStatusTag。 | TradeDisciplineHistory、TradeOperationEditor |
| `frontend/src/views/trade-discipline/components/TradeCheckinForm.vue` | `@container app-viewport (max-width: 760px)` | 窄宽头部/事实/评估上下排列、网格单列，表单草稿保留。 | TradeDisciplineView |
| `frontend/src/views/trade-discipline/components/TradeCheckinRevisionDrawer.vue` | `@container app-viewport (max-width: 760px)` | 窄宽身份与版本切换上下排列、事实/规则单列，长内容在详情抽屉滚动。 | TradeDisciplineView |
| `frontend/src/views/trade-discipline/components/TradeDisciplineHistory.vue` | 无自身 CSS 查询 | 筛选控件最大100%，期间网格最低110；历史表格内部滚动，详情交给统一抽屉。 | TradeDisciplineView |
| `frontend/src/views/trade-discipline/components/TradeOperationEditor.vue` | `@container app-viewport (max-width: 1180px)`<br>`@container app-viewport (max-width: 760px)` | 中窄股票/时间占整行，规则/金额半行；更窄全部单列，输入保留。 | TradeCheckinForm |
| `frontend/src/views/trade-discipline/components/TradeRuleEditor.vue` | `@container app-viewport (max-width: 1100px)`<br>`@container app-viewport (max-width: 760px)` | 规则始终单列；基础字段与资金汇总复用表单标签、顶部对齐及同档控件高度，辅助说明不改变同行对齐；窄宽状态/基础单列并开放主体滚动，更窄头部/表单/footer换行，条件输入保留。 | TradeDisciplineView |
| `frontend/src/views/trade-discipline/components/ViolationReasonCombobox.vue` | 无自身 CSS 查询 | 委托 BuiltinOptionRow。 | TradeCheckinForm |

### 共享键盘行为

`WorkspaceTabs` 的方向键焦点移动会按现有布局坐标补滚被裁掉的标签；折叠后标签不进入焦点序列。`AppSplitWorkspace` 与 `StockChartWorkspace` 的方向键及 Home/End 调整遵守当前尺寸下的边界，与拖拽共用比例处理。其余键盘接入不改变几何或断点；完整按键和作用域规则见 [DESIGN.md](../../DESIGN.md)「键盘能力与适用边界」。

### 共享按钮状态

按钮角色及状态规则引用 [DESIGN 按钮角色与完整状态矩阵](../../DESIGN.md#按钮角色与完整状态矩阵)。本清单只维护响应式边界：状态变化不改变控件尺寸、布局或断点，按下不造成内容跳动。

可点击表格的名称列隐藏时，个股、板块和榜单结果表保留共享行操作入口；该列消费 `action-compact` 宽度折叠规则。板块成分股保留独立查看入口，避免名称和代码同时隐藏后失去键盘操作。
