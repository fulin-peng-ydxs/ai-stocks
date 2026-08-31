import { describe, expect, it } from 'vitest'
import type { LimitLadderLayer, LimitLadderStock } from '@/api/limitLadder'
import { sortLimitLadderLayers } from '@/views/limit-ladder/sorting'

function stock(
  code: string,
  patch: Partial<LimitLadderStock> = {},
): LimitLadderStock {
  return {
    code,
    name: code,
    board: '主板',
    price_limit_pct: 0.1,
    is_st: false,
    st_quality: 'accurate',
    st_source: 'daily_bar',
    is_one_word: false,
    consecutive_days: 1,
    amount: 1,
    industry_name: '未分类',
    industry_board_code: null,
    source_version: 'v1',
    window_limit_up_days: 1,
    window_return_pct: 0,
    window_start_date: null,
    actual_trade_days: 31,
    snapshot_concepts: [],
    latest_related_industry: null,
    latest_related_concept: null,
    ...patch,
  }
}

describe('limit ladder card sorting', () => {
  const layers: LimitLadderLayer[] = [
    {
      consecutive_days: 2,
      stock_count: 2,
      stocks: [
        stock('A', { consecutive_days: 2, window_return_pct: 8 }),
        stock('B', { consecutive_days: 2, window_return_pct: 12 }),
      ],
    },
    {
      consecutive_days: 1,
      stock_count: 2,
      stocks: [
        stock('C', { window_return_pct: 2 }),
        stock('D', { window_return_pct: 5 }),
      ],
    },
  ]

  it('保留接口层级一级顺序，只在层内按用户字段二级排序', () => {
    const sorted = sortLimitLadderLayers(layers, 'return')
    expect(sorted.map((layer) => layer.consecutive_days)).toEqual([2, 1])
    expect(sorted[0]!.stocks.map((item) => item.code)).toEqual(['B', 'A'])
    expect(sorted[1]!.stocks.map((item) => item.code)).toEqual(['D', 'C'])
    expect(layers[0]!.stocks.map((item) => item.code)).toEqual(['A', 'B'])
  })

  it('二级字段相同时稳定保留接口兜底顺序', () => {
    const sorted = sortLimitLadderLayers(layers, 'board')
    expect(sorted[0]!.stocks.map((item) => item.code)).toEqual(['A', 'B'])
    expect(sorted[1]!.stocks.map((item) => item.code)).toEqual(['C', 'D'])
  })
})
