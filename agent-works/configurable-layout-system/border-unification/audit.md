# 全组件边框逐项核查与统一方案

## 文档边界

本报告记录 2026-10-22 对前端快照 `ab036779` 的边框专项核查、实际差异和建议方案。整改前快照与差异保留在下文；2026-10-23 已按用户确认方案实施，当前规则以 [DESIGN.md](../../../DESIGN.md) §6 与共享实现为准。逐组件状态、源码入口和例外见 [完整核查矩阵](component-state-matrix.md)。后续角色变更同步更新 DESIGN 与共享实现；本报告保留审查快照和验证证据，不维护第二套生效规范。

范围覆盖 156 个 Vue 组件单元（含应用壳、通用、业务、布局和页面私有片段）、`AppHoverInfo.ts`，合计 **157 个组件单元**；额外核查 25 个路由 View 的私有边界，以及源码中小写标签与大写组件别名归并后的 **56 种 Element Plus 类型**，另补查 ElMessage、ElMessageBox 两种运行时服务及 v-loading 指令。样式链包括 `global.css`、`buttonStates.css`、`scrollbar.css`、`themeSurfaces.ts`、`useLayoutPreset.ts`、领域标签 helper 和图表 options/tooltip。未审查业务计算、采集结果或资产权限正确性。

## 2026-10-23 实施结果

按已确认的全组件方案完成实现。原157组件快照之外，补核当前新增的ScheduleDownstreamDrawer、LayoutConfigTransferPanel与本次BorderStatePreview，当前范围为159个Vue组件单元加AppHoverInfo.ts（160个组件单元）、25个路由View；全量184个Vue及CSS均进入边界静态门禁。组件形态按职责统一，不要求所有组件添加外框。

| 问题 | 已实施的入口与消费 | 状态与例外 |
|---|---|---|
| F01 | `styles/borders.css` 收口输入状态，补range `.is-active` | disabled > error+focus > error > focus > hover > default；浅/深真实键盘焦点和错误/禁用组合已实测 |
| F02 | `useLayoutPreset.ts`同步`--el-border-radius-base`；textarea/color/segmented局部变体适配 | number/radio-button子部件同步基础半径；circle、checkbox/radio和switch保留形状；自定义14/9圆角恢复由运行时单测验证 |
| F03 | ConfigPanelSection回到card；ConfigGroupForm删除覆盖；IconPicker/PageSegmented回到control/item | 图标hover强中性，已选主色保留；设置组/快捷卡等12px浮层形态改为具名变量 |
| F04 | 菜单/角色与布局管理私有面板消费`.app-surface`；配置/筛选/概览/采集/回测/训练等普通面板消费角色token | 主从栏承载身份、树操作和保存栏，保留其结构并共用表面配方；不为边框强制改成同一栏头模板 |
| G04 | 大弹层16、锚点浮层card、tooltip control；AppHoverInfo合并角色类和消费方类 | 所有当前比较/资金曲线画布均已有宿主外框，改为embedded无框画布；独立股票画布card，工作区内继续去重 |
| G05 | `--app-border-notice-*`明确软提示；强调框保留`--app-border-*` | AppStatusNotice、批量操作提示和概览提示接软提示；CompareQueueRail告警接强调框；领域身份色不变 |
| G06 | AppDetailFields外沿+1px间隙，AppDetailField向间隙投影，父裁切外侧 | 1/2/3列、跨列前不完整行、不完整末行和窄画布单列已复核，空缺位置保持内容面 |
| G07 | `check:borders`加入build；系统组件详情内增加真实BorderStatePreview | 直接消费真实控件、详情网格、AppTableCard和AppStateBlock；仅本地状态，不请求或保存业务数据；原型预览仍不代表业务入口 |

新补核两个既有组件：ScheduleDownstreamDrawer完全委托AppDetailDrawer/AppDetailSection/AppReorderList/AppStatusNotice，无私有边框，loading/error/empty由抽屉状态承接；LayoutConfigTransferPanel已有card外沿与内部操作分隔，textarea与busy禁用继承共享输入适配，无需新增私有样式。

