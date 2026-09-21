import { normalizeMarketBenchmarkCode } from '@/utils/marketBenchmarks'
import {
  COMPARE_METRIC_ORDER,
  COMPARE_RANGE_OPTIONS,
  type CompareMetric,
} from '@/utils/sectorCompare'

export interface SectorAnalysisComponentPreferences {
  defaultChartMode: 'compare' | 'kline'
  showAnalysisPanel: boolean
  benchmarkCode: string
  compareMetrics: CompareMetric[]
  defaultCompareMetric: CompareMetric
  compareWindow: number
}

export function createDefaultSectorAnalysisPreferences(
  overrides: Partial<SectorAnalysisComponentPreferences> = {},
): SectorAnalysisComponentPreferences {
  return {
    defaultChartMode: 'compare',
    showAnalysisPanel: true,
    benchmarkCode: '000905.SH',
    compareMetrics: [...COMPARE_METRIC_ORDER],
    defaultCompareMetric: 'cum',
    compareWindow: 250,
    ...overrides,
  }
}

export function normalizeSectorAnalysisPreferences(
  value: unknown,
): SectorAnalysisComponentPreferences {
  const fallback = createDefaultSectorAnalysisPreferences()
  const input = value && typeof value === 'object' && !Array.isArray(value)
    ? value as Partial<Record<keyof SectorAnalysisComponentPreferences, unknown>>
    : {}
  const compareMetrics = COMPARE_METRIC_ORDER.filter((metric) => (
    Array.isArray(input.compareMetrics) && input.compareMetrics.includes(metric)
  ))
  const visibleMetrics = compareMetrics.length ? compareMetrics : [...fallback.compareMetrics]
  const requestedDefault = String(input.defaultCompareMetric ?? '') as CompareMetric
  return {
    defaultChartMode: input.defaultChartMode === 'kline' ? 'kline' : 'compare',
    showAnalysisPanel: typeof input.showAnalysisPanel === 'boolean'
      ? input.showAnalysisPanel
      : fallback.showAnalysisPanel,
    benchmarkCode: normalizeMarketBenchmarkCode(input.benchmarkCode ?? fallback.benchmarkCode),
    compareMetrics: visibleMetrics,
    defaultCompareMetric: visibleMetrics.includes(requestedDefault)
      ? requestedDefault
      : visibleMetrics[0] ?? fallback.defaultCompareMetric,
    compareWindow: COMPARE_RANGE_OPTIONS.some((option) => option.value === Number(input.compareWindow))
      ? Number(input.compareWindow)
      : fallback.compareWindow,
  }
}
