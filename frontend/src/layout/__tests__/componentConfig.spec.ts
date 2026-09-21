/**
 * 组件配置层（P2）——字段元数据完整性 + 分层合并 + 越权/非法丢弃 + 来源追踪。
 * 字段定义口径：登记组件 kind 真实支持的 Web 配置字段。
 */
import { describe, expect, it } from 'vitest'
import {
  COMPONENT_FIELD_DEFS,
  coerceComponentValue,
  componentConfigPath,
  getComponentFieldDef,
  isComponentConfigPath,
  isLayerAllowed,
  parseComponentConfigPath,
  resolveComponentConfig,
  resolveComponentNumberValue,
  type ComponentConfigLayerInput,
} from '../componentConfig'
import type { PageLayout } from '../schema'

const layout: PageLayout = {
  pageKey: 'demo',
  archetype: 'list',
  hasActionRegion: true,
  density: 'standard',
  responsive: { allowReflow: false, breakpoints: [{ minWidth: 0, columns: 1 }] },
  editable: [],
  slots: [
    { id: 'filters', component: 'filter-bar', region: 'action', order: 1 },
    { id: 'table', component: 'data-table', region: 'main', growMain: true, order: 1, config: { pageSize: 20, defaultSort: 'score:desc' } },
    { id: 'configPanel', component: 'config-panel', region: 'main', parentId: 'table', order: 2 },
    { id: 'settings', component: 'settings-drawer', region: 'overlay', order: 1 },
  ],
}