### 本次验证与边界

- 定向Vitest **18个文件130项通过**，包含真实样板错误/禁用分支与外框节点保留、预设圆角联动/恢复、浮层角色类合并、边界门禁、响应式登记及相关配置消费。测试日志中的缺失页面宿主、permission指令和模拟请求失败为既有夹具/预期异常输出，未计为视觉证据。
- `npm run build`通过：字体、关闭、提示、滚动条及新增边界门禁、vue-tsc、Vite均成功。仅保留既有大包与第三方PURE注释提示。未执行全量单测或Playwright E2E。
- 内置浏览器5181，本地debug_system，原始默认视口及V1(1100×620)、V2(1366×768)、V3(1440×900)按下列范围局部复核，自动比例约91%；另用680px宽画布验证760px详情单列降级。未把这些局部观察当作全站所有页面重新验收。

| 证据 | 入口与状态 | 观察结论 |
|---|---|---|
| C01 | 真实样板，浅色默认、键盘range焦点、错误+焦点、错误+禁用 | 默认中性；焦点稳定为#1677ff，错误为danger内沿和光晕，禁用回中性；textarea/input6，number子件6，color6，分段6 |
| C02 | 真实样板，深色焦点、错误+焦点、错误+禁用、选中+禁用 | 焦点稳定为#3b8cff，错误内沿#ff6b66，禁用中性#454545；禁用分段保留原选中项 |
| C03 | 真实样板详情网格1/2/3列、跨列、不完整行；680px窄画布 | 内缝1px与外沿独立，空缺区域保持内容面，窄画布回单列且无整页横溢出；深色截图核对 |
| C04 | 真实样板结果empty→error→loading | 同一AppTableCard保留主题外框，错误/加载内容切换不拆宿主 |
| C05 | 菜单页V1、默认/选中图标/紧凑popover；系统配置V1展开/收起/恢复 | 主从面板和一级配置组10px；图标触发器与候选6px，选中主色，popover10px；折叠保留外框，无整页横溢出 |
| C06 | 字典页V3，新建类型Dialog默认、textarea键盘焦点、取消 | Dialog主题外沿1px/16px；input与textarea均6px，textarea稳定焦点为主色内沿和3px光晕；取消未保存；无整页横溢出 |

只对以上真实状态及下方提交前复查记录浏览器结论；未逐个制造160组件的全部请求失败、权限组合或鼠标按住帧。其余状态的边界职责由原矩阵源码追踪、共享实现与定向测试覆盖，不能表述成全部视觉状态均已实测。没有保存菜单、权限、字典、系统配置或触发业务写任务；主题恢复白天，验收视口完成后恢复默认。

### 提交前复查

按完整diff及共享消费者复查，修复四处遗漏：

| 问题 | 修复及证据 |
|---|---|
| 深底Popover被`.is-dark`通用规则误归为Tooltip | 浏览器复现6px；将Popover/菜单排除，恢复card角色10px。新增浮层语义选择器回归，并在真实样板加入点击式深底Popover |
| 日期范围禁用底色被普通输入规则覆盖 | 浏览器复现range白底、其它禁用输入灰底；共享disabled分支显式消费`--el-disabled-bg-color`，修复后range/input/textarea/select一致，错误叠加仍中性 |
| 变量与固定圆角混写绕过门禁 | 去除变量调用内的兜底后检查剩余形态值；覆盖变量+8px、calc变量+8px和合法变量兜底 |
| 筛选页历史版本卡片误用了control圆角 | 与配置页同角色版本卡统一为card token |

以上修复不改变业务请求、权限和持久化配置。通过失败回归及浏览器复现确定问题，再修实现并复测；未用修订规范豁免实现差异。

最终定向回归18个文件130项通过，构建（全部设计静态门禁、vue-tsc、Vite）通过；`git diff --check`通过。设计契约、相关实现及维护登记复查完成，本轮发现的四处问题均已修复，未发现剩余阻断项。未重复执行全量测试或Playwright E2E。

