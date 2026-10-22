import { describe, expect, it } from 'vitest'
import { actionSubtypeLabel } from '../tradeDisciplineRuleTypes'

describe('交易纪律买卖类型名称', () => {
  it('版本名称快照优先于当前字典改名', () => {
    expect(actionSubtypeLabel({ action_type: 'buy', action_subtype: 'custom', action_subtype_label: '发布时名称' },
      [{ name: 'custom', label: '改名后名称', action_type: 'buy', builtin: false }])).toBe('发布时名称')
  })
  it.each([
    ['buy', 'open_position', '建仓'],
    ['buy', 'add_position', '加仓'],
    ['sell', 'liquidate', '清仓'],
    ['sell', 'reduce_position', '减仓'],
    ['sell', 'do_t', '做 T'],
    ['buy', '均线回踩', '均线回踩'],
    ['sell', null, '未选择类型'],
  ] as const)('%s 类型 %s 展示 %s', (action_type, action_subtype, expected) => {
    expect(actionSubtypeLabel({ action_type, action_subtype })).toBe(expected)
  })

  it('管理候选的展示名称优先，已删除类型保留规则快照名称', () => {
    const rule = { action_type: 'buy' as const, action_subtype: '均线回踩' }
    expect(actionSubtypeLabel(rule, [{ name: '均线回踩', label: '回踩加仓', action_type: 'buy', builtin: false }])).toBe('回踩加仓')
    expect(actionSubtypeLabel(rule, [])).toBe('均线回踩')
  })
})
