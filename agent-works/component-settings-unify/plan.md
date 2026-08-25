# 组件特性渲染统一与折叠层级一致化

> 入口规范：[DESIGN.md](../../DESIGN.md) §4/§5.2/§7.3/§7.4、[page-template.md](../configurable-layout-system/page-template.md)。
> 触发**页面设计闭环**（改造既有「设置抽屉 / 页面布局编辑器」的组件特性渲染与折叠交互）。

## 背景与问题

「组件特性」（每个 slot 的 `defaultSort / pageSize / hiddenColumns` 等可调项）当前有**两套平行实现**，未复用：

| 场景 | 渲染组件 | 控件 | 折叠 |
|---|---|---|---|
| 运行时设置抽屉 | `components/ComponentAutoSettings.vue` | `PageSegmented` / `el-switch` / `SettingsGroup` | slot(level2) + 列显隐(level3) |
| 页面布局编辑器 | `layout/components/ComponentSettingsSection.vue` | `el-select` / `el-input-number` / `el-segmented` | （上轮加的 slot 级，但页面只显示一个 slot，无意义） |

由此产生三个用户反馈：
1. 抽屉里只有「列显隐」能折叠，「默认排序 / 分页」不能 —— 折叠是按"是不是多行组"零散贴的，没有按层级统一。
2. 页面布局里折叠"整个 slot"无意义 —— 编辑器一次只显示当前点中的一个 slot。
3. 两套不复用；折叠应按层级统一；深层级"内容比标题还高"，视觉层级倒挂。

## 目标

- **单一事实源**：组件特性渲染只保留一份，抽屉与页面布局编辑器共用。
- **折叠层级一致**：规则统一为「slot 是一个组；多行清单类特性（列显隐）作为可折叠子组；单字段为叶子不折叠」，两个场景行为一致。
- **视觉层级修正**：每层标题作为高于内容的小标题，字号随层级递减但不被自身控件压过。

## 页面设计闭环（DESIGN §5.2）

| 计划项 | 内容 |
|---|---|
| 页面定位 | 改造页面：运行时**页面设置抽屉**「组件设置」段 + 系统管理→布局配置→**页面布局**编辑器「组件特性配置」。主流程：用户/管理员按层级调组件展示能力。 |
| 布局选型 | 不改原型、不改 slot、不改页面业务结构。仅改组件特性的**渲染组件与折叠交互**。无新增原型。 |
| Slot 与组件设计 | 按 slot kind 自动继承 `COMPONENT_FIELD_DEFS`，再由 slot `config` 和 `componentMeta` 驱动实例适用性。 |
| 配置设计 | 不新增字段、不改字段层级。沿用 `slots.<id>.config.<field>` 四层合并；抽屉=user 层、页面布局=page 层。 |
| 复用与新增判断 | **删除** `ComponentSettingsSection.vue`；**泛化** `ComponentAutoSettings.vue` 为唯一共享渲染器（新增可选 props 适配 page 层 / 单 slot 聚焦 / 字段策略 / 高亮 / 清除），复用既有 `SettingsGroup`、`PageSegmented`、`SourceTag`、`PageToggleRow`。不新增组件种类 / 配置字段 / 页面业务态。 |
| 维护清单 | 改：`ComponentAutoSettings.vue`、`LayoutPagesView.vue`、`SettingsGroup.vue`；删：`ComponentSettingsSection.vue`；同步 `DESIGN.md` 组件特性渲染说明。`pageRegistry` / 字段元数据 / 后端规则 / schema **不变**。 |
| 验收项 | `npm test`（全量布局契约/字段/校验）、`npm run build`；预览核查：抽屉（board/stocks）、页面布局编辑器三问复现点、设置抽屉无整页滚动；1440×900 主视口。 |

对照 §7.4 维护矩阵：本次属于"既有组件渲染重构"，不落在新页面/新原型/新组件种类/新字段行；维护重点为组件文件 + DESIGN 说明，验证为 `componentConfig.spec`/`pageRegistry.spec`/build + 交互核查。

## 折叠层级规则（统一后）

```
设置抽屉
└─ 布局 / 组件设置 / 业务选项        level 1  卡片 + 箭头，可折叠（不变）
   └─ <slot 名，如 榜单列表>          level 2  可折叠（抽屉多 slot 时有意义）
      ├─ 默认排序 / 每页条数 …        叶子      单控件，不折叠
      └─ 列显隐（N 个列开关）         level 3  可折叠子组

页面布局编辑器（只显示当前聚焦的一个 slot）
└─ <slot 名>                          level 2  标题作锚点，不折叠（folding 唯一组无意义）
   ├─ 默认排序 / 每页条数 …          叶子
   └─ 列显隐                          level 2  可折叠（无 slot 外层时升一级）
```

**设计判断**：折叠只用于"组"（≥2 行的清单/子区），不用于单控件——折叠单控件无收益且制造一堆碎开关。该规则两个场景一致、并写入 DESIGN。

## 取舍记录

- 统一控件到抽屉那套（`PageSegmented` 等）：页面布局编辑器的 `pageSize` 由 `el-input-number`(10–500) 改为分段档位（与用户端一致，取 `PAGE_SIZE_OPTIONS`）；用 `clearable` 可选项在 page 层保留「不覆盖（清除）」能力，行为不丢。
- `SettingsGroup` 标题层级调整会同时作用于抽屉三段——属一致性增益，保守改（仅提升深层标题可读性与间距，不改 level1 卡片）。

## 实施步骤

1. 泛化 `ComponentAutoSettings.vue`：新增可选 props `layer`('user'|'page' 默认 user)、`slotIds`(聚焦过滤)、`allowedLayersOf`(字段策略)、`collapsibleSlot`(默认 true)、`highlightSlot`、`clearable`(默认 false)；字段按 `layer`+策略门控（去掉对 `collapsibleSections` 的硬编码特例）。
2. `LayoutPagesView.vue`：以 `ComponentAutoSettings` 替换 `ComponentSettingsSection`，传 page 层访问器 / 聚焦 slot / 策略 / 高亮 / clearable / `collapsibleSlot=false`。
3. 删除 `ComponentSettingsSection.vue` 及其引用。
4. `SettingsGroup.vue`：深层标题层级修正。
5. `DESIGN.md`：在 §4「设置抽屉」/§7.3 注明组件特性渲染单一事实源与折叠规则。
6. 验收：`npm test` + `npm run build` + 预览三问核查。
