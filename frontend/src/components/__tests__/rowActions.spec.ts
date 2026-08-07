import { describe, expect, it } from 'vitest'
import {
  computeRowLayout,
  type AppRowActionMeasure,
} from '../rowActions'

function action(key: string, label: string, width: number, placement?: 'more'): AppRowActionMeasure {
  return { key, label, placement, measured: width, measuredOk: true }
}

describe('computeRowLayout', () => {
  it('宽度足够时按数量上限截断（limit 仍是硬上限）', () => {
    const actions = [action('a', '查看', 60), action('b', '编辑', 60), action('c', '删除', 60)]
    const r = computeRowLayout(actions, 400, 2, 64)
    expect(r).toEqual({ inlineCount: 2, hasMore: true })
  })

  it('宽度放不下时自动收进更多（行内只留装得下的按钮）', () => {
    // c=1: 60 + 8 + 64 = 132 <= 140；c=2: 128 + 8 + 64 = 200 > 140
    const actions = [action('a', '查看', 60), action('b', '编辑', 60), action('c', '删除', 60)]
    const r = computeRowLayout(actions, 140, 3, 64)
    expect(r).toEqual({ inlineCount: 1, hasMore: true })
  })

  it('全部按钮无需更多即可放下时不再出现更多', () => {
    // 三个按钮：60 + 8 + 60 + 8 + 60 = 196，无更多按钮
    const actions = [action('a', '查看', 60), action('b', '编辑', 60), action('c', '删除', 60)]
    const r = computeRowLayout(actions, 196, 3, 64)
    expect(r).toEqual({ inlineCount: 3, hasMore: false })
  })

  it('宽度少 1px 时自动收进更多，行内只留装得下的按钮', () => {
    // 196 > 195 放不下全部；两个按钮+更多 = 200 > 195 也放不下；一个按钮+更多 = 132 <= 195
    const actions = [action('a', '查看', 60), action('b', '编辑', 60), action('c', '删除', 60)]
    const r = computeRowLayout(actions, 195, 3, 64)
    expect(r).toEqual({ inlineCount: 1, hasMore: true })
  })

  it('显式 more 动作恒入更多且不占行内宽度', () => {
    const actions = [
      action('a', '查看', 60),
      action('b', '编辑', 60),
      action('d', '删除', 60, 'more'),
    ]
    const r = computeRowLayout(actions, 200, 3, 64)
    expect(r.inlineCount).toBe(2)
    expect(r.hasMore).toBe(true)
  })

  it('无可用宽度时退化为纯数量逻辑（jsdom 兜底）', () => {
    const actions = [action('a', '查看', 60), action('b', '编辑', 60), action('c', '删除', 60)]
    const r = computeRowLayout(actions, 0, 2, 64)
    expect(r).toEqual({ inlineCount: 2, hasMore: true })
  })
})