describe('组件字段元数据', () => {
  it('每个字段定义都自洽：layers 非空、enum 必带 options、范围合法', () => {
    for (const [, defs] of Object.entries(COMPONENT_FIELD_DEFS)) {
      for (const def of defs ?? []) {
        expect(def.layers.length, `${def.key} layers 不能为空`).toBeGreaterThan(0)
        if (def.control === 'enum') expect(def.options?.length, `${def.key} enum 缺 options`).toBeGreaterThan(0)
        if (def.min != null && def.max != null) expect(def.min).toBeLessThanOrEqual(def.max)
      }
    }
  })

  it('字段定义只覆盖已消费字段，不预设无消费字段', () => {
    expect(Object.keys(COMPONENT_FIELD_DEFS).sort()).toEqual(['chart', 'config-panel', 'data-table', 'master-detail', 'settings-drawer', 'tabs', 'wide-table'])
    expect((COMPONENT_FIELD_DEFS.chart ?? []).map((d) => d.key)).toEqual([
      'minHeight',
      'stockChart',
      'measurementOperationsExpanded',
      'returnMeasurementMode',
    ])
    expect((COMPONENT_FIELD_DEFS['config-panel'] ?? []).map((d) => d.key).sort()).toEqual([
      'collapsibleSections',
      'defaultCollapsed',
      'showGroupDescription',
      'showSectionDescription',
    ])
    expect((COMPONENT_FIELD_DEFS['data-table'] ?? []).map((d) => d.key).sort()).toEqual(['border', 'defaultSort', 'hiddenColumns', 'pageSize'])
    expect((COMPONENT_FIELD_DEFS['wide-table'] ?? []).map((d) => d.key).sort()).toEqual(['border', 'defaultSort', 'hiddenColumns', 'pageSize'])
    expect((COMPONENT_FIELD_DEFS['master-detail'] ?? []).map((d) => d.key)).toEqual([
      'masterRatio',
      'masterRatioProfiles',
    ])
    expect((COMPONENT_FIELD_DEFS['settings-drawer'] ?? []).map((d) => d.key).sort()).toEqual([
      'bodyScroll',
      'size',
    ])
    expect((COMPONENT_FIELD_DEFS.tabs ?? []).map((d) => d.key)).toEqual(['defaultActive'])
  })

  it('路径构造与解析互逆', () => {
    expect(componentConfigPath('table', 'pageSize')).toBe('slots.table.config.pageSize')
    expect(parseComponentConfigPath('slots.table.config.pageSize')).toEqual({ slotId: 'table', field: 'pageSize' })
    expect(parseComponentConfigPath('density')).toBeNull()
    expect(isComponentConfigPath('slots.table.config.pageSize')).toBe(true)
    expect(isComponentConfigPath('slots.table.minH')).toBe(false)
  })

  it('isLayerAllowed 守门层级', () => {
    const pageSize = getComponentFieldDef('data-table', 'pageSize')!
    expect(isLayerAllowed(pageSize, 'page')).toBe(true)
    expect(isLayerAllowed(pageSize, 'user')).toBe(true)
    const border = getComponentFieldDef('data-table', 'border')!
    expect(isLayerAllowed(border, 'page')).toBe(true)
    expect(isLayerAllowed(border, 'user')).toBe(false)
    const bodyScroll = getComponentFieldDef('settings-drawer', 'bodyScroll')!
    expect(isLayerAllowed(bodyScroll, 'page')).toBe(true)
    expect(isLayerAllowed(bodyScroll, 'user')).toBe(false)
  })

  it('coerce 守门：类型/取值域', () => {
    const pageSize = getComponentFieldDef('data-table', 'pageSize')!
    expect(coerceComponentValue(pageSize, 50)).toBe(50)
    expect(() => coerceComponentValue(pageSize, 5)).toThrow() // < min 10
    expect(() => coerceComponentValue(pageSize, 'x')).toThrow()
    const hidden = getComponentFieldDef('data-table', 'hiddenColumns')!
    expect(coerceComponentValue(hidden, ['a', 'b'])).toEqual(['a', 'b'])
    expect(() => coerceComponentValue(hidden, [1, 2])).toThrow()
    const border = getComponentFieldDef('data-table', 'border')!
    expect(coerceComponentValue(border, false)).toBe(false)
    expect(() => coerceComponentValue(border, 'false')).toThrow()
    const chartHeight = getComponentFieldDef('chart', 'minHeight')!
    expect(coerceComponentValue(chartHeight, 560)).toBe(560)
    expect(() => coerceComponentValue(chartHeight, 479)).toThrow()
    expect(() => coerceComponentValue(chartHeight, 901)).toThrow()
    const masterRatio = getComponentFieldDef('master-detail', 'masterRatio')!
    expect(masterRatio.default).toBe(45)
    expect(coerceComponentValue(masterRatio, 45)).toBe(45)
    expect(() => coerceComponentValue(masterRatio, 29)).toThrow()
    expect(coerceComponentValue(masterRatio, 70)).toBe(70)
    expect(() => coerceComponentValue(masterRatio, 71)).toThrow()
  })

  it('数值消费统一使用字段值域，并以 slot 默认值安全兜底', () => {
    expect(resolveComponentNumberValue('chart', 'minHeight', 720, 650)).toBe(720)
    expect(resolveComponentNumberValue('chart', 'minHeight', 300, 650)).toBe(480)
    expect(resolveComponentNumberValue('chart', 'minHeight', 1200, 650)).toBe(900)
    expect(resolveComponentNumberValue('chart', 'minHeight', undefined, 650)).toBe(650)
    expect(resolveComponentNumberValue('chart', 'minHeight', null, 650)).toBe(650)
    expect(resolveComponentNumberValue('chart', 'minHeight', 560.4, 650)).toBe(560)
    expect(() => resolveComponentNumberValue('tabs', 'defaultActive', 1, 1)).toThrow()
  })
})

