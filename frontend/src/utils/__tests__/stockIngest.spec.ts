import { describe, expect, it } from 'vitest'
import {
  buildStockIngestParams,
  createStockIngestForm,
  isHeavyStockIngestRecipe,
  STOCK_INGEST_RECIPE_OPTIONS,
  stockIngestFormFromTask,
} from '@/utils/stockIngest'

describe('stock ingest shared form contract', () => {
  it('builds resumable share capital history params', () => {
    expect(buildStockIngestParams(createStockIngestForm({
      recipe: 'share_capital_history', years: 10, concurrency: 4,
      scope: 'selected', codes: ['600000.SH'],
    })).params).toEqual({recipe: 'share_capital_history', years: 10,
      concurrency: 4, codes: ['600000.SH']})
  })

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

  it('only submits force-current-day for daily updates', () => {
    const daily = createStockIngestForm({ force_current_day: true })
    expect(buildStockIngestParams(daily).params).toMatchObject({
      recipe: 'daily_update', force_current_day: true,
    })

    const history = createStockIngestForm({
      recipe: 'history_backfill', force_current_day: true,
    })
    expect(buildStockIngestParams(history).params).not.toHaveProperty('force_current_day')
  })

  it('maps legacy scheduled jobs into the unified model', () => {
    expect(stockIngestFormFromTask('update', {})?.recipe).toBe('daily_update')
    expect(stockIngestFormFromTask('update', { force_current_day: true })?.force_current_day).toBe(true)
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
    expect(isHeavyStockIngestRecipe('valuation_invalid_history')).toBe(true)
    expect(isHeavyStockIngestRecipe('delisted_history')).toBe(true)
    expect(isHeavyStockIngestRecipe('daily_update')).toBe(false)
  })

  it('builds full-history and scoped ST refresh params', () => {
    const full = createStockIngestForm({ recipe: 'st_status_refresh' })
    expect(buildStockIngestParams(full)).toEqual({ params: { recipe: 'st_status_refresh' } })
    expect(isHeavyStockIngestRecipe('st_status_refresh')).toBe(true)
    const option = STOCK_INGEST_RECIPE_OPTIONS.find((item) => item.value === 'st_status_refresh')
    expect(option?.description).toContain('不覆盖行情价格')
    expect(option?.description).toContain('采集不直接失效结果')
    expect(option?.description).toContain('读取时按 ST 版本自检')

    const scoped = createStockIngestForm({
      recipe: 'st_status_refresh', scope: 'selected', codes: ['601919.SH'],
      date_start: '2026-07-03', date_end: '2026-07-06',
    })
    expect(buildStockIngestParams(scoped)).toEqual({ params: {
      recipe: 'st_status_refresh', codes: ['601919.SH'],
      date_start: '2026-07-03', date_end: '2026-07-06',
    } })
  })
})