C07：提交前以内置浏览器默认视口复测，深底Popover在浅/深主题均为10px；禁用input/textarea/select/range底色在浅色均为#f3f3f3、深色均为#292929，错误叠加时边界继续为中性。浅色复现截图1280×720、自动比例约91%；本次未重新做V1–V3全页面验收。已恢复白天主题并关闭临时标签页，无业务数据写入。

## 整改前结论与证据口径

- **DESIGN：需要补齐。** 已有边框颜色、卡片/控件圆角、交互和部分边界所有权规则；还缺全组件角色到各库子部件、组合状态、嵌套边界的完整映射。
- **实现遵循：不通过。** 至少存在日期范围焦点样式被覆盖、文本域等输入变体漏接控件圆角、普通配置面板/自定义控件绕过共享圆角、页面私有面板仍重复实现的问题。
- **颜色基础已有统一入口。** `themeBorderVariables()` 输出常规、分隔、强、选中及状态边框，`useLayoutPreset()` 同步到 Element Plus、chrome 和设置浮层变量。多个变量名不等于多套独立颜色，不建议机械合并所有别名。
- **157 个组件均完成源码及状态继承路径登记，不等于157个组件的所有状态都已浏览器通过。** 矩阵使用 S 表示源码追踪；浏览器实测仅指B01–B05及B07/B08明确列出的分支，B06只是前次交付引用。按下、真实请求失败、全部只读权限组合、全部 loading/empty/error 的视觉效果仍有缺口，不以推断补写为通过。
- **没有要求所有组件都画外框。** 排版容器、表格内部列、图例标记、拖动提示、标签、导航与卡片承担不同边界职责；应统一角色与入口，而不是统一成同一外观。

核查视口为内置浏览器专用 5181、1366×768、自动界面比例95%；默认浅色，并对日期范围焦点核查深色。使用既有 `debug_system` 调试账号；未保存菜单、字典、权限、配置、采集、交易或回测数据。界面主题切换后恢复为白天。源码核查覆盖全部组件，浏览器只对下表列明的实际状态提供证据。

## 整改前逐状态差异摘要

| 状态 | 已收口的入口 | 当前差异 | 统一方向 |
|---|---|---|---|
| 默认 | 卡片/表格外壳、普通 input/select/button、导航与主题边框 | textarea、图标触发器、分段选择和私有面板仍各自决定圆角；图表和弹层边界职责不完整 | 补组件角色映射，不由页面决定普通边框配方 |
| 悬停 | 命令按钮、导航、交互卡片、列表候选、帮助入口已有专用规则 | 图标触发器直接主色边框；部分库子件仍依库默认规则；不能把控件 hover 和图表序列高亮混在一起 | 输入用强中性边框；导航/候选/卡片按专用角色，不统一刷主色 |
| 按下 | `buttonStates.css` 和共享交互卡片/导航规则 | 自定义原生控件及库变体未全部进入同一状态矩阵 | 不新增页面 `:active` 配方；本轮此项为源码核查，未逐项捕获鼠标按住帧 |
| 焦点 | 按钮与说明入口的共享 ring，普通输入的原生主色内边界 | **日期范围的 `.is-active` 没被适配，键盘焦点仍灰色**；复合输入与 textarea 的视觉入口不同 | 命令用共享2px焦点轮廓；输入保留内描边结构，补齐各变体的真实焦点 class |
| 选中/展开 | 导航当前态、交互卡片、候选列表、摘要展开已有规则 | 分段控件存在两套实现入口；复选资源行仅内层 checkbox 改变，不能自动当成整卡候选；字典/来源身份色也不是选中 | 明确选中对象；选中边界不能被 hover 覆盖；展开、路由当前态与拖动标记分别定义 |
| 禁用/只读 | button/input/select 与暗色 checkbox/radio 有适配 | 自绘控件和其他库变体仍需按真实 disabled/readonly 透传核对 | 保留外形和值；禁止 hover/按下反馈；不把“无权限只读事实”误画成禁用命令 |
| 加载 | 命令 loading 保留角色原色；异步区域首次骨架/已有内容遮罩；结果卡片稳定 | 组合组件本身不一定有 loading 属性，不能因子控件支持就宣称整组件支持；库预览也不证明真实边界稳定 | loading 锁交互但不套普通 disabled 灰态；外框归宿主，内容替换不拆框 |
| 错误/空态 | AppStateBlock/AppAsyncRegion/AppDetailDrawer 与库表单 error 分支 | 字段校验、区域错误和软提示的边框职责/配方仍不同；部分业务仅 toast，不能据此声称字段已红框 | 字段错误、区域错误、状态提示分角色；error+focus 保留错误语义；外框不随内容失败消失 |

