import { describe, expect, it } from 'vitest'
import {
  buildResultMaintenanceTaskParams,
  consumeResultMaintenanceScheduleIntent,
  createResultMaintenanceTaskForm,
  queueResultMaintenanceScheduleIntent,
  resultMaintenanceTaskFormFromParams,
} from '@/utils/resultMaintenanceTask'

describe('result maintenance task params', () => {
  it('forces correlation recomputation and keeps explicit scope', () => {
    const form = createResultMaintenanceTaskForm({
      target_mode: 'fixed',
      trade_date: '2026-08-28',
      stock_scope: 'selected',
      codes: ['600000.SH'],
    })
    expect(buildResultMaintenanceTaskParams('stock_board_correlation', form)).toEqual({
      params: { force: true, trade_date: '2026-08-28', codes: ['600000.SH'] },
    })
  })

  it('keeps ladder and board invalidation as explicit target actions', () => {
    expect(buildResultMaintenanceTaskParams(
      'limit_ladder_invalidate',
      createResultMaintenanceTaskForm({ target_mode: 'fixed', trade_date: '2026-08-28' }),
    )).toEqual({ params: { target_mode: 'fixed', trade_date: '2026-08-28' } })
    expect(buildResultMaintenanceTaskParams(
      'limit_ladder_invalidate',
      createResultMaintenanceTaskForm({ target_mode: 'all' }),
    )).toEqual({ error: '该结果维护任务不支持全部快照范围' })
    expect(buildResultMaintenanceTaskParams(
      'recompute',
      createResultMaintenanceTaskForm({ target_mode: 'fixed', trade_date: '2026-08-28' }),
    )).toEqual({ params: { target_mode: 'fixed', trade_date: '2026-08-28' } })
  })

  it('restores persisted maintenance params for schedule editing', () => {
    expect(resultMaintenanceTaskFormFromParams('recompute', {
      target_mode: 'fixed', trade_date: '2026-08-28',
    })).toMatchObject({ target_mode: 'fixed', trade_date: '2026-08-28' })
    expect(resultMaintenanceTaskFormFromParams('stock_board_correlation', {
      codes: ['000001.SZ'], force: true,
    })).toMatchObject({ target_mode: 'latest', stock_scope: 'selected', codes: ['000001.SZ'] })
  })

  it('consumes schedule creation intent only once', () => {
    queueResultMaintenanceScheduleIntent('limit_ladder_invalidate')
    expect(consumeResultMaintenanceScheduleIntent()).toBe('limit_ladder_invalidate')
    expect(consumeResultMaintenanceScheduleIntent()).toBeNull()
  })
})
