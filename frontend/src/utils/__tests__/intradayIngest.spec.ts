import { describe, expect, it } from 'vitest'
import { buildIntradayIngestParams, createIntradayIngestForm } from '@/utils/intradayIngest'
import { ISSUE_LAYER, ISSUE_TYPES_ACTIVE, taskDisplayLabel } from '@/api/data'

describe('分时手动和调度参数', () => {
  it('默认全市场近期补采，切回增量不发送旧日期', () => {
    expect(buildIntradayIngestParams(createIntradayIngestForm()).params).toEqual({ mode: 'update' })
    expect(buildIntradayIngestParams({ ...createIntradayIngestForm(), date_start: '2026-09-10' }).params)
      .toEqual({ mode: 'update' })
  })
  it('指定股票不得为空，重采校验日期范围', () => {
    expect(buildIntradayIngestParams({ ...createIntradayIngestForm(), scope: 'selected' }).error).toBeTruthy()
    expect(buildIntradayIngestParams(createIntradayIngestForm({ mode: 'refetch' })).error).toBeTruthy()
    expect(buildIntradayIngestParams(createIntradayIngestForm({
      mode: 'refetch', date_start: '2026-09-10', date_end: '2026-09-09',
    })).error).toBeTruthy()
    expect(buildIntradayIngestParams(createIntradayIngestForm({
      mode: 'refetch', date_start: '2026-09-10', codes: ['600000.SH'],
    })).params).toEqual({ mode: 'refetch', date_start: '2026-09-10', date_end: '2026-09-10', codes: ['600000.SH'] })
  })
  it('独立任务和质量层接线', () => {
    expect(taskDisplayLabel('intraday_ingest', { mode: 'refetch' })).toBe('分时采集·日期区间重采')
    expect(taskDisplayLabel('intraday_ingest')).toBe('分时采集·近期增量补采')
    expect(ISSUE_TYPES_ACTIVE).toContain('intraday_gap')
    expect(ISSUE_LAYER.intraday_partial).toBe('分时')
  })
  it('对象选择往返兼容旧任务，并透传到采集和调度', () => {
    expect(createIntradayIngestForm().asset_type).toBe('all')
    expect(buildIntradayIngestParams(createIntradayIngestForm({ asset_type: 'index' })).params)
      .toEqual({ mode: 'update', asset_type: 'index' })
    expect(createIntradayIngestForm({ asset_type: 'stock', codes: ['600000.SH'] }))
      .toMatchObject({ asset_type: 'stock', scope: 'selected' })
  })
})