describe('组件配置分层合并', () => {
  it('default 取 slot.config 已登记字段', () => {
    const r = resolveComponentConfig(layout, [])
    expect(r.configBySlot.table.pageSize).toBe(20)
    expect(r.configBySlot.table.border).toBe(false)
    expect(r.configBySlot.table.defaultSort).toBe('score:desc')
    expect(r.source['slots.table.config.pageSize']).toBe('default')
    expect(r.source['slots.table.config.border']).toBe('default')
  })

  it('page/user 覆盖按优先级生效并标注来源', () => {
    const layers: ComponentConfigLayerInput[] = [
      { layer: 'page', overlay: { values: { 'slots.table.config.pageSize': 50 } } },
      { layer: 'user', overlay: { values: { 'slots.table.config.pageSize': 100 } } },
    ]
    const r = resolveComponentConfig(layout, layers)
    expect(r.configBySlot.table.pageSize).toBe(100)
    expect(r.source['slots.table.config.pageSize']).toBe('user')
    expect(r.perLayerValues['slots.table.config.pageSize']).toMatchObject({ default: 20, page: 50, user: 100 })
  })

  it('settings-drawer 折叠能力为固定交互，不接受页面或用户配置', () => {
    const r = resolveComponentConfig(layout, [
      { layer: 'page', overlay: { values: { 'slots.settings.config.collapsibleSections': false } } },
      { layer: 'user', overlay: { values: { 'slots.settings.config.defaultCollapsed': ['layout'] } } },
    ])
    expect(r.configBySlot.settings).not.toHaveProperty('collapsibleSections')
    expect(r.configBySlot.settings).not.toHaveProperty('defaultCollapsed')
    expect(r.dropped).toContainEqual({ layer: 'page', path: 'slots.settings.config.collapsibleSections', reason: 'field.unknown' })
    expect(r.dropped).toContainEqual({ layer: 'user', path: 'slots.settings.config.defaultCollapsed', reason: 'field.unknown' })
  })

  it('config-panel 展示与默认折叠配置按层合并', () => {
    const r = resolveComponentConfig(layout, [
      { layer: 'page', overlay: { values: { 'slots.configPanel.config.defaultCollapsed': ['datasource.request'] } } },
      { layer: 'user', overlay: { values: { 'slots.configPanel.config.showSectionDescription': false } } },
    ])
    expect(r.configBySlot.configPanel.collapsibleSections).toBe(true)
    expect(r.configBySlot.configPanel.defaultCollapsed).toEqual(['datasource.request'])
    expect(r.configBySlot.configPanel.showGroupDescription).toBe(true)
    expect(r.configBySlot.configPanel.showSectionDescription).toBe(false)
    expect(r.source['slots.configPanel.config.defaultCollapsed']).toBe('page')
    expect(r.source['slots.configPanel.config.showSectionDescription']).toBe('user')
  })

  it('border 仅 page 层覆盖生效，user 越权丢弃', () => {
    const r = resolveComponentConfig(layout, [
      { layer: 'page', overlay: { values: { 'slots.table.config.border': true } } },
      { layer: 'user', overlay: { values: { 'slots.table.config.border': false } } },
    ])
    expect(r.configBySlot.table.border).toBe(true)
    expect(r.source['slots.table.config.border']).toBe('page')
    expect(r.dropped).toContainEqual({ layer: 'user', path: 'slots.table.config.border', reason: 'layer.notAllowed' })
  })

  it('settings-drawer 内容区滚动仅 page 层生效，user 层越权丢弃', () => {
    const r = resolveComponentConfig(layout, [
      { layer: 'page', overlay: { values: { 'slots.settings.config.bodyScroll': true } } },
      { layer: 'user', overlay: { values: { 'slots.settings.config.bodyScroll': false } } },
    ])
    expect(r.configBySlot.settings.bodyScroll).toBe(true)
    expect(r.source['slots.settings.config.bodyScroll']).toBe('page')
    expect(r.dropped).toContainEqual({
      layer: 'user',
      path: 'slots.settings.config.bodyScroll',
      reason: 'layer.notAllowed',
    })
  })

  it('未知 slot / 未知字段 / 类型非法均丢弃', () => {
    const r = resolveComponentConfig(layout, [
      { layer: 'page', overlay: { values: { 'slots.ghost.config.pageSize': 20 } } },
      { layer: 'page', overlay: { values: { 'slots.table.config.nope': 1 } } },
      { layer: 'page', overlay: { values: { 'slots.table.config.pageSize': 'x' } } },
    ])
    const reasons = r.dropped.map((d) => d.reason).sort()
    expect(reasons).toEqual(['field.unknown', 'slot.notFound', 'value.invalid'])
  })

  it('filter-bar 无受控字段：其 slot 上的覆盖按未知字段丢弃', () => {
    const r = resolveComponentConfig(layout, [
      { layer: 'page', overlay: { values: { 'slots.filters.config.defaultExpanded': true } } },
    ])
    expect(r.configBySlot.filters).toBeUndefined()
    expect(r.dropped).toContainEqual({ layer: 'page', path: 'slots.filters.config.defaultExpanded', reason: 'field.unknown' })
  })
})
