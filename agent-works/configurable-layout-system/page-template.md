# 新页面开发模板与选型清单（AI 固定流程）

> 本文是「把页面交给 AI 开发」的固定抓手：照此选型、声明、填充、校验、登记，减少随机 CSS / 随机滚动 / 随机布局层级。
> 强制规则在代码（`frontend/src/layout/` 校验器 + 契约测试），本文只给流程与可复制骨架。前端规范事实源是 [DESIGN.md](../../DESIGN.md)。

## 0. 开工前必读

1. 读 [DESIGN.md](../../DESIGN.md) §1~§8（三层模型、7 步、原型清单、组件目录、主区策略、预设、组件特性缺口、落地坑）。
2. 读 `frontend/src/layout/archetypes.ts`（原型预设）和 `frontend/src/layout/components.ts`（组件能力目录）。
3. 守 [AGENTS.md](../../AGENTS.md) 的协作约束：原型与组件清单选定后，先给用户推荐 + 理由再开发。

## 1. 固定七步

1. 判断业务页面类型 → 按 §2 决策选一个**原型**。
2. 把推荐原型 + 理由告诉用户，确认后开发。
3. 优先运行 `npm run scaffold-page -- --pageKey <key> --label <中文名> --archetype <原型>` 生成骨架；需要手写时再用 `createLayout(archetype, pageKey)` 起默认 `PageLayout`，按需覆盖 `slots`/`editable`/`responsive`。
4. 模板用 `<LayoutHost :layout="effective">` + 具名插槽（`slot.id`）填业务组件；弹窗/抽屉放 `#overlays`。
5. 跑校验：`npm test`（validator + 契约测试）；DEV 期 `LayoutHost` 会 `assertLayout` 直接抛。
6. `npm run build`（含 vue-tsc 类型检查；改 `frontend/src` 后必构建）。
7. 在 DESIGN.md §9「已迁移页面登记」补一行，并填写下方 §6 登记块。

## 2. 开发计划页面设计块（复制到计划里）

涉及新页面，或改造既有页面的布局、组件、设置抽屉、表格、弹窗/抽屉、页面设置入口时，开发计划必须包含本节；只改后端、接口、文案或不影响布局的业务逻辑时，在计划里写明“不涉及前端页面设计闭环”。

```md
## 前端页面设计闭环

### 页面定位
- 页面类型：
- 用户主流程：
- 是否新页面：
- 是否改造已有页面：

### 布局选型
- 选用原型：list / master-detail / dashboard / form / detail / workbench / wizard
- 选择理由：
- 是否需要新增布局原型：否 / 是，原因：

### Slot 与组件设计
| 区域 | slotId | 组件种类 | 是否 growMain | 滚动归属 | 是否可重排 | 说明 |
|---|---|---|---|---|---|---|
| action |  |  | 否 |  | 否 |  |
| main |  |  |  |  |  |  |
| overlay | settings | settings-drawer | 否 |  | 否 | 页面设置 |

### 空状态设计
- 表格空态：使用全局 `el-table` 空态；如需业务文案只写 `<template #empty>` 文案，不自绘图标。
- 非表格空态：按容器大小使用 `app-empty` / `app-empty--compact` / `app-empty--tiny` / `app-empty-inline`。
- 重复检查：同一区域不能同时渲染表格默认空态和额外 `el-empty`。

### 配置设计
| 类型 | 字段 | 层级 | 落点 | 说明 |
|---|---|---|---|---|
| 布局旋钮 | density | page/user | editable | 信息密度 |
| 组件设置 |  | preset/page/user | COMPONENT_FIELD_DEFS |  |
| 页面记忆 |  | usePageSettings | 业务选项 |  |

### 复用与新增判断
- 复用已有布局：
- 复用已有组件：
- 是否新增组件种类：
- 是否新增组件配置字段：
- 是否新增页面专属业务态：

### 维护清单
- pageRegistry：
- COMPONENT_CATALOG：
- COMPONENT_FIELD_DEFS：
- componentSchemas：
- 后端 layout_config 字段规则：
- componentPreview：
- DESIGN.md §9：
- 测试：

