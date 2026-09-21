import { computed, toValue, type MaybeRefOrGetter, type Ref } from 'vue'
import { ALL_DAYS } from '@/composables/useKlinePrefs'
import { useDefaultedSessionValue } from '@/composables/useDefaultedSessionValue'
import { normalizeMarketBenchmarkCode } from '@/utils/marketBenchmarks'
import {
  PRICE_COMPARE_METRIC_ORDER,
  isPriceCompareMetric,
  type PriceCompareMetric,
} from '@/utils/marketCompare'

export type StockAnalysisMode = 'compare' | 'kline'
export type StockAdjustMode = '' | 'qfq' | 'hfq'

export interface StockAnalysisComponentPreferences {
  defaultChartMode: StockAnalysisMode
  showAnalysisPanel: boolean
  compareRange: number
  benchmarkCode: string
  compareMetrics: PriceCompareMetric[]
  defaultCompareMetric: PriceCompareMetric
}

export function createDefaultStockAnalysisPreferences(
  overrides: Partial<StockAnalysisComponentPreferences> = {},
): StockAnalysisComponentPreferences {
  return {
    defaultChartMode: 'compare',
    showAnalysisPanel: true,
    compareRange: 60,
    benchmarkCode: '000905.SH',
    compareMetrics: [...PRICE_COMPARE_METRIC_ORDER],
    defaultCompareMetric: 'cum',
    ...overrides,
  }
}

export const STOCK_COMPARE_RANGES = [5, 10, 20, 60, 120, 250, ALL_DAYS] as const

export interface StockAnalysisDefaults {
  defaultChartMode: unknown
  showAnalysisPanel: unknown
  compareRange: unknown
  benchmarkCode?: unknown
  compareMetrics?: unknown
  defaultCompareMetric?: unknown
  adjustMode?: unknown
}

function normalizeCompareRange(value: unknown): number {
  const candidate = Number(value)
  return (STOCK_COMPARE_RANGES as readonly number[]).includes(candidate) ? candidate : 60
}

export function normalizeStockAnalysisPreferences(
  value: unknown,
  fallback: StockAnalysisComponentPreferences = createDefaultStockAnalysisPreferences(),
): StockAnalysisComponentPreferences {
  const input = value && typeof value === 'object' && !Array.isArray(value)
    ? value as Partial<Record<keyof StockAnalysisComponentPreferences, unknown>>
    : {}
  const compareMetrics = PRICE_COMPARE_METRIC_ORDER.filter((metric) => (
    Array.isArray(input.compareMetrics) && input.compareMetrics.includes(metric)
  ))
  const visibleMetrics = compareMetrics.length ? compareMetrics : [...fallback.compareMetrics]
  const defaultCompareMetric = isPriceCompareMetric(input.defaultCompareMetric)
    && visibleMetrics.includes(input.defaultCompareMetric)
    ? input.defaultCompareMetric
    : visibleMetrics[0] ?? fallback.defaultCompareMetric
  return {
    defaultChartMode: input.defaultChartMode === 'kline' || input.defaultChartMode === 'compare'
      ? input.defaultChartMode
      : fallback.defaultChartMode,
    showAnalysisPanel: typeof input.showAnalysisPanel === 'boolean'
      ? input.showAnalysisPanel
      : fallback.showAnalysisPanel,
    compareRange: (STOCK_COMPARE_RANGES as readonly number[]).includes(Number(input.compareRange))
      ? Number(input.compareRange)
      : fallback.compareRange,
    benchmarkCode: normalizeMarketBenchmarkCode(input.benchmarkCode ?? fallback.benchmarkCode),
    compareMetrics: visibleMetrics,
    defaultCompareMetric,
  }
}

function normalizeAdjustMode(value: unknown): StockAdjustMode {
  return value === 'hfq' || value === '' ? value : 'qfq'
}

/** 单独使用统一复权默认值时仍走同一标准化与单向会话投影。 */
export function useStockAdjustModeSession(settings: { adjustMode?: unknown }) {
  const configuredAdjustMode = computed(() => normalizeAdjustMode(settings.adjustMode))
  return useDefaultedSessionValue(configuredAdjustMode)
}

/**
 * 将设置抽屉与全局 K 线默认值单向投影为行情分析会话态。
 * 主区只修改返回的 ref，不反写长期默认；远端水合或抽屉修改仍会更新当前会话。
 */
export function useStockAnalysisSession(
  settings: MaybeRefOrGetter<StockAnalysisDefaults>,
  klineDefaultRange: Readonly<Ref<number>>,
) {
  const current = () => toValue(settings)
  const configuredMode = computed<StockAnalysisMode>(() => (
    current().defaultChartMode === 'kline' ? 'kline' : 'compare'
  ))
  const configuredCompareRange = computed(() => normalizeCompareRange(current().compareRange))
  const configuredPanelVisible = computed(() => current().showAnalysisPanel !== false)
  const visibleCompareMetrics = computed<PriceCompareMetric[]>(() => {
    const raw = current().compareMetrics
    const configured: unknown[] = Array.isArray(raw) ? raw : []
    const result = PRICE_COMPARE_METRIC_ORDER.filter((metric) => configured.includes(metric))
    return result.length ? result : [...PRICE_COMPARE_METRIC_ORDER]
  })
  const configuredCompareMetric = computed<PriceCompareMetric>(() => {
    const raw = current().defaultCompareMetric
    const candidate = isPriceCompareMetric(raw)
      ? raw
      : 'cum'
    return visibleCompareMetrics.value.includes(candidate)
      ? candidate
      : visibleCompareMetrics.value[0] ?? 'cum'
  })
  const configuredBenchmarkCode = computed(() => normalizeMarketBenchmarkCode(current().benchmarkCode))

  return {
    analysisPanelVisible: useDefaultedSessionValue(configuredPanelVisible),
    chartMode: useDefaultedSessionValue(configuredMode),
    compareRange: useDefaultedSessionValue(configuredCompareRange),
    compareMetric: useDefaultedSessionValue(configuredCompareMetric),
    benchmarkCode: useDefaultedSessionValue(configuredBenchmarkCode),
    adjustMode: useStockAdjustModeSession({
      get adjustMode() { return current().adjustMode },
    }),
    visibleCompareMetrics,
    klineRange: useDefaultedSessionValue(klineDefaultRange),
  }
}
