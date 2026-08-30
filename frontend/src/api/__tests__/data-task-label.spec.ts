import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
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
    expect(taskDisplayLabel('stock_board_correlation', { codes: ['600000.SH'], force: true }))
      .toBe('个股走势关联板块·指定 1 只·强制重算')
    expect(taskDisplayLabel('stock_board_correlation', { force: false }))
      .toBe('个股走势关联板块·全市场')
    expect(taskDisplayLabel('limit_ladder_recompute', { trade_date: '2026-08-28' }))
      .toBe('连板天梯重算·2026-08-28')
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

  it('相关性任务表单、任务筛选与五阶段标签完整接线', () => {
    const schedule = readFileSync(resolve('src/views/data/ScheduleView.vue'), 'utf8')
    const ingest = readFileSync(resolve('src/views/data/IngestView.vue'), 'utf8')
    const overview = readFileSync(resolve('src/views/data/OverviewView.vue'), 'utf8')
    const stockScope = readFileSync(resolve('src/components/data/StockIngestScopeFields.vue'), 'utf8')

    expect(schedule).toContain("form.task_type === 'stock_board_correlation'")
    expect(schedule).toContain('v-model="form.correlation.scope"')
    expect(schedule).toContain('v-model="form.correlation.codes"')
    expect(schedule).toContain('v-model="form.correlation.force"')
    expect(schedule).toContain('buildStockBoardCorrelationTaskParams(form.correlation)')
    expect(ingest).toContain("'stock_board_correlation'")
    for (const phase of ['read_candidates', 'load_prices', 'calculate', 'validate', 'switch']) {
      expect(ingest).toContain(`${phase}:`)
    }
    expect(ingest).toContain('data-testid="correlation-task-result"')
    expect(ingest).toContain("return '未切换（失败）'")
    expect(overview).toContain('<StockCodeMultiSelect')
    expect(stockScope).toContain('<StockCodeMultiSelect')
  })

  it('连板天梯任务只进入任务中心，不进入可配置调度', () => {
    const schedule = readFileSync(resolve('src/views/data/ScheduleView.vue'), 'utf8')
    const ingest = readFileSync(resolve('src/views/data/IngestView.vue'), 'utf8')

    expect(ingest).toContain("'limit_ladder_recompute'")
    expect(ingest).toContain('data-testid="limit-ladder-task-result"')
    expect(ingest).toContain("row.trigger_source === 'system'")
    expect(ingest).toContain('系统{{ row.job_name')
    expect(schedule).not.toContain('limit_ladder_recompute')
  })
})