## 明确问题与待决策差异

### F01 · P1：日期范围输入丢失主色焦点边界

- 依据：DESIGN「输入与复合控件」「夜间控件」要求焦点可辨；输入保留自身焦点结构，不能被普通/hover边界覆盖。
- 源码：[global.css](../../../frontend/src/styles/global.css) 的输入适配只覆盖 `.el-input__wrapper.is-focus`、`.el-select__wrapper.is-focused`；[AppDatePicker.vue](../../../frontend/src/components/AppDatePicker.vue) 不区分外观，范围控件实际使用 `.el-range-editor.is-active`。
- B02 实测：审计页时间范围已获得键盘焦点、根节点有 `is-active`，浅色仍为 `rgb(212,212,212)` 内描边；鼠标点击组合态为强中性 `rgb(201,201,201)`。深色键盘焦点仍为 `rgb(69,69,69)`，而主色为 `#3b8cff`。
- 影响：`AppDatePicker` 的 daterange/datetimerange 等范围消费者；单值日期通过不能证明范围通过。
- 建议：在共享输入状态入口补 range 的真实焦点 class，并验证 default、hover、focus、disabled、error+focus。不能只在审计页补私有 CSS。

### F02 · P1：库控件变体没有完整消费控件形态

- 依据：DESIGN §6 普通控件消费 `--layout-control-radius`；库控件适配应在共享入口完成。
- 源码：[global.css](../../../frontend/src/styles/global.css) 只将 `.el-button`、`.el-input__wrapper`、`.el-select__wrapper` 的圆角映射到控件 token。文本域、单选按钮、原生 `el-segmented`、颜色触发器和数字输入的子部件仍有库基础半径入口。
- B03 实测：同一个新建字典类型弹窗，普通输入为6px，备注 textarea 为4px；textarea 聚焦能正确变成主色内描边，**问题是圆角漏接，不是焦点完全失效**。
- 影响：AppSearchInput/FixedDecimalInput 等单行包装的基础角色已统一；需要补齐 textarea、number子部件、color、radio-button、segmented 等实际变体，不能对所有原生库标签盲目加边框。
- 建议：根级基础半径映射与各角色覆盖成套设计；矩形触发器跟控件 token，圆形 checkbox/radio/thumb 和胶囊 switch 保留图形语义。

### F03 · P1：自定义普通面板和控件绕过共享圆角

| 组件 | 当前实现 | 建议角色与入口 |
|---|---|---|
| ConfigPanelSection | 一级框固定6px | 主内容配置面板消费 card token；子分区用结构线 |
| ConfigGroupForm | 根固定8px，覆盖同角色分组容器 | 删除消费者的平行外框形态，回到 ConfigPanelSection |
| IconPicker | 触发器4px、候选6px | 触发器消费 control；候选按共享列表项；已正确的焦点/选中规则保留 |
| PageSegmented | 普通组12px、按钮8px；small 才消费 control | contained/tabs 保持语义差异，普通/小号的形态都消费明确角色 |

源码入口和行号见矩阵。本轮 B01 实测 ConfigGroupForm 为8px、根 card token 为10px；B04 实测 IconPicker 触发器4px、候选6px、选中候选主色边框且键盘焦点可见；B05 实测普通 PageSegmented 为12/8px。

### F04 · P1：路由页仍存在平行的普通面板实现

