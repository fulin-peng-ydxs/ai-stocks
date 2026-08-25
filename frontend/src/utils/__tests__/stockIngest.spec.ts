import { describe, expect, it } from 'vitest'
import {
  buildStockIngestParams,
  createStockIngestForm,
  isHeavyStockIngestRecipe,
  stockIngestFormFromTask,
  stockIngestSummary,
} from '@/utils/stockIngest'

describe('stock ingest shared form contract', () => {
  it('builds selected range refetch params', () => {
    const form = createStockIngestForm({
      recipe: 'range_refetch', scope: 'selected', codes: ['600000.SH'],
      date_start: '2026-08-01', date_end: '2026-08-02', concurrency: 2,
    })
    expect(buildStockIngestParams(form)).toEqual({
      params: {
        recipe: 'range_refetch', codes: ['600000.SH'], date_start: '2026-08-01',
        date_end: '2026-08-02', concurrency: 2,
      },
    })
    expect(stockIngestSummary(form)).toContain('1 只指定股票')
  })

  it('rejects an empty selected scope and reversed dates', () => {
    expect(buildStockIngestParams(createStockIngestForm({ scope: 'selected' })).error).toContain('至少选择')
    expect(buildStockIngestParams(createStockIngestForm({
      recipe: 'range_refetch', date_start: '2026-08-02', date_end: '2026-08-01',
    })).error).toContain('不得早于')
    expect(buildStockIngestParams(createStockIngestForm({ concurrency: 0 })).error).toContain('1–16')
    expect(buildStockIngestParams(createStockIngestForm({
      recipe: 'history_backfill', years: 31,
    })).error).toContain('1–30')
  })

  it('maps legacy scheduled jobs into the unified model', () => {
    expect(stockIngestFormFromTask('update', {})?.recipe).toBe('daily_update')
    expect(stockIngestFormFromTask('backfill', { years: 5 })?.years).toBe(5)
    expect(stockIngestFormFromTask('ingest_date', {
      date_start: '2026-08-01', codes: ['600000.SH'],
    })).toMatchObject({
      recipe: 'range_refetch', scope: 'selected', codes: ['600000.SH'],
    })
  })

  it('warns for every potentially heavy ingest recipe', () => {
    expect(isHeavyStockIngestRecipe('history_backfill')).toBe(true)
    expect(isHeavyStockIngestRecipe('range_refetch')).toBe(true)
    expect(isHeavyStockIngestRecipe('valuation_history')).toBe(true)
    expect(isHeavyStockIngestRecipe('delisted_history')).toBe(true)
    expect(isHeavyStockIngestRecipe('daily_update')).toBe(false)
  })
})
