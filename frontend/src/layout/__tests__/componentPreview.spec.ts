/**
 * 组件预览映射完整性（P6）——保证「系统组件」库里每个登记组件都有可视化预览原型，
 * 不会出现"目录里有、预览渲染不出来"的缺口。
 */
import { describe, expect, it } from 'vitest'
import { COMPONENT_CATALOG } from '../components'
import { PREVIEW_ARCHETYPE, FEEDBACK_DEFAULT_STATE, previewArchetypeOf } from '../componentPreview'
import { COMPONENT_STATES, type ComponentKind } from '../schema'

const ARCHETYPES = new Set([
  'table', 'list', 'tree', 'controls', 'chart', 'kpi',
  'form', 'feedback', 'overlay', 'tabs', 'detail', 'master', 'structure',
])

describe('组件预览映射完整性（P6）', () => {
  it('四态契约只有 ready / loading / empty / error', () => {
    expect(COMPONENT_STATES).toEqual(['ready', 'loading', 'empty', 'error'])
  })

  it('目录里每个组件都有合法预览原型', () => {
    for (const kind of Object.keys(COMPONENT_CATALOG) as ComponentKind[]) {
      const arch = previewArchetypeOf(kind)
      expect(ARCHETYPES.has(arch), `${kind} 预览原型非法: ${arch}`).toBe(true)
      expect(PREVIEW_ARCHETYPE[kind], `${kind} 未登记预览原型`).toBeTruthy()
    }
  })

  it('目录里每个组件都声明 loading / empty / error 稳定占位策略', () => {
    for (const kind of Object.keys(COMPONENT_CATALOG) as ComponentKind[]) {
      const states = COMPONENT_CATALOG[kind].defaultStates
      for (const state of ['loading', 'empty', 'error'] as const) {
        expect(states[state]?.reserveSpace, `${kind} 缺少 ${state} 稳定占位策略`).toBe(true)
      }
    }
  })

  it('PREVIEW_ARCHETYPE 不含目录外的多余键', () => {
    for (const kind of Object.keys(PREVIEW_ARCHETYPE)) {
      expect(COMPONENT_CATALOG[kind as ComponentKind], `${kind} 不在组件目录中`).toBeTruthy()
    }
  })

  it('FEEDBACK_DEFAULT_STATE 的键都是 feedback 类组件', () => {
    for (const kind of Object.keys(FEEDBACK_DEFAULT_STATE) as ComponentKind[]) {
      expect(COMPONENT_CATALOG[kind]?.category, `${kind} 不是 feedback 类`).toBe('feedback')
      expect(previewArchetypeOf(kind)).toBe('feedback')
    }
  })

  it('settings-drawer 已入库且为 overlay 预览', () => {
    expect(COMPONENT_CATALOG['settings-drawer']).toBeTruthy()
    expect(previewArchetypeOf('settings-drawer')).toBe('overlay')
  })
})
