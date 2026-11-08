# 页面开发模板与选型清单

本文用于新建或改造页面的选型、设计说明与接线。布局原型（archetype）是 `list` 等生产布局类型，评审原型是 HTML／结构图产物；选择前者不要求先制作后者。共享入口变化时同步示例。

参考：[设计规则](../../DESIGN.md) · [配置运行机制](../architecture/frontend-layout.md) · [验证与总维护清单](../testing/guide.md) · [菜单与权限接入](../architecture/system-rbac-tenant.md#新页面接入菜单和权限)。

## 1. 实施流程

新页面执行适用步骤；既有页面仅处理受影响部分，不重新选择未变化的布局原型或重复登记。布局原型和组件能力分别以 `frontend/src/layout/archetypes.ts`、`frontend/src/layout/components.ts` 为准。关键方案存在实质取舍或交互不确定时，给出推荐与理由并确认；已有明确需求、适用方案或有效授权时直接实施，只暂停依赖未决事项的部分。

1. 按 DESIGN §5.2 选择布局原型，查真实复用组件清单与同类页面，按本文 §2 说明设计和必要例外。
2. 优先用 §6 脚手架生成。`data-scaffold-placeholder` 在接入真实组件与四态后删除；`responsive-review-pending` 在完成响应式设计和实测后替换为具体结论。手写页面同样添加响应式待验收标记，并以 `createLayout(archetype, pageKey)` 起默认布局，按需声明 slots、editable、responsive。
3. 按 §3–§4 接入 registry、`useRemoteLayoutConfig`、`LayoutHost` 同名 slot 与真实组件；浮层放 `#overlays`，表格复用 `AppDataTable + AppTableColumn`，按 DESIGN 声明列语义及成长/嵌入模式。
4. 按下方登记决策及总维护清单同步组件、配置、消费者、文档和测试。新增导航/API/受控按钮同步菜单、功能点、守卫、`v-permission` 和默认授权。
5. 核对路由、registry 与 DESIGN `page-registry` 的唯一同名行；脚手架会同步生成，手写时使用 §5 登记块。DEV 下 `LayoutHost` 调用 `assertLayout` 抛错必须解决，不能跳过布局校验。
6. 组合总维护清单的基础行与专项行完成验证，交付记录实际结果和缺口。

### 1.1 页面使用或新增组件的登记决策

先查 DESIGN「组件资产分层」及现有组件，再按本次用途判断；系统不会从 Vue 标签自动推断 kind。字段归属及适用性以 DESIGN §7.3 和「设置抽屉」为准。

| 本次用途 | 接入动作 |
|---|---|
| 已有组件承担独立布局、成长、滚动或配置能力 | 登记对应 kind 的 slot，由 LayoutHost 同名插槽承载并真实消费字段 |
| 仅为复合组件内部实现，无独立布局/配置语义 | 直接复用，不登记假 slot |
| 复合组件封装多个可配置实例或业务口径 | 按 DESIGN §7.3 接入复合组件与业务偏好契约，反查直接/间接消费者，避免整项漏登 |
| 新真实 Vue 组件 | 判断页面私有、业务域复用或全局复用；稳定复用单元维护组件清单、实际消费者和测试 |
| 需要布局平台识别的新能力 | 新增或关联系统 kind；只做 UI 复用时不新增 kind |
| 页面设置/布局需真实消费的新属性 | 按字段治理契约接入定义、schema、后端、安全渲染器和消费者；纯内部 props 不登记 |

说明本次采用的分类及维护项；局部变更可在会话中简述，不填写无关分类。

## 2. 页面设计说明

- **新页面和布局改造**：实施前使用下方模板，覆盖页面定位、布局与组件、响应式、四态、配置、复用和验证；仅填写实际存在的区域，关键例外说明理由。布局原型选择说明理由及是否需要新增；缺少正确性所需输入时注明缺项，只暂停依赖部分。
- **局部组件、样式或交互改动**：只说明受影响区域与契约、复用入口、需同步的维护项和验证范围；影响响应式时补充相应触发、恢复及状态保留设计。无需复制完整模板或逐项填写“不适用”。
- **不涉及页面呈现的改动**：不填写本节。

同一页面设计说明只保留一处，嵌入已有计划的所属任务或会话；已有独立方案时引用并补本次差异，不重复填写。只有用户或有效项目要求时才保存文件。

填写时按属性所有者区分布局、组件字段和业务偏好，补齐文案容量、常显字段说明、图标和帮助正文设计；响应式说明须给出核心内容的降级或可达路径，不能只写“自适应”。按总维护清单选取实际维护项及验证范围，已有入口未变时不重复登记。

```md
## 前端页面设计闭环

### 页面定位

- 页面类型：
- 用户主流程：
- 是否新页面：
- 是否改造已有页面：

### 布局选型

- 选用布局原型：list / master-detail / dashboard / form / detail / workbench / wizard
- 选择理由：
- 是否需要新增布局原型：否 / 是，原因：

### Slot 与组件设计

| 区域 | slotId | 组件种类 | 是否 growMain | 滚动归属 | 是否可重排 | 说明 |
|---|---|---|---|---|---|---|
| action |  |  | 否 |  | 否 |  |
| main |  |  |  |  |  |  |
| overlay | settings | settings-drawer | 否 |  | 否 | 页面设置 |

### 响应式设计

| 区域 / 组件 | 核心内容 | 辅助内容 | 尺寸来源与触发条件 | 换行 / 折叠 / 隐藏 / 抽屉 / 内滚 | 恢复入口与状态保留 |
|---|---|---|---|---|---|
| action / 筛选操作 |  |  |  |  |  |
| main / 主结果与分析 |  |  |  |  |  |
| footer / 分页 |  |  |  |  |  |
| overlay / 浮层 |  |  |  |  |  |

- 页面目标画像、实际断点、slot 最小尺寸与滚动所有者：
- 复用的响应式组件及消费点：
- 低高度时固定区和主内容的空间冲突如何解决：
- 宽屏富余分配给哪一主表 / 主图 / 概览：

### 四态反馈设计

| 状态 | 页面 / 组件处理 | 复用组件 / 样式 | 结论 |
|---|---|---|---|
| ready / 价值态 |  |  |  |
| loading / 加载态 |  |  |  |
| empty / 空态 |  |  |  |
| error / 异常态 |  |  |  |

- 四态切换、重试入口及必要例外：

### 控件、排版与主题

- 控件与操作：命令影响范围、主次/危险角色、所属工具区、共享组件及 loading / disabled / focus；提示、键盘和可访问名称：
- 表格、表单与浮层：共享入口、容量、尺寸档位、滚动与长内容承接：
- 字体、间距与密度：语义 token / 类、菜单标题入口、继承范围及必要特例：
- 主题或品牌变化（仅涉及此类改动时）：共享事实源、消费者与明暗模式验证：

### 配置设计

| 类型 | 字段 | 层级 | 落点 | 说明 |
|---|---|---|---|---|
| 布局旋钮 | density | page/user | editable / 基础布局 | 信息密度 |
| 布局旋钮 | slots.&lt;slotId&gt;.visible | page/user | editable / 模块显示 | 完整模块显隐 |
| 组件设置 |  | page/user | COMPONENT_FIELD_DEFS |  |
| 业务偏好 |  | usePageSettings | 业务选项 |  |

### 动效设计

- 页面与标准异步区域是否复用 `WorkspaceRouteView` / `AppAsyncRegion` / `AppDataTable` 的共享显现能力，避免页面再次叠加动画：
- 折叠是否复用 `SettingsGroup` / `AppSummaryDisclosureCard`，保持编辑值和原挂载语义：
- 本次动效改变的状态与消费者：

### 浮层设计

- 触发来源：页面 / 应用顶栏
- 浮层类型：dialog / 页面业务抽屉 / 页面设置抽屉 / 视口级全局抽屉
- 组件选型：`AppDialog` / `AppDetailDrawer` / 专用 `PageDrawer` / `PageSettingsDrawer` / 应用级 `PageDrawer boundary="app"`
- 承载边界：当前 `LayoutHost` 内容区 / 整个视口
- 滚动归属：抽屉正文内滚，页面不跟随滚动
- 关闭策略：关闭按钮 / 遮罩 / Esc / 完成动作后关闭
- Teleport 样式入口：唯一全局类或 `:global`

### 复用与新增判断

- 复用已有布局：
- 复用已有组件：
- 复用/新增真实组件：
- 是否为独立系统组件实例；若是，已有 kind 与 slotId：
- 若仅作为内部实现而不登记 slot，理由：
- 真实组件是否进入 DESIGN.md 清单：
- 是否关联系统组件种类：
- 是否新增组件种类：
- 是否新增组件配置字段：
- 是否新增页面专属业务态：

### 本次维护项

- 布局 / slot / kind / 字段 / 业务偏好的维护项：
- 新增或变化的真实组件及消费点：
- 页面登记、响应式说明与验收证据：
- RBAC：涉及导航、API 或受控动作时列出菜单、功能码、守卫及授权验证：

### 验收

- 总维护清单命中的改动类型与定向测试：
- 构建准入是否触发及结果：
- 真实入口与页面实测范围、观察结果、未验证项及必要例外：

```

## 3. PageLayout 骨架（列表页示例）

```ts
// pageRegistry.ts：页面结构与组件实例适用性事实源。
import type { PageLayout } from '@/layout'

const registryLayout: PageLayout = {
  pageKey: 'my-page',          // 与 usePageSettings 同源，便于偏好聚合
  archetype: 'list',
  hasActionRegion: true,
  density: 'standard',
  responsive: { allowReflow: false, breakpoints: [{ minWidth: 0, columns: 1 }] },
  slots: [
    { id: 'filters', component: 'filter-bar', region: 'action', order: 1 },
    {
      id: 'table',
      component: 'data-table',
      region: 'main',
      growMain: true,
      minH: 360,
      order: 1,
      config: { pagination: true },
    },
  ],
  editable: [
    { path: 'density', label: '信息密度', type: 'enum', options: ['compact', 'standard', 'comfortable'] },
    { path: 'slots.table.minH', label: '主表最低高', type: 'int', min: 300, max: 760 },
  ],
}
```

```ts
// 页面运行时：必须从 registry 取布局并使用远端入口，不能直接 useLayoutConfig 绕过
// page/user 层与管理员字段策略。
import { ref } from 'vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'

const pageKey = 'my-page'
const settingsOpen = ref(false)
const editOpen = ref(false)
const detailOpen = ref(false)
const pageLayout = getPageLayout(pageKey)
const {
  effective,
  resetAll: resetLayout,
  knobs: layoutKnobs,
  valueOf,
  sourceOf,
  layerValuesOf,
  setKnob,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  componentLayerValuesOf,
  componentAllowedLayers,
} = useRemoteLayoutConfig(pageLayout)

const drawerConfig = {
  knobs: layoutKnobs,
  valueOf,
  sourceOf,
  layerValuesOf,
  setKnob,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  componentLayerValuesOf,
  componentAllowedLayers,
}
```

## 4. 模板骨架

### 4.1 浮层选型

根据触发位置、内容容量和操作范围选择共享入口：

| 触发位置与用途 | 共享入口 | 计划中核对 |
|---|---|---|
| 破坏性确认 | `ElMessageBox` | 动作、对象、取消与失败恢复 |
| 短表单、单组编辑、轻量查看 | `AppDialog` | 内容容量、语义档位、提交状态 |
| 完整业务详情、长编辑、历史版本 | `AppDetailDrawer` | 四态、正文分区、关闭与草稿保护 |
| 实时日志、资产搜索、窄屏工作区回退 | 专用 `PageDrawer` | 专用交互模型及所属页面边界 |
| 页面设置 | `PageSettingsDrawer` | 自动配置/业务偏好归属、来源与重置 |
| 用户中心、视觉环境等应用级入口 | `PageDrawer boundary="app"` | 应用级覆盖边界与返回焦点 |

页面和应用外壳均不得直接使用 `el-drawer`，也不得直接消费 `PageDrawerSurface`。共享组件关系见 DESIGN 的真实组件清单；具体 props、插槽和实现以组件源码为准。

### 4.2 页面骨架

```vue
<template>
  <LayoutHost :layout="effective" :component-value-of="componentValueOf">
    <template #action> <!-- 筛选/批量/工具栏，固定不滚；多个固定块用 <div class="lh-action"> 包一层 --> </template>
    <template #main>   <!-- 主表/主图/主列表 --> </template>
    <template #footer> <!-- 可选：固定底部批量条/购物车条（选择跨页累积）；纯渲染槽，不入 schema --> </template>
    <template #overlays>
      <AppDialog v-model="editOpen" title="编辑名称" size="medium">
        <!-- 短表单或轻量查看 -->
      </AppDialog>

      <AppDetailDrawer v-model="detailOpen" title="业务详情" size="xl">
        <!-- 页面业务详情；长内容在抽屉正文内滚 -->
      </AppDetailDrawer>

      <PageSettingsDrawer
        v-model="settingsOpen"
        title="页面名称"
        :page-key="pageKey"
        :config="drawerConfig"
        @reset="resetLayout"
      />
    </template>
  </LayoutHost>
</template>
```

> 使用 `usePageSettings` 业务偏好的页面，需把其 reset 与 `resetLayout` 组合为同一重置函数并绑定 `@reset`；上述最小骨架未声明业务偏好；仅在有实际业务项时添加 `#business` 插槽。组件导入和业务字段由实际页面补齐；完整可运行的初始文件优先由脚手架生成。
> 多组件主区（mixed/columns）按 `slot.id` 具名放置：`<template #<slotId>>…</template>`。可参考已登记且通过契约测试的同原型页面。
> 业务代码不得直接使用 `el-dialog`、`el-descriptions` 或 `el-drawer`。Teleport 生成的内部 DOM 样式使用唯一全局类或 `:global`。

## 5. 页面登记块（填好贴进 DESIGN.md `page-registry` 表格）

```text
| pageKey | 页面 | 原型 | 可编辑旋钮 | 组件清单 |
| `<page-key>` | `<PageView>`（中文名） | `<archetype>` | `density` | action:`toolbar` / main:`section` |
```

## 6. 布局原型与脚手架

在 `frontend/` 下执行，替换 pageKey、中文名、布局原型、路由和 View 名，再接入真实业务内容：

```bash
npm run scaffold-page -- --pageKey research --label "研究页" --archetype list --route /research --view ResearchView
```

`--archetype` 取值及初始 slot 如下；选型遵守 DESIGN §5.2，脚手架只提供骨架。

| 布局原型 | 初始结构 | 业务接入要点 |
|---|---|---|
| `list` | action:filter-bar + main:data-table(growMain) | 筛选、批量操作与单张主表；表内滚动，不做多列重排 |
| `master-detail` | action:filter-bar + main:data-table + main:detail | 列表与详情双栏，各自内滚 |
| `dashboard` | main:kpi-grid + main:chart | KPI、图表与概览；仅平级块重排，大表内滚 |
| `form` | main:form | 创建/编辑；字段区内滚，提交固定在语义尾部或 footer，不写视口高度 |
| `detail` | main:detail | 摘要、分区与审阅；详情区内滚，关键操作放 action 或吸顶区 |
| `workbench` | action:toolbar + main:section | 固定参数区与混合成长结果；在主 section 内组织分析块和成长表 |
| `wizard` | main:steps | 多步骤；步骤条稳定，当前步骤内滚，导航位于流程底部 |
