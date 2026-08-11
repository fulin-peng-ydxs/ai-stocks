// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest'
import {
  ALL_DAYS,
  klineRangeQueryStart,
  trimAlignedKlineRange,
  trimKlineRange,
  useKlinePrefs,
} from '@/composables/useKlinePrefs'

describe('useKlinePrefs', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('读取旧 localStorage fallback 并保持原接口', () => {
    localStorage.setItem('ai-stocks:kline-prefs', JSON.stringify({
      periods: [30, 90],
      includeAll: false,
      defaultPeriod: 90,
    }))

    const { prefs, options, validDefault } = useKlinePrefs()

    expect(prefs.periods).toEqual([30, 90])
    expect(options.value).toEqual([
      { value: 30, label: '近 30 日' },
      { value: 90, label: '近 90 日' },
    ])
    expect(validDefault.value).toBe(90)
  })

  it('重置后恢复默认范围和全部选项', () => {
    const { prefs, options, reset } = useKlinePrefs()
    prefs.includeAll = false
    reset()

    expect(prefs.periods).toEqual([60, 120, 250])
    expect(prefs.defaultPeriod).toBe(120)
    expect(options.value.at(-1)).toEqual({ value: ALL_DAYS, label: '全部' })
  })

  it('快捷周期截断数据边界，只有全部保留完整历史', () => {
    const rows = Array.from({ length: 600 }, (_, index) => index)
    expect(trimKlineRange(rows, 120)).toEqual(rows.slice(-120))
    expect(trimKlineRange(rows, ALL_DAYS)).toEqual(rows)
    expect(klineRangeQueryStart('2026-08-07', 60, '2021-01-01')).toBe('2026-04-09')
    expect(klineRangeQueryStart('2026-08-07', ALL_DAYS, '2021-01-01')).toBe('2021-01-01')
  })

  it('多条走势按同一组交易日对齐截断', () => {
    const series = {
      a: [{ trade_date: '01' }, { trade_date: '02' }, { trade_date: '04' }],
      b: [{ trade_date: '01' }, { trade_date: '03' }, { trade_date: '04' }],
    }

    expect(trimAlignedKlineRange(series, 2)).toEqual({
      a: [{ trade_date: '04' }],
      b: [{ trade_date: '03' }, { trade_date: '04' }],
    })
  })
})
