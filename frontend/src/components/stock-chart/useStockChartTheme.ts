import { computed, type ComputedRef } from 'vue'
import { useTheme } from '@/composables/useTheme'
import { useLayoutPreset } from '@/layout/useLayoutPreset'
import { stockChartTheme, type StockChartTheme } from './chartUtils'

/**
 * 股票画布主题的唯一响应式消费入口。
 * themeRevision 在整套 CSS token 写入后变化，保证调用方不会读取半更新主题。
 */
export function useStockChartTheme(): ComputedRef<StockChartTheme> {
  const { isDark } = useTheme()
  const { themeRevision } = useLayoutPreset()
  return computed(() => {
    void themeRevision.value
    return stockChartTheme(isDark.value)
  })
}
