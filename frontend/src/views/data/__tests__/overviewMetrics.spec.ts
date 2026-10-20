import { describe, expect, it } from 'vitest'
import type { Overview } from '@/api/data'
import { overviewMetrics, intradayCoverageText } from '../overviewMetrics'

function fixture(overrides: Partial<Overview> = {}): Overview {
  return {
    latest_trade_date: '2026-10-19', codes: { active: 2, delisted: 0 }, bar_rows: 4,
    quality: { score: 100, open: 0, by_severity: {}, by_layer: [] },
    gaps: { stocks_with_gap: 0, gap_days_total: 0, latest_trade_date: '2026-10-19' },
    last_scan_at: null, st_status: undefined as unknown as Overview['st_status'],
    ...overrides,
  }
}

describe('概览信息层级', () => {
  it('单纯定义使用问号帮助，有额外事实分项的指标使用信息详情', () => {
    const metrics = overviewMetrics(fixture())
    expect(metrics.filter((item) => item.info.kind === 'help').map((item) => item.key))
      .toEqual(['latestTradeDate', 'codes', 'barRows', 'score'])
    expect(metrics.filter((item) => item.info.kind === 'details').map((item) => item.key))
      .toEqual(['intraday', 'stStatus', 'board', 'quality', 'gaps'])
  })

  it('逐股表只摘要覆盖状态，完整与空归档不会伪装成异常入口', () => {
    const coverage = { complete_days: 8, partial_days: 0, missing_days: 0, monitoring_start: null, target_end: null, archive_end: null }
    expect(intradayCoverageText(coverage)).toBe('完整 8 日')
    coverage.partial_days = 2
    expect(intradayCoverageText(coverage)).toBe('部分 2 日')
    coverage.missing_days = 1
    expect(intradayCoverageText(coverage)).toBe('缺失 1 日')
    expect(intradayCoverageText({ ...coverage, complete_days: 0, partial_days: 0, missing_days: 0 })).toBe('暂无归档')
  })
  it('只常驻目标日覆盖，累计覆盖与归档日期保留在详情', () => {
    const intraday = {
      stocks: 2, bar_rows: 720, monitoring_start: '2026-10-16', target_end: '2026-10-19',
      archive_end: '2026-10-19', complete_days: 3, partial_days: 1, missing_days: 0,
      latest_complete_stocks: 1, latest_expected_stocks: 2,
    }
    const metric = overviewMetrics(fixture({ intraday })).find((item) => item.key === 'intraday')!
    expect(metric.summary).toBe('目标日完整 50%')
    expect(metric.info.kind).toBe('details')
    if (metric.info.kind !== 'details') throw new Error('分时应提供事实明细')
    expect(metric.info.rows).toContainEqual({ label: '目标日完整 / 应采', value: '1 / 2 只' })
    expect(metric.info.rows).toContainEqual({ label: '累计缺失', value: '0 个股票交易日' })
    expect(metric.info.rows).toContainEqual({ label: '监控起点', value: '2026-10-16' })
    expect(metric.action).toBe('stocks')
    intraday.missing_days = 4
    expect(overviewMetrics(fixture({ intraday })).find((item) => item.key === 'intraday')?.action).toBe('stocks')
  })

  it('区别未知、未监控、没有应采日期与真实零值', () => {
    const get = (ov: Overview | null) => overviewMetrics(ov).find((item) => item.key === 'intraday')!
    expect(get(null)).toMatchObject({ value: '—', summary: '尚无统计', action: undefined })
    const intraday = { stocks: 0, bar_rows: 0, monitoring_start: null, target_end: null, archive_end: null, complete_days: 0, partial_days: 0, missing_days: 0 }
    expect(get(fixture({ intraday }))).toMatchObject({ value: '0', summary: '尚未开始监控', action: 'intraday-ingest' })
    intraday.stocks = 1
    expect(get(fixture({ intraday }))).toMatchObject({ summary: '尚无应采目标日', action: 'stocks' })
  })

  it('按最高现存严重程度摘要，不在高危为零时掩盖中危问题', () => {
    const metrics = overviewMetrics(fixture({ quality: { score: 100, open: 7, by_severity: { high: 0, mid: 6, low: 1 }, by_layer: [] } }))
    expect(metrics.find((item) => item.key === 'quality')).toMatchObject({ summary: '中危 6 项', tone: 'warning' })
    expect(metrics.find((item) => item.key === 'score')).toMatchObject({ value: '100', tone: 'success' })
  })
})