- [MenuResourceView.vue](../../../frontend/src/views/system/MenuResourceView.vue) 的 `.mr-col` 与 [RoleManageView.vue](../../../frontend/src/views/system/RoleManageView.vue) 的 `.rm-col` 自绘边框/8px圆角和几乎相同的栏头结构；布局管理页 `.plain-panel` 固定6px。
- B04 实测菜单左右栏为8px；现有 [AppWorkspacePane.vue](../../../frontend/src/components/AppWorkspacePane.vue) 已提供主题圆角、栏头和内部图表边界归属。
- 影响：只修通用组件目录仍会留下页面私有规则，所以矩阵额外逐项登记25个路由View。
- 建议：按相同变化原因迁移有标题的工作区栏到现有 AppWorkspacePane；不适合整组件复用的普通面板消费同一表面角色，不复制 border/radius 配方。

### G04 · P2：弹层、画布和嵌套边界需要明确角色，不能一刀切

- B03 实测 AppDialog 为无实体 border、4px圆角；B05 PageDrawerSurface 为1px边框、16px圆角。后者在现有规范中属于允许的抽屉形态，不能把16px直接判违规；短对话框、ElMessageBox确认框、锚点popover和tooltip的角色映射仍不充分。
- EquityChart、SectorCompareChart、StockCompareChart 的包裹层固定6px且无实体 border。它们有的嵌在工作区中，**不能据“无框”直接要求再加卡片**；应先确定 standalone/embedded 的边界所有者。
- TradeDisciplineQuickCard 当前仅在用户中心抽屉内消费，12px符合浮层卡片例外，不属于F03；StockChartSettingSection的固定K线框是只读值而非选择按钮，AppRowActions的4px是菜单子项，PermissionTree的8px是嵌套权限组，均需先登记角色再判定。
- AppWorkspacePane 已明确清除直属股票画布的重复框；表格已由 AppTableCard/工作区承接。这是可复用的边界所有权模式。
- 建议：独立表面绘一次外框；嵌入内容只绘内部必要分隔线；弹层角色与普通面板不同，但颜色来源、粗细、形态入口和例外必须可追溯。

### G05 · P2：状态边框有多种配方，缺少子角色映射

- AppStatusNotice 使用 `--el-color-*-light-7`；TradeDisciplineQuickCard/TradeRuleEditor 使用 `--app-border-warning/success/danger`；CompareQueueRail 错误chip使用 warning 原色；StockGroupBatchActions 使用 primary-light-7。
- B05补查当前浅色变量：warning状态框为`#e1b682`、warning-light-7为`#fcdcb5`；danger状态框为`#df9a96`、danger-light-7为`#fbc7c3`。
- 这些值均可由主题派生，**不能把“颜色不同”直接判为硬编码违规**。差异在于普通边框告警、浅底软提示、选中态、来源/字典身份没有完整映射到明确子角色。
- 建议：为“软提示”和“强调状态框”明确不同配方并绑定消费者；金融涨跌、来源身份、字典与自选分组继续保留领域helper，不统一刷成系统错误/成功色。

### G06 · P2：结构网格外沿与内部线的所有者尚需收口

- AppDetailFields 自绘dl外框，AppDetailField 对每个单元格绘右/下 inset 线；代码层同时存在父外沿与末行/末列内描边。需要按最后一行/列以及跨列字段确认是否有重复外沿，不能只看默认两列。
- B08已在审计详情就绪态核对到父网格实体边框与末项右/下inset同时存在；**尚未做像素级重复描边判定及全部跨列/单列组合，不列为已复现的视觉故障**。
- 建议：父容器拥有外沿、子项仅拥有内部接缝；跨列、单列响应式和空值布局一并验收，不能粗暴取消全部分隔线。

### G07 · P2：全组件状态映射及验收守卫仍不完整

- 现有字体、关闭入口、提示、滚动条检查及主题变量测试可以保护部分契约；没有完整覆盖所有库子件圆角、真实焦点 class、边界归属和组合状态。
- LayoutComponentPreview/LayoutPagePreview 的 ready 状态允许代表性原型，不是真实业务组件；原型的 default/loading/empty/error 不能证明对应消费组件的所有边界已通过。此处是验收边界，不要求废弃现有目录预览。
- 建议：用角色到消费者的清单维护准入；只检查普通卡片/控件的游离 border/radius，允许已登记图形/身份/浮层例外。源码检查发现问题后，必须以真实组件/消费入口复核，避免只新增CSS文本断言。

