import type { Bar, IndicatorRow } from '@/api/stocks'

export type KlinePeriod = 'day' | 'week' | 'month' | 'year'

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

function ema(values: readonly (number | null)[], period: number): Array<number | null> {
  const alpha = 2 / (period + 1)
  let state: number | null = null
  let validCount = 0
  return values.map((value) => {
    if (value == null || !Number.isFinite(value)) return null
    state = state == null ? value : alpha * value + (1 - alpha) * state
    validCount += 1
    return validCount >= period ? state : null
  })
}

/** 与后端 compute_macd 的 adjust=false、min_periods 口径一致，仅用于周期图表派生展示。 */
export function computePeriodMacd(bars: readonly PeriodBar[]): IndicatorRow[] {
  const fast = ema(bars.map((bar) => bar.close), 12)
  const slow = ema(bars.map((bar) => bar.close), 26)
  const diff = fast.map((value, index) => (
    value == null || slow[index] == null ? null : value - slow[index]!
  ))
  const dea = ema(diff, 9)
  return bars.map((bar, index) => {
    const currentDiff = diff[index]
    const currentDea = dea[index]
    const previousDiff = diff[index - 1]
    const previousDea = dea[index - 1]
    const valid = currentDiff != null
      && currentDea != null
      && previousDiff != null
      && previousDea != null
    return {
      trade_date: bar.date,
      macd_diff: currentDiff,
      macd_dea: currentDea,
      macd_hist: currentDiff == null || currentDea == null
        ? null
        : 2 * (currentDiff - currentDea),
      macd_golden_cross: valid ? currentDiff > currentDea && previousDiff <= previousDea : null,
      macd_dead_cross: valid ? currentDiff < currentDea && previousDiff >= previousDea : null,
    }
  })
}

function samePeriod(left: PeriodBar | undefined, right: PeriodBar | undefined, period: KlinePeriod) {
  return Boolean(left && right && klinePeriodKey(left.date, period) === klinePeriodKey(right.date, period))
}

/**
 * 图表只公开一条周期变换入口：日 K 沿用后端指标；其它周期先独立聚合可见区间，
 * 再用暖机周期补足后向指标。范围边界落在周期中间时，可见首柱保持用户选择的严格范围。
 */
export function buildKlinePeriodSeries(
  bars: readonly Bar[],
  warmupBars: readonly Bar[],
  indicators: readonly IndicatorRow[],
  period: KlinePeriod,
): KlinePeriodSeries {
  const visible = aggregateKlineBars(bars, period)
  if (period === 'day') {
    return {
      bars: visible,
      warmupBars: aggregateKlineBars(warmupBars, period),
      indicators: [...indicators],
    }
  }

  const warmup = aggregateKlineBars(warmupBars, period)
  if (samePeriod(warmup.at(-1), visible[0], period)) warmup.pop()
  const allBars = [...warmup, ...visible]
  const allIndicators = computePeriodMacd(allBars)
  return {
    bars: visible,
    warmupBars: warmup,
    indicators: allIndicators.slice(warmup.length),
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
