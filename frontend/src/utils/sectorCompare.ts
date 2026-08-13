// 板块对比指标口径：把 board_bar 收盘序列换算成「区间累计涨跌幅」（区间首日归 0）。
// 截面指标（即时净流入、涨跌家数）只有最新快照，由页面直接取 SectorRow 字段，不做折线；
// 「单日」是累计窗口=1 的退化形态，同样只有截面快照（今日涨跌），由页面取 pct_today 做柱状。
// 指标池与周期选项均为数据驱动（常量数组），便于后续把走势对比抽成可复用组件。
import type { SectorBar } from '@/api/sectors'
import { ALL_DAYS } from '@/composables/useKlinePrefs'

export type CompareMetric =
  | 'cum' | 'roll_5d' | 'roll_10d' | 'roll_20d' | 'inflow' | 'breadth'

export interface CompareMetricMeta {
  label: string
  kind: 'line' | 'bar'
  unit: string
  /** 趋势指标窗口：number=固定窗口；'dynamic'=跟随周期选择器。截面指标（bar）无窗口。 */
  window?: number | 'dynamic'
}

/** 指标池（顺序即头部槽位展示顺序）。 */
export const COMPARE_METRIC_ORDER: CompareMetric[] = [
  'cum', 'roll_5d', 'roll_10d', 'roll_20d', 'inflow', 'breadth',
]

export const COMPARE_METRIC_META: Record<CompareMetric, CompareMetricMeta> = {
  cum: { label: '累计涨跌', kind: 'line', unit: '%', window: 'dynamic' },
  roll_5d: { label: '5日涨幅', kind: 'line', unit: '%', window: 5 },
  roll_10d: { label: '10日涨幅', kind: 'line', unit: '%', window: 10 },
  roll_20d: { label: '20日涨幅', kind: 'line', unit: '%', window: 20 },
  inflow: { label: '即时净流入', kind: 'bar', unit: '亿' },
  breadth: { label: '涨/跌家数', kind: 'bar', unit: '家' },
}

/** 对比周期选项（数据驱动；「单日」窗口=1，仅累计涨跌可用，走柱状截面）。 */
export interface CompareRangeOption { label: string; value: number }
export const COMPARE_RANGE_OPTIONS: CompareRangeOption[] = [
  { label: '单日', value: 1 },
  { label: '5日', value: 5 },
  { label: '10日', value: 10 },
  { label: '20日', value: 20 },
  { label: '60日', value: 60 },
  { label: '120日', value: 120 },
  { label: '250日', value: 250 },
  { label: '全部', value: ALL_DAYS },
]

function pct(last: number, ref: number): number | null {
  if (!Number.isFinite(last) || !Number.isFinite(ref) || ref === 0) return null
  return +(((last - ref) / ref) * 100).toFixed(2)
}

/** 区间累计涨跌：以序列首个有效收盘为基准，(close_t / base - 1)。无效收盘（0/NaN）置 null。 */
function cumulativeSeries(bars: SectorBar[]): (number | null)[] {
  const base = bars.find((b) => Number.isFinite(b.close) && b.close !== 0)?.close
  if (base == null || base === 0) return bars.map(() => null)
  return bars.map((b) => (Number.isFinite(b.close) && b.close !== 0 ? pct(b.close, base) : null))
}

/** 把收盘序列换算成逐 bar 的区间累计涨跌幅（与输入 bars 同长同序）；截面指标无逐 bar 序列。 */
export function metricSeries(bars: SectorBar[], metric: CompareMetric): (number | null)[] {
  if (COMPARE_METRIC_META[metric].kind === 'bar') return bars.map(() => null)
  return cumulativeSeries(bars)
}

/** 指标有效窗口（交易日）：dynamic 跟随周期选择器，固定窗口返回自身。 */
export function metricWindow(metric: CompareMetric, rangeDays: number): number {
  const w = COMPARE_METRIC_META[metric].window
  if (w === 'dynamic') return rangeDays
  if (typeof w === 'number') return w
  return rangeDays
}

/** 指标渲染形态：截面指标恒为柱状；累计涨跌窗口=1（单日）退化为柱状截面。 */
export function metricKind(metric: CompareMetric, rangeDays: number): 'line' | 'bar' {
  const meta = COMPARE_METRIC_META[metric]
  if (meta.kind === 'bar') return 'bar'
  if (metric === 'cum' && rangeDays === 1) return 'bar'
  return 'line'
}
