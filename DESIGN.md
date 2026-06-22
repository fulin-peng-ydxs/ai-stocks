# DESIGN.md — 复盘啦 前端设计与布局规范

> 本文是前端的**地图/索引**：新建或改造页面前先读这里，按它指到具体代码与原型。
> 单一事实源分工：**强制规则在代码**（`frontend/src/layout/` 的校验器与注册表，违规即拒）；本文只描述「有哪些、选哪个、去哪找、注意什么」，不复述规则细节，避免漂移。
> 视觉 token（配色/字体/间距）见 `frontend/src/styles/global.css` 的 CSS 变量；本文当前聚焦**布局系统**，视觉 token 章节可后续用 `project-design-md-generator` 补全。

---

## 1. 布局系统总览

布局走**可配置布局系统**（`frontend/src/layout/`）：页面声明一份 `PageLayout` schema，交给 `<LayoutHost>` 渲染，**不再手写 `.v-page`/`.v-grow`/高度**。三层模型：

| 层 | 内容 | 可变性 | 落点 |
|---|---|---|---|
| L1 布局原型 | 列表/主从/仪表盘/表单/详情/工作台/向导 | 开发期选定、用户确认、运行期锁死 | 代码默认 schema |
| L2 布局参数 | 密度、断点列数、组件最低高宽… | 受限档位 + 白名单 + 取值域校验 | localStorage `ai-stocks:layout:<pageKey>` |
| L3 组件偏好 | 分页大小、排序、字段显隐/列宽 | 自由 | localStorage（`usePageSettings`） |

「可改不能乱改」= L1 锁死 + L2 `editable` 白名单经 `coerceEditableValue` 守门 + 合并后整体过 `validateLayout`，非法回落默认。

---

## 2. 新建一个页面（固定 7 步）

1. 判断业务页面类型 → 用 §3 决策流程选一个**原型**。
2. 把推荐原型 + 理由告诉用户，确认后再开发（守 CLAUDE.md「关键方案先确认」）。
3. 用 `createLayout(archetype, pageKey)` 起一份默认 `PageLayout`，按需覆盖 `slots`/`editable`/`responsive`。
4. 模板用 `<LayoutHost :layout="...">` + 具名插槽（`slot.id`）填业务组件；弹窗/抽屉放 `#overlays`。
5. 跑校验：`npm test`（validator 单测）+ DEV 期 LayoutHost 会 `assertLayout`，不合规直接抛。
6. `npm run build`（含 vue-tsc 类型检查；改 `frontend/src` 后必构建）。
7. 在本文 §7「已迁移页面」登记该页选用的原型与可编辑旋钮。

样板参考：`frontend/src/views/BoardView.vue`（列表原型，端到端跑通）。

---

## 3. 原型清单与决策流程

原型预设见 `frontend/src/layout/archetypes.ts`（A~G，开箱即合规）。

| 原型 | 适用 |
|---|---|
| `list` 列表页 | 筛选/批量 + 一张主表（最高频） |
| `master-detail` 主从页 | 左列表 + 右详情，两栏各自内滚 |
| `dashboard` 仪表盘 | KPI 卡 + 图表网格，平级块可重排多列 |
| `form` 表单页 | 标题吸顶 + 字段区内滚 + 按钮吸底 |
| `detail` 详情页 | 摘要/操作吸顶 + 分区内容内滚 |
| `workbench` 工作台 | 参数区固定 + 混合成长区（固定分析块 + 主表） |
| `wizard` 向导页 | 步骤条吸顶 + 内容内滚 + 导航吸底 |

**决策流程**（原规范 §2 的判断逻辑）：
1. 这屏有没有「操作→内容」上下级关系？有 → 顶部固定操作区 + 下方主内容区（`hasActionRegion:true`）；没有（平级面板）→ `hasActionRegion:false`。
2. 数清主内容区组件个数与各自业务最低高宽（见 §4 目录）。
3. 各最低尺寸之和 ≤ 可用空间 → 富余给主表/主图 grow；否则进兜底阶梯：内部滚动 → 满足三条件才重排多列 → 整区滚动兜底（不可跳级）。

> ⚠️ 单个体量很大的列表/表格**不要**重排——重排省不了它本身的高度，直接走内部滚动。

---

## 4. 组件最低尺寸目录

权威值在 `frontend/src/layout/components.ts` 的 `COMPONENT_CATALOG`（每种组件的 minW/minH、默认滚动归属、能否成主表、能否重排）。slot 显式覆盖尺寸时**不得低于目录下限**（校验器拦）。改目录值 = 改全站布局下限，属规范级变更。

---

## 5. 主内容区策略（LayoutHost 自动选择）

| 策略 | 触发 | 落点 |
|---|---|---|
| `grow` | 单组件、非整区滚动型 | `.v-grow`（表体内滚、表头吸顶） |
| `scroll` | 单组件整区滚动型 / 多组件无主表 | `.v-scroll` |
| `mixed` | 多组件且恰一个 `growMain` | `VMixedGrow`（固定块 + 主表内滚，规范 §4-F） |
| `columns` | 多组件且 `allowReflow` | `VColumns`（ResizeObserver 按容器宽取列数，规范 §5） |

---

## 6. 落地坑（务必注意）

- **teleport + scoped 样式陷阱**：`el-dialog`/`el-drawer` 默认 teleport 到 `<body>`，弹层根**不带组件 `data-v-` 作用域属性**。在 `scoped` 块里用「自定义类前缀」给库内部元素（`.el-drawer__body`/`.el-dialog__body`）写样式**永不匹配、静默失效**。正解：给弹层传唯一自定义类，把针对库内部元素的规则放**非 scoped** `<style>` 块。
- **混合成长区 ≠ 整区滚动**：「固定分析块 + 一张主表」用 `mixed`（主表 `min-height` + 表体内滚），不要用 `.v-scroll` 整体滚动——否则分页选 50/100 会把页面撑下去、主表被挤到不足最低高。
- **flex 链路 `min-height:0`**：所有滚动祖先要带 `min-height:0`，否则 flex 子项无法收缩、溢出而非内滚。
- **禁视口硬编码高度**：不写 `height:calc(100vh - Npx)`；高度由 flex 链路传导（LayoutHost 已兜住）。

---

## 7. 已迁移页面登记

| 页面 | 原型 | 可编辑旋钮（L2） | 备注 |
|---|---|---|---|
| `BoardView`（每日榜单） | `list` | `density` 信息密度 | M2/M3 样板，端到端跑通；原 L3「紧凑表格」已收敛进 L2 密度 |

> 其余页面（`StocksView`/`ScreenView`/`BacktestView`/`OverviewView`/`ConfigView`/data 子页…）仍手写 `.v-page`/`.v-grow` 契约，按批次渐进迁移。`OverviewView` 这类「双列双成长表」需先扩展渲染器（columns-of-grow）再迁。

---

## 8. 代码位置

- 类型/原型/目录/校验：`frontend/src/layout/{schema,archetypes,components,validator,path}.ts`
- 渲染器：`frontend/src/layout/components/{LayoutHost,VMixedGrow,VColumns}.vue`
- L2 覆盖层：`frontend/src/layout/useLayoutConfig.ts` + 自定义面板 `LayoutSettingsSection.vue`
- 全局契约样式与密度类：`frontend/src/styles/global.css`（`.v-page/.v-grow/.v-scroll/.lh-density-*`）
- 设计与规划文档：`agent-works/configurable-layout-system/plan.md`
- 历史原理稿（待全部迁完后退场）：`ai-agent/前端布局自适应规范.md`
