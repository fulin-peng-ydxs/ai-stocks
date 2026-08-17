import { computed, type Ref } from 'vue'
import { ALL_DAYS } from '@/composables/useKlinePrefs'
import { useDefaultedSessionValue } from '@/composables/useDefaultedSessionValue'

export type StockAnalysisMode = 'compare' | 'kline'

export const STOCK_COMPARE_RANGES = [5, 10, 20, 60, 120, 250, ALL_DAYS] as const

export interface StockAnalysisDefaults {
  defaultChartMode: unknown
  showAnalysisPanel: unknown
  compareRange: unknown
}

function normalizeCompareRange(value: unknown): number {
  const candidate = Number(value)
  return (STOCK_COMPARE_RANGES as readonly number[]).includes(candidate) ? candidate : 60
}

/**
 * 将设置抽屉与全局 K 线默认值单向投影为行情分析会话态。
 * 主区只修改返回的 ref，不反写长期默认；远端水合或抽屉修改仍会更新当前会话。
 */
export function useStockAnalysisSession(
  settings: StockAnalysisDefaults,
  klineDefaultRange: Readonly<Ref<number>>,
) {
  const configuredMode = computed<StockAnalysisMode>(() => (
    settings.defaultChartMode === 'kline' ? 'kline' : 'compare'
  ))
  const configuredCompareRange = computed(() => normalizeCompareRange(settings.compareRange))
  const configuredPanelVisible = computed(() => settings.showAnalysisPanel !== false)

  return {
    analysisPanelVisible: useDefaultedSessionValue(configuredPanelVisible),
    chartMode: useDefaultedSessionValue(configuredMode),
    compareRange: useDefaultedSessionValue(configuredCompareRange),
    klineRange: useDefaultedSessionValue(klineDefaultRange),
  }
}
