import { ALL_DAYS } from '@/composables/useKlinePrefs'

export type PriceCompareMetric =
  | 'cum' | 'roll_5d' | 'roll_10d' | 'roll_20d' | 'roll_30d' | 'roll_60d'

export interface PriceCompareMetricMeta {
  label: string
  window: number | 'dynamic'
}

export interface PricePoint {
  date: string
  close: number
}

export interface PriceCompareSeries {
  code: string
  name: string
  bars: PricePoint[]
}

export const PRICE_COMPARE_METRIC_ORDER: PriceCompareMetric[] = [
  'cum', 'roll_5d', 'roll_10d', 'roll_20d', 'roll_30d', 'roll_60d',
]

export const PRICE_COMPARE_METRIC_META: Record<PriceCompareMetric, PriceCompareMetricMeta> = {
  cum: { label: '累计涨跌', window: 'dynamic' },
  roll_5d: { label: '5日涨幅', window: 5 },
  roll_10d: { label: '10日涨幅', window: 10 },
  roll_20d: { label: '20日涨幅', window: 20 },
  roll_30d: { label: '30日涨幅', window: 30 },
  roll_60d: { label: '60日涨幅', window: 60 },
}

export const MARKET_BENCHMARK_OPTIONS = [
  { label: '不对比指数', value: '' },
  { label: '中证 500', value: '000905.SH' },
  { label: '沪深 300', value: '000300.SH' },
]

export interface AlignedPriceComparison {
  dates: string[]
  valuesByCode: Record<string, (number | null)[]>
  closesByCode: Record<string, (number | null)[]>
}

export function isPriceCompareMetric(value: unknown): value is PriceCompareMetric {
  return PRICE_COMPARE_METRIC_ORDER.includes(value as PriceCompareMetric)
}

/** N 日涨幅需要 N+1 个收盘点；固定指标条始终需要至少 61 点。 */
export function priceCompareLookback(metric: PriceCompareMetric, rangeDays: number): number {
  if (metric === 'cum' && rangeDays === ALL_DAYS) return 6000
  const window = priceMetricWindow(metric, rangeDays)
  return Math.max(window + 1, 61)
}

/** 同一指标条一次加载覆盖所有可见卡片，避免切换指标后其它卡片因请求窗口偏短而变空。 */
export function priceCompareSetLookback(
  metrics: readonly PriceCompareMetric[],
  rangeDays: number,
): number {
  return Math.max(...metrics.map((metric) => priceCompareLookback(metric, rangeDays)), 61)
}

export function priceMetricWindow(metric: PriceCompareMetric, rangeDays: number): number {
  const window = PRICE_COMPARE_METRIC_META[metric].window
  return window === 'dynamic' ? rangeDays : window
}

function validClose(value: number): boolean {
  return Number.isFinite(value) && value > 0
}

function calendarDates(series: readonly PriceCompareSeries[], calendar?: readonly PricePoint[]): string[] {
  if (calendar !== undefined) {
    return Array.from(new Set(calendar.filter((bar) => validClose(bar.close)).map((bar) => bar.date))).sort()
  }
  return Array.from(new Set(series.flatMap((item) => item.bars
    .filter((bar) => validClose(bar.close))
    .map((bar) => bar.date)))).sort()
}

/**
 * 按统一市场日期轴前向延续停牌期间的最后有效收盘；上市前保持 null。
 * 所有曲线随后从首个共同有效日期归零，避免不同基期计算伪超额。
 */
function alignCloses(bars: readonly PricePoint[], dates: readonly string[]): (number | null)[] {
  const ordered = [...bars]
    .filter((bar) => validClose(bar.close))
    .sort((left, right) => left.date.localeCompare(right.date))
  let cursor = 0
  let latest: number | null = null
  return dates.map((date) => {
    while (cursor < ordered.length && ordered[cursor]!.date <= date) {
      latest = ordered[cursor]!.close
      cursor += 1
    }
    return latest
  })
}

export function alignPriceComparison(
  series: readonly PriceCompareSeries[],
  window: number,
  benchmark?: PriceCompareSeries | null,
  calendar?: readonly PricePoint[],
): AlignedPriceComparison {
  const participants = benchmark ? [...series, benchmark] : [...series]
  if (!participants.length) return { dates: [], valuesByCode: {}, closesByCode: {} }
  const allDates = calendarDates(participants, calendar ?? benchmark?.bars)
  const requestedDates = window === ALL_DAYS ? allDates : allDates.slice(-(window + 1))
  const aligned = Object.fromEntries(participants.map((item) => [
    item.code,
    alignCloses(item.bars, requestedDates),
  ])) as Record<string, (number | null)[]>
  const commonStart = requestedDates.findIndex((_, index) => (
    participants.every((item) => aligned[item.code]?.[index] != null)
  ))
  const requiresCompleteWindow = window !== ALL_DAYS
  if (
    commonStart < 0
    || (requiresCompleteWindow && requestedDates.length < window + 1)
    || (requiresCompleteWindow && commonStart !== 0)
  ) {
    return { dates: [], valuesByCode: {}, closesByCode: {} }
  }
  const dates = requestedDates.slice(commonStart)
  const closesByCode: Record<string, (number | null)[]> = {}
  const valuesByCode: Record<string, (number | null)[]> = {}
  for (const item of participants) {
    const closes = (aligned[item.code] ?? []).slice(commonStart)
    const base = closes[0]
    closesByCode[item.code] = closes
    valuesByCode[item.code] = base == null || base === 0
      ? closes.map(() => null)
      : closes.map((close) => close == null ? null : +((close / base - 1) * 100).toFixed(2))
  }
  return { dates, valuesByCode, closesByCode }
}

/** 当前观察对象在统一市场日期轴上的 N 日收益；历史不足不缩短周期代算。 */
export function priceReturn(
  series: PriceCompareSeries | null | undefined,
  window: number,
  calendar?: readonly PricePoint[],
): number | null {
  if (!series) return null
  const allDates = calendarDates([series], calendar)
  const dates = window === ALL_DAYS ? allDates : allDates.slice(-(window + 1))
  if (dates.length < (window === ALL_DAYS ? 2 : window + 1)) return null
  const closes = alignCloses(series.bars, dates)
  const first = closes[0]
  const last = closes[closes.length - 1]
  if (first == null || last == null || first === 0) return null
  return +((last / first - 1) * 100).toFixed(2)
}
