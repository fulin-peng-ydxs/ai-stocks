import type { Bar, IndicatorRow } from '@/api/stocks'
import type { KlinePeriod } from '@/api/stocks'

export type { KlinePeriod } from '@/api/stocks'

export interface PeriodBar extends Bar {
  periodStartDate: string
  periodEndDate: string
  tradingDayCount: number
}

export interface KlinePeriodSeries {
  bars: PeriodBar[]
  warmupBars: PeriodBar[]
  indicators: IndicatorRow[]
}

export const KLINE_PERIOD_OPTIONS: Array<{ label: string; value: KlinePeriod }> = [
  { label: '日K', value: 'day' },
  { label: '周K', value: 'week' },
  { label: '月K', value: 'month' },
  { label: '年K', value: 'year' },
]

export const KLINE_PERIOD_LINE_LABELS: Record<KlinePeriod, string> = {
  day: '日线',
  week: '周线',
  month: '月线',
  year: '年线',
}

function dateParts(value: string): [number, number, number] | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) return null
  return [year, month, day]
}

/** 纯 UTC 日历运算，避免浏览器时区把周边界推到相邻日期。 */
export function klinePeriodKey(date: string, period: KlinePeriod): string {
  if (period === 'day') return date
  const parts = dateParts(date)
  if (!parts) return date
  const [year, month, day] = parts
  if (period === 'month') return `${year}-${String(month).padStart(2, '0')}`
  if (period === 'year') return String(year)

  const current = new Date(Date.UTC(year, month - 1, day))
  const weekday = current.getUTCDay() || 7
  current.setUTCDate(current.getUTCDate() + 4 - weekday)
  const isoYear = current.getUTCFullYear()
  const yearStart = new Date(Date.UTC(isoYear, 0, 1))
  const week = Math.ceil((((current.getTime() - yearStart.getTime()) / 86_400_000) + 1) / 7)
  return `${isoYear}-W${String(week).padStart(2, '0')}`
}

function finiteValues(values: Array<number | null | undefined>): number[] {
  return values.filter((value): value is number => value != null && Number.isFinite(value))
}

function nullableSum(values: Array<number | null | undefined>): number | null {
  const valid = finiteValues(values)
  return valid.length ? valid.reduce((sum, value) => sum + value, 0) : null
}

function aggregateGroup(group: readonly Bar[]): PeriodBar {
  const first = group[0]!
  const last = group[group.length - 1]!
  const highs = finiteValues(group.map((bar) => bar.high))
  const lows = finiteValues(group.map((bar) => bar.low))
  const preClose = group.find((bar) => bar.pre_close != null && Number.isFinite(bar.pre_close))
    ?.pre_close ?? null
  return {
    date: last.date,
    open: first.open,
    high: highs.length ? Math.max(...highs) : first.high,
    low: lows.length ? Math.min(...lows) : first.low,
    close: last.close,
    // 市值和股本是周期末存量，不能像成交额一样求和，也不能取周期内前一天填补缺口。
    ...(last.total_mv !== undefined ? { total_mv: last.total_mv } : {}),
    ...(last.float_mv !== undefined ? { float_mv: last.float_mv } : {}),
    ...(last.total_share !== undefined ? { total_share: last.total_share } : {}),
    ...(last.float_share !== undefined ? { float_share: last.float_share } : {}),
    ...(last.capital_evidence !== undefined ? { capital_evidence: last.capital_evidence } : {}),
    pre_close: preClose,
    // 接口类型保证日线 volume 为数值；这里仍保留运行时全缺失为空的聚合语义。
    volume: nullableSum(group.map((bar) => bar.volume)) as number,
    amount: nullableSum(group.map((bar) => bar.amount)),
    turnover_rate: nullableSum(group.map((bar) => bar.turnover_rate)),
    periodStartDate: first.date,
    periodEndDate: last.date,
    tradingDayCount: group.length,
  }
}

/** 把已经按交易日范围截断的日线聚合为自然周、月或年 K，保留当前未完成周期。 */
export function aggregateKlineBars(
  bars: readonly Bar[],
  period: KlinePeriod,
): PeriodBar[] {
  if (!bars.length) return []
  const sorted = [...bars].sort((left, right) => left.date.localeCompare(right.date))
  if (period === 'day') {
    return sorted.map((bar) => ({
      ...bar,
      periodStartDate: bar.date,
      periodEndDate: bar.date,
      tradingDayCount: 1,
    }))
  }
  const groups: Bar[][] = []
  let activeKey = ''
  for (const bar of sorted) {
    const key = klinePeriodKey(bar.date, period)
    if (key !== activeKey) {
      groups.push([])
      activeKey = key
    }
    groups.at(-1)!.push(bar)
  }
  return groups.map(aggregateGroup)
}

function samePeriod(left: PeriodBar | undefined, right: PeriodBar | undefined, period: KlinePeriod) {
  return Boolean(left && right && klinePeriodKey(left.date, period) === klinePeriodKey(right.date, period))
}

/**
 * 图表只负责周期 K 线聚合；指标由后端统一按同一周期计算后传入。
 * 范围边界落在周期中间时，可见首柱保持用户选择的严格范围。
 */
export function buildKlinePeriodSeries(
  bars: readonly Bar[],
  warmupBars: readonly Bar[],
  indicators: readonly IndicatorRow[],
  period: KlinePeriod,
): KlinePeriodSeries {
  const visible = aggregateKlineBars(bars, period)
  const warmup = aggregateKlineBars(warmupBars, period)
  if (samePeriod(warmup.at(-1), visible[0], period)) warmup.pop()
  return {
    bars: visible,
    warmupBars: warmup,
    indicators: [...indicators],
  }
}

/** 收盘到收盘的实际交易日间隔；日 K 下与索引差完全一致。 */
export function tradingDaysBetween(
  bars: readonly PeriodBar[],
  startIndex: number,
  endIndex: number,
): number {
  const start = Math.min(startIndex, endIndex)
  const end = Math.max(startIndex, endIndex)
  return bars.slice(start + 1, end + 1)
    .reduce((total, bar) => total + bar.tradingDayCount, 0)
}
