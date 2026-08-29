import { describe, expect, it } from 'vitest'

import {
  BOARD_ISSUE_ITEMS,
  BOARD_STAGE_OPTIONS,
  ISSUE_TYPES_ACTIVE,
  RECOVER_ACTION_LABEL,
  taskDisplayLabel,
} from '@/api/data'

describe('taskDisplayLabel', () => {
  it('质检恢复任务带上问题类型，其它任务保持通用名称', () => {
    expect(taskDisplayLabel('fix', { issue_type: 'data_gap' }))
      .toBe('质检问题恢复·行情·近端缺某日')
    expect(taskDisplayLabel('verify')).toBe('数据质检')
    expect(taskDisplayLabel('board', { mode: 'update' })).toBe('板块采集·增量')
    expect(taskDisplayLabel('board', { mode: 'backfill' })).toBe('板块采集·全量回填')
    expect(taskDisplayLabel('board', {
      mode: 'update', board_type: 'concept', only: ['bar', 'fund'],
    })).toBe('板块采集·增量·概念·指数+资金流')
    expect(taskDisplayLabel('stock_ingest', { recipe: 'daily_update' }))
      .toBe('个股采集·日常同步')
    expect(taskDisplayLabel('stock_ingest', { recipe: 'valuation_gaps' }))
      .toBe('个股采集·市值缺口修复')
  })

  it('板块质检类型、恢复文案和采集阶段使用同一套定义', () => {
    expect(ISSUE_TYPES_ACTIVE).toContain('board_index_invalid')
    expect(BOARD_ISSUE_ITEMS.map((item) => item.key)).toEqual([
      'board_member_incomplete', 'board_index_gap', 'board_index_gap_daily',
      'board_index_invalid', 'board_fund_unmatched', 'board_fund_missing', 'board_fund_stale',
    ])
    expect(RECOVER_ACTION_LABEL.board_index_gap_daily).toBe('重采缺失日指数')
    expect(RECOVER_ACTION_LABEL.board_index_invalid).toBe('重采异常日指数')
    expect(BOARD_STAGE_OPTIONS.map((item) => item.value)).toEqual(['dict', 'members', 'bar', 'fund'])
  })
})
