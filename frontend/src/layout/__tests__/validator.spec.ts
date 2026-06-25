/**
 * 布局校验器单测（M1 护栏）。显式 import vitest API（不开 globals），
 * 这样 `vue-tsc -b` 对 spec 的类型检查无需额外全局类型即可通过。
 */
import { describe, expect, it } from 'vitest'
import { ARCHETYPES, COMPONENT_CATALOG, createLayout, type ComponentKind, type PageLayout } from '../index'
import { coerceEditableValue, LayoutConfigError, validateLayout } from '../validator'

const errorsOf = (layout: PageLayout) => validateLayout(layout).filter((i) => i.level === 'error')
const codesOf = (layout: PageLayout) => validateLayout(layout).map((i) => i.code)

describe('archetype 预设开箱即合规', () => {
  for (const archetype of ARCHETYPES) {
    it(`${archetype} 预设无 error`, () => {
      expect(errorsOf(createLayout(archetype, `test-${archetype}`))).toEqual([])
    })
  }
})

describe('组件最低尺寸下限（规范 §3）', () => {
  it('显式 minH 低于组件下限 → error', () => {
    const layout = createLayout('list', 'p')
    const table = layout.slots.find((s) => s.id === 'table')!
    table.minH = 100 // data-table 下限 300
    expect(codesOf(layout)).toContain('slot.minH.below')
  })

  it('显式 minH 高于下限 → 合规', () => {
    const layout = createLayout('list', 'p')
    layout.slots.find((s) => s.id === 'table')!.minH = 500
    expect(errorsOf(layout)).toEqual([])
  })
})

describe('组件能力目录（M1）', () => {
  const requiredKinds: ComponentKind[] = [
    'page-shell', 'section', 'split-pane', 'slot-group',
    'filter-bar', 'search-box', 'advanced-filter', 'toolbar', 'batch-bar',
    'data-table', 'wide-table', 'simple-list', 'description-list', 'tree-table',
    'pagination', 'column-settings', 'sort-control', 'export-button',
    'form', 'form-section', 'field-grid', 'inline-editor',
    'loading-state', 'empty-state', 'error-state', 'skeleton',
    'kpi-grid', 'metric-card', 'stat-strip', 'chart', 'mini-chart', 'chart-grid', 'trend-panel',
    'detail-panel', 'detail', 'drawer', 'dialog', 'settings-drawer', 'side-panel',
    'master-detail', 'tabs', 'steps', 'collapse', 'kanban', 'timeline',
    'tree-nav', 'anchor-nav', 'breadcrumb',
  ]

  it('需求文档列出的首批组件均有能力元信息', () => {
    for (const kind of requiredKinds) {
      const meta = COMPONENT_CATALOG[kind]
      expect(meta, kind).toBeTruthy()
      expect(meta.label).toBeTruthy()
      expect(meta.minW).toBeGreaterThan(0)
      expect(meta.minH).toBeGreaterThan(0)
      expect(meta.configCapabilities.length).toBeGreaterThan(0)
    }
  })
})

describe('组件专属配置 schema', () => {
  it('表格合法专属配置通过', () => {
    const layout = createLayout('list', 'p')
    layout.slots.find((s) => s.id === 'table')!.config = {
      pagination: true,
      pageSize: 50,
      hiddenColumns: ['amount'],
      rowClick: 'open-detail',
    }
    expect(errorsOf(layout)).toEqual([])
  })

  it('表格非法专属配置类型被拒绝', () => {
    const layout = createLayout('list', 'p')
    layout.slots.find((s) => s.id === 'table')!.config = {
      pageSize: 50.5,
      rowClick: 'teleport',
    }
    expect(codesOf(layout)).toContain('component.config.type')
  })

  it('未知专属配置 key 被拒绝', () => {
    const layout = createLayout('list', 'p')
    layout.slots.find((s) => s.id === 'table')!.config = { freeCss: '.x{}' }
    expect(codesOf(layout)).toContain('component.config.unknownKey')
  })
})

