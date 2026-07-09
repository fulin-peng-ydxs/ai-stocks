/**
 * 组件配置层（P2）——字段元数据完整性 + 分层合并 + 越权/非法丢弃 + 来源追踪。
 * 字段定义口径：只登记已被页面消费的字段（data-table/tabs/settings-drawer 首批字段）。
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
    expect(Object.keys(COMPONENT_FIELD_DEFS).sort()).toEqual(['data-table', 'settings-drawer', 'tabs', 'wide-table'])
    expect((COMPONENT_FIELD_DEFS['data-table'] ?? []).map((d) => d.key).sort()).toEqual(['border', 'defaultSort', 'hiddenColumns', 'pageSize'])
    expect((COMPONENT_FIELD_DEFS['wide-table'] ?? []).map((d) => d.key).sort()).toEqual(['border', 'defaultSort', 'hiddenColumns', 'pageSize'])
    expect((COMPONENT_FIELD_DEFS['settings-drawer'] ?? []).map((d) => d.key).sort()).toEqual([
      'bodyScroll',
      'collapsibleSections',
      'defaultCollapsed',
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
    expect(isLayerAllowed(pageSize, 'preset')).toBe(true) // pageSize 已放开 preset 层（预设×组件默认）
    const ds = getComponentFieldDef('data-table', 'defaultSort')!
    expect(isLayerAllowed(ds, 'preset')).toBe(false) // defaultSort（页面专属枚举）仍仅 page/user
    const border = getComponentFieldDef('data-table', 'border')!
    expect(isLayerAllowed(border, 'page')).toBe(true)
    expect(isLayerAllowed(border, 'user')).toBe(false)
    expect(isLayerAllowed(border, 'preset')).toBe(false)
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

  it('settings-drawer 折叠态默认值与用户层覆盖生效', () => {
    const r = resolveComponentConfig(layout, [
      { layer: 'page', overlay: { values: { 'slots.settings.config.defaultCollapsed': ['components'] } } },
      { layer: 'user', overlay: { values: { 'slots.settings.config.defaultCollapsed': ['layout', 'business'] } } },
    ])
    expect(r.configBySlot.settings.collapsibleSections).toBe(true)
    expect(r.configBySlot.settings.defaultCollapsed).toEqual(['layout', 'business'])
    expect(r.source['slots.settings.config.defaultCollapsed']).toBe('user')
    expect(r.perLayerValues['slots.settings.config.defaultCollapsed']).toMatchObject({
      default: [],
      page: ['components'],
      user: ['layout', 'business'],
    })
  })

  it('preset 层组件默认生效：pageSize 已放开 preset', () => {
    const r = resolveComponentConfig(layout, [
      { layer: 'preset', overlay: { values: { 'slots.table.config.pageSize': 50 } } },
    ])
    expect(r.configBySlot.table.pageSize).toBe(50)
    expect(r.source['slots.table.config.pageSize']).toBe('preset')
  })

  it('border 仅 page 层覆盖生效，user/preset 越权丢弃', () => {
    const r = resolveComponentConfig(layout, [
      { layer: 'preset', overlay: { values: { 'slots.table.config.border': true } } },
      { layer: 'page', overlay: { values: { 'slots.table.config.border': true } } },
      { layer: 'user', overlay: { values: { 'slots.table.config.border': false } } },
    ])
    expect(r.configBySlot.table.border).toBe(true)
    expect(r.source['slots.table.config.border']).toBe('page')
    expect(r.dropped).toContainEqual({ layer: 'preset', path: 'slots.table.config.border', reason: 'layer.notAllowed' })
    expect(r.dropped).toContainEqual({ layer: 'user', path: 'slots.table.config.border', reason: 'layer.notAllowed' })
  })

  it('越权层级被丢弃：defaultSort 仅 page/user，preset 覆盖无效', () => {
    const r = resolveComponentConfig(layout, [
      { layer: 'preset', overlay: { values: { 'slots.table.config.defaultSort': 'x' } } },
    ])
    expect(r.configBySlot.table.defaultSort).toBe('score:desc') // 仍为 default
    expect(r.dropped).toContainEqual({ layer: 'preset', path: 'slots.table.config.defaultSort', reason: 'layer.notAllowed' })
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
