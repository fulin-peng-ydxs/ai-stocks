import { describe, expect, it } from 'vitest'
import { createLayout } from '../index'
import { cloneLayout, getLayoutValue, setLayoutValue } from '../path'

describe('布局路径读写', () => {
  it('读写顶层字段 density', () => {
    const l = createLayout('list', 'p')
    expect(getLayoutValue(l, 'density')).toBe('standard')
    const c = cloneLayout(l)
    setLayoutValue(c, 'density', 'compact')
    expect(getLayoutValue(c, 'density')).toBe('compact')
    expect(getLayoutValue(l, 'density')).toBe('standard') // clone 不污染原对象
  })

  it('读写嵌套字段 responsive.allowReflow', () => {
    const l = createLayout('dashboard', 'p')
    expect(getLayoutValue(l, 'responsive.allowReflow')).toBe(true)
    setLayoutValue(l, 'responsive.allowReflow', false)
    expect(getLayoutValue(l, 'responsive.allowReflow')).toBe(false)
  })

  it('读写 slots.<id>.<field>', () => {
    const l = createLayout('list', 'p')
    setLayoutValue(l, 'slots.table.minH', 500)
    expect(getLayoutValue(l, 'slots.table.minH')).toBe(500)
  })

  it('未知 slot / 不可达路径安全无操作', () => {
    const l = createLayout('list', 'p')
    setLayoutValue(l, 'slots.nope.minH', 999) // 不应抛
    expect(getLayoutValue(l, 'slots.nope.minH')).toBeUndefined()
    expect(getLayoutValue(l, 'a.b.c')).toBeUndefined()
  })
})
