# 开发验证与维护清单

按本次改动的可观察结果和风险选择验证层次、维护对象及完成证据。新增功能和已有功能修改使用同一套选择方法。

参考：

- [通用测试与门禁维护](~/ai-agent-config/config/force/testing-standards.md#验证选择与门禁维护)
- [项目命令与环境识别](../../AGENTS.md) · [环境配置](../architecture/environment-configuration.md#环境身份与运行模式) · [测试账号](../multi-tenant-rbac/test-users.md)
- [设计规则](../../DESIGN.md) · [页面实施模板](../configurable-layout-system/page-template.md) · [布局运行机制](../architecture/frontend-layout.md) · [显示比例策略](../configurable-layout-system/display-scale-policy.md)
- [E2E 准入与生命周期](../e2e-automation/guide.md)
- [菜单与权限接入](../architecture/system-rbac-tenant.md#新页面接入菜单和权限) · [数据目录](../architecture/data-management.md) · [任务运行态](../architecture/task-runtime.md) · [个股采集](../architecture/stock-collection.md) · [板块采集](../architecture/board-collection.md)

## 验证选择与完成条件

1. 明确本次可观察结果与受影响范围：入口/权限 → 输入与边界 → 处理 → 写入或任务终态 → 回读与下游消费 → 页面反馈及失败恢复。只验证变化及受其影响的链路，不为纯文档或局部展示改动启动无关业务流程。
2. 先在能证明风险的最低层覆盖正常、失败与边界；新增后端领域逻辑优先服务/领域单测，新增布局、校验、配置合并和权限消费逻辑补 Vitest。写入检查失败后的数据与状态；重试检查重复执行结果；敏感数据检查实际输出。存在处理代码不等于行为已验证。
3. 接口、存储或异步任务改动按需补 API/集成与代表性真实入口；计算、采集、质检、回测等闭环直接核对真实终态和落表。Mock 页面只证明前端消费行为，纯算法基准不能替代输入加载、计算和落表链路。
4. 页面呈现或操作可达性变化必须完成受影响页面浏览器实测；纯函数/状态逻辑用定向测试，不影响布局与行为的文案、注释和展示属性做差异与格式检查。新页面和布局改造按下方「页面与响应式实测」覆盖关键视口。
5. 对照总清单完成实现、文档和门禁同步，交付前核对完整改动。规则变更复用共享检查器及合法/违规样例；既有入口不足时才扩展，不另建页面私有检查流程。禁止为通过而弱化断言、扩大豁免或跳过必要检查。
6. 报告执行命令、范围、通过/失败/跳过、实际入口结果、未验证项及原因，区分 Vitest、后端测试、构建、Playwright 与临时浏览器复核。必要验证失败或未完成时不得宣称验收通过；自审和源码走读不能替代运行证据。源码与条件未变时复用有效证据，不重复构建或回归。

领域、服务、API 和 Vitest 按受影响逻辑选择单用例、文件或相关模块范围，默认不跑全量；全量 Vitest 用于发布门禁或明确的完整验收需求（含符合专项准入的 `test:design`）。测试无法隔离受影响范围或存在跨模块回归风险时，可依据具体证据扩大低层回归范围并说明理由。低层证据已充分覆盖本次风险，且没有其他适用的必检项时，停止追加更重验证。Playwright 的新增、执行及整组/多视口准入按 E2E 指南判断，不因已有覆盖就扩大范围，也不能用其准入条件阻止必要的低层回归。

### 设计规范变更与门禁覆盖

新增或实质更新 DESIGN 规则时，必须同步适用的共享实现与消费者、合法/违规样例、实际 CI 或专项入口，并明确覆盖边界。验证方式按通用测试规范选择；仅编写规划规则时标明待实现、待接入，不自动启动开发。

本项目新增设计检查器接入 `check:design`，共享行为测试按 [CI 接入要求](../architecture/continuous-integration.md#接入扩展与变更影响)进入实际套件。扩展门禁时覆盖组件别名、包装、条件分支和局部覆盖等适用消费方式；技术例外按所属规则限定对象、条件和原因，并检查失效登记。

下表记录当前已实现的部分门禁及其验证边界，供查找入口；未列入表的新增规则同样执行上述维护要求，按总维护清单中的对应类别补齐验证。表中记录不代表全部设计规则已自动覆盖。

| 设计规则与共享入口 | 自动检查与正反例 | 持续执行及页面边界 |
| --- | --- | --- |
| 标题名称/说明分离 | `check-design-consistency.mjs::auditHeadings`、`design-consistency.spec.ts` / `design-consistency-regressions.spec.ts`、`StockChartPanelHeader.spec.ts` | `check:design` / 常用 CI；运行时菜单或接口标题仍需实际页面核对 |
| 禁止游离间距、共享动效 token | `auditSpacingMotion`、同一组契约正反例；精确技术例外及失效检查 | CSS、内联对象/函数返回值和脚本 HTML；私有变量仅追踪当前/同选择器作用域与根定义，不模拟任意选择器继承。实际几何、层叠及减少动态效果按页面验证 |
| 同一上下文实色主按钮数量 | `auditPrimaryActions`、别名/条件互斥/弹层正反例 | 模板可确定的条件及 computed；跨组件组合和复杂运行态仍需消费者测试及页面核对 |
| 日期时间格式统一 | `auditDateTimeConsumers`、`dateTime.spec.ts` 与消费正反例 | 逐分支检查展示表达式、实际公共导入与有限业务包装器；常见日期字段、时间戳列与私有格式化受检查，不推断任意接口字段的运行时类型。不改写业务日期计算或提交载荷，动态数据来源需消费者验证 |
| 样式配方复用 | `auditSharedStyleRecipes` 拒绝复制已发布的数字强调配方；`npm run audit:style-reuse` 提供其它重复配方候选 | 候选不是硬违规，按角色/状态判断；共享 class 不能替代最终呈现验证 |

## 验证机制与命令

后端命令从仓库根目录运行；`npm` 命令在 `frontend/` 下运行。执行前完成下方「环境、数据与服务保护」。以下是定向执行形式，替换示例文件和用例名后使用：

```bash
# 仓库根目录；先检查测试的数据库访问与隔离要求
python -m pytest backend/tests/test_xxx.py::test_name -q

# frontend/；替换为受影响的实际用例
npm test -- src/layout/__tests__/pageRegistry.spec.ts
```

| 机制 / 入口 | 实际覆盖 | 不能替代的证据 |
|---|---|---|
| `npm run check:design` | 本地源码的字体、CSS 变量、表头、设置结构、关闭控件、提示、滚动条、边框、操作行、数值、设计契约、标题/间距/动效/主按钮/日期消费及响应式登记扫描 | 未编码的语义规则、运行时行为与真实呈现 |
| `npm test -- <测试文件>` | `pretest` 自动执行静态门禁，再运行指定 Vitest；纯逻辑用 node，真实组件装配可用 jsdom | 类型检查、真实浏览器几何及后端闭环；`npm test` 无过滤时才运行全量 Vitest |
| `python -m pytest backend/tests/test_xxx.py::test_name -q` | 指定领域、服务、API 或存储测试；依据用例判断真实存储、内存库及 Mock 边界 | 未覆盖的真实入口、外部来源及代表性规模；全量入口为 `python -m pytest backend/tests/ -q`，不默认执行 |
| `python -m backend.cli verify-catalog` | 双库物理发现、表/字段业务元数据、归属/来源/关系及质量/鲜活度策略契约；表新增或修改时合并前必跑 | 数据值正确性和业务结果 |
| `./start.sh database gate` | 独立真实 PG 与 DuckDB 的新装、冻结旧库升级、重跑保护、完整结构/seed 负例、失败恢复及真实 CLI/目录验收；缺依赖或跳过均失败 | 业务实例实际状态、大表性能及领域数据转换；完整策略见 [数据库专题](../architecture/database-lifecycle.md) |
| `./start.sh database check` | 指定环境当前双库的实例、结构、完成摘要、必需 seed 和目录只读验收 | 初始化/修复写入和领域数据质量；文件锁与服务保护沿用本指南 |
| `python -m backend.cli verify-data`、领域规模测试 | 实际数据质量/完整性及按需跨源核验；专项规模测试验证真实服务链路的加载、计算、落表和重跑 | 外部接口 Mock 的真实性；数据质检不是任意功能的验收替代 |
| AI 内置浏览器 | 临时复现、点击、控制台、视觉、焦点、滚动和响应式实测 | 长期自动回归、未观察状态和后端业务正确性 |
| Playwright | 满足专项准入的浏览器独有稳定关键链路 | 已由低层测试负责的计算口径、任务重试、并发和落库；命令与夹具仅按专项指南执行 |
| `npm run check` / `npm run test:contracts` | 本地快检：`check` 执行设计静态门禁、布局与共享设计行为套件和类型检查；`test:contracts` 仅运行该套件，收集范围由 `vitest.contracts.config.ts` 定义 | 业务页面全量、浏览器原生行为、生产构建和 E2E |
| `npm run build` | 静态门禁 + `vue-tsc -b` + Vite 生产构建；不运行 Vitest | 行为、权限、数据和视觉验收 |
| `npm run test:design` | 安全前检 + 全量 Vitest + 构建 + 五组串行 E2E；由专用 runner 管理夹具与恢复 | 后端 pytest、数据目录/质量核验及未覆盖业务链路，不是全栈验收总命令 |

**构建准入**：只有构建配置、依赖、路由或懒加载、全局资源、生产产物受影响，执行发布门禁，或用户明确要求时才运行 `npm run build`。开发预览使用 HMR；普通局部模板、组件逻辑或样式不因改动文件就默认构建。下方清单所有行共用此条件。

常用/专项 CI 的覆盖、命令、调用与新增测试接入统一见 [CI 编排与持续维护](../architecture/continuous-integration.md)。直接手动运行 pytest 时，PG/Redis 不可用仍可能 skip，真实库 API 冒烟也可能整组跳过；命令退出成功不能把跳过项计为通过，依赖与规模须按待验收场景落实。

## 总维护清单

先按改动所在层选择基础行（文档、后端领域、API、前端逻辑或页面呈现），再叠加表结构、任务、布局、权限及共享组件等专项行。改缺陷时复用或补充能复现原问题并断言修复结果的用例。多个命中项合并验证，不机械重复执行；没有命中的专项行时仍按基础行覆盖实际变化，不能据此免测。表中未带路径的前端测试名按 `frontend/src/**/__tests__/` 定位，后端测试位于 `backend/tests/`；列出的文件是选取入口，仍按实际影响覆盖消费者和失败分支。

| 变更类型 | 必须同步维护 | 必须验证 |
|---|---|---|
| 纯文档 / 规范重构 | 有效规则、条件与例外、引用、示例和机器读取契约（frontmatter、字体 token、`page-registry` / `design-contracts` 区块）；独有要求迁入对应正文，重复要求保留一处 | 差异与语义对照、路径/锚点、代表性任务走读；影响解析时执行对应契约测试，不启动无关后端或页面验收 |
| CI 编排 / 测试归属 | 按 [CI 专题](../architecture/continuous-integration.md#接入扩展与变更影响) 维护登记、执行机制和生成表；本指南保留本地验证选择 | 按该专题验证受影响执行器、分流和结果判据 |
| 后端领域 / 业务规则 | 领域实现、共享入口、上下游消费者、相应架构事实与测试 | 定向服务/领域测试；数据口径、防未来函数、回测撮合等覆盖正常、边界和失败；必要时代表性真实入口及回读 |
| API / 权限 / 租户资产 | 路由守卫、资源 seed/SQL、默认角色决策、前端权限消费、归属条件与 RBAC 文档 | 路由扫描；请求真实受控入口验证最小权限/无权/fail-closed、跨用户/租户隔离、输入及异常映射、写后回读和下游消费；不能只检查按钮隐藏 |
| 表结构 / 数据契约 | 按数据库接入流程同步 DDL、旧库升级、机器契约、表/字段元数据、归属/来源/关系和质量策略 | 合并前 `./start.sh database gate`；实际实例另按数据库专题验收，数据值或质量规则变化时补质检 |
| 采集 / 长任务 / 批处理 | 共享任务与采集入口、任务/采集事实文档 | 状态、幂等、取消、重试、互斥、补偿与真实终态；代表性规模按下方「批处理与真实数据链路」验证 |
| 前后端新增 / 改动业务链路 | 实际入口、输入契约、处理、结果、上下游、页面状态及对应事实文档 | 跨层业务变更合并受影响项，沿真实入口→处理→结果/终态→回读及页面反馈验证；写功能覆盖保存及失败恢复，只读功能核对查询与消费结果；局部纯逻辑/呈现变更由下方基础行选择验证，不强行执行无关写任务 |
| 前端逻辑 / 组件行为 | 纯函数、composable、组件状态、请求消费、字段守门与共享消费者；已有用例同步行为契约 | 定向 Vitest 覆盖正常、边界及失败；布局、配置、权限接线或类型/模板接口变化运行 `npm run check`，其它纯计算逻辑以定向 Vitest 验证；只有真实浏览器装配才能暴露的交互风险再按专项准入补最小 E2E |
| 页面局部呈现 / 文案 | 受影响区域、DESIGN 对应契约、复用组件、必要的响应式说明；只记录局部设计决策 | 样式/布局/可达性变化执行受影响静态门禁和内置浏览器实测，行为变化叠加定向 Vitest；局部改动只复核受影响状态/断点，不默认三视口；不影响布局与行为的文案、注释或展示属性做差异与格式检查 |
| 新页面 / 页面布局改造 | 页面设计、脚手架、`pageRegistry.ts`、`router/index.ts`、DESIGN 登记；受影响组件/页面响应式记录，导航或受控动作叠加 RBAC | `npm run check`、页面/组件行为测试；权限变化叠加权限测试，关键视口按下方实测方法；路由/懒加载变化触发构建 |
| 响应式降级变化 | DESIGN §8、`responsive-components.md`、`responsive-pages.md`、真实组件与页面降级设计 | 按下方「页面与响应式实测」同步清单、验证触发/恢复/状态保留及关键视口 |
| 布局原型新增 / 修改 | `archetypes.ts`、`schema.ts`、`validator.ts`、`LayoutHost.vue`、DESIGN 原型说明 | `validator.spec.ts`、布局契约测试 |
| 系统组件种类新增 / 修改 | `COMPONENT_CATALOG`、`componentSchemas.ts`、`componentPreview.ts`、系统组件页展示 | `componentPreview.spec.ts`、`pageRegistry.spec.ts`；信息改动运行相关布局测试，预览四态改动验证非 ready 态真实复用 `AppStateBlock` |
| 组件配置字段新增 / 修改 | `COMPONENT_FIELD_DEFS`、`componentSchemas.ts`、后端 `layout_config.py` 字段/值域/实例归属规则、脚手架和 `ComponentAutoSettings` 通用或专用安全渲染器、系统组件覆盖页、页面真实消费、DESIGN 字段治理入口 | `component-config-contract.spec.ts`、`componentConfig.spec.ts`、后端 layout 测试；自动继承、实例适用性、default/page/user 合并、保存/回显、策略收紧、越权、类型与值域验证 |
| 页面消费已有字段 | slot、`componentMeta`、字段消费、策略接线与会话状态；字段定义遵循 DESIGN §7.3 | `pageRegistry.spec.ts`：自动继承、适用性、策略接线、正向消费及禁止页面直写；页面交互验证 |
| 真实复用组件（全局 / 业务域） | 组件文件、DESIGN 真实复用组件清单、至少一个实际消费页面；业务域组件明确业务边界；需要配置化时再同步系统组件种类/字段事实源 | 组件/消费页测试、对应页面交互验收；涉及页面布局时做关键视口 |
| 按钮 / 图标操作体系 | `buttonStates.css`、`global.css`、`AppIconButton` / `AppCloseButton`、消费者及 DESIGN 按钮角色/状态矩阵 | `check:close-controls`、`button-system.spec.ts`、`interaction-color-consumers.spec.ts`、消费者测试；关闭入口见下方“共享控件的专项验证”，状态组合见“共享交互与边框状态” |
| 资产方案会话候选 | `AssetProfileSelect`、消费页详情/运行快照及 DESIGN 资产浏览契约 | `AssetProfileSelect.spec.ts`、消费页测试；浏览器复核列表/下拉、多个加载项、切回我的方案及再选、移除当前/未选中候选 |
| 操作行共同尺寸 | `controlRowSizing.ts`、`AppControlRow` / `AppTabToolbar` / `AppAdvancedSearch`、公共适配及 DESIGN 操作行规则 | `check:control-rows`、`AppControlRow.spec.ts`、`control-row-consumers.spec.ts`、`control-presentation.spec.ts`；混合控件、三档密度、动态尺寸、输入保留及浮层外框实测；详细覆盖见下方“共享控件的专项验证” |
| 分段选择状态 | `PageSegmented`、`useLayoutPreset.ts` 分段变量、`global.css` 及 DESIGN 分段矩阵 | `PageSegmented.spec.ts`、`useLayoutPreset.spec.ts`；contained neutral/primary 与 tabs、明暗底板/悬浮/按下、选中/禁用/焦点 |
| 提示 / 截断机制 | DESIGN 提示契约、AppHoverInfo / useHoverIntent、AppIconButton / AppActionHint、AppOverflowTooltipHost 及专用原文来源 | `check:tooltips`、提示/消费者测试；实际停留、移动、点击、键盘和主题验收；详细覆盖见下方“共享控件的专项验证” |
| 表单辅助说明 | `AppFormHelp`、真实组件登记、消费表单与响应式记录 | `AppFormHelp.spec.ts`、`formHelpContract.spec.ts`；横向标签、顶部标签表单及窄视口长说明实测 |
| 图表依赖 / 光标标签 | ECharts 锁定版本与 `patches/echarts+5.6.0.patch`、图表消费者及 DESIGN 图表契约；升级同步补丁 | `chartAxisPointerLabel.spec.ts` 几何回归、真实光标位置复核 |
| 基础表面 / 视觉预设 | `light` / `dark`、`themeSurfaces.ts`、预设目录与运行时消费者 | `presets.spec.ts`；预设能力变化验证后端目录、运行时选择及固定表面不受覆盖 |
| 字体 / 间距体系 | `global.css` typography/spacing token、DESIGN 排版与节奏规范；新增语义层级时同步 token、文档和消费点 | `check:design` 的 CSS 变量及控件间距门禁、相关样式契约测试、关键页面视觉验收；静态门禁不证明运行时继承或实际留白；详细覆盖见下方“共享控件的专项验证” |
| 滚动条与滚动容器 | DESIGN 滚动契约、`AppScrollArea`、Element Plus 适配与 `scrollbar.css`；迁移同步 viewport 引用、位置恢复、测高、成长布局和断言 | `check:scrollbars`、显隐/清理/消费者测试；悬停、键盘、滚动、拖出与低高度实测，不新增局部显隐 E2E；详细覆盖见下方“共享控件的专项验证” |
| 基础密度与一键统一 | `LayoutHost`、`useRemoteLayoutConfig`、`pageDensitySync`、`PageDensitySyncSettings`、registry 与 `layout/user-density` | 配置保留、事务回滚、账号/租户隔离、缓存/在途请求/后续逐页编辑；代表性页面、三档密度和浮层实测 |
| 全局界面比例 | 显示比例策略、`useDisplayScale`、`displayScaleProfiles`、`sizeProfileMatching`、`useLayoutViewport`、`displayScaleGeometry`、全局偏好、根画布/遮罩及第三方补丁 | 尺寸档案/坐标换算/真实组件交互单测、尺寸断点契约、补丁安装校验；分隔条/图表/滚动恢复与 Teleport 浮层实测 |
| 共享交互状态 | `global.css`、`borders.css`、`design-contracts.json` 的状态/变量/角色、消费者与 DESIGN 契约 | `check:contracts`、`design-contract-gates.spec.ts`；键盘/选择/嵌套操作/禁用测试及明暗焦点/悬停实测 |
| 规范规则 / 检查器变更或漏检修复 | 设计规则按[设计规范变更与门禁覆盖](#设计规范变更与门禁覆盖)维护实际映射；其他规则接入所属领域门禁 | 既有漏检先用最小夹具复现，再确认修复后被拒绝；真实消费者与统一入口按影响复核 |
| 共享边框与中性选择 | `themeSurfaces.ts` 的边框/选择变量、`useLayoutPreset.ts`、`borders.css`、`design-contracts.json::segmentedRoles`、消费者与 DESIGN §4/§6 | 按下方「共享交互与边框状态」覆盖配方、层叠、宿主及组合状态 |
| 品牌字标 / 主题强调色 | `BrandMark.vue`、`useLayoutPreset.ts`、登录页/应用外壳及 DESIGN 品牌规则 | `BrandMark.spec.ts`、`useLayoutPreset.spec.ts`；登录页与工作台同模式同预设实测 |
| 页面浮层 | `#overlays`、`AppDialog` / `AppDetailDrawer` / 专用 `PageDrawer` / `PageSettingsDrawer`、唯一浮层类；新增公共能力时同步 DESIGN 组件清单 | 统一组件测试、`layout-contract.spec.ts`、页面与顶部栏边界、正文内滚、关闭行为 |
| 纯业务偏好 | `usePageSettings`、页面业务态及设置抽屉业务选项 | 业务行为验证 |
| 基础控件与容器属性归属 | `design-contracts.json::styleRoles`、共享适配、布局所有者、DESIGN 属性职责；维护新增控件、专项登记和根包装继承 | `check:contracts` 的覆盖/失效登记/精确绑定检查、各家族合法与违规样例、all 重置及运行时精确授权；真实样板与代表性页面的字阶、尺寸、浮层、明暗主题和缩放 |
| 列表高级搜索 | `searchGroups.ts`、filter-bar slot / `commonFields`、`AppAdvancedSearch` 和 `ComponentAutoSettings`；接线见布局实现文档的“高级搜索字段与设置接线” | 阈值、动态权限回退、控件保留、摘要状态/明暗呈现、定位/清除、错误聚焦、保存失败重试；收展/常显替换不额外查询 |
| 键盘与焦点路径 | DESIGN 键盘契约、共享入口、消费点及快捷键的可见说明/可访问属性/权限/忙态守卫 | 原生/共享键盘行为测试；弹层、关闭恢复和 KeepAlive 焦点实测；详细覆盖见下方“共享控件的专项验证” |
| 共享动效 | DESIGN 动效契约、`global.css`、`directives/reveal.ts`、`WorkspaceRouteView` / `AppAsyncRegion` / `AppDataTable`、折叠组件和消费者 | 快速切换、刷新不重播、错误接管、减少动画、缓存页恢复；折叠保留编辑值和挂载语义 |
| 布局与偏好运行机制 | 布局实现文档、共享配置核心、前后端字段、自动渲染器、消费页、脚手架与专用偏好；按影响更新环境配置/比例策略 | 按下方「配置加载、保存与恢复」选择前后端测试并验证真实归属 |

## 专项验证方法

### 批处理与真实数据链路

全量批处理、超长参数列表、窗口/聚合 SQL 或明确规模门槛的改动，小夹具之外必须补代表性规模回归。阶段验收通过真实入口或等价规模覆盖输入加载、计算、落表及重跑结果；纯算法基准、Mock 响应和页面结果不能替代此链路。

质量修复验证入口：

- `backend/tests/test_quality_repair_parallel.py`：落库、复检及失败续跑。
- `backend/tests/test_quality_repair_scale.py`：真实 API 与规模回归，执行见[CI 专项](../architecture/continuous-integration.md)。

测试固定外部响应，耗时仅用于本地处理成本对比，不代表真实来源吞吐。

### 页面与响应式实测

新页面和布局改造默认临时复核 `1100×620`、`1366×768`、`1440×900`，涉及宽屏分栏再覆盖 `1920×1080`；局部改动只复核受影响状态和断点。新增断点检查临界两侧，采用不同界面比例时确认仍按布局尺寸触发。覆盖代表性长名称、多条件、大总数以及加载、空、错误态，观察核心操作可达、无整页溢出、展开/恢复不丢筛选与草稿，记录实际视口、界面比例、结果及缺口。CSS 几何由浏览器验证，jsdom 和响应式画像登记不能代替实测。

新增/删除 Vue 文件或改变 CSS 查询时，在 `frontend/` 执行 `npm run docs:responsive` 同步 `responsive-components.md` 自动列，并人工核对降级、恢复及消费者；更新[页面验收记录](../configurable-layout-system/responsive-pages.md)中受影响页面的摘要行与对应详情，保留日期、视口、实际输入与结果及覆盖缺口。实施和实测完成后，才将源码中的 `responsive-review-pending` 整段替换为具体响应式说明与验证结论；手写页面同样适用。

`check:responsive` 检查源码一致性及待补项，`responsive-inventory.spec.ts` 检查记录与同步器边界；`typography-spacing-system.spec.ts` 扫描全部 Vue/CSS 尺寸媒体查询（含范围语法），`layout-contract.spec.ts` 覆盖主体高度、入口和分页。新增降级行为补触发、恢复及状态保留的最低层边界测试，JS 阈值和业务优先级由定向测试与人工实测确认。复用已有响应式布局与组件，不新增平行配置。

### 共享控件的专项验证

`check:contracts` 同时执行输入与选择容量检查，覆盖静态/动态宽度、语义档位、私有 CSS、导入别名、根包装器、单控件包裹层及多选容量覆盖；`control-width-contract.spec.ts` 维护合法与违规样例、真实消费者和空态入口。宽度 token 与表内容量估算保持一致，日期时间范围等复合几何在共享组件持有。改动后浏览器复核长内容、受限容器、表内分组换行及日期浮层，不能用静态通过代替实际宽度和内容可达性。

金额数字输入的真实库回归运行 `npx vitest run src/components/__tests__/MoneyInputNumber.spec.ts`：覆盖格式化录入后失焦与加减的显示/模型一致性，以及手数切金额时可访问上下限的同步和移除。Element Plus 的对应兼容修复维护在锁版本补丁中，ESM/CJS 同步；升级时复核用例和补丁安装，不能在各页面分别处理失焦回填。

执行 `npm run check:typography`：解析全部生产 Vue/CSS/TS，检查字体变量定义、角色类型、别名循环、CSS 简写、模板内联样式、脚本字体对象及 HTML tooltip 样式；品牌例外不豁免整个文件。`npm run build` 自动先执行该守卫。

`typography-audit.spec.ts` 以违规夹具证明拦截有效；`typography-spacing-system.spec.ts` 保留语义组件、导航、微字号选择器和间距契约；`chartTypography.spec.ts` 验证图表真实读取 CSS token。

静态守卫不能代替浏览器的层叠、裁切和继承检查。全局字体变更还需生产构建，并用内置浏览器抽查导航、数据指标、长说明、表格、抽屉及图表；记录实际状态，不把未打开的页面或设备写成实测通过。

校验入口为 `npm run check:close-controls`（构建门禁同时执行），检测直接手写关闭图形、缺少名称和私有视觉配方；允许危险删除与非交互预览图形。交互、离开拦截和焦点恢复由定向组件测试覆盖，明暗主题的实际命中区、裁切与状态须在内置浏览器复核，源码扫描不能替代页面验收。

门禁 `npm run check:control-rows` 使用模板 AST 与 PostCSS 检查独立尺寸、绑定高度和局部覆盖，并覆盖行外常规入口、普通表单/设置字段尺寸继承、共享买卖方向操作插槽与分段控件宽度（含业务类、内联样式、动态绑定及媒体/容器查询），构建同时执行；动态样式无法确认时要求收口。静态检查不证明最终几何一致，必须在代表性真实控件组合与页面按主题、密度和换行边界验证实际外框，同一缩放下归一化高度差不超过 1px，并检查焦点、禁用、加载和输入保留。

`npm run check:tooltips` 按 Vue/TS AST 检查原生/透传 title、旧自动接口、图标名称及直接包裹的重复提示，已接入生产构建；组件标题、插槽和 iframe 名称不误报。定向测试覆盖图标默认提示、文案覆盖与动态更新、显式豁免、关闭例外、真实截断、禁用原因、焦点/鼠标区分、点击关闭及监听清理；内置浏览器复核实际主题、位置和消失行为。

`npm run check:scrollbars` 是构建门禁，检查未接入的原生滚动区、私有显隐样式及消费方覆盖参数；行为、真实库组件和资源清理由定向 Vitest 覆盖。临时内置浏览器复核正文、表格、抽屉和导航的实际进出、滚动与拖动，不能只用样式文本断言替代交互验收。

新增/修改键盘入口须验证：鼠标与键盘等价、焦点可见、输入法与组合键不误触、禁用/忙态/权限一致、子控件不冒泡激活、弹层优先、缓存页面不残留监听。语义和事件用定向 Vitest 验证；真实焦点移动与滚动由内置浏览器复核。

### 共享交互与边框状态

按钮改动先核对链接、命令、选择和静态标签角色，再检查 scoped 与子文字样式覆盖；在实际明暗背景及代表性浮层复核颜色、焦点、选中、禁用和加载。不能以 class 存在或静态门禁通过替代真实呈现。

DESIGN 动效章节登记的共享交互角色变化时，按各角色适用边界选择受影响消费者，定向测试覆盖选择与嵌套点击边界、禁用和共享角色消费；内置浏览器复核明暗主题、普通/悬停/按下/选中/焦点状态及滚动边界，未能模拟的输入媒体偏好需注明静态契约验证范围。

`check:borders` 经 `check:design` 接入测试与构建，检查全量 Vue/CSS 中的普通游离圆角、边框直写颜色及页面私改输入边界；追踪 `AppWorkspacePane` / `.app-surface` 宿主中的股票画布，穿透异步与插槽层检查显式 `embedded`，独立弹层重置宿主作用域。

`presets.spec.ts` 验证首屏兜底，`useLayoutPreset.spec.ts` 验证预设映射，`PageSegmented.spec.ts` 与交互消费者测试验证字重层叠。`borderContract.spec.ts` 覆盖表面配方、分段角色正反例、全量消费者扫描，以及删除嵌入声明后必须失败的变异；`StockChartWorkspace.spec.ts` 使用真实宿主、异步层、画布和生产边框样式验证嵌入/独立外沿及模式切换。受影响组件和页面还须复核明暗模式下错误叠加焦点、选中叠加禁用、loading 和宿主边界。

系统组件详情的 `BorderStatePreview` 可核对真实控件组合态、详情 1/2/3 列及结果三态；样板不请求或保存业务数据，只证明当前样板，不能替代消费页面验收。

### 配置加载、保存与恢复

按变化所在入口选择测试：分层核心使用 `merge.spec.ts`、`useLayoutConfig.spec.ts`、`componentConfig.spec.ts`；远端与会话使用 `useRemoteLayoutConfig.spec.ts`、`useUserPreference.spec.ts`、`useDrawerPreferences.spec.ts`、`useDefaultedSessionValue.spec.ts`、`useComponentPageSizeSession.spec.ts`；设置接线使用 `PageSettingsDrawer.spec.ts`、`pageRegistry.spec.ts`；预设使用 `presets.spec.ts`、`useLayoutPreset.spec.ts`。

后端对应 `test_layout_config.py`、`test_layout_density_sync.py`、`test_stage4_layout.py`、`test_user_preference.py`。覆盖水合前编辑、分层来源、非法值及策略收紧、保存失败、回读和恢复。PG 内容、跨设备同步、并发时序与归属隔离需按实际风险取真实证据，本地 fallback 不能证明远端保存或隔离成功。

## 环境、数据与服务保护

- 调试目标、运行档案和环境变量按 AGENTS 的环境识别要求核对；只读文档/本地静态检查不要求启动服务。固定调试账号选择最小权限，不用系统管理员替代普通权限边界；pytest 使用用例内临时用户，不依赖固定调试账号。
- 跑后端测试前判断是否可能访问 `data/ai_stocks.duckdb`。CI 专用执行器已在导入应用前设置独立三库和临时路径，按 CI 专题管理资源，不需停日常后端；直接 pytest 或其他可能访问业务库的入口，启动 FastAPI、触发 DuckDB 初始化、访问行情/数据管理/布局接口、异步任务、采集、质检、回测或任何可能取文件锁的链路，必须先执行 `./start.sh status`，保存可信运行模式/参数，再通过 `./start.sh stop` 停掉运行中的后端；后台持锁时不得硬跑。脚本停服失败时不裸杀进程，除非用户明确同意。
- 成功、失败或中断后恢复原状态：原本运行则通过 `./start.sh` 按保存的可信模式、参数与环境恢复，再执行 `./start.sh status` 确认 `/api/health=200`；原本停止则保持停止。不能固定按 dev 重启，清理或恢复失败须报告。
- PG 测试使用隔离身份和精确清理；涉及平台级菜单、功能点、角色授权或 `app_config` 时使用随机临时身份，禁止删除、重建或改写真实内置菜单/功能点。无法命名空间隔离的全局表必须使用独立测试库，不能对共享开发库全表删除后回填或用写死默认值“恢复”。执行前检查夹具实际写入范围，不因 fixture 名为 test 就假定已隔离。
- 日常前端为 `5173`，截图/交互验证使用专用 `5181`，不得抢占日常端口。临时复核默认使用 AI 内置浏览器，可用可见文本定位；临时定位方式不直接沉淀为长期 E2E 选择器。未经明确指定或同意使用其登录会话，不连接个人 Chrome/Edge。内置浏览器不可用时先说明，不自动换工具；普通临时复核无需 E2E 写开关或登录限流豁免。
- 物理 E2E 写入、PG 实时指纹、DuckDB 独占锁、账号、数据前缀、安全开关与失败恢复由 E2E 专用 runner 管理；执行前满足专项生命周期的环境、目标与独占锁前提。
