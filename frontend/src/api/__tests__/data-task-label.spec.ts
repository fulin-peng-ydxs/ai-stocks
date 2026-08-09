import { describe, expect, it } from 'vitest'

import { taskDisplayLabel } from '@/api/data'

describe('taskDisplayLabel', () => {
  it('质检恢复任务带上问题类型，其它任务保持通用名称', () => {
    expect(taskDisplayLabel('fix', { issue_type: 'data_gap' }))
      .toBe('质检问题恢复·行情缺口(疑似漏采)')
    expect(taskDisplayLabel('verify')).toBe('数据质检')
    expect(taskDisplayLabel('board', { mode: 'update' })).toBe('板块采集·增量')
    expect(taskDisplayLabel('board', { mode: 'backfill' })).toBe('板块采集·全量回填')
  })
})
