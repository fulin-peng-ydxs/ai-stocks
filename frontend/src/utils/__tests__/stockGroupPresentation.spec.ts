import { describe, expect, it } from 'vitest'
import {
  DEFAULT_STOCK_GROUP_COLOR,
  STOCK_GROUP_COLOR_PRESETS,
  isDefaultStockGroupMember,
  stockGroupTagStyle,
} from '@/utils/stockGroupPresentation'

describe('stockGroupPresentation', () => {
  it('缺少分组字段时按未加入默认自选处理，避免列表渲染中断', () => {
    expect(isDefaultStockGroupMember(undefined)).toBe(false)
    expect(isDefaultStockGroupMember(null)).toBe(false)
    expect(isDefaultStockGroupMember([])).toBe(false)
    expect(isDefaultStockGroupMember([{ is_default: true }])).toBe(true)
  })

  it('统一分组默认色、预设色和轻量背景', () => {
    expect(STOCK_GROUP_COLOR_PRESETS).toContain(DEFAULT_STOCK_GROUP_COLOR)
    expect(stockGroupTagStyle()).toEqual({
      color: DEFAULT_STOCK_GROUP_COLOR,
      borderColor: DEFAULT_STOCK_GROUP_COLOR,
      backgroundColor: `${DEFAULT_STOCK_GROUP_COLOR}14`,
    })
    expect(stockGroupTagStyle('#1677ff')).toEqual({
      color: '#1677ff',
      borderColor: '#1677ff',
      backgroundColor: '#1677ff14',
    })
  })
})
