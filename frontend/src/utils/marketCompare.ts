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
 * 相对涨跌归零基准随对比模式划分：对比指数时统一到首个共同有效日期，
 * 纯股票/板块间对比时各自从自身首个有效值起算（见 alignPriceComparison）。
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

/** 每序列从自身首个有效收盘起算的 ×100% 相对涨跌；首个有效值之前留空（gap），停牌期冻结（0%）。 */
function computeRelativeValues(closes: readonly (number | null)[]): (number | null)[] {
  const firstIndex = closes.findIndex((close) => close != null)
  const base = firstIndex >= 0 ? closes[firstIndex] : null
  return base == null || base === 0
    ? closes.map(() => null)
    : closes.map((close) => close == null ? null : (close / base - 1) * 100)
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

  // 对比指数：超额收益须统一基期，基期不同会算出伪超额。统一从首个共同有效日期起算，
  // 个别序列上市较晚只缩短基准期、不否决整体；只有连一个共同有效日期都没有才判不可比。
  if (benchmark) {
    const activeParticipants = participants.filter((item) =>
      (aligned[item.code] ?? []).some((value) => value != null))
    if (!activeParticipants.length) return { dates: [], valuesByCode: {}, closesByCode: {} }
    const commonStart = requestedDates.findIndex((_, index) => (
      activeParticipants.every((item) => aligned[item.code]?.[index] != null)
    ))
    if (commonStart < 0) return { dates: [], valuesByCode: {}, closesByCode: {} }
    const dates = requestedDates.slice(commonStart)
    const closesByCode: Record<string, (number | null)[]> = {}
    const valuesByCode: Record<string, (number | null)[]> = {}
    for (const item of participants) {
      const closes = (aligned[item.code] ?? []).slice(commonStart)
      closesByCode[item.code] = closes
      valuesByCode[item.code] = computeRelativeValues(closes)
    }
    return { dates, valuesByCode, closesByCode }
  }

  // 纯股票/板块间对比：无超额概念，各序列从自身首个有效值起算，
  // 上市前/缺数据留空（gap），停牌前向延续（0% 涨幅）。不因个别序列缺起点而否决整体。
  const closesByCode: Record<string, (number | null)[]> = {}
  const valuesByCode: Record<string, (number | null)[]> = {}
  for (const item of participants) {
    const closes = aligned[item.code] ?? []
    closesByCode[item.code] = closes
    valuesByCode[item.code] = computeRelativeValues(closes)
  }
  return { dates: requestedDates, valuesByCode, closesByCode }
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
  return (last / first - 1) * 100
}