describe('状态占位策略', () => {
  it('状态反馈组件必须声明稳定占位', () => {
    const layout = createLayout('dashboard', 'p')
    layout.slots = [{ id: 'empty', component: 'empty-state', region: 'main', order: 1 }]
    layout.responsive = { allowReflow: false, breakpoints: [{ minWidth: 0, columns: 1 }] }
    expect(codesOf(layout)).toContain('component.state.reserveSpace.required')
    expect(codesOf(layout)).toContain('component.state.minH.required')
  })

  it('状态反馈组件声明稳定占位后通过', () => {
    const layout = createLayout('dashboard', 'p')
    layout.slots = [{
      id: 'empty',
      component: 'empty-state',
      region: 'main',
      order: 1,
      config: { reserveSpace: true, minH: 120 },
    }]
    layout.responsive = { allowReflow: false, breakpoints: [{ minWidth: 0, columns: 1 }] }
    expect(errorsOf(layout)).toEqual([])
  })

  it('显式状态策略不能取消稳定占位', () => {
    const layout = createLayout('list', 'p')
    layout.slots.find((s) => s.id === 'table')!.states = { empty: { reserveSpace: false } }
    expect(codesOf(layout)).toContain('slot.state.unstable')
  })
})

describe('主表唯一与 growMain 约束（规范 §1）', () => {
  it('主内容区两个 growMain → error', () => {
    const layout = createLayout('workbench', 'p')
    layout.slots.find((s) => s.id === 'chart')!.growMain = true // 已有 table growMain
    expect(codesOf(layout)).toContain('growMain.multiple')
  })

  it('growMain 落在不能成主的组件 → error', () => {
    const layout = createLayout('form', 'p')
    layout.slots.find((s) => s.id === 'form')!.growMain = true // form canGrowMain=false
    expect(codesOf(layout)).toContain('slot.growMain.unsupported')
  })
})

describe('重排多列三条件（规范 §5）', () => {
  it('开启重排但含有强阅读顺序的大表 → error', () => {
    const layout = createLayout('dashboard', 'p')
    layout.slots.push({ id: 'tbl', component: 'data-table', region: 'main', order: 9 })
    expect(codesOf(layout)).toContain('reflow.nonReflowable')
  })

  it('重排后单列净宽跌破组件最低宽 → error', () => {
    const layout = createLayout('dashboard', 'p')
    // 600px 拆 3 列，单列约 192px，低于 chart 最低宽 280px
    layout.responsive.breakpoints = [
      { minWidth: 0, columns: 1 },
      { minWidth: 600, columns: 3 },
    ]
    expect(codesOf(layout)).toContain('reflow.belowMinWidth')
  })

  it('allowReflow=false 却声明多列 → error', () => {
    const layout = createLayout('list', 'p')
    layout.responsive.breakpoints = [
      { minWidth: 0, columns: 1 },
      { minWidth: 1024, columns: 2 },
    ]
    expect(codesOf(layout)).toContain('reflow.disabledButMultiCol')
  })
})

describe('滚动轴唯一（规范 §6）', () => {
  it('同一主内容区出现两个整区滚动 → error', () => {
    const layout = createLayout('dashboard', 'p')
    layout.slots = [
      { id: 'a', component: 'detail', region: 'main', scroll: 'region', order: 1 },
      { id: 'b', component: 'detail', region: 'main', scroll: 'region', order: 2 },
    ]
    layout.responsive = { allowReflow: false, breakpoints: [{ minWidth: 0, columns: 1 }] }
    expect(codesOf(layout)).toContain('scroll.region.multiple')
  })
})

describe('可编辑白名单 path 真实性', () => {
  it('path 指向不存在的 slot → error', () => {
    const layout = createLayout('list', 'p')
    layout.editable.push({ path: 'slots.nope.minH', label: 'x', type: 'int', min: 1, max: 9 })
    expect(codesOf(layout)).toContain('editable.path.invalid')
  })

  it('指向真实 slot 的合法字段 → 合规', () => {
    const layout = createLayout('list', 'p')
    layout.editable.push({ path: 'slots.table.minW', label: 'x', type: 'int', min: 360, max: 800 })
    expect(errorsOf(layout)).toEqual([])
  })
})