### 验收
- cd frontend && npm test
- cd frontend && npm run build
- 视口验证：1100×620 / 1366×768 / 1440×900
- 检查无整页滚动、无视口高度硬编码、设置抽屉分段正常
```

如果计划声明“新增布局原型 / 组件种类 / 组件配置字段”，但没有维护清单，计划视为不完整，不能直接进入开发。

## 3. 组件 / 布局维护矩阵

| 变更类型 | 必须同步维护 | 必须验证 |
|---|---|---|
| 新页面 | 脚手架、`pageRegistry.ts`、`router/index.ts`、`DESIGN.md §9` | `pageRegistry.spec.ts`、`layout-contract.spec.ts`、build、关键视口 |
| 新布局原型 | `archetypes.ts`、`schema.ts`、`validator.ts`、`LayoutHost.vue`、DESIGN 原型说明 | `validator.spec.ts`、布局契约测试 |
| 新组件种类 | `COMPONENT_CATALOG`、`componentSchemas.ts`、`componentPreview.ts`、系统组件页展示 | `componentPreview.spec.ts`、`pageRegistry.spec.ts` |
| 新组件配置字段 | `COMPONENT_FIELD_DEFS`、`componentSchemas.ts`、后端 `layout_config.py`、页面真实消费、DESIGN 字段表 | `componentConfig.spec.ts`、后端 layout 测试、保存/回显验证 |
| 页面消费已有字段 | `pageRegistry.consumedComponentFields`、`componentMeta`、页面读取/写入逻辑 | `pageRegistry.spec.ts`、页面交互验证 |
| 纯业务偏好 | `usePageSettings` / 页面业务态，放入「业务选项」并标注「页面记忆」 | 业务行为验证、必要时 build |

新增可配置能力必须同时具备三个事实源：组件能力事实源（`COMPONENT_CATALOG`）、字段配置事实源（`COMPONENT_FIELD_DEFS`）、页面消费事实源（`pageRegistry.consumedComponentFields` / `componentMeta`）。禁止新增页面不读取的“假配置”；禁止绕过 `LayoutHost`、绕过 `pageRegistry` 或另建并行配置体系。

## 4. 原型决策

| 原型 | 选它当… |
|---|---|
| `list` | 筛选/批量 + 一张主表（最高频） |
| `master-detail` | 左列表 + 右详情，两栏各自内滚 |
| `dashboard` | KPI 卡 + 图表网格，平级块可重排多列 |
| `form` | 标题吸顶 + 字段区内滚 + 按钮吸底 |
| `detail` | 摘要/操作吸顶 + 分区内容内滚 |
| `workbench` | 参数区固定 + 混合成长区（固定分析块 + 主表） |
| `wizard` | 步骤条吸顶 + 内容内滚 + 导航吸底 |

判断要点：① 有「操作→内容」上下级关系 → `hasActionRegion:true`，否则 `false`。② 数清主区组件个数与各自最低高宽。③ 各最低尺寸之和 ≤ 可用空间 → 富余给主表/主图 grow；否则走兜底阶梯：内部滚动 → 满足三条件才重排多列 → 整区滚动（不可跳级）。单个大表**不要**重排。

## 5. PageLayout 骨架（列表页示例）

```ts
import { useLayoutConfig, type PageLayout } from '@/layout'

const pageLayout: PageLayout = {
  pageKey: 'my-page',          // 与 usePageSettings 同源，便于偏好聚合
  archetype: 'list',
  hasActionRegion: true,
  density: 'standard',
  responsive: { allowReflow: false, breakpoints: [{ minWidth: 0, columns: 1 }] },
  slots: [
    { id: 'filters', component: 'filter-bar', region: 'action', order: 1 },
    { id: 'table', component: 'data-table', region: 'main', growMain: true, minH: 360, order: 1 },
  ],
  editable: [
    { path: 'density', label: '信息密度', type: 'enum', options: ['compact', 'standard', 'comfortable'] },
    { path: 'slots.table.minH', label: '主表最低高', type: 'int', min: 300, max: 760 },
  ],
}

const { effective, knobs: layoutKnobs, valueOf, sourceOf, setKnob } = useLayoutConfig(pageLayout)
```

## 6. 模板骨架

```vue
<template>
  <LayoutHost :layout="effective">
    <template #action> <!-- 筛选/批量/工具栏，固定不滚；多个固定块用 <div class="lh-action"> 包一层 --> </template>
    <template #main>   <!-- 主表/主图/主列表 --> </template>
    <template #footer> <!-- 可选：固定底部批量条/购物车条（选择跨页累积）；纯渲染槽，不入 schema --> </template>
    <template #overlays>
      <!-- el-dialog / el-drawer 放这里；给唯一自定义类，针对库内部元素的样式放非 scoped <style> -->
      <PageSettingsDrawer>
        <LayoutSettingsSection :knobs="layoutKnobs" :value-of="valueOf" :source-of="sourceOf" :set="setKnob" />
      </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>