## 建议统一方案（待实施）

### 1. 保留现有事实源，补齐角色映射

不新增一套平行主题或万能外壳。继续使用 `themeBorderVariables()`、`--layout-card-radius`、`--layout-control-radius`、buttonStates、共享交互状态，以及现有 AppWorkspacePane / ConfigPanelSection / AppTableCard / PageDrawerSurface。

| 角色 | 推荐外形 | 统一入口与边界 |
|---|---|---|
| 普通独立表面 | 1 CSS px、中性 border、card radius（当前10px） | 工作区栏/配置面板/结果卡片按现有专用组件复用 |
| 输入/命令触发器 | 1 CSS px或已有内描边、control radius（当前6px） | 全局库适配 + 必要的自绘控件共享角色；不在消费页补样式 |
| 内部分隔线 | 1 CSS px、divider | 父外沿、子接缝分工；不以一圈边框替代分隔线 |
| 对话框/抽屉 | 推荐归统一大弹层角色，默认16px；是否实体描边统一决定 | 在弹层唯一入口消费CSS角色；保留蒙层与阴影职责；不新增Web配置字段 |
| 锚点popover/菜单 | 推荐紧凑浮层角色，消费card形态；tooltip可用control形态 | 全局库适配，触发器与浮层分开归属 |
| 整卡候选/当前项 | 普通中性框、选中主色框或已登记标记 | shared interaction-card / list-item / navigation，按角色区分 |
| 告警/软提示 | 状态强调框和浅底软提示两种有名配方 | 状态容器消费语义角色；表单错误、领域身份独立 |
| 图形与身份形态 | 圆形、胶囊、图例、拖动提示保留 | 明确登记例外；不按普通卡片/控件半径迁移 |

以上方案已由用户“处理”确认并于2026-10-23实施；生效规则维护在DESIGN §6，不在本报告平行维护。

### 2. 将状态优先级写成可执行映射

- default：只显示所属角色的基础边界。
- hover：输入用强中性边界；候选/导航/卡片按各自共享规则。不要让所有hover都变成主色。
- focus：命令用共享焦点轮廓；输入沿用原生内边界。补 `.is-active`、`.is-focused`、`:focus` 等实际变体，不能只匹配其中一个class。
- selected：保存选择标记，hover不得覆盖；焦点轮廓独立叠加。展开、路由当前、拖动预览、业务身份不都映射成selected。
- disabled/readonly：保留可读值和外形，禁用交互反馈；只读事实面板不整块变灰。
- loading：动作锁定，保留角色边框；不要因为DOM有disabled属性就误套普通disabled样式。
- error+focus：字段错误边界继续表达错误，焦点可见但不覆盖错误语义。区域error/empty保留所属外壳。
- selected+disabled、loading+disabled、error+focus、父面板+子表面必须单独纳入组合态验收，不能只验七张单态截图。

### 3. 分批实施并控制回归面

| 批次 | 内容 | 主要消费者 | 最低验证 |
|---|---|---|---|
| P1-A | range焦点；textarea/number/color/radio-button/segmented子件适配 | 日期筛选、字典/用户表单、交易纪律字段 | 真实焦点、hover+focus、disabled、error+focus；浅/深主题；已有状态单测 |
| P1-B | 普通配置面板、自绘图标/分段控件、页面私有工作区栏迁移 | 系统设置、菜单、角色、布局管理、交易纪律 | 同角色消费者抽样；展开/关闭/只读；自定义圆角预设；不重复套框 |
| P2-C | 弹层与图表边界所有者；软提示配方；描述网格接缝 | AppDialog/Popover/比较图/详情抽屉 | standalone/embedded、跨列/单列、loading/empty/error、嵌套浮层 |
| P2-D | 角色映射清单与静态守卫，补真实组件状态样板 | 所有新组件/新增变体 | 普通角色禁止游离配方；例外可追溯；来源与消费点一致 |

