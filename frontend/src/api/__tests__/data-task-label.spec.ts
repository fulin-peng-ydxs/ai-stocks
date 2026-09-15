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
    expect(taskDisplayLabel('enrich_basic')).toBe('基础资料刷新')
    expect(taskDisplayLabel('board', { mode: 'update' })).toBe('板块采集·增量')
    expect(taskDisplayLabel('board', { mode: 'backfill' })).toBe('板块采集·全量回填')
    expect(taskDisplayLabel('board', {
      mode: 'update', board_type: 'concept', only: ['bar', 'fund'],
    })).toBe('板块采集·增量·概念·指数+资金流')
    expect(taskDisplayLabel('stock_ingest', { recipe: 'daily_update' }))
      .toBe('个股采集·日常同步')
    expect(taskDisplayLabel('stock_ingest', { recipe: 'valuation_gaps' }))
      .toBe('个股采集·市值缺口修复')
    expect(taskDisplayLabel('stock_ingest', { recipe: 'st_status_refresh' }))
      .toBe('个股采集·ST状态刷新')
    expect(taskDisplayLabel('stock_board_correlation', { codes: ['600000.SH'], force: true }))
      .toBe('走势相关重算·最新完整交易日·指定 1 只')
    expect(taskDisplayLabel('stock_board_correlation', { force: false }))
      .toBe('走势相关重算·最新完整交易日·全市场')
    expect(taskDisplayLabel('limit_ladder_invalidate', { target_mode: 'all' }))
      .toBe('连板天梯失效·全部快照')
    expect(taskDisplayLabel('recompute', { target_mode: 'fixed', trade_date: '2026-08-28' }))
      .toBe('每日榜单失效·2026-08-28')
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

  it('市场指数质检类型复用质量台账与恢复任务映射', () => {
    expect(ISSUE_TYPES_ACTIVE).toEqual(expect.arrayContaining([
      'market_index_gap', 'market_index_gap_daily', 'market_index_invalid',
    ]))
    expect(RECOVER_ACTION_LABEL.market_index_gap).toBe('补齐市场指数')
    expect(RECOVER_ACTION_LABEL.market_index_gap_daily).toBe('重采市场指数缺失日')
    expect(RECOVER_ACTION_LABEL.market_index_invalid).toBe('重采市场指数异常日')
    expect(taskDisplayLabel('fix', { issue_type: 'market_index_invalid' }))
      .toBe('质检问题恢复·市场指数·字段非法')
  })

  it('价量错配复用质量台账与单日重采映射', () => {
    expect(ISSUE_TYPES_ACTIVE).toContain('price_volume_mismatch')
    expect(RECOVER_ACTION_LABEL.price_volume_mismatch).toBe('重采该日')
    expect(taskDisplayLabel('fix', { issue_type: 'price_volume_mismatch' }))
      .toBe('质检问题恢复·行情·价量口径错配')
  })

  it('ST 质量类型统一进入专属层并指向刷新恢复', () => {
    expect(ISSUE_TYPES_ACTIVE).toEqual(expect.arrayContaining([
      'st_status_missing', 'st_status_approximate', 'st_status_mismatch',
    ]))
    expect(RECOVER_ACTION_LABEL.st_status_missing).toBe('刷新ST状态')
    expect(taskDisplayLabel('fix', { issue_type: 'st_status_mismatch' }))
      .toBe('质检问题恢复·ST状态·日线投影不一致')
  })

  it('三类结果维护复用同一字段组件，相关性五阶段标签完整接线', () => {
    const schedule = readFileSync(resolve('src/views/data/ScheduleView.vue'), 'utf8')
    const ingest = readFileSync(resolve('src/views/data/IngestView.vue'), 'utf8')
    const overview = readFileSync(resolve('src/views/data/OverviewView.vue'), 'utf8')
    const stockScope = readFileSync(resolve('src/components/data/StockIngestScopeFields.vue'), 'utf8')

    expect(schedule).toContain('<ResultMaintenanceTaskFields')
    expect(schedule).toContain('buildResultMaintenanceTaskParams(form.task_type, form.resultMaintenance)')
    expect(schedule).toContain('onActivated(openResultScheduleFromIntent)')
    expect(schedule).toContain('consumeResultMaintenanceScheduleIntent()')
    expect(ingest).toContain('queueResultMaintenanceScheduleIntent(type)')
    expect(ingest).toContain("router.push('/data/schedule')")
    expect(schedule).not.toContain('保存只会登记调度，不会立即执行')
    expect(ingest).toContain('<ResultMaintenanceTaskFields')
    expect(ingest).toContain('buildResultMaintenanceTaskParams(resultType.value, resultForm.value)')
    expect(ingest).toContain("route.path !== '/data/ingest'")
    expect(ingest).toContain("queryTaskType === 'stock_ingest' && requestedRecipe")
    expect(ingest).toContain("q.task_type === 'stock_ingest' && typeof q.recipe === 'string'")
    expect(ingest).not.toContain('本次只按以上参数立即执行')
    expect(ingest).not.toContain('manual-result-execution-scope')
    expect(ingest.match(/>手动执行<\/el-button>/g)).toHaveLength(5)
    expect(ingest).not.toContain('>配置采集</el-button>')
    expect(ingest).toContain('data-testid="manual-stock-ingest"')
    expect(ingest).toContain('data-testid="manual-board-ingest"')
    expect(ingest).toContain('data-testid="ingest-execute-submit"')
    expect(ingest).toMatch(/<AppDialog[^>]*align-center[^>]*data-testid="ingest-options-dialog"/)
    expect(ingest).toMatch(/<AppDialog[^>]*align-center[^>]*data-testid="result-maintenance-dialog"/)
    expect(ingest.match(/按以上参数执行/g)).toHaveLength(2)
    expect(ingest).not.toContain('>执行…</el-button>')
    expect(ingest).not.toContain('>配置采集…</el-button>')
    expect(ingest).not.toContain('>更多选项…</el-button>')
    expect(ingest).toContain("'stock_board_correlation'")
    for (const phase of ['read_candidates', 'load_prices', 'calculate', 'validate', 'switch']) {
      expect(ingest).toContain(`${phase}:`)
    }
    expect(ingest).toContain('data-testid="correlation-task-result"')
    expect(ingest).toContain("return '未切换（失败）'")
    expect(overview).toContain('<StockCodeMultiSelect')
    expect(stockScope).toContain('<StockCodeMultiSelect')
  })

  it('天梯失效开放调度，内部天梯重算仍只进入任务中心', () => {
    const schedule = readFileSync(resolve('src/views/data/ScheduleView.vue'), 'utf8')
    const ingest = readFileSync(resolve('src/views/data/IngestView.vue'), 'utf8')

    expect(ingest).toContain("'limit_ladder_recompute'")
    expect(ingest).toContain("'limit_ladder_invalidate'")
    expect(ingest).toContain('data-testid="limit-ladder-task-result"')
    expect(ingest).toContain("row.trigger_source === 'system'")
    expect(ingest).toContain('系统{{ row.job_name')
    expect(schedule).not.toContain('limit_ladder_recompute')
    expect(schedule).toContain('ResultMaintenanceTaskFields')
  })
})