describe('coerceEditableValue 取值域守门（L2 可改不能乱改）', () => {
  const enumKnob = { path: 'density', label: 'd', type: 'enum' as const, options: ['compact', 'standard', 'comfortable'] }
  const intKnob = { path: 'slots.table.minH', label: 'h', type: 'int' as const, min: 300, max: 800 }

  it('enum 合法值通过', () => {
    expect(coerceEditableValue(enumKnob, 'compact')).toBe('compact')
  })
  it('enum 非法值拒绝', () => {
    expect(() => coerceEditableValue(enumKnob, 'huge')).toThrow(LayoutConfigError)
  })
  it('int 越界拒绝', () => {
    expect(() => coerceEditableValue(intKnob, 200)).toThrow(LayoutConfigError)
    expect(() => coerceEditableValue(intKnob, 900)).toThrow(LayoutConfigError)
  })
  it('int 非整数拒绝', () => {
    expect(() => coerceEditableValue(intKnob, 350.5)).toThrow(LayoutConfigError)
  })
  it('int 合法值规范化', () => {
    expect(coerceEditableValue(intKnob, 500)).toBe(500)
  })
})

describe('overlay 与嵌套 slot 可寻址模型（P5）', () => {
  // 基线：workbench 顶层 toolbar(action) + body(section,main)。
  const base = (): PageLayout => ({
    pageKey: 'p5',
    archetype: 'workbench',
    hasActionRegion: true,
    density: 'standard',
    responsive: { allowReflow: false, breakpoints: [{ minWidth: 0, columns: 1 }] },
    editable: [],
    slots: [
      { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
      { id: 'body', component: 'section', region: 'main', order: 1 },
    ],
  })

  it('嵌套 data-table（parentId=body）合规，不影响顶层主区', () => {
    const layout = base()
    layout.slots.push({ id: 'trades', component: 'data-table', region: 'main', parentId: 'body', order: 2 })
    expect(errorsOf(layout)).toEqual([])
  })

  it('overlay 抽屉 slot 合规，不计入 action/main 红线', () => {
    const layout = base()
    layout.slots.push({ id: 'settings', component: 'drawer', region: 'overlay', order: 1 })
    expect(errorsOf(layout)).toEqual([])
  })

  it('parentId 指向不存在的 slot → error', () => {
    const layout = base()
    layout.slots.push({ id: 'trades', component: 'data-table', region: 'main', parentId: 'ghost' })
    expect(codesOf(layout)).toContain('slot.parent.missing')
  })

  it('parentId 自引用 → error', () => {
    const layout = base()
    layout.slots.push({ id: 'self', component: 'data-table', region: 'main', parentId: 'self' })
    expect(codesOf(layout)).toContain('slot.parent.self')
  })

  it('仅支持一层嵌套：父 slot 本身已嵌套 → error', () => {
    const layout = base()
    layout.slots.push({ id: 'mid', component: 'data-table', region: 'main', parentId: 'body' })
    layout.slots.push({ id: 'deep', component: 'data-table', region: 'main', parentId: 'mid' })
    expect(codesOf(layout)).toContain('slot.parent.nested')
  })

  it('嵌套 growMain 不计入顶层主区 growMain 上限', () => {
    const layout = base()
    // 顶层主表 + 嵌套主表：嵌套的不应触发 growMain.multiple。
    layout.slots[1] = { id: 'body', component: 'data-table', region: 'main', growMain: true, order: 1 }
    layout.slots.push({ id: 'inner', component: 'data-table', region: 'main', parentId: 'body', growMain: true })
    expect(codesOf(layout)).not.toContain('growMain.multiple')
  })
})