```

> 多组件主区（mixed/columns）按 `slot.id` 具名放置：`<template #<slotId>>…</template>`。参考端到端样板 `frontend/src/views/BoardView.vue`。

## 7. 验收红线（机制性强制，违反则 `npm test` 失败）

- 不得新增视口硬编码高度（`height:/min-height: …vh` 或 `calc(…vh)`）——`layout-contract.spec.ts` 扫描 `src/views` 拦截。`max-height: …vh` 仅限弹层安全上限。
- 新页面不得绕过 `LayoutHost` 手写 `.v-page/.v-grow/.v-scroll`——契约测试拦截（存量白名单仅供迁移过渡）。
- 不得使用未登记组件种类——`validateLayout` 拦截。
- 不得把页面业务结构放进用户级配置；不得把不可重排的大表放进多列重排——`validateLayout` 拦截。
- 列表交互：分页/排序走服务端、筛选变更自动触发、多选跨页累积（见 [DESIGN.md](../../DESIGN.md) 交互规则）。
- 空状态：表格走全局空态；非表格使用 `app-empty*` 统一类名，不新增页面私有空态样式。

## 8. 页面登记块（填好贴进 DESIGN.md §9 表格）

```text
| 页面 | 原型 | 组件清单 | 可编辑旋钮(L2) | 已验证视口 | 备注 |
| <PageView>（中文名） | <archetype> | <region>:<kind>… | <path> … | 1100×620 / 桌面 | … |
```

填写示例：

```text
| BoardView（每日榜单） | list | action:filter-bar / main:data-table(growMain) | density | 1100×620 / 1440 | L3「紧凑表格」已收敛进 L2 密度 |
```

## 9. 7 个原型可复制骨架

> 推荐先用脚手架生成，再按以下原型补业务内容：
>
> ```bash
> npm run scaffold-page -- --pageKey demo-list --label "示例列表" --archetype list --route /demo/list --view DemoListView
> ```

### 9.1 list

```bash
npm run scaffold-page -- --pageKey my-list --label "列表页" --archetype list --route /my-list --view MyListView
```

结构：`action:filter-bar` + `main:data-table(growMain)`。适合筛选、批量操作和一张主表；主表内部滚动，不做多列重排。

### 9.2 master-detail

```bash
npm run scaffold-page -- --pageKey my-master-detail --label "主从页" --archetype master-detail --route /my-master-detail --view MyMasterDetailView
```

结构：`action:filter-bar` + `main:data-table` + `main:detail`。适合左侧列表、右侧详情；两栏各自承载滚动，不把详情塞进弹窗替代主流程。

### 9.3 dashboard

```bash
npm run scaffold-page -- --pageKey my-dashboard --label "仪表盘" --archetype dashboard --route /my-dashboard --view MyDashboardView
```

结构：`main:kpi-grid` + `main:chart`。适合 KPI、图表和概览面板；只对平级块做安全重排，单个大表仍走内滚。

### 9.4 form

```bash
npm run scaffold-page -- --pageKey my-form --label "表单页" --archetype form --route /my-form --view MyFormView
```

结构：`main:form`。适合创建/编辑页；字段区内滚，提交按钮应固定在表单语义尾部或 footer，不写视口高度。

### 9.5 detail

```bash
npm run scaffold-page -- --pageKey my-detail --label "详情页" --archetype detail --route /my-detail --view MyDetailView
```

结构：`main:detail`。适合摘要、分区详情和审阅页；长内容由详情区内滚，关键操作放 action 或详情吸顶区。

### 9.6 workbench

```bash
npm run scaffold-page -- --pageKey my-workbench --label "工作台" --archetype workbench --route /my-workbench --view MyWorkbenchView
```

结构：`action:toolbar` + `main:section`。适合参数区固定、结果区混合成长的分析工作台；固定分析块和成长表放在主 section 内组织。

### 9.7 wizard

```bash
npm run scaffold-page -- --pageKey my-wizard --label "向导页" --archetype wizard --route /my-wizard --view MyWizardView
```

结构：`main:steps`。适合多步骤流程；步骤条稳定展示，当前步骤内容内滚，导航按钮保持在流程底部。
