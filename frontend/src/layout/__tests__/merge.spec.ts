import { describe, expect, it } from 'vitest'
import {
  editablePathSet,
  knobMap,
  makeLayoutOverride,
  mergeLayoutConfig,
  type MergeLayer,
} from '../index'
import { createLayout } from '../archetypes'

function layers(values: {
  preset?: Record<string, string | number | boolean>
  page?: Record<string, string | number | boolean>
  user?: Record<string, string | number | boolean>
  pageSchemaVersion?: number
  userSchemaVersion?: number
}): MergeLayer[] {
  const layout = createLayout('list', 'p')
  const allowed = editablePathSet(layout)
  const knobs = knobMap(layout)
  return [
    { layer: 'preset', override: values.preset && makeLayoutOverride(values.preset), allowedPaths: allowed, knobs, dropMode: 'whole-layer' },
    {
      layer: 'page',
      override: values.page && makeLayoutOverride(values.page, values.pageSchemaVersion),
      allowedPaths: allowed,
      knobs,
      dropMode: 'whole-layer',
    },
    {
      layer: 'user',
      override: values.user && makeLayoutOverride(values.user, values.userSchemaVersion),
      allowedPaths: allowed,
      knobs,
      dropMode: 'item',
    },
  ]
}

describe('布局覆盖链路 default < preset < page < user', () => {
  it('用户配置覆盖页面配置，页面配置覆盖预设配置', () => {
    const base = createLayout('list', 'p')
    const result = mergeLayoutConfig(base, layers({
      preset: { density: 'compact' },
      page: { density: 'comfortable' },
      user: { density: 'standard' },
    }))

    expect(result.layout.density).toBe('standard')
    expect(result.sourceMeta.density).toBe('user')
    expect(result.perLayerValues.density).toMatchObject({
      default: 'standard',
      preset: 'compact',
      page: 'comfortable',
      user: 'standard',
    })
    expect(result.dropped).toEqual([])
  })

  it('页面配置覆盖预设配置', () => {
    const base = createLayout('list', 'p')
    const result = mergeLayoutConfig(base, layers({
      preset: { density: 'compact' },
      page: { density: 'comfortable' },
    }))

    expect(result.layout.density).toBe('comfortable')
    expect(result.sourceMeta.density).toBe('page')
  })

  it('非法用户配置逐项丢弃但页面不崩', () => {
    const base = createLayout('list', 'p')
    const result = mergeLayoutConfig(base, layers({
      preset: { density: 'compact' },
      user: { density: 'huge', 'slots.table.minH': 100 },
    }))

    expect(result.layout.density).toBe('compact')
    expect(result.layout.slots.find((slot) => slot.id === 'table')?.minH).toBeUndefined()
    expect(result.dropped.map((item) => item.path).sort()).toEqual(['density', 'slots.table.minH'])
  })

  it('页面层非法时整层回退到上一层', () => {
    const base = createLayout('list', 'p')
    const result = mergeLayoutConfig(base, layers({
      preset: { density: 'compact' },
      page: { density: 'comfortable', 'slots.table.minH': 100 },
    }))

    expect(result.layout.density).toBe('compact')
    expect(result.sourceMeta.density).toBe('preset')
    expect(result.dropped.some((item) => item.layer === 'page' && item.reason === 'layout.invalid')).toBe(true)
  })

  it('schema 版本不匹配时整层回落', () => {
    const base = createLayout('list', 'p')
    const result = mergeLayoutConfig(base, layers({
      preset: { density: 'compact' },
      user: { density: 'comfortable' },
      userSchemaVersion: 999,
    }))

    expect(result.layout.density).toBe('compact')
    expect(result.sourceMeta.density).toBe('preset')
    expect(result.dropped).toContainEqual({ layer: 'user', path: 'density', reason: 'schemaVersion.mismatch' })
  })
})