同步更新点：DESIGN负责生效规则；themeSurfaces/useLayoutPreset负责变量；global/buttonStates负责库与状态适配；实际组件负责结构与事件；responsive-components/pages记录消费者及实际验收范围。只有涉及真实Web可配置字段时才改componentConfig、schema和后端规则，不能为了样式统一制造新配置项。

## 浏览器与交付证据记录

| 编号 | 入口与实际状态 | 观察结果 | 未覆盖边界 |
|---|---|---|---|
| B01 | 系统配置，默认/禁用按钮、number输入、一级分组 | card token10、control token6；输入6；配置分组8；禁用按钮中性保形 | 未保存配置、未触发联网测试；本轮未制造服务端配置失败 |
| B02 | 审计日期范围，鼠标点击+焦点、Tab键焦点；浅/深主题 | `is-active`存在；浅色普通灰/hover强灰、深色普通灰，均未显示主色焦点 | 日期错误值/disabled分支未在此入口制造；不能据此推断单值日期也失败 |
| B03 | 字典新建类型弹窗，默认与备注文本域焦点 | dialog无实体border/4px；input6px；textarea4px且焦点主色；取消关闭 | 未保存字典；未把toast或字段校验人为改成统一红框 |
| B04 | 菜单页选择现有节点，图标触发、候选默认/已选、键盘焦点 | 私有左右栏8px；trigger4px、候选6px；已选候选主色边框；键盘焦点已有主色实线 | 未选择新图标、未保存菜单；未制造禁用图标、真实加载失败 |
| B05 | 视觉环境抽屉，默认/已选分段、浅/深切换 | Drawer16px有主题边框；普通分段12/8px，选中强中性边框；恢复白天 | 未更改导航布局或保存自定义预设；不以该设置控件代表业务原生segmented |
| B06 | 既有表格外框交付记录核对 | ab036779已完成独立表格外框/列线分离；本报告矩阵保留该事实 | 上轮119项测试和三视口结果属于上一轮交付，不计为本轮重新运行 |
| B07 | 系统配置一级分组展开→折叠→恢复 | 折叠后仍有中性外框与8px圆角、aria-expanded=false，展开恢复；源码补查其它disclosure入口 | SettingsGroup/AppSummaryDisclosureCard的全部浏览器组合、错误/空态和权限组合未全部执行 |
| B08 | 审计详情就绪态网格；图表边界源码补查 | dl有中性边框/10px圆角，末项仍有右/下inset；chart主题、options/tooltip、父工作区清除子框规则已源码检查 | 未做G06像素级与全部跨列判断；未新跑回测/采集制造图表loading/error |

已运行现有定向状态测试：AppIconButton、AppCloseButton、AppAsyncRegion、AppStateBlock、AppDataTable、AppDatePicker、AppSelect、PageSegmented、ConfigGroupForm、IconPicker、AppSummaryDisclosureCard、PageDrawerSurface，按 `loading|加载|禁用|错误|失败|焦点|disabled|错误态` 筛选。**12项通过、57项未命中筛选而跳过，8个文件有命中、4个文件无命中**。这些测试验证状态分流/事件，不证明CSS圆角或真实焦点颜色正确；尤其不能以AppDatePicker无命中测试宣称F01通过。

2026-10-22审查轮没有修改前端实现、执行构建、全量测试或Playwright E2E。2026-10-23整改的验证另见前方记录。没有把源码推断、既有交付证据、预览原型或库默认行为登记成新的浏览器通过记录。

## 已确认例外与剩余验收边界

- 抽屉16px、设置分组12px、用户中心内的交易纪律快捷卡12px有现行规范依据；圆形帮助入口、图例1px、胶囊标签、拖动轮廓有独立语义。仅因与10/6px不同不能判违规。
- 登录页的品牌形态不按普通工作台面板机械迁移；其错误+焦点已有专用错误色分支，应作为有名例外复核。
- `border`配置目前只控制表格列分隔线，不能用来解决全部组件的外框问题。
- 157组件矩阵的浏览器未覆盖状态仍保留为未实测；后续需以批准的角色映射和真实组件状态样板补齐，不能把本报告当作全状态视觉验收证书。
